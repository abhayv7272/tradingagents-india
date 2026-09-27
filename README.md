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
┌─ DATA (free, no keys) ───────────────────────────────┐
│ yfinance: price, indicators, financials (₹)          │
│ Google News India: company + macro (RBI, CPI, SEBI)  │
│ Reddit: Indian retail chatter                        │
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
┌─ TRADER → entry/target/stop-loss/size ───────────────┐
┌─ RISK TEAM: 😤 Aggressive ⟷ 🛡️ Conservative ⟷ 😐 Neutral ┐
┌─ PORTFOLIO MANAGER → 🎯 FINAL DECISION (JSON) ───────┐
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

## ⚠️ Disclaimer

Ye project **educational research** ke liye hai — financial/investment advice **nahi**. AI models galat ho sakte hain (especially free-tier). SEBI-registered advisor ki salah ka replacement nahi hai. Apna research karo, apna risk lo.

## 🙏 Credits

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0) — original multi-agent architecture
- Data: Yahoo Finance (unofficial), Google News RSS, Reddit public feeds
