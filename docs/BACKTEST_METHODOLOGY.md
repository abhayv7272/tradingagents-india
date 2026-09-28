# Deterministic Strategy & Walk-Forward Methodology

Version: `deterministic-v1` (September 2026)

> Historical performance is not a guarantee of future returns. This project is educational research, not investment advice.

## 1. Authority boundary

`indiaagents.strategy` owns the detailed action, setup state, trigger, entry zone, stop, targets, quantity and exit rules. `indiaagents.backtest` owns all historical fills and statistics. No LLM is called from either package. The LLM receives the code result only to explain it, identify risks and provide bull/bear critique. `pipeline._lock_deterministic_decision` prevents the LLM portfolio-manager JSON from replacing code-owned economics.

Given identical OHLCV/reference data, analysis date, portfolio inputs and configuration, output is deterministic. Bootstrap intervals use a fixed seed that is disclosed in metrics.

## 2. Point-in-time feature rules

### Daily

The feature frame contains 10/20 EMA, 20/50/200 SMA, RSI(14), MACD(12,26,9), Wilder-style ATR(14), Bollinger width, volume/20-session average, 10/20-session volatility ratio, gap size, shifted 20/55-session breakout levels, 252-session drawdown and a normalized 20-session OLS trend slope.

Breakout levels use `High.shift(1).rolling(...)`: today's close never compares against today's still-forming high. Volatility contraction thresholds are calculated from the prior bar's rolling width distribution. Missing sessions are not forward-filled.

### Weekly

Daily bars are grouped into `W-FRI` candles. A weekly candle is usable only when its Friday label is on or before the analysis date. A Wednesday analysis therefore sees the prior completed Friday, not a partial week. Weekly calculations include 10/20/40-week SMA, four-week slope of the 20-week SMA, RSI, MACD and positive/neutral/negative trend state.

### Confirmed pivots and zones

A pivot with `left=L`, `right=R` is timestamped as available only on bar `pivot_index + R`. Before that confirmation close it is unavailable to both current analysis and backtest. Daily and weekly confirmed pivots are clustered with configurable ATR tolerance. Zones retain touch count, most recent touch and source. Previous completed week/month levels and still-open recent gap zones can supplement them. Gaps older than 180 sessions are intentionally excluded from active execution zones.

## 3. Relative strength

The engine aligns closes by actual common dates and computes stock minus reference total price performance over 21/63/126 sessions, plus an annualized log-ratio slope. It supports:

- stock vs NIFTY 50;
- stock vs an explicitly mapped NSE sector index;
- an optional explicitly supplied peer basket.

Mappings live in `indiaagents/strategy/relative_strength.py`. Missing sector/peer data is reported as `unavailable`; it is never replaced with a fabricated neutral/positive value. Historical sector membership is not reconstructed.

## 4. Long-side setups

Setups are evaluated in a fixed priority order and a trade is never forced:

1. **Weekly-trend breakout** — positive completed-week trend, daily trend, close above shifted 55-session high, configured volume expansion, positive NIFTY RS and positive sector RS when sector data exists.
2. **Breakout retest** — confirmed earlier breakout, former resistance retest, bullish close and relative-strength confirmation.
3. **Trend pullback** — weekly/daily uptrend, pullback to EMA/SMA or confirmed support, contracting selling volume and bullish reversal close.
4. **Range breakout / volatility contraction** — recent contraction, bounded prior range, shifted 20-session breakout and volume/RS confirmation.
5. **Bottoming reversal probe** — only in the deterministic bottoming state, with RSI recovery, positive MACD histogram, higher low, bullish reversal and volume confirmation; allocation is capped at 5%.

An incomplete setup is `WAITING`. For a fresh investor it maps to `WAIT`, never `HOLD`. For an existing holder, close/weekly-trend/failed-breakout/relative-strength rules map to `HOLD`, `TRIM` or `EXIT`. Critical stale/insufficient data maps to `REVIEW`.

## 5. Entry, stop, targets and sizing

- Breakout entry zones are trigger plus 0.05–0.50 ATR. Pullback zones are based on the closed reversal and support trigger.
- Stops use the nearest confirmed structural support/setup invalidation minus an ATR buffer.
- A stop narrower than the configured minimum ATR is widened. A stop above entry is invalid. A stop wider than the configured maximum percentage rejects the trade.
- T1 is 1R or a defensible nearby resistance. T2 is at least 2R (and never below the configured minimum R:R), optionally extended to the next major resistance.
- Quantity is the integer minimum of rupee-risk capacity, regime/allocation cap and the configured percentage of 20-session median traded value.
- `maximum rupee loss = quantity × (conservative entry-zone high − stop)`.
- Conservative risk profile spends only 75% of the user's maximum risk budget. “Aggressive” never exceeds that user maximum.

A code-valid active occurrence is still not an `ENTER` recommendation when validated out-of-sample evidence is unavailable. It remains `WAIT` and is available for measurement.

## 6. Event-driven execution

The simulator is long-only and supports one position per symbol:

1. A signal is generated after a completed close.
2. Earliest entry is the next tradable session. It fills at the next open when inside the entry zone, at the zone trigger after an intraday crossing, or is rejected after an excessive gap above the zone.
3. A gap below an effective stop exits at the opening price, not the stale stop price.
4. Default same-bar policy is `adverse`: if stop and target are both touched and ordering is unknown, the stop is processed first.
5. T1 takes the configured partial quantity; T2 exits the balance. Integer holdings that cannot be split exit at the reachable target.
6. Chandelier trailing stop (`highest closed price − N×ATR`) is updated after close and becomes effective only next session. After T1, the effective stop is at least breakeven.
7. Trend/RS exits and time stops observed after close execute at the next open.
8. Every fill stores date, side, raw price, slippage-adjusted price, quantity, costs and reason.

Administrative `TEST_WINDOW_END` liquidation is explicit in the ledger and prevents an unseen window from carrying exposure into another independently measured window.

## 7. Indian cash-equity costs

Defaults in `IndiaCostConfig` are configurable assumptions, not a broker invoice:

| Component | Default |
|---|---:|
| Brokerage | 0.03% of turnover, capped at ₹20/order |
| STT (delivery approximation) | 0.10% buy and 0.10% sell |
| NSE transaction charge | 0.00297% |
| SEBI charge | 0.00010% |
| GST | 18% of brokerage + exchange + SEBI charges |
| Stamp duty | 0.015% on buy turnover |
| Slippage | 5 bps per side |
| Optional impact estimate | 0 bps per side |

Slippage/impact worsens execution price. Statutory/broker charges are deducted separately. Net return after both is the primary result. Rates and tax treatment change; users must set the current broker/exchange values before relying on a simulation.

## 8. Walk-forward protocol

Default windows are:

- 504 sessions training/calibration;
- 126 sessions validation;
- five-session embargo;
- 126 sessions unseen test;
- 126-session roll step;
- expanding training history.

`deterministic-v1` performs **no parameter search**. Its interpretable rules are frozen and hashed before every test window. Validation boundaries are still explicit so a small future calibration grid can be selected without touching test data. No forward-return labels are currently used, so label-overlap purging is not required; embargo is retained to isolate boundaries. Final metrics aggregate only unseen test windows.

If parameter selection is added later, it must use a small declared grid, choose only from training/validation, freeze the chosen hash and never report validation results as OOS test results.

## 9. Metrics and uncertainty

Net metrics include trades, win rate, average win/loss, profit factor, expectancy in R, total return, CAGR (when the period is long enough), NIFTY-relative alpha, max drawdown, Sharpe, Sortino, holding period, turnover, stop-hit rate, gap-loss rate, longest losing streak, exposure and setup/regime/sector groups.

A fixed-seed non-parametric trade bootstrap reports 95% percentile intervals for net P&L, expectancy R and win rate. It does not model serial dependence; that limitation is shown next to the interval.

## 10. Acceptance gate

Default universe-level criteria all must pass:

- at least 50 unseen OOS trades;
- at least three unseen test windows;
- net expectancy greater than 0R after costs;
- profit factor at least 1.20;
- max drawdown no worse than 25%;
- at least three stocks with supplied per-stock OOS trade counts;
- no one stock contributing more than 70% of OOS trades;
- at least two market regimes represented;
- no one regime contributing more than 80% of OOS trades.

A bare caller-supplied stock count is not accepted as diversity evidence; per-stock and per-regime counts must reconcile exactly to the reported OOS sample before concentration checks can pass. Failure returns `NO VALIDATED EDGE` and fresh action remains `WAIT`/`REVIEW`. A single-symbol UI run is labelled **stock-specific occurrences only** and cannot pass universe diversity, even if its own statistics look good.

## 11. Data integrity limitations

The current source adapter documents rather than hides these limitations:

- Yahoo is a current adjusted-history vintage, not immutable as-of data.
- Adjusted OHLC can reflect splits/dividends/bonuses known after an old analysis date; Yahoo volume-adjustment semantics may differ.
- Unadjusted fallback data requires corporate-action processing before strict comparison.
- The project does not have a delisting-complete historical universe, so current-universe survivorship and selection bias remain.
- Missing bars are dropped, not fabricated; exchange halts, circuits and auctions are not reconstructed.
- Symbol changes and historical sector membership are not fully reconstructed.
- Daily bars do not reveal intrabar path, order-book depth, delivery volume or actual impact.
- Yahoo's historical vintage can be revised.

Therefore this is a point-in-time **rule/execution implementation** on the supplied bar vintage, not a claim of leak-free institutional-grade Indian market data. Confidence must be reduced accordingly.

## 12. Recalibration guidance

Run a broad, survivorship-aware universe evaluation periodically (for example quarterly), not after every losing trade. Freeze configuration before unseen windows. Keep parameter changes few and economically interpretable. Archive code hash, settings, data provenance and raw official bhavcopy/broker snapshots when available. A deterioration in rolling unseen expectancy or a confidence interval crossing zero should remove the edge claim, not trigger an unconstrained search.

Offline mechanics smoke test:

```bash
python scripts/synthetic_backtest.py
```

Synthetic results validate only determinism and execution mechanics; they are never market evidence.
