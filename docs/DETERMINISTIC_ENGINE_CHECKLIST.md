# Deterministic Engine Delivery Checklist

## Phase 1 — end-to-end core (implemented)

- [x] Typed portfolio, strategy, action, zone, plan and evidence contracts
- [x] Daily and completed-week point-in-time features
- [x] Confirmation-dated daily/weekly pivots and ATR price zones
- [x] Prior completed week/month and bounded open-gap zones
- [x] NIFTY/sector/optional-peer relative strength with explicit unavailable state
- [x] Five deterministic long-side setups; no forced trade
- [x] ENTER/ADD/HOLD/WAIT/TRIM/EXIT/REVIEW action model
- [x] Structure+ATR stop, deterministic T1/T2, partial/trailing/time/failed-breakout exits
- [x] Risk/allocation/regime/liquidity-capped integer sizing
- [x] LLM economics override lock and separate AI commentary
- [x] Next-session event-driven fills, gap-stop handling and adverse same-bar policy
- [x] Configurable India cash-equity costs and net metrics
- [x] Expanding/rolling embargoed walk-forward windows with frozen parameter hash
- [x] Bootstrap uncertainty and strategy acceptance gate
- [x] Extensible OHLCV source protocol and explicit data provenance limitations
- [x] Explicit-button cached Streamlit backtest; optional CLI walk-forward run
- [x] Markdown/HTML deterministic and OOS sections
- [x] Offline synthetic tests and reproducible smoke script

## Data/institutional hardening still requires external datasets

- [ ] Immutable official NSE/BSE bhavcopy archive with corporate-action master
- [ ] Delisting-complete, point-in-time constituent universe
- [ ] Historical symbol and sector-membership master
- [ ] Delivery volume, circuits, auctions and order-book/impact observations
- [ ] Multi-stock universe runner backed by the above data (the gate already accepts universe counts)
- [ ] Broker-specific invoice reconciliation and periodically versioned tax schedules

These unchecked items are disclosed limitations, not fake placeholders. Current output must not be described as survivorship-free or institutional-grade.
