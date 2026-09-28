# Data-source and fallback audit — 29 September 2026

## Conclusion

The sandbox could not complete a TLS handshake with **any** tested external HTTPS provider. This is a cross-host environment restriction, not evidence that all providers are individually down. Live success is therefore **not verified** here. TLS verification was not and must not be disabled.

Before this audit, a Yahoo OHLCV transport exception escaped before Alpha Vantage fallback, several adapters collapsed network/rate/parse/configuration failures into `None` or `[]`, and recent historical news/social queries could include publications after the analysis date. Those defects are fixed. Offline fixtures now verify parser, fallback, malformed payload, rate-limit and point-in-time behavior.

## Live reachability observed in this sandbox

| Category | Provider | Result | Interpretation |
|---|---|---|---|
| Adjusted stock/index OHLCV | Yahoo/yfinance | `network-blocked` | TLS connection closed before an application response |
| Unadjusted OHLCV fallback | Alpha Vantage | `unconfigured` | `ALPHA_VANTAGE_API_KEY` absent; no request made |
| Live quote cross-check | NSE | `network-blocked` | TLS failure; unofficial endpoint also commonly blocks cloud IPs |
| Live quote cross-check | Alpha Vantage | `unconfigured` | API key absent |
| Statements / quote summary | Yahoo/yfinance | `network-blocked` | statement empties are promoted when yfinance swallows the transport error and quote-summary exposes it |
| Independent latest fundamentals | Screener.in | `network-blocked` | TLS failure; unofficial HTML adapter |
| Company and India macro headlines | Google News India RSS | `network-blocked` | TLS failure |
| Community discovery | Reddit / Google News fallback | `network-blocked` | TLS failure |
| Indian/global market context | Yahoo/yfinance | `network-blocked` | no usable instruments |
| Global macro | FRED | `unconfigured` | `FRED_API_KEY` absent; no request made |

A repeatable operator check is available:

```bash
python scripts/check_data_sources.py --ticker RELIANCE.NS --name "Reliance Industries"
python scripts/check_data_sources.py --ticker RELIANCE.NS --json
```

The command never prints keys, never disables certificate checks, and exits successfully when providers are unreachable because reachability is diagnostic output rather than a core-test assertion.

A separate web retrieval check on 29 September successfully opened Screener's homepage, its current Reliance consolidated page, and the search endpoint. The search response currently returns `/company/RELIANCE/consolidated/`; the adapter now canonicalizes that exact shape without generating a duplicate `/consolidated/consolidated/` request. The displayed top ratios (market cap, price, high/low, P/E, book value, dividend yield, ROCE, ROE and face value) match the offline parser fixture. This confirms the current route/payload shape, but does not override the application sandbox's direct TLS failure.

## End-to-end categories and behavior

### Price history and benchmark

- Yahoo remains primary adjusted daily OHLCV.
- A minimum 600-calendar-day request gives the 200-day/40-week logic a safe warm-up margin.
- OHLCV is normalized, date-bounded, deduplicated and checked for positive/consistent bars. Exchange-local timezone removal preserves the India session date instead of shifting midnight bars to the prior UTC date.
- A Yahoo exception, empty result or sub-260-session result now reaches Alpha Vantage.
- Alpha Vantage is explicitly labelled unadjusted BSE data and cannot silently masquerade as Yahoo-adjusted data.
- NIFTY benchmark history has its own health row; unavailable benchmark or sector data produces honestly unavailable relative strength.
- Selected OHLCV has rows, start/end, adjusted flag, limitations and a stale check.
- Backtest source composition now carries an explicit Alpha status in its failure chain.

### Current quote cross-checks

- NSE and Alpha Vantage current quotes are suppressed on historical runs.
- Missing Alpha key is `unconfigured`, provider call-frequency messages are `rate-limited`, malformed payloads are `parse-failed`, and a valid payload without data is `empty`.
- NSE is an unofficial current quote endpoint. BSE-only symbols are `suppressed`, not failed.
- Cross-source deviations above 2% remain a deterministic evidence warning.

