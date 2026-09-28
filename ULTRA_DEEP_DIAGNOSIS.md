# Ultra-Deep Diagnosis — TradingAgents India

**Audit date:** 28 September 2026  
**Scope:** source code, packaging, deterministic quant/regime layer, market/fundamental/news data, LLM orchestration, reports, security, existing backtests and test reliability.

## Executive verdict

The architecture is promising, but the pre-audit checkout was **not runnable** because two tracked Python files had syntax errors. More importantly, historical reports were not fully point-in-time: stock OHLCV was date-bounded, but market context, FRED macro, macro news, current valuation ratios and earnings calendar could leak information from after the analysis date. This made the repository's strongest historical/backtest claims less reliable than stated.

The deterministic layer is useful as a guardrail, not yet as a proven alpha engine. The recorded walk-forward rank IC is only **0.0294**, and the Qlib POC's reported top-minus-bottom 10-day spread is **0.005%** before costs. That is too small to justify strong return claims. It can still be used as weak ranking evidence if uncertainty is shown honestly.

## Bugs fixed in this audit

| Severity | Finding | Fix |
|---|---|---|
| Blocker | `fundamentals.py` had an invalid nested f-string; importing the pipeline failed | Corrected shares-outstanding formatting |
| Blocker | `tests/backtest_score.py` had an invalid nested f-string | Rewrote HOLD alpha formatting |
| Critical | Bundled sklearn 1.6.1 model fails to load under newer sklearn allowed by `>=1.6,<2.0` (`ModuleNotFoundError: _loss`) | Pinned runtime to `scikit-learn>=1.6.1,<1.7`; added an offline model-load regression test |
| Critical | Historical macro context always used today's NIFTY/VIX/USDINR/Brent | Added `trade_date` bounds to market-context histories |
| Critical | Historical FRED calls returned latest observations | Added `observation_end=trade_date` |
| Critical | Historical India macro news used a relative `when:30d` query from today | Added explicit `after/before` date windows |
| Critical | Current earnings calendar was injected into historical runs | Calendar is now used only for a current-date analysis |
| Critical risk | Regime table labelled position as `% capital` but encouraged **75–100% in one stock** | Replaced with total-portfolio caps: maximum 20% for confirmed uptrend; 0% in confirmed downtrend |
| High | Historical fundamentals silently mixed current market ratios with old technical data | Future fiscal columns are filtered; reports now show a prominent point-in-time limitation warning |
| High | `a or b` fallback let truthy `NaN` win for EBITDA/equity/cash/OCF | Added null-aware `_first_valid` |
| High | Generic industrial ratios were presented to banks/NBFCs without qualification | Added sector warning recommending NIM, GNPA/NNPA, PCR, CAR/CET1, CASA and credit-cost metrics |
| High availability | Known symbols could not resolve whenever Yahoo validation was temporarily unavailable | Known local mappings now resolve; actual OHLCV fetch remains the data validation gate |
| Medium | Beta divided by zero for flat synthetic/benchmark data and emitted warnings/NaN | Added finite positive-variance guard |
| Medium | Invalid env settings could create huge loops/token payloads | Added central settings validation and clamps |
| Medium security | Streamlit progress events were rendered as unsafe HTML without escaping external strings | Escaped stage/time/detail before HTML rendering |
| Medium security | Markdown sanitization escaped raw tags but allowed `javascript:`/`data:` links | Unsafe generated URL schemes are neutralized |
| Medium truthfulness | One provider was still called a “model battle” and criticized/synthesized itself | Battle now requires at least two independent configured providers |
| Low packaging | `.env.example` omitted supported Alpha Vantage and FRED variables | Added both variables and setup links |
| Low quality | Duplicate `ioc` dictionary key | Removed duplicate |
| Test infrastructure | pytest collected custom `test(fn)` decorators as broken tests | Marked custom decorators non-tests and added standard offline regression tests |

## Test results

### Reliable offline checks

