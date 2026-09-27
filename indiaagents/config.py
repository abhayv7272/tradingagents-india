"""
TradingAgents India — Configuration
Free-tier multi-provider (Gemini + Groq + OpenRouter) setup for Indian stocks.
Inspired by TauricResearch/TradingAgents (Apache-2.0), re-imagined for India.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*a, **k):  # type: ignore
        return False

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
MEMORY_DIR = REPORTS_DIR / "memory"


def _load_streamlit_secrets() -> None:
    """Streamlit Community Cloud par keys 'Secrets' section se aati hain (waha
    .env file nahi hoti). Unhe os.environ mein daal do taaki baaki code same
    kaam kare — locally ye silently skip ho jata hai."""
    try:
        import streamlit as st
        for key, value in st.secrets.items():
            if isinstance(value, str) and key.upper() not in os.environ:
                os.environ[key.upper()] = value
    except Exception:
        pass  # not running inside Streamlit, or no secrets configured — fine


_load_streamlit_secrets()

# Load .env from project root (if present) — for local runs
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Provider / model preferences
# ---------------------------------------------------------------------------

GEMINI_MODEL_PREFERENCE = [
    # Newest free-tier flash models first (validated with a live call at runtime)
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
    "gemini-3.5-flash", "gemini-flash-latest", "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite", "gemini-flash-lite-latest",
    # legacy (deprecated for new keys, kept as last resort)
    "gemini-2.5-flash", "gemini-2.0-flash",
]

GROQ_MODEL_PREFERENCE = [
    "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-70b-versatile",
]

NVIDIA_MODEL_PREFERENCE = [
    "nvidia/nemotron-3-ultra-550b-a55b",      # Nemotron 3 Ultra 550B (MoE, 55B active)
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/llama-3.1-nemotron-70b-instruct",
]

MISTRAL_MODEL_PREFERENCE = [
    "ministral-14b-latest",     # "tez" — fast, free tier
    "ministral-14b-2512",
    "mistral-small-latest",
    "mistral-medium-latest",
    "ministral-8b-latest",
]

OPENROUTER_MODEL_PREFERENCE = [
    # free (:free) models — 2026 lineup, auto-validated at runtime
    "qwen/qwen3.8-27b:free",
    "inclusionai/ling-3.0-flash-fin:free",   # finance-tuned!
    "nvidia/nemotron-3.5-lightning:free",
    "thinkingmachines/inkling:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# Provider metadata: env vars for keys, base URL (OpenAI-compatible ones),
# and a conservative minimum interval between calls to respect free RPM.
PROVIDERS: dict[str, dict] = {
    "gemini": {
        "key_env": ["GOOGLE_API_KEYS", "GOOGLE_API_KEY", "GEMINI_API_KEY"],  # pool supported
        "native": True,  # native Google AI REST API (most robust for free tier)
        "rpm": 10,       # free tier ~10 RPM per key (pool multiplies this)
        "min_interval": 6.5,
        "model_env": "GEMINI_MODEL",
        "preference": GEMINI_MODEL_PREFERENCE,
    },
    "nvidia": {
        "key_env": ["NVIDIA_API_KEY"],
        "base_url": "https://integrate.api.nvidia.com/v1",
        "rpm": 40,
        "min_interval": 2.0,
        "model_env": "NVIDIA_MODEL",
        "preference": NVIDIA_MODEL_PREFERENCE,
    },
    "mistral": {
        "key_env": ["MISTRAL_API_KEY"],
        "base_url": "https://api.mistral.ai/v1",
        "rpm": 30,
        "min_interval": 1.5,
        "model_env": "MISTRAL_MODEL",
        "preference": MISTRAL_MODEL_PREFERENCE,
    },
    "groq": {
        "key_env": ["GROQ_API_KEY"],
        "base_url": "https://api.groq.com/openai/v1",
        "rpm": 30,
        "min_interval": 4.0,
        "model_env": "GROQ_MODEL",
        "preference": GROQ_MODEL_PREFERENCE,
    },
    "openrouter": {
        "key_env": ["OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1",
        "rpm": 20,
        "min_interval": 3.5,
        "model_env": "OPENROUTER_MODEL",
        "preference": OPENROUTER_MODEL_PREFERENCE,
    },
}

# Role -> provider preference chain for BATTLE MODE.
# Different model families get adversarial roles so they genuinely disagree.
ROLE_ASSIGNMENTS: dict[str, list[str]] = {
    "market_analyst":     ["gemini", "nvidia", "mistral", "openrouter"],
    "fundamentals_analyst": ["nvidia", "gemini", "mistral", "openrouter"],
    "news_analyst":       ["gemini", "mistral", "nvidia", "openrouter"],
    "social_analyst":     ["mistral", "gemini", "nvidia", "openrouter"],
    "bull_researcher":    ["nvidia", "gemini", "mistral", "openrouter"],
    "bear_researcher":    ["mistral", "gemini", "nvidia", "openrouter"],
    "research_manager":   ["nvidia", "gemini", "mistral", "openrouter"],   # deep judge (550B)
    "battle_critic":      ["gemini", "nvidia", "mistral", "openrouter"],   # fanned out
    "battle_synthesizer": ["gemini", "nvidia", "mistral", "openrouter"],   # deep
    "trader":             ["gemini", "nvidia", "mistral", "openrouter"],
    "aggressive_analyst": ["nvidia", "gemini", "mistral", "openrouter"],
    "conservative_analyst": ["gemini", "nvidia", "mistral", "openrouter"],
    "neutral_analyst":    ["mistral", "gemini", "nvidia", "openrouter"],
    "portfolio_manager":  ["nvidia", "gemini", "mistral", "openrouter"],   # final call (550B)
    "reflection":         ["gemini", "nvidia", "mistral", "openrouter"],
}

DEEP_ROLES = {"research_manager", "battle_synthesizer", "portfolio_manager"}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    # Battle mode: "auto" (use all available providers), "off" (single provider)
    battle_mode: str = "auto"
    debate_rounds: int = 2          # bull-bear debate rounds (2 turns each round)
    risk_rounds: int = 1            # risk team passes
    report_language: str = "hinglish"  # hinglish | english | hindi
    selected_analysts: tuple = ("market", "social", "news", "fundamentals")
    news_article_limit: int = 15
    macro_news_limit: int = 12
    lookback_months: int = 6
    temperature: float = 0.3
    max_output_tokens: int = 3000
    llm_retries: int = 3
    mock_llm: bool = False          # demo mode without API keys

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        s.battle_mode = os.getenv("BATTLE_MODE", s.battle_mode).strip().lower()
        try:
            s.debate_rounds = int(os.getenv("DEBATE_ROUNDS", s.debate_rounds))
        except ValueError:
            pass
        try:
            s.risk_rounds = int(os.getenv("RISK_ROUNDS", s.risk_rounds))
        except ValueError:
            pass
        s.report_language = os.getenv("REPORT_LANGUAGE", s.report_language).strip().lower()
        s.mock_llm = os.getenv("MOCK_LLM", "0").strip().lower() in ("1", "true", "yes")
        return s


def get_api_keys(provider: str) -> list[str]:
    """All non-empty API keys for a provider (comma-separated pools supported)."""
    keys: list[str] = []
    for env in PROVIDERS[provider]["key_env"]:
        raw = (os.environ.get(env) or "").strip()
        if raw:
            keys += [k.strip() for k in raw.split(",") if k.strip()]
    # dedupe, keep order
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def get_api_key(provider: str) -> str | None:
    ks = get_api_keys(provider)
    return ks[0] if ks else None


def available_providers() -> list[str]:
    """Providers that have at least one API key configured."""
    return [p for p in PROVIDERS if get_api_keys(p)]


def language_instruction(lang: str) -> str:
    """Instruction appended to every agent prompt so output is user-readable."""
    if lang == "hinglish":
        return (
            "\n\nIMPORTANT — OUTPUT LANGUAGE (Hinglish): Write your full answer in Hinglish — "
            "Roman-script Hindi mixed naturally with English, exactly like an Indian finance "
            "YouTuber or a savvy Mumbai analyst explains things. Example style: "
            "\"RELIANCE ka revenue growth solid hai, margins thode pressure mein hain, but O2C "
            "segment demand cycle upar hai.\" Narration Hindi-me, technical/finance terms English "
            "me (RSI, MACD, ROE, market cap, P/E). Currency INR (₹) and Indian units "
            "(lakh/crore) use karo. Never use Devanagari script; keep it Roman."
        )
    if lang == "hindi":
        return (
            "\n\nIMPORTANT — OUTPUT LANGUAGE: पूरा उत्तर हिंदी (देवनागरी) में लिखें। "
            "तकनीकी वित्तीय शब्द (RSI, ROE, P/E आदि) अंग्रेज़ी में रख सकते हैं। "
            "करेंसी ₹ और लाख/करोड़ का प्रयोग करें।"
        )
    return "\n\nOUTPUT LANGUAGE: English. Use INR (₹) and Indian units (lakh/crore)."
