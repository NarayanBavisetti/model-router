"""Thin HTTP wrappers. OpenRouter is used purely as a delivery pipe: every call names the
exact model id from config.py. No auto-router, no model fallbacks on their side."""
import os, time, httpx
from dotenv import load_dotenv
from config import MODELS, MAX_OUTPUT_TOKENS, TEMPERATURE, FRONTIER_REASONING_EFFORT, RETRY_BUDGET_S, MAX_RETRIES, RETRY_BACKOFF_S, SERVER_SIDE_FALLBACK, FAILOVER_TIER

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SARVAM_URL = "https://api.sarvam.ai/v1/chat/completions"

REFUSAL_PHRASES = [
    "i can't help", "i cannot help", "i can't assist", "i cannot assist", "i'm unable to",
    "i am unable to", "i can't provide", "i cannot provide", "i won't be able to",
    "as an ai language model", "i'm not able to help", "i must decline",
]


def looks_like_refusal(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    head = t[:200]
    return any(p in head for p in REFUSAL_PHRASES)


OVERLOAD_WORDS = ("overloaded", "capacity", "busy", "try again", "temporarily unavailable")
TRANSIENT = ("rate_limit", "overloaded", "timeout")  # worth retrying the same model


def _result(text="", input_tokens=0, output_tokens=0, latency_ms=0.0, error="none", detail="", provider_cost_usd=None,
            retries=0, served_tier=None, served_model=None):
    return {"text": text, "input_tokens": input_tokens, "output_tokens": output_tokens,
            "latency_ms": round(latency_ms, 1), "error": error, "error_detail": detail,
            "provider_cost_usd": provider_cost_usd, "retries": retries,
            "served_tier": served_tier, "served_model": served_model}


def tier_for_model(model_id: str, default: str) -> str:
    """OpenRouter reports which model actually ran (it may be our server-side fallback). Map it back to a tier."""
    for t, m in MODELS.items():
        if m["model_id"] == model_id:
            return t
    return default


def _classify_http(r: httpx.Response) -> tuple[str, str]:
    """Map a non-200 response to an error class: rate_limit | overloaded | timeout | api_error."""
    body = r.text[:200]
    if r.status_code == 429:
        return "rate_limit", f"HTTP 429: {body}"
    if r.status_code in (502, 503, 529) or any(w in body.lower() for w in OVERLOAD_WORDS):
        return "overloaded", f"HTTP {r.status_code}: {body}"
    if r.status_code in (408, 504):
        return "timeout", f"HTTP {r.status_code}: {body}"
    return "api_error", f"HTTP {r.status_code}: {body}"


def _once(url, headers, body, timeout_s) -> tuple[str, str, dict | None, httpx.Response | None]:
    """One HTTP attempt. Returns (error_class, detail, json_or_None, response_or_None)."""
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=timeout_s)
    except httpx.TimeoutException:
        return "timeout", f"> {timeout_s}s", None, None
    except Exception as e:
        return "api_error", str(e)[:200], None, None
    if r.status_code != 200:
        err, detail = _classify_http(r)
        return err, detail, None, r
    data = r.json()
    if "error" in data and not data.get("choices"):
        msg = str(data["error"])[:200]
        return ("overloaded" if any(w in msg.lower() for w in OVERLOAD_WORDS) else "api_error"), msg, None, r
    return "none", "", data, r


def call_model(tier: str, prompt: str, system: str | None = None, reasoning: bool = False,
               max_tokens: int = MAX_OUTPUT_TOKENS) -> dict:
    """Returns a dict with text, token counts, latency and error in {none, timeout, api_error}.
    `reasoning` is honoured ONLY on the frontier tier; every other tier always runs with thinking off."""
    m = MODELS[tier]
    key_name = "OPENROUTER_API_KEY" if m["provider"] == "openrouter" else "SARVAM_API_KEY"
    if not os.getenv(key_name):
        return _result(error="api_error", detail=f"{key_name} is not set in .env")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    use_reasoning = reasoning and tier == "frontier" and FRONTIER_REASONING_EFFORT

    if m["provider"] == "openrouter":
        url, headers = OPENROUTER_URL, {"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
                                        "HTTP-Referer": "http://localhost", "X-Title": "model-router"}
        body = {"model": m["model_id"], "messages": messages, "max_tokens": max_tokens, "temperature": TEMPERATURE,
                "reasoning": {"effort": FRONTIER_REASONING_EFFORT if use_reasoning else m.get("reasoning_off", "none")}}
        nxt = FAILOVER_TIER.get(tier)  # outage failover: one tier DOWN (cheapest goes up)
        if SERVER_SIDE_FALLBACK and nxt and MODELS[nxt]["provider"] == "openrouter":
            # explicit ordered list from OUR policy: chosen model first, failover second. Not the auto-router.
            body["models"] = [m["model_id"], MODELS[nxt]["model_id"]]
    else:  # sarvam
        url, headers = SARVAM_URL, {"api-subscription-key": os.getenv("SARVAM_API_KEY", "")}
        body = {"model": m["model_id"], "messages": messages, "max_tokens": max_tokens, "temperature": TEMPERATURE,
                "reasoning_effort": None}  # None = thinking off (Sarvam default is "medium")

    # Transient failures (rate limit, overloaded, timeout) are retried on the SAME model inside a 30 s budget,
    # like OpenRouter's own window. Waits count as latency. Failed attempts carry no tokens and no cost.
    # Anything else (hard error, refusal, truncated) goes straight back so the engine can escalate a tier.
    t0 = time.perf_counter()
    retries = 0
    while True:
        err, detail, data, r = _once(url, headers, body, m["timeout_s"])
        elapsed = time.perf_counter() - t0
        if err in TRANSIENT and retries < MAX_RETRIES and elapsed < RETRY_BUDGET_S:
            wait = RETRY_BACKOFF_S * (retries + 1)
            if r is not None and r.headers.get("retry-after"):
                try:
                    wait = float(r.headers["retry-after"])
                except ValueError:
                    pass
            wait = min(wait, max(0.0, RETRY_BUDGET_S - elapsed))
            time.sleep(wait)
            retries += 1
            continue
        break
    latency = (time.perf_counter() - t0) * 1000
    if err != "none":
        return _result(latency_ms=latency, error=err, detail=detail + (f" (after {retries} retries)" if retries else ""), retries=retries)
    choice = data["choices"][0]
    text = (choice["message"].get("content") or "").strip()
    usage = data.get("usage", {}) or {}
    finish = choice.get("finish_reason")
    served_model = data.get("model") or m["model_id"]
    served_tier = tier_for_model(served_model, tier)
    # Seen in the wild: HTTP 200 with a cut-off answer, usage all zeros and no error field. Treat as a failed call.
    if finish not in (None, "stop", "length", "end_turn") or (text and not usage.get("completion_tokens")):
        return _result(text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), latency, error="truncated",
                       detail=f"finish_reason={finish}, completion_tokens={usage.get('completion_tokens')}", retries=retries,
                       served_tier=served_tier, served_model=served_model)
    return _result(text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), latency,
                   provider_cost_usd=usage.get("cost"), retries=retries, served_tier=served_tier, served_model=served_model)


def cost_usd(tier: str, input_tokens: int, output_tokens: int) -> float:
    m = MODELS[tier]
    return input_tokens / 1e6 * m["input_usd_per_m"] + output_tokens / 1e6 * m["output_usd_per_m"]
