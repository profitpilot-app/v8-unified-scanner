import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


CFG = {
    "min_price": 0.001,
    "max_price": 20.0,
    "min_dollar_volume": 25_000,
    "max_float": 15_000_000,
    "max_market_cap": 500_000_000,
    "max_spread": 5.0,
    "watch": 32,
    "precursor": 48,
    "building": 60,
    "confirmed": 72,
    "chase": 15.0,
}

TIER_1 = (
    "merger", "acquisition", "fda approval", "fda fee waiver", "exclusive license",
    "definitive agreement", "contract award", "reverse split", "debt extinguished",
)
TIER_2 = (
    "phase 2", "phase 3", "clinical", "strategic alternatives", "compliance regained",
    "patent issued", "bylaw change", "financing cleanup", "partnership",
)
TOXIC = (
    "at-the-market", "atm offering", "prospectus supplement", "chapter 11",
    "notice of delisting", "delisting", "convertible note offering",
)


class State:
    DISCOVERED = "DISCOVERED"
    ARMED = "ARMED"
    LATENT = "LATENT"
    WATCH = "WATCH"
    PRECURSOR = "PRECURSOR"
    BUILDING = "BUILDING"
    ENTRY = "ENTRY ZONE"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    DECAY = "MOMENTUM DECAY"
    REVERSAL = "REVERSAL"
    EXTENDED = "EXTENDED / CHASE RISK"
    REJECTED = "REJECTED"


ALERTABLE = {State.PRECURSOR, State.BUILDING, State.ENTRY, State.CONFIRMED, State.ACTIVE}


@dataclass
class Memory:
    state: str = State.DISCOVERED
    trigger_price: Optional[float] = None
    trigger_ts: Optional[float] = None
    first_alert_move: Optional[float] = None
    last_price: Optional[float] = None
    high_score: int = 0
    history: deque = field(default_factory=lambda: deque(maxlen=480))