### Fundamentals

- Yahoo income statement, balance sheet, cash flow and quote-summary calls are independently guarded.
- A failure in one statement cannot abort the complete research pipeline.
- Period columns are sorted newest-first and periods after the analysis date are removed.
- Historical current-ratio/market-cap fields and latest Screener snapshots remain suppressed.
- Yahoo does not expose immutable as-filed statement vintages or publication timestamps. Period-end filtering is therefore only a partial PIT guard and is labelled as such.
- Screener is an unofficial latest HTML cross-check, not represented as official/reliable.

### Company and macro news

- RSS parsing is fixture-testable separately from transport.
- Every historical date before the current India-market date uses explicit `after`/`before` bounds, including recent historical dates.
- The adapter rechecks publication dates locally and drops missing-date headlines in historical mode.
- Independent RSS queries run in a bounded pool, avoiding ten serial timeout periods.
- Empty, transport-blocked and malformed RSS are distinct. Empty does not imply market silence.
- Google News is a discovery index, not a complete immutable archive.

### Social/community data

- Reddit Atom entries are locally bounded to `analysis_date - 7 days <= publication < analysis_date + 1 day`.
- Current Reddit search is not queried for analysis dates older than one month because it cannot supply that PIT window.
- Google News community discovery fallback uses an explicit bounded historical query.
- Entries without a parseable publication time are excluded from historical evidence.
- Missing community data is not interpreted as neutral sentiment or no chatter.

### Market context and FRED

- NIFTY is fetched once and reused for regime output rather than downloaded twice.
- Each market-context instrument has rows, as-of and stale/failure status.
- FRED requests ten observations so missing-value markers do not prevent selection of two numeric observations.
- FRED observations are sorted and re-bounded locally to the analysis date.
- Missing key, rate limit, malformed response, no observation and stale observation are separate states.

### Cache, provenance and orchestration

- HTTP cache keys use SHA-256; credential-bearing URLs are never persisted as names or diagnostic text.
- Only HTTP-200 bodies are cached.
- Writes are atomic to prevent partial payloads under concurrent Streamlit sessions.
- Cache hits are labelled. Expired content is never silently served as fresh evidence.
- Optional evidence categories fetch concurrently and degrade independently. Strategy-critical OHLCV still fails closed.
- Streamlit Data tab, Markdown, HTML and CLI now expose source health/provenance.

## Status contract

| Status | Meaning |
|---|---|
| `available` | Parsed, usable and within its freshness threshold |
| `stale` | Parsed and usable, but older than the category threshold |
| `empty` | Provider returned a usable response with no usable rows/items |
| `unconfigured` | Required optional key/configuration is absent; no request was attempted |
| `network-blocked` | TLS, connection, timeout or access-denied transport failure |
| `rate-limited` | Provider explicitly rejected request frequency/volume |
| `parse-failed` | Response arrived but did not match the validated contract |
| `suppressed` | Deliberately not queried because the endpoint is current-only or inapplicable to the symbol/PIT run |

## Offline verification

Core and parser tests require no network. They cover:

- Yahoo exception reaching Alpha fallback;
- all-provider failure returning a safe explicit error;
- independent Yahoo statement failure handling;
- Alpha missing-key versus rate-limit distinction;
- Screener HTTP 429 classification;
- future/unknown-date headline exclusion;
- Google RSS network versus parser failure;
- historical Reddit future-post exclusion;
- FRED unconfigured and 429 behavior;
- single-fetch NIFTY market context;
- malformed/impossible Alpha and NSE payload rejection;
- cache hit provenance and refusal to serve expired content as fresh.

Live-provider success must be rechecked from the actual deployment environment with the diagnostic command. Network checks remain separate from deterministic core tests.
