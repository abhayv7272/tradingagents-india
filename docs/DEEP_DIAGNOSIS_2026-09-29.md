# Post-Implementation Deep Diagnosis — 29 September 2026

## Verdict

The deterministic mechanics are internally consistent under the expanded offline suite, but it would be dishonest to call the entire production system “perfect.” Live Yahoo/Google connectivity was unavailable in the audit sandbox, and current free data cannot remove survivorship/corporate-action vintage limitations. The system therefore correctly remains fail-closed and does not claim a validated market edge.

## Defects found and corrected during this diagnosis

1. **Distant resistance could produce T1 above T2.** Randomized price-path checks found seven ordering violations in 120 plan snapshots. T1 is now bounded at 1R (or a defensible 0.8R–1R resistance), while T2 remains at least 2R/next major resistance. Re-run: zero violations.
2. **Walk-forward test windows could overlap** when `step_sessions < test_sessions`, duplicating trades and overstating evidence. Such configurations now raise a clear error.
3. **Maximum drawdown used a negative sign.** Metrics now report the conventional positive loss magnitude, while the gate remains conservative.
4. **Pipeline data-quality hard block could show `REVIEW` with a non-zero prospective quantity.** The hard block now zeroes quantity, allocation and maximum planned loss.
5. **Streamlit could display an old cached result under newly changed widget settings.** Stored results now carry a complete economic/settings key and are hidden with a warning until explicitly re-run.
6. **Alpha Vantage “full” history did not actually request `outputsize=full`.** The URL is now correct and fixture-tested.
7. **Malformed OHLC bars were not structurally rejected.** Non-positive/inconsistent bars are dropped with a warning before any feature or fill calculation.
8. **Backtest entry sizing ignored configured entry slippage/impact.** Expected execution price is now included in risk and allocation quantity calculation.
9. **Trading horizon did not alter time stop.** Safe deterministic defaults are now swing 15, positional 30 and long-term 60 sessions.
10. **Acceptance diversity was count-only.** A caller-supplied stock count alone can no longer pass. Per-stock OOS trade counts are required; one stock is capped at 70% and one regime at 80% of OOS trades.
11. **Walk-forward `minimum_windows` was dead configuration.** It now drives the default acceptance gate and is validated.

## Verification matrix

| Check | Result |
|---|---|
| Python compile (`indiaagents`, app, CLI, scripts, tests) | PASS |
| Standard pytest | 44 passed |
| Existing deep diagnosis | 84 passed, 0 failed, 13 network-skipped (97 total) |
| Existing source suite | 24 passed, 0 failed, 2 network-skipped (26 total) |
| Ruff fatal/security subset (`E9,F63,F7,F82,S506,S307`) | PASS |
| Streamlit `AppTest` initial render | 0 exceptions |
| Streamlit server health | PASS |
| Point-in-time full-history vs prefix-only strategy snapshots | identical |
| Randomized level/risk properties | 120 snapshots, 0 violations after fix |
| Repeated full walk-forward result | byte-for-byte equal |
| New strategy/backtest package line coverage | approximately 88% |
| Synthetic walk-forward | 5 windows, 2 trades, net +0.277%, `NO VALIDATED EDGE` |

Synthetic output validates execution mechanics only. It is not evidence of an investable edge.

## What is verified

- Completed-week resampling and confirmation-dated pivots do not expose future bars.
- Shifted breakout levels and strategy snapshots are prefix invariant.
- Stop/entry/target directions, R:R and planned portfolio risk are deterministic.
- Signals execute no earlier than the next session.
- Gap stops, adverse same-bar ordering, partial exits, trailing stops and time stops have fixture coverage.
- Cash reconciles to closed-trade net P&L after charges.
- Walk-forward boundaries are embargoed and non-overlapping.
- Transaction costs and entry slippage affect net results and sizing.
- Fresh `WAIT` vs holder `HOLD/TRIM/EXIT`, event `REVIEW`, stale-data `REVIEW` and quality hard blocks are code-enforced.
- LLM proposals remain separate and cannot replace code-owned economics.
- Reports expose missing evidence, costs, windows and limitations.

## Not fully verifiable in this sandbox

- Live end-to-end Yahoo, Google News, NSE and Screener behavior: outbound TLS was intermittent/blocked. These checks are explicitly network-skipped.
- Real-data profitability or a universe-level validated edge: no such claim is made.
- Immutable as-of adjusted history, delisting-complete universe, historical symbol/sector membership and official corporate-action reconstruction: current free sources do not provide these.
- Broker/order-book execution, circuits, auctions and delivery-volume impact: daily OHLCV cannot reconstruct these.
- Streamlit result tabs after a real remote data run: initial headless UI and server health pass, but a complete browser run requires reachable sources.

## Operational assessment

The code is suitable for deterministic educational research and honest OOS measurement on supplied data. It is not an institutional point-in-time data platform. Production deployment should retain `NO VALIDATED EDGE` unless a survivorship-aware multi-stock evaluation supplies the required per-stock evidence and every acceptance check passes.

Historical performance is not a guarantee of future returns.
