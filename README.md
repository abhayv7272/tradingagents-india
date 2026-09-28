# 📈 TradingAgents India

**Free, multi-agent AI stock research for the Indian market (NSE/BSE).**

Stock ka naam dalo → 4 Analysts + 🐂 Bull vs 🐻 Bear debate + ⚔️ **3-Model Battle** + Risk Team + Portfolio Manager = **poori Hinglish research report**, bilkul **FREE** API keys pe.

> Inspired by [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0) — unki multi-agent trading-firm architecture ko India ke liye rebuild kiya gaya hai, free-tier models ke saath, aur ek naye **Battle Mode** ke saath jahan alag-alag AI companies ke models ek dusre ki research red-team karte hain.

---

## 🏗️ Kaise kaam karta hai

```
   TUM: "RELIANCE" type karo
              │
              ▼
┌─ DATA (multi-source, 6 sources — free, no keys*) ────┐
│ yfinance: price, indicators, financials (₹)          │
│ Screener.in: MCap, P/E, BV, ROCE, ROE (independent)  │
│ NSE: live quote cross-check (last/VWAP/52w)          │
│ Alpha Vantage: OHLCV fallback (optional free key)    │
│ Google News India: company + macro (RBI, CPI, SEBI)  │
│ Reddit: Indian retail chatter + FRED macro (US)      │
│ Market context: NIFTY, SENSEX, VIX, USD/INR, Brent   │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌─ ANALYST TEAM (parallel, different models) ──────────┐
│ 📈 Technical  💰 Fundamentals  📰 News  💬 Social    │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌─ RESEARCH TEAM ──────────────────────────────────────┐
│ 🐂 Bull (model B) ⟷ 🐻 Bear (model C) — rounds      │
│ ⚖️ Research Manager (deep model) → draft verdict     │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌─ ⚔️ MODEL BATTLE (naya!) ────────────────────────────┐
│ Gemini + Groq + OpenRouter — teeno ek dusre ki       │
│ research ko AUDIT karte hain: factual errors, blind  │
│ spots, agree/disagree. Synthesizer improved verdict  │
│ banata hai. (Different AI = different biases!)       │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌─ DETERMINISTIC ENGINE → setup/entry/SL/targets/size ─┐
│  (daily+weekly+pivots+RS; LLM sirf explanation)      │
┌─ RISK TEAM: 😤 Aggressive ⟷ 🛡️ Conservative ⟷ 😐 Neutral ┐
┌─ PORTFOLIO MANAGER → commentary; code action LOCK ───┐
└──────────────────────┬───────────────────────────────┘
                       ▼
       📄 reports/RELIANCE.NS_<date>/report.md + report.html
       + memory log (agle run mein past decisions ka reflection)
```

## 🌐 Free Hosting — apna khud ka URL (GitHub + Streamlit Cloud)

Ye app **bilkul free** tumhare apne URL pe chala sakte ho — **[DEPLOY.md](DEPLOY.md)** mein step-by-step Hinglish guide hai (GitHub → Streamlit Community Cloud, 15 min). Cloudflare Pages iske liye sahi nahi (sirf static sites), Streamlit Cloud wahi free kaam karta hai.

## 🆓 Free API keys (2 minute ka kaam)

| Provider | Free limit | Link | Env var |
|---|---|---|---|
| **Google Gemini** | ~1500 req/day, 10 RPM | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `GOOGLE_API_KEY` |
| **Groq** (Llama 3.3 70B) | ~1000 req/day, 30 RPM | [console.groq.com/keys](https://console.groq.com/keys) | `GROQ_API_KEY` |
| **OpenRouter** (free models) | ~50 req/day | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) | `OPENROUTER_API_KEY` |

> Gemini key **must** hai (primary). Groq + OpenRouter milne se Battle Mode asli ban jata hai — teen alag model families ladti hain. Data (price/fundamentals/news) ke liye **koi key nahi chahiye**.

## 🚀 Setup

