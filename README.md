# V8 Unified Scanner
Live-ready FastAPI scanner combining the five recovered engines: Early Ignition Watch, Pre-Repricing Runner Watch, Asymmetric Stock Watch, Afternoon Catalyst Scan, and Early Stock Alerts.

## Current implementation
Unified score, two-signal trigger discovery, entry zone/ideal entry/chase limit, RVOL/velocity/float/breakout/catalyst/risk scoring, 5s/15s/60s event engine, reversal/decay states, ranked signal API, Alpaca WebSocket reconnect loop, Docker/Render-ready service.

## Live mode
Set `LIVE_FEED_ENABLED=true`, `ALPACA_API_KEY`, and `ALPACA_API_SECRET`. Default stream is Alpaca IEX; change `ALPACA_STREAM_URL` only if your account is entitled to another feed. Do not commit credentials.

Important: live bars do not supply reliable float, market cap, spread, SEC/news, options or social data. Those require reference/news providers. Until those are wired, the live engine uses conservative defaults and may reject/under-score symbols. It does not place trades.

## Run
`pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8080`

## Test
`pytest -q`

Endpoints: `/`, `/health`, `/signals`, `/signal/{ticker}`, `POST /tick`.

Educational/research software; signals are not guaranteed outcomes.
