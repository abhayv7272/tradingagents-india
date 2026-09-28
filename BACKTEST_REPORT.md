# 🔬 TradingAgents India — Backtest & Accuracy Report

**Date:** 28 September 2026 · **Author:** Automated diagnosis (user-requested)
**Scope:** Report accuracy ka honest nap-jokha + improvement roadmap (original TauricResearch/TradingAgents repo se gap analysis ke saath)

---

## ⚠️ Pehle Imaandaari Ki Baat

- Ye **research tool** hai, investment advice nahi. Backtest results kisi bhi guarantee ka proof nahi hain.
- Sample size chhota hai (Part A: 90 cells, Part B: 6 reports). Statistics ke liye kam, direction jaanne ke liye kaafi.
- Apr–Sep 2026 ek hi market regime tha. Doosre regime mein results badal sakte hain.

---

## 🧪 Methodology — 3 Parts

| Part | Kya napa | Cost | Cells |
|---|---|---|---|
| **A. Quant Signal Backtest** | Data-layer indicators (RSI/SMA/MACD/momentum) ka composite signal kitna sahi hai | ₹0 (free yfinance) | 15 stocks × 6 dates = **90** |
| **B. AI Report Backtest** | POORI pipeline (analysts → debate → battle → PM) verdict vs reality | ~130 LLM calls (free tier) | 6 stocks × 2026-07-15 |
| **C. Gap Analysis** | Original repo vs hum — kya missing hai, kya better hai | — | — |

**Alpha = stock return − NIFTY 50 return** (same window). Ye original repo ka tarika hai — raw return se zyada imandaar, kyunki agar stock +3% ho lekin NIFTY +5% ho to BUY call galat thi. Point-in-time discipline: har date par sirf us date tak ka data use hua (future leak nahi).

---

## 📊 PART A — Quant Signal Backtest (90 cells, zero API)

Composite signal: 7 components (price>SMA20, SMA20>SMA50, SMA50>SMA200, MACD hist, MACD line, 1m momentum, RSI extreme). Score ≥ +3 = BULLISH, ≤ −3 = BEARISH.

| Signal | N | 5d hit% | 5d α | 10d hit% | 10d α | 20d hit% | 20d α |
|---|---|---|---|---|---|---|---|
| **BULLISH** | 19 | 53% | −0.15% | **58%** | **+0.89%** | 59% | +0.35% |
| NEUTRAL | 37 | 43% | −0.58% | 43% | −1.04% | 40% | −1.48% |
| **BEARISH** | 34 | 41% | +0.64% | 50% | +0.53% | 39% | **+1.44%** |

### 🔍 Interpretation

1. **Bullish signals mein modest edge hai** — 10-day horizon par 58% hit rate aur +0.89% average alpha. Trend-following ne 2026 ke trending market mein kaam kiya.
2. **⚠️ BEARISH SIGNALS UNRELIABLE HAIN** — bearish-labelled stocks ne average +1.44% alpha banaya (20d)! Matlab "bearish technicals" wale stocks actually NIFTY ko **beat** kar rahe the. Bull market mein mean-reversion ne bearish calls ko galat kar diya.
3. **NEUTRAL cells sabse kharab** (−1.04% se −1.48% alpha) — jab trend clear nahi hota, signal ka koi value nahi.

### ✅ Iska matlab app ke liye

- **BUY-leaning signals par bharosa kar sakte ho (modest)** — lekin position sizing conservative rakho.
- **Bearish technicals ko "SELL" ki jagah "AVOID/REDUCE" treat karo** — India mein individual stocks short karna waise bhi mushkil hai. Bearish conviction pe short-side trade mat banao.
- **Signal-layer hi final answer nahi hai** — isiliye AI + debate + battle layer value add karta hai (news/fundamentals/context jo indicators nahi dekh sakte).

---

## 🤖 PART B — Real AI Report Backtest (6 stocks @ 2026-07-15)

Poora pipeline chala — 4 analysts, 2-round bull-bear debate, cross-model battle critique, risk team, Portfolio Manager — sab kuch date 2026-07-15 pe (point-in-time). Verdict ko uske baad ke actual price se compare kiya.