```bash
cd tradingagents-india
pip install -r requirements.txt

cp .env.example .env    # phir .env mein apni keys paste karo

# Web dashboard (recommended — browser mein sabse easy):
streamlit run app.py

# Ya CLI se:
python run.py RELIANCE
python run.py TCS --rounds 2 --lang hinglish
python run.py INFY --mock        # demo bina keys
```

Ek full run ≈ 18-25 LLM calls leta hai (free quota mein easily fit). Report `reports/` folder mein save hoti hai.

## 🎛️ Options

| Option | Values | Default |
|---|---|---|
| Battle Mode | `auto` / `off` | `auto` (saare available models) |
| Debate rounds | 1-3 | 2 |
| Language | `hinglish` / `english` / `hindi` | `hinglish` |
| Analysts | market, social, news, fundamentals | all |

## 📊 Original repo se kya alag hai?

| | TradingAgents (original) | TradingAgents India |
|---|---|---|
| Market | US-centric (default) | 🇮🇳 NSE/BSE-first, ₹ lakh/crore |
| LLM | Paid GPT-6 default | **Free tier**: Gemini + Groq + OpenRouter |
| Battle Mode | ❌ (single provider) | ⚔️ **Cross-model red-team + synthesis** |
| Data news | Alpha Vantage (US) | Google News India (ET, Moneycontrol, BS...) |
| Macro | FRED (US) | RBI/CPI/SEBI/FII/rupee/crude headlines |
| Social | StockTwits + Reddit | Reddit (Indian subs) + honest fallback |
| Benchmark | SPY | NIFTY 50 (alpha auto-calculated) |
| Memory | decision log + reflection | ✅ same, India-adapted |
| Interface | Terminal CLI | Web dashboard + CLI |
| Report | English | Hinglish 🎉 |

## 🧭 Deterministic Strategy + Walk-Forward Backtest

`deterministic-v1` mein **LLM trade economics decide nahi karta**. Historical OHLCV, completed-week candles, confirmed pivots, ATR zones, volume, NIFTY/sector relative strength aur regime se code ye fields calculate karta hai:

- detailed action: `ENTER / ADD / HOLD / WAIT / TRIM / EXIT / REVIEW`;
- active/waiting setup and exact close/volume/RS trigger;
- entry zone, structure+ATR stop and stop reason;
- T1/T2, R:R, partial exits, chandelier trail and time stop;
- integer quantity, allocation and maximum portfolio loss.

Fresh investor ke liye incomplete setup **WAIT** hai; `HOLD` sirf existing holding ke liye hai. Active occurrence bhi `ENTER` nahi banta jab tak universe-level OOS acceptance gate pass na ho. Single-stock result ko stock-specific occurrences bola jata hai—50 trades ya diversification fabricate nahi hoti.

Implemented setups:

1. weekly-trend breakout;
2. breakout retest;
3. trend pullback;
4. range breakout / volatility contraction;
5. bottoming reversal probe (small allocation, multiple confirmations).

Backtester signal close ke baad banata hai, earliest next session execute karta hai, gap-through-stop ko open par fill karta hai, ambiguous stop+target candle mein adverse ordering use karta hai, partial exits/trailing/time stop process karta hai aur every fill/reason store karta hai. Indian delivery cost assumptions (brokerage, STT, exchange/SEBI charges, GST, stamp duty, slippage, optional impact) configurable hain; **net return after costs** primary hai.

### UI

1. Sidebar mein existing holding, average price, quantity, capital, max risk (safe default 1%), max allocation, horizon aur risk profile set karo.
2. Research button deterministic current setup banata hai; expensive backtest automatically run nahi hota.
3. **Historical evidence** tab mein period/cost/window/setup settings choose karke explicit walk-forward button dabao.
4. Equity/drawdown, fills/trades, setup/regime tables aur `VALIDATED EDGE` / `NO VALIDATED EDGE` gate dekho.

### CLI