class UnifiedScannerV9:
    """Unified early-mover engine. Discovery alerts start monitoring; they are not buy instructions."""

    def __init__(self):
        self.mem = defaultdict(Memory)

    @staticmethod
    def structure(t):
        post_split = int(t.get("post_split_shares") or t.get("float_shares") or 50_000_000)
        rs_sessions = int(t.get("reverse_split_sessions") or 999)
        volume = float(t.get("cumulative_volume") or t.get("volume_today") or 0)
        turnover = (volume / post_split) if post_split > 0 else 0
        recent_rs = rs_sessions <= 10
        extreme_microfloat = recent_rs and post_split < 600_000
        high_priority = recent_rs and post_split < 1_000_000
        armed = bool(
            recent_rs
            or t.get("armed_continuation")
            or float(t.get("prior_move_pct") or 0) >= 40
            or turnover >= 1
        )
        return {
            "post_split_shares": post_split,
            "reverse_split_sessions": rs_sessions,
            "turnover": turnover,
            "recent_reverse_split": recent_rs,
            "extreme_microfloat": extreme_microfloat,
            "high_priority_microfloat": high_priority,
            "armed": armed,
        }

    def hard_filter(self, t, structure):
        price = float(t.get("price", 0))
        dollar_volume = float(t.get("daily_volume_usd", 0))
        float_shares = int(t.get("float_shares") or structure["post_split_shares"])
        market_cap = float(t.get("market_cap", 0))
        spread = float(t.get("spread_pct", 0))
        if not CFG["min_price"] <= price <= CFG["max_price"]:
            return "PRICE_FILTER"
        if dollar_volume < CFG["min_dollar_volume"] and not structure["extreme_microfloat"]:
            return "LIQUIDITY_FILTER"
        if float_shares > CFG["max_float"] and not structure["recent_reverse_split"]:
            return "FLOAT_FILTER"
        if market_cap and market_cap > CFG["max_market_cap"]:
            return "MARKET_CAP_FILTER"
        if spread > CFG["max_spread"] and not structure["extreme_microfloat"]:
            return "SPREAD_FILTER"
        if t.get("halted"):
            return "HALTED"

    def score(self, t, event=None, structure=None):
        structure = structure or self.structure(t)
        text = str(t.get("sec_text", "")).lower()
        form = str(t.get("form_type", "")).upper()
        if form in {"S-1", "S-3", "424B3", "424B5"} or any(k in text for k in TOXIC):
            return 0, {"risk": "TOXIC"}
        rvol = float(t.get("rvol", 1))
        velocity_1m = float(t.get("price_vector_1m", 0))
        velocity_5m = float(t.get("price_vector_5m", 0))
        day_move = float(t.get("day_change_pct", 0))
        float_shares = int(t.get("float_shares") or structure["post_split_shares"])
        components = {
            "volume": 25 if rvol >= 8 else 20 if rvol >= 5 else 15 if rvol >= 3 else 9 if rvol >= 2 else 4 if rvol >= 1.5 else 0,
            "velocity": 20 if velocity_1m >= 3 else 17 if velocity_1m >= 2 else 13 if velocity_1m >= 1.2 else 8 if velocity_1m >= .7 else 4 if velocity_1m > 0 else 0,
            "five_minute": 8 if velocity_5m >= 5 else 6 if velocity_5m >= 3 else 3 if velocity_5m >= 1.5 else 0,
            "float": 15 if float_shares <= 600_000 else 13 if float_shares <= 2_000_000 else 10 if float_shares <= 5_000_000 else 6 if float_shares <= 10_000_000 else 2,
            "turnover": 12 if structure["turnover"] >= 2 else 10 if structure["turnover"] >= 1 else 7 if structure["turnover"] >= .5 else 4 if structure["turnover"] >= .2 else 0,
            "reverse_split": 12 if structure["extreme_microfloat"] else 8 if structure["high_priority_microfloat"] else 4 if structure["recent_reverse_split"] else 0,
            "breakout": 12 if t.get("breakout_valid") else 7 if t.get("near_breakout") else 0,
            "catalyst": 20 if any(k in text for k in TIER_1) else 12 if any(k in text for k in TIER_2) else 0,
            "event": 0,
            "asymmetry": min(10, max(0, int(t.get("asymmetry_score", 0)))),
            "early_move": 6 if 2 <= day_move <= 5 else 3 if 0 < day_move < 10 else 0,
        }
        if t.get("compression_break"):
            components["breakout"] = min(15, components["breakout"] + 3)
        events = set((event or {}).get("events", []))
        if "RAPID_INCREASE" in events:
            components["event"] += 7
        if "VOLUME_BURST" in events:
            components["event"] += 6
        if "BUY_IMBALANCE" in events:
            components["event"] += 4
        if "FAST_REVERSAL" in events or "TOP_REVERSAL" in events:
            components["event"] -= 15
        if "SELL_IMBALANCE" in events:
            components["event"] -= 8
        total = sum(v for v in components.values() if isinstance(v, (int, float)))
        return max(0, min(100, int(round(total)))), components

    @staticmethod
    def independent_signals(components):
        return sum([
            components["volume"] > 0,
            components["velocity"] > 0 or components["five_minute"] > 0,
            components["breakout"] > 0,
            components["catalyst"] > 0,
            components["event"] > 0,
            components["turnover"] > 0,
            components["asymmetry"] > 0,
        ])

    @staticmethod
    def entry_plan(t, memory):
        if memory.trigger_price is None:
            return None
        price = float(t["price"])
        trigger = memory.trigger_price
        width = max(1.5, min(float(t.get("volatility_pct", 3)), 6))
        high = trigger * (1 + width / 100)
        chase = trigger * 1.15
        expansion = (price - trigger) / trigger * 100
        spread_ok = float(t.get("spread_pct", 0)) <= CFG["max_spread"]
        depth_ok = bool(t.get("depth_ok", True))
        status = "BELOW_TRIGGER" if expansion < 0 else "ENTRY_ZONE" if price <= high else "ABOVE_ENTRY" if price < chase else "CHASE_RISK"
        return {
            "trigger": trigger,
            "entry_low": trigger,
            "ideal_entry": (trigger + high) / 2,
            "entry_high": high,
            "chase_limit": chase,
            "expansion_pct": expansion,
            "status": status,
            "spread_ok": spread_ok,
            "depth_ok": depth_ok,
            "entry_confirmed": status == "ENTRY_ZONE" and spread_ok and depth_ok,
        }

    def process_tick(self, t, event=None):
        symbol = str(t.get("ticker", "")).upper()
        memory = self.mem[symbol]
        structure = self.structure(t)
        rejected = self.hard_filter(t, structure)
        if rejected:
            memory.state = State.REJECTED
            return {"ticker": symbol, "state": memory.state, "score": 0, "reason": rejected, "structure": structure}
        score, components = self.score(t, event, structure)
        if score == 0 and components.get("risk"):
            memory.state = State.REJECTED
            return {"ticker": symbol, "state": memory.state, "score": 0, "reason": components["risk"], "structure": structure}
        independent = self.independent_signals(components)
        event_names = set((event or {}).get("events", []))
        day_move = float(t.get("day_change_pct", 0))
        early_move = 2 <= day_move <= 5
        discovery_support = independent >= (1 if structure["extreme_microfloat"] and early_move else 2)
        discovery_anchor = bool(early_move or t.get("near_breakout") or t.get("breakout_valid") or components["event"] > 0 or structure["turnover"] >= .2)
        if memory.trigger_price is None and score >= CFG["precursor"] and discovery_support and discovery_anchor:
            memory.trigger_price = float(t["price"])
            memory.trigger_ts = float(t.get("timestamp", time.time()))
            memory.first_alert_move = day_move
        plan = self.entry_plan(t, memory)
        if memory.state in ALERTABLE | {State.ACTIVE} and "TOP_REVERSAL" in event_names:
            state = State.REVERSAL
        elif memory.state in ALERTABLE | {State.ACTIVE} and ({"FAST_REVERSAL", "SELL_IMBALANCE"} & event_names):
            state = State.DECAY
        elif plan and plan["expansion_pct"] >= CFG["chase"]:
            state = State.EXTENDED
        elif plan and plan["expansion_pct"] < 0:
            state = State.WATCH
        elif plan and plan["entry_confirmed"] and score >= CFG["confirmed"]:
            state = State.CONFIRMED
        elif plan and plan["status"] == "ENTRY_ZONE" and score >= CFG["building"]:
            state = State.ENTRY
        elif plan and score >= CFG["building"]:
            state = State.BUILDING
        elif plan:
            state = State.PRECURSOR
        elif score >= CFG["precursor"]:
            state = State.PRECURSOR
        elif score >= CFG["watch"]:
            state = State.LATENT if structure["armed"] else State.WATCH
        elif structure["armed"]:
            state = State.ARMED
        else:
            state = State.DISCOVERED
        memory.state = state
        memory.high_score = max(memory.high_score, score)
        memory.last_price = float(t["price"])
        memory.history.append({"ts": t.get("timestamp", time.time()), "price": memory.last_price, "score": score, "state": state})
        return {
            "ticker": symbol,
            "state": state,
            "score": score,
            "price": memory.last_price,
            "day_change_pct": day_move,
            "trigger_price": memory.trigger_price,
            "trigger_timestamp": memory.trigger_ts,
            "first_alert_move_pct": memory.first_alert_move,
            "entry_plan": plan,
            "components": components,
            "structure": structure,
            "engines": self._engines(components, structure, t),
            "metrics": {
                "rvol": float(t.get("rvol", 1)),
                "spread_pct": float(t.get("spread_pct", 0)),
                "price_vector_1m": float(t.get("price_vector_1m", 0)),
                "price_vector_5m": float(t.get("price_vector_5m", 0)),
                "daily_volume_usd": float(t.get("daily_volume_usd", 0)),
            },
        }

    @staticmethod
    def _engines(components, structure, t):
        engines = ["Early Stock Alerts"]
        if components["velocity"] or components["volume"] or components["turnover"]:
            engines.append("Early Ignition Watch")
        if components["catalyst"] or structure["recent_reverse_split"] or structure["armed"]:
            engines.append("Pre-Repricing Runner Watch")
        if components["asymmetry"] or t.get("financing_cleanup"):
            engines.append("Asymmetric Stock Watch")
        if components["catalyst"]:
            engines.append("Afternoon Catalyst Scan")
        return engines


UnifiedScannerV8 = UnifiedScannerV9
