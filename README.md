# Unified Early-Mover Scanner v9
Live watchlist scanner combining the five recovered engines: Early Ignition Watch, Pre-Repricing Runner Watch, Asymmetric Stock Watch, Afternoon Catalyst Scan, and Early Stock Alerts.

## Current implementation
Unified score, JAGX reverse-split microfloat override, post-split float turnover, +2–5% early alerts, ARMED/LATENT/PRECURSOR/BUILDING states, entry zone/ideal entry/chase limit, RVOL/velocity/float/breakout/catalyst/risk scoring, 5s/15s/60s event engine, reversal/decay states, ranked signal API, Alpaca snapshots plus WebSocket reconnect loop, and dashboard CORS.

## Live mode
Set `LIVE_FEED_ENABLED=true`, `ALPACA_API_KEY`, and `ALPACA_API_SECRET`. Default stream is Alpaca IEX; change `ALPACA_STREAM_URL` only if your account is entitled to another feed. Configure up to 30 symbols with `SCAN_SYMBOLS` and optional non-price reference data with `SCANNER_REFERENCE_JSON`. Do not commit credentials.

Important: this is a configured-watchlist scanner, not a whole-market discovery feed. Alpaca supplies licensed quotes/trades; it does not supply reliable float, SEC/news, options, social data, or complete market depth. Those require separate providers. The engine uses conservative defaults when reference data is missing. Browser notifications work while the dashboard is open. It never places trades.

## Run
`pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8080`

## Test
`pytest -q`

Endpoints: `/`, `/health`, `/config`, `/signals`, `/alerts`, `/signal/{ticker}`, `/audit/{ticker}`, `POST /tick`, and `POST /self-test`.

Educational/research software; signals are not guaranteed outcomes.
