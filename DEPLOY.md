# 🚀 Free Hosting Guide — TradingAgents India ko apne khud ke URL pe chalao

Tum is sandbox par mujhpar depend kiye bina, **bilkul free** apna personal app URL bana sakte ho. Teen options hain — **Option 1 recommended hai.**

> 💡 **Pehle ek baat:** App API keys **sirf tab** use karta hai jab tum "🚀 Research Banao" button dabate ho. Idle hone par kuch nahi kharch hota. Toh quota tumhare haath mein hai.

---

## ⭐ Option 1: Streamlit Community Cloud (BEST — 100% free, hamesha)

Ye Streamlit company ka **official free hosting** hai jo GitHub se direct connect hota hai. Jo tum Cloudflare+GitHub se karne ka soch rahe the, wahi kaam ye karta hai — aur Python apps ke liye yehi sahi tool hai (Cloudflare Pages sirf static HTML/JS sites ke liye hai).

**Tumhara final URL aisa banega:** `https://tumhara-username-tradingagents-india-app.streamlit.app`

### Step-by-step (15 minute ka kaam):

**Step 1 — GitHub account + repo:**
1. [github.com/signup](https://github.com/signup) se free account banao (agar already hai to skip)
2. GitHub par **New repository** → naam do: `tradingagents-india` → **Private** select karo (better) → Create

**Step 2 — Code upload karo:**
1. Workspace se **`tradingagents-india.zip`** download karo (ye maine bana di hai)
2. Zip ko apne computer par extract karo
3. GitHub repo page par **"uploading an existing file"** link pe click karo
4. Saari files/folders drag-drop kar do: **`app.py`, `run.py`, `requirements.txt`, `.gitignore`, `README.md`, `DEPLOY.md`, `indiaagents/` (⚠️ `indiaagents/models/` folder ZAROORI hai — `ml_score_v1.joblib` + `ml_calib_v1.json` — bina iske ML Quant Score card nahi dikhega), `scripts/`, `tests/`, docs**
5. ⚠️ **`.env` file upload MAT karo** — usme tumhari API keys hain! (zip mein bhi nahi hai, don't worry)
6. **Commit changes** dabao

**Step 3 — Streamlit Cloud par deploy:**
1. [share.streamlit.io](https://share.streamlit.io) kholo → **"Sign in with GitHub"**
2. Email continue karo (free, credit card NAHI maangta)
3. **"New app"** / **"Create app"** dabao
4. Select karo:
   - **Repository:** `<tumhara-username>/tradingagents-india`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **Advanced settings → Python version:** `3.12` (recommended)
5. **Secrets** section mein (ye tumhari keys ka safe jagah hai) ye paste karo:

```toml
GOOGLE_API_KEYS = "key1,key2,key3,key4,key6,key7,key8"
NVIDIA_API_KEY = "nvapi-..."
MISTRAL_API_KEY = "mstrl_..."
GROQ_API_KEY = "gsk-..."
OPENROUTER_API_KEY = "sk-or-..."
FRED_API_KEY = "..."
```

   (Gemini keys comma se separate — pool rotation automatic chalega. Values ko apni asli keys se replace karna! **`GROQ_API_KEY` ab zaroori hai** — Groq gpt-oss-120b free provider hai.)

6. **Deploy!** dabao
7. 2-5 minute wait karo — app build hoga aur **tumhara personal URL** ready! 🎉
8. Browser mein bookmark kar lo

**Deploy ke BAAD verify karo (ye sab dikhna chahiye):**
- Sidebar mein **⚡ Groq** badge (gpt-oss-120b) — GROQ_API_KEY kaam kar rahi hai
- Report mein **🧠 ML Quant Score card** (0-100 + IC) — models/ folder sahi upload hua
- Report mein **🛡️ Market Regime card** (HTML) / **Market Regime | Position band** row (MD) — regime engine live
- Koi bhi stock run karke REGIME CLAMP/LOCK transparency note check karo (agar regime band se bahar position nikle)

**Secrets baad mein change karna ho:** share.streamlit.io → tumhara app → ⚙️ Settings → Secrets → edit → Save (app auto-restart hoga)

### Streamlit Cloud par dhyan rakhne wali baatein:
- **App sota hai** agar koi 2-3 din use na kare — pehla open 30-60 second lagta hai (wake-up). Baaki normal speed.
- **Reports app restart hone pe clear ho sakti hain** — important report turant **⬇️ Download** button se save kar lo
- Free tier: 1 GB RAM, public URL (koi bhi khol sakta hai — chahe to URL kisi ko mat batao)
- Code update karna ho: GitHub repo mein edit karo → app **automatic redeploy** ho jata hai

---

## 🔄 Option 2: Hugging Face Spaces (backup, bhi free)

Agar Streamlit Cloud koi issue de to:
1. [huggingface.co](https://huggingface.co) par free account banao
2. **New Space** banao → **SDK: Streamlit** select karo → Public/Private
3. Wahi files upload karo (Step 2 jaisa, `.env` bina)
4. Space ke **Settings → Variables and secrets** mein same keys add karo (names same rakhna: `GOOGLE_API_KEYS`, etc.)
5. Space ka URL ready — `https://tumhara-username-tradingagents-india.hf.space`

---

## 💻 Option 3: Apne laptop/PC par (sabse reliable — koi sleep, koi limit nahi)

```bash
# 1. Python 3.10+ install karo (python.org se)
# 2. Project folder kholo, phir:
pip install -r requirements.txt

# 3. .env banao (.env.example ki copy) — apni keys paste karo
# 4. Chalao:
streamlit run app.py
# Browser mein khulega: http://localhost:8501
```

Laptop band karne pe app band ho jata hai — but keys 100% private, unlimited runs, reports hamesha save.

---

## ❓ Common Questions

**Q: Cloudflare se kyun nahi?**
Cloudflare Pages sirf **static sites** host karta hai (HTML/JS jo browser mein chalta hai). Hamara app **Python server** hai jisme API keys hide rehti hain — usko chalane ke liye Python runtime chahiye. Streamlit Community Cloud/HF Spaces ye bilkul free dete hain. (Aur browser mein keys daalna unsafe hota hai — koi bhi dekh sakta hai.)

**Q: Keys ka kharcha?**
Ek full report ≈ 22 API calls. Tumhare paas Gemini 7-key pool hai (~10,500 calls/day) + NVIDIA + Mistral — practically unlimited for personal use. App button dabane par hi calls karta hai.

**Q: Free hamesha rahega?**
Haan — Streamlit Community Cloud ka free tier permanent hai (single app ke liye). HF Spaces bhi.

**Q: Kya main dono (yahan sandbox + apna URL) use kar sakta hoon?**
Bilkul! Same code, same keys, dono jagah chalega.

---

## 🔐 Security Notes

1. `.env` ya secrets **kabhi public GitHub repo mein mat daalna**
2. Repo **Private** rakhna sabse safe hai
3. Agar kabhi keys leak hone ka shaq ho, rotate kar do:
   - Gemini: [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → delete + nayi banao
   - NVIDIA/Mistral/OpenRouter: unke consoles se
4. Gemini ki 7 working keys tumhare `.env` (sandbox) mein hain — wahi values Streamlit Secrets mein daalna

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

## Optional: Alpha Vantage data fallback (multi-source layer)

`ALPHA_VANTAGE_API_KEY` (free: alphavantage.co/support/#api-key, 25 req/day) add karne se
jab Yahoo ka data na mile / short ho (BETA jaisi stocks) tab OHLCV fallback milta hai.
**Bina is key ke bhi sab chalta hai** — Screener.in + NSE + Google News + FRED key-free hain:
```toml
ALPHA_VANTAGE_API_KEY = "YOUR_KEY"
```