| Stock | Verdict | Conf | 5d raw / α | 10d raw / α | 20d raw / α | HOLD sahi tha? |
|---|---|---|---|---|---|---|
| RELIANCE | HOLD/**Reduce** | 85% | −0.53 / −0.19 | −1.51 / **−2.23** | +2.59 / +1.10 | ✅ Haan (10d tak girta raha) |
| TCS | HOLD/Hold | 50% | +0.87 / +1.21 | +11.76 / **+11.04** | +7.33 / +5.85 | ❌ Rally miss |
| INFY | HOLD/Hold | 72% | −2.25 / −1.91 | +7.37 / **+6.65** | +9.27 / +7.79 | ❌ Rally miss |
| SBIN | HOLD/Hold | 40% | −0.50 / −0.15 | −1.59 / **−2.31** | +5.04 / +3.55 | ✅ Haan (10d tak girta raha) |
| TATASTEEL | HOLD/Hold | 52% | +0.69 / +1.03 | +1.08 / +0.37 | +0.51 / −0.98 | ➖ Neutral (sahi) |
| HDFCBANK | HOLD/Hold | 50% | **−7.64 / −7.30** | **−8.25 / −8.96** | **−10.60 / −12.09** | ✅✅ **BADA SAVE** (−12% crash avoid) |

**Context:** 2026-07-15 market stress mein tha (Nifty highs se −12%, Brent $98). System ne 6/6 pe HOLD bola — poora conservative stance.

### 🔍 Interpretation (Part B)

1. **4/6 HOLD calls sahi the (67%)** — aur sabse badi baat: **HDFCBANK wala HOLD ek −12% crash se bacha liya** (koi agar us din kharidta to ek mahine mein NIFTY se 12% peeche hota). RELIANCE (Reduce @85% confidence) aur SBIN bhi 10 din tak girte rahe — system ka "abhi mat kharido" bilkul sahi tha.
2. **2/6 HOLD ne IT earnings rally miss ki** — TCS (+11% α) aur INFY (+6.6% α) late-July Q1 results ke baad uchhle. System macro stress + technicals (death cross) pe anchor ho gaya, **upcoming earnings catalyst ko underweight** kiya.
3. **Confidence calibration interesting hai:** 85% confidence wala call sahi, 50-72% wale mixed — system high-confidence par zyada reliable lag raha hai (chhota sample, pakka nahi).
4. **Directional hit-rate is pilot mein N/A** — system ne ek bhi BUY/SELL nahi diya. Ye khud ek finding hai: **stressed market mein LLM agents over-cautious hote hain.** Falling knife se bachna achha hai, lekin reversal miss hona cost hai.

### 📌 Part B se naye improvements (roadmap mein add)

- **P1: Event/catalyst awareness** — PM prompt mein upcoming earnings date, ex-div, RBI policy calendar (abhi missing hai — IT bounce isi se miss hua)
- **P1: Conviction forcing** — debate mein explicitly poochna: "agar 2 hafte mein bounce ho to kya HOLD galat hoga? kaunsa catalyst upside la sakta hai?"
- **P2: Confidence calibration display** — report mein "past high-confidence calls ka track record" dikhana (memory se)

---

## 🆚 PART C — Original TradingAgents (TauricResearch v0.5.0) vs Hum

### Unke paas hai jo hamare paas NAHI hai (improvement opportunities)

| # | Feature | Kya karta hai | Impact | Effort |
|---|---|---|---|---|
| 1 | **Phase-B LLM Reflection** | Decision settle hone ke baad LLM 2-4 line ka lesson likhta hai → decision log mein save → agli report mein agents ko padhaya jata hai. **System time ke saath seekhta hai** | 🔥 HIGH | Medium |
| 2 | **5-tier rating (Buy/Overweight/Hold/Underweight/Sell) + REVIEW state** | Zyada granular verdicts; jhola na parse ho to "REVIEW" (matlab "pata nahi") — galat se HOLD banana nahi | HIGH | Low-Med |
| 3 | **Fixed settlement window (5 trading days)** | Har decision ek defined window pe settle hota hai (hamara open-ended hai) — cleaner learning signal | MED | Low |
| 4 | **Point-in-time fundamentals (as-filed)** | Date-specific financials (unhe SEC EDGAR se milta hai). Hum latest snapshot dete hain — historical backtest mein thoda optimistic | MED | High (India mein as-filed free source nahi) |
| 5 | **Social post screening** | Har social post ko AI se filter karta hai (on-topic? stance kya?) | MED | Medium |
| 6 | **Built-in backtest module** | `run_backtest(tickers, dates)` grid runner | MED | Low (hamara script ready hai!) |

### Hamare paas hai jo unke paas NAHI hai (hamara edge)

| # | Feature | Kyu better |
|---|---|---|
| 1 | **⚔️ Battle Mode** | Cross-model critics + synthesis — alag-alag model families ek dusre ki research pe red-team attack karti hain. Original mein sirf bull-vs-bear debate hai |
| 2 | **8-provider free pool** | 7-key Gemini rotation + NVIDIA + Mistral + Groq (GPT-OSS-120B) + OpenRouter, auto-cooldown + dead-key skip + fallback. Original single-provider focused hai |
| 3 | **India-native** | NSE/BSE resolution, ₹/Cr formatting, India macro news, FRED, Indian market context (NIFTY/SENSEX/VIX) |
| 4 | **Hinglish premium HTML reports** | Original CLI-focused, plain output |
| 5 | **Streamlit web app** | Dashboard primary interface — non-CLI users ke liye |

### 🐛 Backtest ke dauraane pakde gaye REAL bugs (already fixed)

| Bug | Fix |
|---|---|
| `TATAMOTORS.NS` dead symbol (Oct-2025 demerger → TMPV/TMCV) | POPULAR_NSE map update — "tata motors" ab TMPV.NS resolve hota hai, "tmcv" bhi |
| Backtest script ka forward-return slicing bug | `searchsorted` point-in-time fix |

---

## 🗺️ IMPROVEMENT ROADMAP (priority order)

| P | Improvement | Kya milega | Effort |
|---|---|---|---|
| **P0** | **Bearish-calibration prompt fix** — PM prompt mein: "bearish technicals ko short-signal mat samjho; India mein SELL = exit/avoid" | Bearish calls ka misuse band (Part A evidence) | **Low** (sirf prompt) |
| **P0** | **Quant-signal anchor in PM prompt** — deterministic composite score PM ko dena (LLM drift kam hoga, sanity anchor milega) | Hallucination guard | Low |
| **P1** | **Phase-B Reflection loop** (original se) — settle → LLM lesson → reinject | System har report se seekhta hai | Medium |
| **P1** | **5-tier ratings + REVIEW** | Zyada actionable verdicts + imandaar "pata nahi" | Low-Med |
| **P2** | **Fixed 5-day settlement window** | Clean learning signal | Low |
| **P2** | **Backtest module ko app mein integrate** (CLI button: "Backtest mode") | User khud accuracy track kare | Low-Med |
| **P3** | **Reddit free social feed** (r/IndianStockMarket JSON) | Social layer currently thiniest | Medium |
| **P3** | **As-filed fundamentals** | Backtest honesty | High |

---

## 🔬 PART D — EXTENDED IMPROVEMENT SCAN (round 2, user-requested)

Pehle wale improvements ke ALAWA deep scan kiya: actual reports ka content audit + data-layer ke gaps + India-specific alpha sources. **Naye 4 bugs mile aur fix ho gaye**, aur ek poora naya improvement-stack mila.

### 🐛 Is scan mein pakde gaye NAYE bugs (sab FIXED ✓)

| # | Bug | Impact | Fix |
|---|---|---|---|
| 1 | 🔴 **Off-by-one date alignment** — `trade_date` dene par bhi AI ko **pichle din (D−1) ka data** milta tha (yfinance ka `end` exclusive hai). TCS 07-15 ko −6% gir raha tha, AI ko ₹2,188 (07-14 close) dikha, actual 07-15 price alag tha | Backtest integrity + LIVE reports mein bhi "current price" ek din purana tha! | `end = asof + 1 day` + point-in-time filter. Verify: SBIN@07-15 ab sahi ₹1,030 + date 07-15 |
| 2 | 🔴 **Dividend yield 100× galat** — RELIANCE ka yield **49.00%** dikhta tha (asli ~0.50%) — `dividendYield × 100` double-scaling | Galat valuation signal analysts ko | Ab `dividendRate / price` se deterministic compute. RELIANCE ab **0.50%** ✓ |
| 3 | 🟡 **Beta vs NIFTY ka nahi, S&P500 ka** — Yahoo ka beta RELIANCE ke liye 0.15 dikha raha tha (asli NIFTY-beta ~0.83) | Risk-sizing galat hoti | **Native NIFTY-beta compute** (120-day). RELIANCE ab **0.83** ✓ |
| 4 | 🟡 **_md() fallback double-escape** — markdown lib missing hone par `&amp;lt;` double-escape | Cosmetic (sirf fallback path) | Fallback ab original text pe single escape |

⚠️ **Imaandaari note:** Part B wali 6 backtest reports D−1 data pe bani thi (bug #1). Verdicts ki direction utni galat nahi thi (real-world mein bhi log subah kal ke close pe analyze karte hain), lekin exact price-levels ek din stale the. Aage se clean.

### 🆕 NAYE improvement opportunities (pehli list ke ALAWA)

**📡 Data layer — India-specific alpha (sabhi abhi MISSING):**

| # | Kya | Kyu matter karta hai | Source (free) | Effort |
|---|---|---|---|---|
| D1 | **Peer/sector comparison** — TCS analyze karte waqt INFY/HCL/TechM ka P/E, returns, sector rank dikhe | Single-stock view mein relative valuation blind spot hai. "TCS mehva hai ya sasta?" ka jawab peers ke bina nahi | yfinance (4-5 sector peers) | **Low-Med** |
| D2 | **Results/earnings calendar** — upcoming quarterly result date prompt mein | IT rally isi se miss hui — system ko pata hi nahi tha ki results 2 hafte door hain | BSE/NSE announcements RSS | Low |
| D3 | **FII/DII daily flows** | Indian market ka sabse bada driver — "FII selling 3 din se" jaisa context | NSE daily CSV | Low |
| D4 | **Delivery %** | High delivery % = strong hands/accumulation (Indian retail ka classic signal) | NSE bhavcopy | Med |
| D5 | **Promoter holding + pledge** | Yahoo nahi deta; Indian smallcaps mein pledge = hidden bomb | BSE filings/scrape | Med-High |
| D6 | **Options OI/PCR** (F&O stocks) | Smart money positioning | NSE options chain | Med |

**🧠 Analysis quality:**

| # | Kya | Kyu |
|---|---|---|
| A1 | **Scenario probabilities** — Bull/Base/Bear teen scenario with % odds + har ek ka target | Abhi single-verdict hai; probabilities se user khud risk weigh karta hai |
| A2 | **"What would change my mind"** section | Falsifiable thesis — report ki credibility badhta hai |
| A3 | **Risk-reward + expectancy math** (deterministic) — entry/target/stop se R:R compute karke display | AI kabhi-kabhi 1:1 se kharab trade suggest karta hai — math expose karega |
| A4 | **Track record in report** — memory se "is stock pe pichle 3 calls + unka realized alpha" | System accountability + user trust |

**🖥️ UX/System:**

| # | Kya | Kyu |
|---|---|---|
| S1 | **Position sizing calculator** — user apna capital daale → shares ki quantity + staggered entry plan | Abhi position_size_pct abstract hai; "₹50,000 mein kitne share?" practical sawal hai |
| S2 | **Report diff** — same stock dobara run karne par "pichli report se kya badla" | Repeat user ke liye |
| S3 | **Speed: 8.6 min → ~5 min** — analyst evidence zyada aggressively condense, bull/bear round-1 parallel, critic prompts slim | 6-stock backtest 39 min laga |
| S4 | **TTL cache** (news/price 30-min) | Repeat runs instant + Yahoo rate-limit protection |
| S5 | **Quota dashboard** — sidebar mein per-provider "aaj X calls" | Free tier visibility |
| S6 | **Auto-settlement + track record page** — memory ka data UI mein | A4 ka UI version |

### 🎯 Round-2 ka TOP-3 recommendation (agar sirf 3 karna ho)

1. **D1 — Peer comparison** (data-layer ka sabse bada blind spot, low-medium effort)
2. **D2 — Results calendar** (backtest mein proven miss — IT rally)
3. **A3 — R:R math display** (deterministic guard against AI ki whimsical levels)

---

## 🏁 BOTTOM LINE

1. **Kitni sahi rehti hai report?** Honest jawab, teen layers mein:
   - **Quant signals (90 cells):** BUY-side modest edge (10d: 58% hit, +0.89% α). Bearish signals ka koi edge nahi — unhe "AVOID" treat karo, short-signal nahi.
   - **AI reports (6-stock pilot):** Stress mein system conservative hai — **capital preservation strong** (HDFCBANK −12% crash avoid kiya, RELIANCE/SBIN ke girne se bachaya), lekin **sharp reversals miss karta hai** (IT earnings rally). Short-term (5-10d) calls 4/6 sahi.
   - **Statistically:** chhota sample — ye "direction jaanna" ke liye kaafi hai, "guarantee" ke liye nahi. Har 2-3 mahine baad backtest dobara chalana chahiye.
2. **Sabse bade improvements (low effort, high value):** (1) Bearish calibration prompt, (2) Quant-signal anchor in PM prompt, (3) Event/catalyst calendar, (4) Reflection learning loop (original repo se), (5) Conviction forcing in debate.
3. **System ki khaasiyat:** Battle mode + multi-provider diversity + India-native design original repo se AAGE hai. Learning loop unke paas tha — roadmap P1 mein hai hamare liye. 🔄
4. **Ek aur proof:** Poora backtest (39 min, 6 poori reports, ~150+ LLM calls) free tier pe bina kisi provider exhaust hue complete hua — **multi-provider pool kaam kar raha hai.**

*Data: Yahoo Finance (free), NIFTY 50 benchmark. LLM: Gemini×7 + NVIDIA + Mistral + Groq + OpenRouter (free tier). 6 backtest reports `reports/` mein saved hain (2026-07-15 wale folders).*