- Python compile check: **PASS** after fixes.
- Targeted Ruff fatal/security rules (`E9`, `F63`, `F7`, `F82`, duplicate keys, `eval`): **PASS**.
- New offline regressions: **8 passed, 0 failed**. They cover model loading, safe portfolio bands, settings validation, ticker outage behavior, historical macro/FRED boundaries, fundamental as-of filtering and unsafe Markdown URLs.
- Existing deep diagnosis: **84 passed, 0 failed, 13 network-skipped (97 total)**.
- Existing multi-source suite: **24 passed, 0 failed, 2 network-skipped (26 total)**.
- Synthetic coverage passed for factor shape/order, look-ahead invariance, model determinism, JSON parsing, LLM key-pool rotation, fallback chains, memory math, report/XSS rendering, chart edge cases and regime clamp logic.

### Environment-dependent checks

This sandbox's outbound TLS connection to Yahoo/Google/Screener/NSE was intermittent or blocked. Therefore live-ticker, live-chart and end-to-end mock tests that still require real market data could not be treated as product failures. The existing custom `@net_test` wrapper only converts network exception classes to skips; a live test that receives `None` and then raises `AssertionError` is incorrectly counted as a failure. Live reachability should be separated from unit tests and run in a scheduled integration job.

## Technical-analysis diagnosis

### What is good

- Indicators are computed on data truncated at `trade_date`.
- Factor generation is point-in-time under synthetic mutation tests.
- NaN/flat-series regime guards exist.
- Position upper bounds and confirmed-downtrend lock are deterministic code, not merely prompts.
- Recent daily rows and volume flags give the LLM dates to cite.

### What remains weak or misleading

1. **Regime confidence is overstated.** Five of six conditions sounds diversified, but all six are transformations of the same close-price history (moving averages, MACD, ROC, RSI). It is one technical evidence family, not six independent confirmations.
2. **Support/resistance is simplistic.** A 63-session absolute min/max is not swing detection and is highly sensitive to one wick.
3. **“Volume profile” is an approximation.** It allocates each day's entire volume to the closing-price bin; it is not exchange volume-at-price.
4. **Corporate-action point-in-time risk remains.** Today's adjusted Yahoo history can incorporate later splits/dividends into old bars. A strict backtest needs as-of-vintage data or carefully handled raw OHLC and corporate actions.
5. **No liquidity/execution model.** Bid-ask spread, impact, circuit limits, delivery volume, auction risk, slippage and taxes/STT are absent.
6. **No sector-relative strength.** Stock vs NIFTY alone is insufficient; compare against sector index and relevant peer basket.
7. **No multi-timeframe confirmation.** Daily factors dominate; weekly trend and intraday execution are absent.
8. **Hard lock is based on technicals only.** A deterministic zero-fresh-entry policy is conservative, but should be labelled a strategy policy—not objective market truth.

### Recommended next technical work

- Replace extrema support/resistance with confirmed pivots plus ATR tolerance and touch counts.
- Add stock/NIFTY and stock/sector relative-strength trends.
- Add rolling liquidity: median traded value, zero-volume days, delivery %, impact-cost proxy and circuit events.
- Backtest all rules with walk-forward purging, transaction costs, delistings and corporate actions.
- Report uncertainty: factor coverage, stale-bar age, source disagreement and model version.
- Parse entry/stop/target numerically and enforce R:R, stop direction and maximum risk per trade in code.

## Fundamental-analysis diagnosis

### Current strengths

- Income statement, balance sheet, cash flow and market snapshot are separately displayed.
- Independent Screener cross-check and P/E conflict warning exist.
- Missing values degrade to em dashes instead of becoming hallucinated numbers.

### Major gaps

