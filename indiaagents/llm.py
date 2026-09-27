"""
LLM Engine — free-tier multi-provider with battle mode support.

Three providers, one engine:
  * Gemini  — native Google AI REST API (best free quota: ~1500 req/day)
  * Groq    — OpenAI-compatible (Llama models, fast)
  * OpenRouter — OpenAI-compatible (:free models, 50 req/day)

Features:
  * Per-provider rate pacing (free RPM limits)
  * Retries with exponential backoff on 429/5xx
  * Automatic fallback to the next provider in the role's chain
  * Auto model detection (picks the best free model available to your key)
  * Usage stats -> "Model Battle Scoreboard" in the report
  * Mock mode for demo runs without any keys
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field

import requests

from .config import (
    DEEP_ROLES,
    PROVIDERS,
    ROLE_ASSIGNMENTS,
    Settings,
    get_api_keys,
)

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ---------------------------------------------------------------------------
# Usage stats
# ---------------------------------------------------------------------------

@dataclass
class CallStat:
    role: str
    provider: str
    model: str
    ok: bool
    latency_s: float
    chars: int = 0
    note: str = ""


@dataclass
class EngineStats:
    calls: list[CallStat] = field(default_factory=list)
    lock = threading.Lock()

    def add(self, stat: CallStat):
        with self.lock:
            self.calls.append(stat)

    def by_provider(self) -> dict:
        out: dict[str, dict] = {}
        with self.lock:
            for c in self.calls:
                d = out.setdefault(c.provider, {"ok": 0, "fail": 0, "models": set(),
                                                "roles": []})
                d["ok" if c.ok else "fail"] += 1
                d["models"].add(c.model)
                if c.ok:
                    d["roles"].append(c.role)
        for d in out.values():
            d["models"] = sorted(d["models"])
        return out

    def total(self) -> tuple[int, int]:
        ok = sum(1 for c in self.calls if c.ok)
        return ok, len(self.calls) - ok


# ---------------------------------------------------------------------------
# Provider clients
# ---------------------------------------------------------------------------

class BaseProvider:
    name: str = "?"

    def __init__(self, cfg: dict, api_key: str, settings: Settings):
        self.cfg = cfg
        self.api_key = api_key
        self.settings = settings
        self.model: str | None = None  # resolved lazily
        self._lock = threading.Lock()  # pacing lock
        self._last_call = 0.0

    # ---- pacing -----------------------------------------------------------
    def _pace(self):
        """Block until we respect the provider's min interval (free RPM)."""
        with self._lock:
            wait = self._last_call + self.cfg["min_interval"] - time.time()
            if wait > 0:
                time.sleep(min(wait, 90))
            self._last_call = time.time()

    # ---- interface --------------------------------------------------------
    def detect_model(self) -> str:
        raise NotImplementedError

    def chat(self, system: str, user: str, temperature: float, max_tokens: int) -> str:
        raise NotImplementedError

    def _headers(self) -> dict:
        return {"Content-Type": "application/json"}


