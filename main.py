import asyncio
import json
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import httpx
import websockets
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from audit import AlertAudit
from events import SubMinuteEventEngine
from scanner import ALERTABLE, UnifiedScannerV9


def env_value(name, default=None):
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value or default


def env_json(name, default):
    try:
        return json.loads(env_value(name, json.dumps(default)))
    except (TypeError, json.JSONDecodeError):
        return default


DEFAULT_SYMBOLS = ["JAGX", "GIPR", "TNMG", "IMCC", "SSM", "TCRT"]
SYMBOLS = list(dict.fromkeys(s.strip().upper() for s in env_value("SCAN_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",") if s.strip()))[:30]
REFERENCE = {
    "JAGX": {
        "float_shares": 520_088,
        "post_split_shares": 520_088,
        "reverse_split_sessions": 4,
        "armed_continuation": True,
        "benchmark_only": True,
        "sec_text": "historical JAGX benchmark: reverse split; FDA fee waiver",
    },
    **env_json("SCANNER_REFERENCE_JSON", {}),
}

scanner = UnifiedScannerV9()
event_engine = SubMinuteEventEngine()
audit = AlertAudit()
latest = {}
market = defaultdict(dict)
price_history = defaultdict(lambda: deque(maxlen=600))
last_processed = defaultdict(float)
feed = {
    "connected": False,
    "mode": "simulation",
    "last_error": None,
    "last_event": None,
    "last_snapshot": None,
    "subscribed_symbols": SYMBOLS,
    "coverage": "watchlist",
    "config": {"enabled": False, "api_key_present": False, "api_secret_present": False, "stream_url_present": False},
}


def credentials():
    return env_value("ALPACA_API_KEY"), env_value("ALPACA_API_SECRET")


def pct_change(new, old):
    return 0.0 if not old else (float(new) - float(old)) / float(old) * 100


def history_change(symbol, seconds, price):
    now = time.time()
    candidates = [p for ts, p in price_history[symbol] if now - ts >= seconds]
    return pct_change(price, candidates[-1]) if candidates else 0.0


def make_tick(symbol, price=None):
    state = market[symbol]
    price = float(price or state.get("price") or 0)
    volume = float(state.get("volume") or 0)
    prev_close = float(state.get("prev_close") or 0)
    prev_volume = float(state.get("prev_volume") or 0)
    bid = float(state.get("bid") or 0)
    ask = float(state.get("ask") or 0)
    midpoint = (bid + ask) / 2 if bid and ask else price
    spread = ((ask - bid) / midpoint * 100) if bid and ask and midpoint else 0
    reference = REFERENCE.get(symbol, {})
    tick = {
        "ticker": symbol,
        "price": price,
        "previous_close": prev_close,
        "day_change_pct": pct_change(price, prev_close),
        "daily_volume_usd": price * volume,
        "cumulative_volume": volume,
        "volume_today": volume,
        "rvol": (volume / prev_volume) if prev_volume else 1,
        "price_vector_1m": history_change(symbol, 60, price),
        "price_vector_5m": history_change(symbol, 300, price),
        "spread_pct": spread,
        "near_breakout": bool(state.get("near_breakout")),
        "breakout_valid": bool(state.get("breakout_valid")),
        "timestamp": time.time(),
        **reference,
    }
    tick.setdefault("float_shares", int(env_value("DEFAULT_FLOAT_SHARES", "10000000")))
    return tick


def process_symbol(symbol, price=None, event=None, source="live_feed"):
    tick = make_tick(symbol, price)
    if tick["price"] <= 0:
        return None
    result = scanner.process_tick(tick, event)
    latest[symbol] = result
    audit.record(result, source)
    return result


async def refresh_snapshots():
    key, secret = credentials()
    if not key or not secret or not SYMBOLS:
        return
    url = "https://data.alpaca.markets/v2/stocks/snapshots"
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    params = {"symbols": ",".join(SYMBOLS), "feed": "iex"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json().get("snapshots", response.json())
    for symbol, snapshot in payload.items():
        daily = snapshot.get("dailyBar") or {}
        previous = snapshot.get("prevDailyBar") or {}
        trade = snapshot.get("latestTrade") or {}
        quote = snapshot.get("latestQuote") or {}
        minute = snapshot.get("minuteBar") or {}
        price = trade.get("p") or minute.get("c") or daily.get("c")
        market[symbol].update({
            "price": price,
            "volume": daily.get("v", 0),
            "prev_close": previous.get("c", 0),
            "prev_volume": previous.get("v", 0),
            "bid": quote.get("bp", 0),
            "ask": quote.get("ap", 0),
            "near_breakout": bool(price and daily.get("h") and price >= daily.get("h") * .98),
            "breakout_valid": bool(price and previous.get("h") and price > previous.get("h")),
        })
        if price:
            price_history[symbol].append((time.time(), float(price)))
            process_symbol(symbol, price, source="alpaca_snapshot")
    feed["last_snapshot"] = time.time()


async def snapshot_loop():
    while True:
        try:
            await refresh_snapshots()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            feed["last_error"] = f"snapshot {type(exc).__name__}: {exc}"
        await asyncio.sleep(30)


async def live_feed():
    url = env_value("ALPACA_STREAM_URL", "wss://stream.data.alpaca.markets/v2/iex")
    key, secret = credentials()
    feed["config"].update({"api_key_present": bool(key), "api_secret_present": bool(secret), "stream_url_present": bool(url)})
    if not key or not secret:
        feed["last_error"] = "Missing ALPACA_API_KEY/ALPACA_API_SECRET"
        return
    delay = 2
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
                auth = json.loads(await ws.recv())
                if any(item.get("T") == "error" for item in auth):
                    raise RuntimeError(str(auth))
                await ws.send(json.dumps({"action": "subscribe", "trades": SYMBOLS, "quotes": SYMBOLS, "bars": SYMBOLS}))
                subscription = json.loads(await ws.recv())
                if any(item.get("T") == "error" for item in subscription):
                    raise RuntimeError(str(subscription))
                feed.update({"connected": True, "mode": "live", "last_error": None})
                delay = 2
                async for raw in ws:
                    for item in json.loads(raw):
                        kind, symbol = item.get("T"), item.get("S")
                        if not symbol:
                            continue
                        now = time.time()
                        if kind == "q":
                            market[symbol].update({"bid": item.get("bp", 0), "ask": item.get("ap", 0)})
                        elif kind == "b":
                            market[symbol].update({"price": item.get("c", 0), "volume": item.get("v", market[symbol].get("volume", 0))})
                            price_history[symbol].append((now, float(item.get("c", 0))))
                            process_symbol(symbol, item.get("c", 0))
                        elif kind == "t":
                            price, size = float(item.get("p", 0)), float(item.get("s", 0))
                            event = event_engine.add_trade(symbol, price, size, side=None)
                            market[symbol]["price"] = price
                            market[symbol]["volume"] = float(market[symbol].get("volume", 0)) + size
                            price_history[symbol].append((now, price))
                            feed["last_event"] = {"ticker": symbol, **event, "timestamp": now}
                            if now - last_processed[symbol] >= 2:
                                last_processed[symbol] = now
                                process_symbol(symbol, price, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            feed.update({"connected": False, "last_error": f"{type(exc).__name__}: {exc}"})
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


@asynccontextmanager
async def lifespan(app):
    tasks = []
    enabled = (env_value("LIVE_FEED_ENABLED", "false") or "false").lower() == "true"
    feed["config"]["enabled"] = enabled
    if enabled:
        tasks = [asyncio.create_task(live_feed()), asyncio.create_task(snapshot_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Unified Early-Mover Scanner", version="9.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://pre-repricing-runner-scanner-v51.dannyinhouston872966.chatgpt.site",
        "http://localhost:3000",
        "http://localhost:8080",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Tick(BaseModel):
    ticker: str
    price: float
    previous_close: float = 0
    day_change_pct: float = 0
    daily_volume_usd: float = 0
    cumulative_volume: float = 0
    float_shares: int = 50_000_000
    post_split_shares: int | None = None
    reverse_split_sessions: int = 999
    armed_continuation: bool = False
    prior_move_pct: float = 0
    market_cap: float = 0
    spread_pct: float = 0
    depth_ok: bool = True
    rvol: float = 1
    vol_1m: float = 0
    price_vector_1m: float = 0
    price_vector_5m: float = 0
    near_breakout: bool = False
    breakout_valid: bool = False
    compression_break: bool = False
    volatility_pct: float = 3
    sec_text: str = ""
    form_type: str = ""
    asymmetry_score: int = 0
    financing_cleanup: bool = False
    halted: bool = False
    timestamp: float | None = None


@app.get("/")
def root():
    return {"name": "Unified Early-Mover Scanner", "version": "9.0.0", "feed": feed, "signals": len(latest), "execution": "alerts_only_no_trading"}


@app.get("/health")
def health():
    return {"ok": True, "feed": feed, "symbols": len(scanner.mem), "signal_count": len(latest)}


@app.get("/config")
def config():
    return {
        "version": "9.0.0",
        "symbols": SYMBOLS,
        "engines": ["Early Ignition Watch", "Pre-Repricing Runner Watch", "Asymmetric Stock Watch", "Afternoon Catalyst Scan", "Early Stock Alerts"],
        "coverage": "configured watchlist only; not a whole-market screener",
        "alert_delivery": "dashboard polling and browser notifications while the page is open",
        "trade_execution": False,
        "jagx_benchmark": {"expected_first_alert": "+2.8% at 8:47 AM CT", "volume": "4.1x", "post_split_shares": 520_088},
    }


@app.post("/tick")
def tick(tick: Tick):
    data = tick.model_dump()
    data["timestamp"] = data["timestamp"] or time.time()
    result = scanner.process_tick(data)
    latest[tick.ticker.upper()] = result
    audit.record(result, "manual_tick")
    return result


@app.get("/signals")
def signals():
    return sorted(latest.values(), key=lambda item: (item.get("state") in ALERTABLE, item.get("score", 0)), reverse=True)


@app.get("/signal/{ticker}")
def signal(ticker: str):
    return latest.get(ticker.upper(), {"ticker": ticker.upper(), "state": "UNKNOWN"})


@app.get("/alerts")
def alerts():
    return [item for item in signals() if item.get("state") in ALERTABLE]


@app.get("/audit/{ticker}")
def audit_history(ticker: str):
    return {"ticker": ticker.upper(), "alerts": audit.history(ticker)}


@app.post("/audit/mover/{ticker}")
def audit_mover(ticker: str, price: float, gain: float):
    return audit.audit_mover(ticker, price, gain)


@app.post("/self-test")
def self_test():
    base = {
        "ticker": "V8TEST", "price": 1.0, "previous_close": .97, "day_change_pct": 3.09,
        "daily_volume_usd": 750_000, "cumulative_volume": 600_000, "float_shares": 2_500_000,
        "market_cap": 25_000_000, "spread_pct": 1.0, "rvol": 6.0, "vol_1m": 120_000,
        "price_vector_1m": 1.8, "price_vector_5m": 3.1, "near_breakout": True,
        "breakout_valid": True, "compression_break": True, "volatility_pct": 3.0,
        "sec_text": "definitive agreement contract award", "form_type": "", "asymmetry_score": 8,
        "halted": False, "timestamp": time.time(),
    }
    result = scanner.process_tick(base)
    jagx = scanner.process_tick({
        **base, "ticker": "JAGXTEST", "price": .11, "previous_close": .107,
        "day_change_pct": 2.8, "daily_volume_usd": 50_000, "cumulative_volume": 2_132_000,
        "float_shares": 520_088, "post_split_shares": 520_088, "reverse_split_sessions": 4,
        "rvol": 4.1, "price_vector_1m": .8, "price_vector_5m": 2.2,
        "sec_text": "reverse split fda fee waiver",
    })
    return {
        "ok": result.get("trigger_price") is not None and jagx.get("trigger_price") is not None and jagx.get("first_alert_move_pct") == 2.8,
        "general_result": result,
        "jagx_benchmark": jagx,
        "feed_config": feed.get("config"),
    }