1. **Not fully point-in-time.** Yahoo does not expose filing-publication timestamps. Current `info` fields (P/E, market cap, forward P/E, beta, dividend rate) are latest snapshots even during an old analysis. Historical reports now warn about this, but strict fundamental backtests must exclude these fields or use as-filed filings.
2. **Mostly annual, not quarterly.** Indian earnings reactions depend on quarterly revenue, EBITDA, PAT, margins, guidance and segment performance.
3. **No peer/historical valuation context.** A P/E number alone is not “cheap” or “expensive.” Add 5-year percentile, EV/EBITDA, P/B where appropriate, PEG only with defensible growth, and sector peers.
4. **Bank/NBFC metrics were structurally wrong for the business.** Generic debt/current-ratio/FCF analysis must be replaced by asset-quality, capital and funding metrics.
5. **No earnings quality.** Add CFO/PAT, receivable/inventory days, accruals, exceptional items, related-party transactions and auditor qualifications.
6. **No ownership/governance.** Promoter holding/pledge changes, institutional flows, dilution, warrants and board/auditor events matter materially in India.
7. **No estimate revision layer.** Forward earnings revision breadth and management-guidance change often matter more than trailing numbers.
8. **No source freshness metadata.** Every figure should show fiscal period, publication date, source and consolidated/standalone status.

### Recommended next fundamental work

- Ingest NSE/BSE corporate filings with announcement timestamps and immutable raw snapshots.
- Build sector-specific schemas (banks, NBFCs, insurers, commodity producers, SaaS/IT, utilities).
- Add quarterly trend tables and TTM calculations with restatement handling.
- Add peer valuation percentiles and a reverse-DCF/scenario valuation rather than one-point fair value.
- Require every LLM fundamental claim to cite a supplied field and period; reject unsupported numeric claims.

## Quant/backtest diagnosis

- The final model is trained on **raw 10-day forward return**, while evaluation uses daily cross-sectional rank IC. Calling its output an exact “expected 10-day move” is stronger than the evidence supports.
- IC 0.0294 is weak and only two folds are recorded. It may be real, unstable or regime-specific.
- The Qlib POC reports a **0.005%** quintile spread, effectively zero before costs.
- The universe is current large caps, creating survivorship/selection bias.
- Existing AI backtest sample is only six reports in one regime and all decisions were HOLD; it cannot establish directional accuracy.
- No bootstrap confidence intervals, turnover, drawdown, hit-rate significance, calibration curve or cost model are reported.

**Recommendation:** rename the displayed quantity to “model ranking signal / model-implied return,” hide it automatically when artifact/runtime versions mismatch or rolling IC is below threshold, and run a true out-of-sample portfolio simulation with costs.

## Architecture/product improvements

1. Fetch independent data sources concurrently with bounded workers and per-source deadlines; the current data stage is largely sequential.
2. Introduce typed schemas (Pydantic/dataclasses) for data provenance and PM output instead of loose dictionaries.
3. Add a run manifest: code commit, model hash, prompts version, source timestamps, provider/model IDs and all warnings.
4. Add explicit user inputs: existing holding, average cost, horizon, risk tolerance, portfolio size and sector exposure. Without these, “position size” is generic, not suitability-aware advice.
5. Compute portfolio correlation and aggregate exposure; a single-stock engine cannot know whether a 10% suggestion creates concentration.
6. Separate `BUY/SELL/HOLD` from `ENTER/ADD/TRIM/EXIT/WAIT` and from rating. The action depends on whether the user already owns the stock.
7. Fail closed on stale/insufficient primary data. LLM prose should never turn unavailable evidence into confidence.
8. Add CI with offline fixtures; schedule live provider/source health checks separately.

## Follow-up implementation after the audit

The first P0 follow-up is now implemented as code rather than prompt advice:

- **Deterministic data-quality score (0–100):** price-history coverage, bar freshness, independent-price agreement, fundamental coverage, company news, India macro, sentiment and FRED are scored separately with visible limitations.
- **Quality guard:** stale/critical evidence forces HOLD, 0% allocation and confidence ≤35%; low evidence caps allocation/confidence; medium evidence caps confidence.
- **Trade-plan guard:** parses absolute INR entry/target/stop, verifies `stop < entry < target`, requires R:R ≥1:1.5, and caps position so stop-loss risk is no more than 1% of total capital. Invalid BUY economics become HOLD.
- **Historical leakage hardening:** current Yahoo valuation fields, Screener snapshots and current live-quote cross-checks are suppressed in old-date reports rather than merely warned about.
- **UI/report transparency:** evidence score, limitations and code-verified R:R are visible in Markdown, HTML and Streamlit.
- **Five additional offline guardrail tests** bring standard pytest coverage to **13 passed**.

## Bottom line

After this patch the code compiles, the bundled model loads under its compatible dependency, historical macro leakage is substantially reduced, portfolio caps are safer, and several security/availability problems are fixed. The app is suitable as an **educational research assistant**, but its output should not be marketed as validated trading accuracy. The next highest-value milestone is a timestamped, point-in-time Indian filings dataset plus a cost-aware, survivorship-safe walk-forward backtest.

---

## Deterministic strategy / walk-forward implementation (September 2026)

The audit's highest-priority technical milestone is now implemented end-to-end in `indiaagents.strategy` and `indiaagents.backtest`.

### What changed

- Daily plus **completed-week-only** feature frames; no partial future-Friday candle is exposed.
- Confirmed daily/weekly pivots carry separate pivot and right-bar confirmation dates. ATR-clustered zones include touches, recency, completed prior week/month levels and recent unfilled gaps.
- Stock/NIFTY and maintainable stock/sector relative strength provides 1M/3M/6M spread, ratio slope and regime agreement. Missing mappings/data remain `unavailable`.
- Five non-forced deterministic setups produce `ENTER/ADD/HOLD/WAIT/TRIM/EXIT/REVIEW`, exact triggers/zones, structure+ATR stops, T1/T2, exits and integer size.
- The pipeline stores the LLM proposal as `ai_decision`, then applies a deterministic lock. LLM economics cannot enter the primary `deterministic` result or overwrite report/UI levels.
- Reusable event-driven simulator implements next-session orders, adverse same-bar ordering, realistic gap-stop opens, partials, trailing/time/trend/RS exits and a reasoned fill ledger.
- Indian delivery-market cost components, net OOS metrics, grouped performance, fixed-seed bootstrap intervals, embargoed walk-forward boundaries and a strict acceptance gate are code, not generated prose.
- Streamlit has portfolio inputs and four required concerns: current setup, historical evidence, action reasons and explicit settings. Backtests use an explicit cached button, not widget-triggered downloads.
- Source protocols allow official bhavcopy/broker implementations later. Current Yahoo provenance explicitly discloses adjusted-vintage, corporate-action, survivorship, delisting, symbol and sector-membership limitations.

### Honesty boundary retained

This implementation fixes rule/execution look-ahead in code, but it cannot transform Yahoo's present-day adjusted history into an immutable historical vintage or manufacture a delisting-complete universe. Consequently a single-symbol run is labelled stock-specific and cannot pass universe diversity. `NO VALIDATED EDGE` remains the default until every gate condition passes on genuine unseen windows after costs.

Detailed methodology: [`docs/BACKTEST_METHODOLOGY.md`](docs/BACKTEST_METHODOLOGY.md).

Status/external-data checklist: [`docs/DETERMINISTIC_ENGINE_CHECKLIST.md`](docs/DETERMINISTIC_ENGINE_CHECKLIST.md).

Historical performance is not a guarantee of future returns.

### Post-implementation verification — 29 September 2026

A second property-based/offline audit found and fixed target ordering, overlapping unseen-window, drawdown-sign, hard-block sizing, cache-key, Alpha Vantage full-history, malformed-OHLC, slippage-sizing, horizon-time-stop and concentration-gate defects. Final detailed results and the remaining live-data boundary are recorded in [`docs/DEEP_DIAGNOSIS_2026-09-29.md`](docs/DEEP_DIAGNOSIS_2026-09-29.md).