class GeminiProvider(BaseProvider):
    """Native Google AI (Generative Language) REST API — the free-tier workhorse.
    Supports a KEY POOL: round-robin across keys, per-key pacing, auto-rotation
    on 429/403, so N keys give N× the free-tier RPM/RPD quota."""
    name = "gemini"

    def __init__(self, cfg: dict, api_keys: list[str], settings: Settings):
        super().__init__(cfg, api_keys[0] if api_keys else "", settings)
        self.keys = list(api_keys)
        self._key_idx = 0
        self._key_lock = threading.Lock()
        self._key_last_call = {i: 0.0 for i in range(len(self.keys))}
        self._key_dead: set[int] = set()
        self._key_cooldown: dict[int, float] = {}

    # ---- key rotation ------------------------------------------------------
    def _next_key(self) -> tuple[int, str]:
        """Pick the next usable key: round-robin, skipping dead/cooling keys.
        Never sleeps while holding the lock (that would serialize the pool)."""
        while True:
            with self._key_lock:
                now = time.time()
                n = len(self.keys)
                # drop expired cooldowns
                for i in [i for i, t in self._key_cooldown.items() if t <= now]:
                    del self._key_cooldown[i]
                usable = {i for i in range(n)
                          if i not in self._key_dead and i not in self._key_cooldown}
                if usable:
                    # TRUE round-robin: scan starting from _key_idx
                    for offset in range(n):
                        idx = (self._key_idx + offset) % n
                        if idx in usable:
                            self._key_idx = (idx + 1) % n  # next scan starts after this
                            return idx, self.keys[idx]
                soonest = min(self._key_cooldown.values(), default=now + 5)
                wait = max(0.2, min(soonest - now, 30))
            time.sleep(wait)  # sleep OUTSIDE the lock

    def _pace_key(self, idx: int):
        """Respect per-key RPM. Reserves the next slot atomically; sleeps
        outside the lock so other threads can grab other keys meanwhile."""
        while True:
            with self._key_lock:
                now = time.time()
                wait = self._key_last_call.get(idx, 0) + self.cfg["min_interval"] - now
                if wait <= 0:
                    self._key_last_call[idx] = now  # reserve slot
                    return
            time.sleep(min(wait, 5))  # sleep outside lock, re-check after

    def _mark(self, idx: int, status: str):
        with self._key_lock:
            if status == "dead":
                self._key_dead.add(idx)
            elif status == "cooldown":
                self._key_cooldown[idx] = time.time() + 65

    def _alive_count(self) -> int:
        with self._key_lock:
            return len([i for i in range(len(self.keys)) if i not in self._key_dead])

    def _headers_for(self, key: str) -> dict:
        return {"Content-Type": "application/json", "x-goog-api-key": key}

    # ---- model detection with live validation ------------------------------
    def detect_model(self) -> str:
        if self.model:
            return self.model
        import os
        override = (os.environ.get(self.cfg["model_env"]) or "").strip()
        if override:
            self.model = override
            return self.model
        names: list[str] = []
        idx, key = self._next_key()
        try:
            r = requests.get(f"{GEMINI_BASE}/models?pageSize=200",
                             headers=self._headers_for(key), timeout=20)
            if r.status_code == 200:
                names = [m["name"].split("/")[-1]
                         for m in r.json().get("models", [])
                         if "generateContent" in m.get("supportedGenerationMethods", [])]
        except Exception as e:
            logger.warning("Gemini model list failed: %s", e)
        # candidates: preference order first, then any other flash models
        cands = [p for p in self.cfg["preference"] if p in names]
        extra = sorted(
            n for n in names
            if n not in cands and "gemini" in n and "flash" in n
            and not any(x in n for x in ("image", "tts", "preview", "robotics",
                                         "computer-use", "omni", "transcribe"))
        )
        cands += extra
        # LIVE validation: deprecated models still appear in the list (e.g. 2.5-flash
        # 404s for new keys). Verify each candidate with a tiny real call.
        for cand in cands:
            try:
                self._pace_key(idx)
                r = requests.post(
                    f"{GEMINI_BASE}/models/{cand}:generateContent",
                    headers=self._headers_for(key),
                    json={"contents": [{"parts": [{"text": "Reply: OK"}]}],
                          "generationConfig": {"maxOutputTokens": 50}},
                    timeout=45)
                if r.status_code == 200 and "candidates" in r.json():
                    self.model = cand
                    return self.model
                logger.info("gemini model %s rejected: HTTP %s", cand, r.status_code)
            except Exception as e:
                logger.info("gemini model %s probe failed: %s", cand, e)
        self.model = cands[0] if cands else "gemini-3.8-flash"
        return self.model

    # ---- chat ----------------------------------------------------------------
    def chat(self, system, user, temperature, max_tokens):
        model = self.detect_model()
        payload_base = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        last_err = None
        attempts = 0
        max_attempts = (self.settings.llm_retries + 1) * 2
        while attempts < max_attempts:
            attempts += 1
            if self._alive_count() == 0:
                raise ProviderError("Gemini: saare pool keys dead/401 ho gaye")
            idx, key = self._next_key()
            self._pace_key(idx)
            url = f"{GEMINI_BASE}/models/{model}:generateContent"
            # first attempt with thinking budget 0 (fast + token-efficient);
            # some models reject it, so fall back to no thinkingConfig on 400
            for use_thinking_cfg in (True, False):
                payload = json.loads(json.dumps(payload_base))
                if use_thinking_cfg and "flash" in model:
                    payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
                try:
                    r = requests.post(url, headers=self._headers_for(key),
                                      json=payload, timeout=240)
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
                    break
                if r.status_code in (401, 403):
                    self._mark(idx, "dead")
                    last_err = f"key#{idx + 1} unauthorized"
                    break  # rotate key
                if r.status_code == 429 or r.status_code >= 500:
                    self._mark(idx, "cooldown")
                    last_err = f"key#{idx + 1} rate-limited ({r.status_code})"
                    break  # rotate key
                if r.status_code == 400:
                    err_txt = r.text[:400]
                    if "thinking" in err_txt.lower() and use_thinking_cfg:
                        continue  # retry same key without thinkingConfig
                    last_err = f"400: {err_txt[:200]}"
                    break
                try:
                    r.raise_for_status()
                    data = r.json()
                    cands = data.get("candidates", [{}])
                    parts = (cands[0].get("content") or {}).get("parts", [])
                    # thinking models may return thought parts — keep final text only
                    text = "".join(p.get("text", "") for p in parts
                                   if p.get("text") and not p.get("thought")).strip()
                    if text:
                        return text
                    # maybe thoughts consumed the budget — retry with more tokens
                    last_err = "empty response (thinking ate the budget?)"
                    payload_base["generationConfig"]["maxOutputTokens"] = (
                        int(payload_base["generationConfig"]["maxOutputTokens"]) + 1500)
                    break
                except Exception as e:
                    last_err = f"{type(e).__name__}: {str(e)[:150]}"
                    break
            time.sleep(min(1.5 * attempts, 10))
        raise ProviderError(f"Gemini failed after {attempts} attempts: {last_err}")