```bash
# Fresh investor (incomplete setup => WAIT)
python run.py RELIANCE --mock --capital 100000 --max-risk 1 --max-allocation 15

# Existing holding context
python run.py TCS --existing-holding --average-buy-price 3500 --quantity 10 \
  --capital 500000 --horizon positional --risk-profile conservative

# Explicit, cost-aware OOS walk-forward run (network history required)
python run.py INFY --mock --walk-forward --backtest-years 10

# Fully offline deterministic mechanics check (synthetic data is NOT edge evidence)
python scripts/synthetic_backtest.py
```

Detailed methodology, cost table and integrity limits: **[docs/BACKTEST_METHODOLOGY.md](docs/BACKTEST_METHODOLOGY.md)**

Delivery/status checklist: **[docs/DETERMINISTIC_ENGINE_CHECKLIST.md](docs/DETERMINISTIC_ENGINE_CHECKLIST.md)**

### Acceptance gate defaults

At least 50 unseen OOS trades, three test windows, positive net expectancy, PF ≥1.20, max drawdown ≤25%, three stocks and two regimes. Any failed condition returns **NO VALIDATED EDGE** and no forced fresh entry.

### Important data honesty

Yahoo history current adjusted-data vintage hai. Strict historical splits/dividends/bonuses, delistings, symbol changes, historical sector membership aur survivorship-free universe current free sources se guarantee nahi kiye ja sakte. App is limitation ko disclose karta hai; “leak-free institutional-grade data” claim nahi karta. Official NSE/BSE bhavcopy or broker adapter future mein source protocol ke through add ho sakta hai without strategy rewrite.

## ⚠️ Disclaimer

Ye project **educational research** ke liye hai — financial/investment advice **nahi**. Historical performance future returns ki guarantee nahi hai. AI models galat ho sakte hain (especially free-tier). SEBI-registered advisor ki salah ka replacement nahi hai. Apna research karo, apna risk lo.

## 🙏 Credits

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0) — original multi-agent architecture
- Data: Yahoo Finance (unofficial), Google News RSS, Reddit public feeds

## Optional: extra FREE providers (zyada capacity + battle diversity)

In sab OPTIONAL hain — jiska key mile wo Secrets mein add kar do:

| Provider | Kahan se key | Free limit |
|---|---|---|
| `GROQ_API_KEY` | console.groq.com | 14,400 req/day (llama-3.1-8b) |
| `CEREBRAS_API_KEY` | cloud.cerebras.ai | 14,400 req/day + 1M tokens/day (gpt-oss-120b) |
| `SAMBANOVA_API_KEY` | cloud.sambanova.ai | ~20 req/day (backup) |

Streamlit Secrets mein bas ek line aur:
```toml
GROQ_API_KEY = "gsk_..."
CEREBRAS_API_KEY = "csk-..."
SAMBANOVA_API_KEY = "..."
```
App khud detect karke sidebar badge aur battle rotation mein shamil kar degi.

## 🧮 Quant Engine (Qlib-inspired)

Microsoft Qlib ke Alpha158 approach se inspired deterministic layer (v1.2, Sep 2026):

- **27 point-in-time factors** (KBAR/ROC/MA/STD/Volume/RSI/MACD/Bollinger/52w)
- **ML Score 0-100** — HistGradientBoosting model, offline trained (49 NSE stocks, 6y, walk-forward val IC +0.029)
- Har report mein **ML Quant Score card + Next results date** + PM ko deterministic anchor
- Prompts calibrated (bearish≠short, scenario odds, R:R mandatory, conviction check)
- **Reflection loop** — har run ke baad lesson save → agli report mein inject

Retrain: `python3 scripts/train_ml_model.py` (monthly recommended; IC < 0.01 → model card auto-hide)
Backtest: `python3 tests/backtest_quant.py` · POC: `tests/qlib_poc.py`
Deep diagnosis: `python tests/test_diagnosis.py` — **97 tests** (lookahead-leak guard, ML determinism, regime flat/NaN guards, clamp/lock matrix, PM parse-retry wiring, report regime rows)

## 🛡️ TradeHive Layer (hard discipline — Handshakeworm/TradeHive-TradingAgents se inspired)

"Hard discipline + soft judgment" architecture — LLM jo bhi bole, CODE guard hai:

- **7-regime deterministic state machine** (confirmed_uptrend → bottoming) — 5-of-6 rule
- **Regime → position hard bands** (confirmed_downtrend = 0% LOCK; code clamp PM ke output pe)
- **Reason-first JSON** — PM pehle rationale likhta hai, decision baad mein (KV-cache chain-of-thought)
- **4-dim evidence structure** bull/bear mein (fundamentals/technicals/macro + reversal signals + conviction computation)
- **Parse-error feedback retry** — LLM ko uski JSON galti wapas dikhti hai
- Report mein: Market Regime + position band + clamp transparency note

### Deep-dive 2 (source-code level adoption)

Repo ke poore source (bull/bear researchers, RM, trader, PM, schemas, DEV_SPEC §1-7) padh
kar jo aur mila:

- **4-type reversal-signal taxonomy** (bull: topping / bear: bottoming mirror) — har type
  ki quantitative definition: (a) volume-price divergence naye 20d swing high/low par,
  (b) extreme one-sided sentiment, (c) price desensitization to catalyst, (d) decisive
  ±8% reversal day on ≥1.5x volume + confirmation
- **Anti-noise rules** — trending regime mein DEFAULT 0 signals; 2-day persistence with
  cited DATES; single-day sirf decisive events ke liye; anti-double-counting (score
  girana ≠ signal list karna); "NOT FOUND" type list-entries prohibited; RSI/MACD/
  valuation ALONE = signal nahi
- **Regime-relative scoring baselines** — downtrend mein bull technicals ka default 4-6
  (weak bull evidence wahan NORMAL hai), uptrend mein bear technicals ka default 4-6;
  normal pullback ≠ structural breakdown (bear over-scoring ka ilaaj)
- **Bear researcher ko EQUAL evidence structure** — pehle sirf bull mein tha
- **REGIME LOCK** — clamp ke baad BUY-0% inconsistent hota tha; ab decision HOLD/WAIT
  lock hota hai transparent note ke saath (TradeHive ka "clamp ke baad action re-derive")
- **Deterministic data-quality score (0-100)** — history/freshness/source agreement/
  fundamentals/news/macro/sentiment coverage; weak/stale evidence confidence, size aur
  action ko code se constrain karta hai
- **Code-level trade guard** — absolute ₹ entry/target/stop parse, BUY level direction,
  minimum 1:1.5 R:R, max 1% capital-at-risk sizing; invalid economics BUY ko HOLD banata hai
- **Historical leak suppression** — old-date reports mein current Yahoo valuation,
  Screener snapshot, live NSE quote aur current earnings calendar inject nahi hote
- **Volume-profile position structure** (deterministic) — kahan volume concentrated hai,
  overhead supply vs support-below, heaviest zones (S/R), new-highs-thin-volume /
  selling-exhaustion flags
- **Last-5-sessions table** ±3% ABNORMAL flags ke saath — LLM reversal signals mein
  specific DATES cite kar sake
- **PM engagement rules** — risk debate point-by-point address (rubber-stamp prohibited),
  survivability check, 2+ reversal signals = downgrade weight, dimension agreement/
  divergence tie-breaking
- **Regime legal-transitions context** — "consolidation se seedha confirmed_uptrend
  nahi hota" (PM/trader/risk team sab ko dikhta hai)
- **Negation filter** — `key_risks` list se "NOT FOUND"/"None"/"N/A" entries drop
  (TradeHive `filter_reversal_signals` ka adaptation)

Bands below are **% of total portfolio capital** (single-stock exposure), not % of a planned trade:

| Regime | Band | |
|---|---:|---|
| confirmed_uptrend | 10-20% | normal/full single-stock allocation |
| early_uptrend | 5-10% | starter allocation |
| consolidation | 0-5% | watch / small allocation |
| topping | 0-5% | avoid fresh entry / trim |
| early_downtrend | 0-3% | capital preservation |
| **confirmed_downtrend** | **0%** | **hard lock on fresh entry** |
| bottoming | 0-5% | small probe |