class OpenAICompatProvider(BaseProvider):
    """Groq / OpenRouter via the OpenAI SDK (chat completions)."""
    name = "compat"

    def __init__(self, name: str, cfg: dict, api_key: str, settings: Settings):
        super().__init__(cfg, api_key, settings)
        self.name = name
        from openai import OpenAI
        self.client = OpenAI(base_url=cfg["base_url"], api_key=api_key, timeout=180,
                             max_retries=0)

    def detect_model(self) -> str:
        if self.model:
            return self.model
        import os
        override = (os.environ.get(self.cfg["model_env"]) or "").strip()
        if override:
            self.model = override
            return self.model
        names: list[str] = []
        try:
            if self.name == "openrouter":
                # :free models only, keep the list lean
                r = requests.get(f"{self.cfg['base_url']}/models", timeout=30)
                r.raise_for_status()
                names = [m["id"] for m in r.json().get("data", [])
                         if m["id"].endswith(":free")]
            else:
                names = [m.id for m in self.client.models.list().data]
        except Exception as e:
            logger.warning("%s model list failed: %s", self.name, e)
        keyword = ["instruct", "chat"] if self.name == "openrouter" else ["versatile", "instruct"]
        cands = _pick_list_by_preference(names, self.cfg["preference"], keyword)
        if not cands and names:
            cands = [names[0]]
        # OpenRouter free models are intermittently rate-limited upstream —
        # probe the top candidates with a tiny live call and pick one that works.
        if self.name == "openrouter" and cands:
            for cand in cands[:3]:
                try:
                    self._pace()
                    resp = self.client.chat.completions.create(
                        model=cand,
                        messages=[{"role": "user", "content": "Reply: OK"}],
                        max_tokens=200, temperature=0)
                    if (resp.choices[0].message.content or "").strip():
                        self.model = cand
                        return self.model
                except Exception as e:
                    logger.info("openrouter probe %s failed: %s", cand, str(e)[:100])
        self.model = cands[0] if cands else "unknown"
        return self.model

    def chat(self, system, user, temperature, max_tokens):
        self._pace()
        model = self.detect_model()
        last_err = None
        for attempt in range(self.settings.llm_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    return text
                last_err = "empty response"
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
            _backoff(attempt)
            self._pace()
        raise ProviderError(f"{self.name} failed: {last_err}")


class ProviderError(Exception):
    pass


def _pick_by_preference(available: list[str], preference: list[str], keywords: list[str]) -> str | None:
    picks = _pick_list_by_preference(available, preference, keywords)
    return picks[0] if picks else None


def _pick_list_by_preference(available: list[str], preference: list[str],
                             keywords: list[str]) -> list[str]:
    """Ordered candidate list: preference matches first, then keyword matches."""
    a = set(available)
    out: list[str] = []
    for p in preference:
        if p in a:
            out.append(p)
    if not out:
        # partial match (model names keep changing)
        for p in preference:
            base = p.split(":")[0]
            for cand in sorted(available):
                if cand.split(":")[0] == base or base in cand:
                    out.append(cand)
                    break
    if not out:
        for kw in keywords:
            for cand in sorted(available):
                if kw in cand and "mini" not in cand:
                    out.append(cand)
                    break
    if not out and available:
        out = [sorted(available)[0]]
    return out


def _backoff(attempt: int, retry_after: str | None = None):
    if retry_after:
        try:
            time.sleep(min(float(retry_after), 60))
            return
        except ValueError:
            pass
    time.sleep(min(2 ** attempt + random.random(), 30))


# ---------------------------------------------------------------------------
# Mock provider (demo mode — no keys needed)
# ---------------------------------------------------------------------------

class MockProvider(BaseProvider):
    name = "mock"

    def __init__(self, settings: Settings):
        super().__init__({}, "mock-key", settings)

    def detect_model(self) -> str:
        self.model = "mock-model (demo)"
        return self.model

    def chat(self, system, user, temperature, max_tokens):
        self._pace = lambda: None  # no pacing in mock
        time.sleep(0.4)
        return _mock_response(system, user)


def _mock_response(system: str, user: str) -> str:
    """Deterministic-ish demo answers so the full pipeline runs without keys."""
    s = (system + user).lower()
    if "portfolio manager" in s or "final decision" in s or "json" in s:
        return (
            '```json\n'
            '{\n'
            '  "decision": "BUY",\n'
            '  "confidence": 64,\n'
            '  "rating": "Buy",\n'
            '  "rationale": "DEMO MODE: Company ke fundamentals stable hain aur technicals '
            'oversold zone se recovery dikha rahe hain. News flow mixed hai par long-term '
            'view positive banta hai. Ye ek demonstration answer hai — real analysis ke liye '
            'free API keys add karo.",\n'
            '  "key_risks": ["Global market weakness", "Input cost pressure", "DEMO MODE — real keys ke bina ye final decision example hai"],\n'
            '  "entry_zone": "current price ke aas-paas",\n'
            '  "target": "8-12% upside (demo)",\n'
            '  "stop_loss": "6-8% below entry (demo)",\n'
            '  "position_size_pct": 3,\n'
            '  "timeframe": "1-3 months (demo)"\n'
            '}\n'
            '```'
        )
    if "bull" in s:
        return ("Bull Analyst (DEMO): Growth story strong hai — revenue CAGR consistent, "
                "market leadership solid, aur management guidance confident. Valuation "
                "historical average se thoda neeche hai, jo entry opportunity deta hai. "
                "Sector tailwinds bhi saath de rahe hain. Bear ke risk points real hain, "
                "par risk-reward ratio abhi favor kar raha hai.")
    if "bear" in s:
        return ("Bear Analyst (DEMO): Dekhiye, near-term headwinds kaafi hain — margin "
                "pressure, competition intensity badh rahi hai, aur global cues unpredictable "
                "hain. Price important moving averages ke neeche trade kar raha hai. Bull "
                "optimistic hai, par downside protection pehle sochna chahiye.")
    if "technical" in s or "indicator" in s or "market analyst" in s:
        return ("DEMO Technical Report: Price last 6 months mein range-bound raha hai. "
                "RSI neutral zone (50-55) mein hai, MACD flat, aur price 50-SMA ke aas-paas "
                "ghum raha hai. Volume average se normal hai.\n\n"
                "| Indicator | Value | Signal |\n|---|---|---|\n"
                "| RSI (14) | ~52 | Neutral |\n| MACD | Flat | Neutral |\n"
                "| 50-SMA | Near price | Support |\n| ATR | Moderate | Normal volatility |")
    return ("DEMO MODE answer: Ye ek placeholder analysis hai jo dikhata hai ki pipeline "
            "kaise chalega. Real AI analysis ke liye apni free API keys (.env file mein) "
            "add karo — Gemini, Groq, aur OpenRouter teeno free hain. Data (price, "
            "fundamentals, news) is report mein REAL hai; sirf AI text demo hai.")


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

class LLMEngine:
    """Routes roles to providers, handles fallback, records battle stats."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.stats = EngineStats()
        self.providers: dict[str, BaseProvider] = {}
        if settings.mock_llm:
            self.providers["mock"] = MockProvider(settings)
            return
        for name, cfg in PROVIDERS.items():
            keys = get_api_keys(name)
            if not keys:
                continue
            try:
                if cfg.get("native"):
                    p = GeminiProvider(cfg, keys, settings)  # full key pool
                else:
                    p = OpenAICompatProvider(name, cfg, keys[0], settings)
                self.providers[name] = p
            except Exception as e:
                logger.warning("Could not init provider %s: %s", name, e)
        if not self.providers:
            raise ProviderError(
                "Koi LLM provider configure nahi hai! .env mein GOOGLE_API_KEY / "
                "GROQ_API_KEY / OPENROUTER_API_KEY daalo, ya DEMO mode (mock) use karo."
            )

    # ----------------------------------------------------------------------
    def provider_names(self) -> list[str]:
        return list(self.providers.keys())

    def provider_models(self) -> dict[str, str]:
        out = {}
        for n, p in self.providers.items():
            try:
                out[n] = p.detect_model()
            except Exception:
                out[n] = "?"
        return out

    def _chain_for(self, role: str) -> list[str]:
        """Provider preference chain for a role (battle assignment + fallback)."""
        have = set(self.providers.keys())
        chain = [p for p in ROLE_ASSIGNMENTS.get(role, ["gemini"]) if p in have]
        # append any remaining providers as final fallbacks
        chain += [p for p in have if p not in chain]
        # battle off -> collapse to one provider for everything
        if self.settings.battle_mode == "off" and chain:
            first = ROLE_ASSIGNMENTS.get(role, ["gemini"])[0]
            primary = first if first in have else chain[0]
            chain = [primary] + [p for p in chain if p != primary]
        return chain or list(have)

    # ----------------------------------------------------------------------
    def call(self, role: str, system: str, user: str,
             temperature: float | None = None, max_tokens: int | None = None,
             provider: str | None = None) -> tuple[str, str]:
        """Run one LLM call. Returns (text, provider_used). Falls back on failure."""
        temp = self.settings.temperature if temperature is None else temperature
        if role in DEEP_ROLES:
            temp = min(temp, 0.2)
        tokens = max_tokens or (self.settings.max_output_tokens + 1000
                                if role in DEEP_ROLES else self.settings.max_output_tokens)
        chain = [provider] if provider and provider in self.providers else self._chain_for(role)
        last_err = None
        for pname in chain:
            p = self.providers[pname]
            t0 = time.time()
            try:
                text = p.chat(system, user, temp, tokens)
                self.stats.add(CallStat(role, pname, p.model or "?", True,
                                        round(time.time() - t0, 1), len(text)))
                return text, pname
            except Exception as e:
                last_err = e
                self.stats.add(CallStat(role, pname, p.model or "?", False,
                                        round(time.time() - t0, 1), 0, str(e)[:120]))
                logger.warning("Role %s: provider %s failed (%s); trying next",
                               role, pname, e)
        raise ProviderError(f"Role '{role}' — saare providers fail ho gaye. Last: {last_err}")

    # ----------------------------------------------------------------------
    def call_parallel(self, jobs: list[dict]) -> list[tuple[str | None, str | None, str]]:
        """Run independent calls in parallel (different providers don't block each other).
        Each job: {'role', 'system', 'user', 'provider'?...}. Returns list of
        (text|None, provider|None, error|None) in the same order."""
        results: list[tuple[str | None, str | None, str]] = [None] * len(jobs)

        def _run(i, job):
            try:
                text, prov = self.call(**job)
                results[i] = (text, prov, None)
            except Exception as e:
                results[i] = (None, None, str(e))

        threads = [threading.Thread(target=_run, args=(i, j), daemon=True)
                   for i, j in enumerate(jobs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results
