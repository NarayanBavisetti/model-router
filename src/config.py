"""
Model tiers, prices and knobs. Edit this file to swap models.

Prices verified on 2026-10-08:
  - OpenRouter: GET https://openrouter.ai/api/v1/models  (pricing.prompt / pricing.completion are USD per token)
  - Sarvam:     https://docs.sarvam.ai/api/pricing       (INR per 1M tokens, sarvam-105b: in 29.28 / out 73.2)
"""

USD_TO_INR = 88.0  # FX assumption used everywhere costs are shown in both currencies

# Tier order from cheapest to most capable. Fallback moves ONE step up this ladder.
TIER_ORDER = ["cheap", "indic", "mid", "upper_mid", "frontier"]

MODELS = {
    "cheap": {
        "provider": "openrouter",
        "model_id": "google/gemini-2.5-flash-lite",  # alt: openai/gpt-5-nano ($0.05 / $0.40)
        "input_usd_per_m": 0.10,
        "output_usd_per_m": 0.40,
        "timeout_s": 20,
        "reasoning_off": "none",
    },
    "indic": {
        "provider": "sarvam",
        "model_id": "sarvam-105b",
        # Sarvam prices are published in INR; converted with USD_TO_INR so all maths is in USD.
        "input_usd_per_m": round(29.28 / USD_TO_INR, 4),   # 0.3327
        "output_usd_per_m": round(73.20 / USD_TO_INR, 4),  # 0.8318
        "timeout_s": 30,
    },
    "mid": {
        "provider": "openrouter",
        "model_id": "google/gemini-3.8-flash",
        "input_usd_per_m": 0.75,
        "output_usd_per_m": 3.75,
        "timeout_s": 30,
        "reasoning_off": "minimal",  # provider rejects "none"; "minimal" measured at 0 reasoning tokens
    },
    "upper_mid": {
        "provider": "openrouter",
        "model_id": "anthropic/claude-sonnet-5.5",
        "input_usd_per_m": 2.00,
        "output_usd_per_m": 10.00,
        "timeout_s": 60,
        "reasoning_off": "minimal",  # provider rejects "none"; "minimal" measured at 0 reasoning tokens
    },
    "frontier": {
        "provider": "openrouter",
        "model_id": "anthropic/claude-opus-5.5",
        "input_usd_per_m": 4.00,
        "output_usd_per_m": 20.00,
        "timeout_s": 90,
        "reasoning_off": "minimal",  # provider rejects "none"; "minimal" measured at 0 reasoning tokens
    },
}

# Two ladders.
# FAILOVER_TIER: where a request goes when the chosen model is DOWN (timeout, rate limit, overloaded, API error).
# One tier DOWN: a cheaper answer beats no answer, and an outage must never make a request more expensive.
# Only the cheapest tier has nowhere to go down, so it goes up. Used by the pre-check, the in-request
# models=[chosen, failover] list sent to OpenRouter, and the client-side retry.
FAILOVER_TIER = {"frontier": "upper_mid", "upper_mid": "mid", "mid": "cheap", "indic": "cheap", "cheap": "mid"}
# NEXT_TIER: where a request goes when the model ANSWERED but badly (refusal, truncated, judge score below the floor).
# One tier UP, because a weaker model will not fix a bad answer. "indic" skips to "mid" (next by price is a specialist).
NEXT_TIER = {"cheap": "mid", "indic": "mid", "mid": "upper_mid", "upper_mid": "frontier", "frontier": None}

# Reasoning / thinking is OFF everywhere ("reasoning_off" is the lowest setting each provider accepts; verified
# 2026-10-08 to produce 0 reasoning tokens). Only the frontier tier may turn it on, and only
# when a request explicitly asks for it (see providers.call_model). None = off.
FRONTIER_REASONING_EFFORT = "low"

# Lookup 1: workload -> what the customer cares about. Detected from the prompt by the classifier.
# Voice agents are not in the dataset; intent tagging (classification) stands in for the voice LLM step.
WORKLOAD_PRIORITY = {
    "classification": "speed",        # voice agent / intent tagging: a pause past ~1.5 s ends the call
    "call_centre_summary": "cost",    # volume makes cost dominant
    "translation": "cost",            # bulk throughput; Indic goes to Sarvam anyway
    "document_extraction": "quality", # a wrong number or date is unacceptable
}
DEFAULT_PRIORITY = "balanced"         # workload not recognised

# Lookup 3: priority row x difficulty column -> tier.
ROUTE_TABLE = {
    "speed":    {"easy": "cheap", "medium": "cheap",     "hard": "mid"},
    "cost":     {"easy": "cheap", "medium": "mid",       "hard": "upper_mid"},
    "balanced": {"easy": "cheap", "medium": "mid",       "hard": "frontier"},
    "quality":  {"easy": "mid",   "medium": "upper_mid", "hard": "frontier"},
}

# Classifier for Lookup 1 (workload) and Lookup 2 (difficulty): "deberta" (zero-shot mDeBERTa NLI, local,
# non-generative, ~100 ms per lookup on MPS, ~1 s on CPU, $0), "rules" (keyword lists, ~0.05 ms), or
# "hybrid" (rules when a keyword matches, DeBERTa otherwise). The benchmark can compare them.
ROUTER_CLASSIFIER = "deberta"
DEBERTA_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
DEBERTA_CUT_CHARS = 400           # difficulty: the instruction is at the top of the prompt
DEBERTA_WORKLOAD_CUT_CHARS = 800  # workload: needs a little of the body too

RESOLVED_SCORE = 8  # a request counts as a resolved business outcome when the judge gives >= this

# Failure handling, modelled on OpenRouter's routing + failover (openrouter.ai/blog/insights/model-routing):
# 1. Pre-check: a tier with >= HEALTH_FAIL_THRESHOLD failures in the last HEALTH_WINDOW_S is skipped BEFORE the call
#    (one tier up), so an outage costs the user no extra latency. Failures expire out of the window on their own.
HEALTH_WINDOW_S = 30
HEALTH_FAIL_THRESHOLD = 2
# 2. In-request failover: every OpenRouter call carries models=[chosen, next tier up]. If the chosen model is down,
#    rate-limited or errors, OpenRouter runs the next one inside the same request (no second round trip). Both names
#    come from our policy, so this is explicit fallback, not the auto-router. Sarvam has no equivalent, so for it
#    one quick same-model retry is allowed before escalating client-side.
SERVER_SIDE_FALLBACK = True
RETRY_BUDGET_S = 5
MAX_RETRIES = 1
RETRY_BACKOFF_S = 1.0   # used when the provider sends no Retry-After header
# 3. Client-side escalation (engine.py): anything still failing, a refusal, a truncated reply or a low judge score
#    is retried once on the next tier up. Failed attempts carry no tokens and no cost.

QUALITY_FLOOR = 5          # judge score (0-10) below which the router escalates once
JUDGE_TIER = "mid"         # LLM-as-judge runs on this tier; its cost is reported separately
MAX_OUTPUT_TOKENS = 4096   # serving calls; 1024 and 2048 both cut off long-document answers (finish_reason=length), see README
TEMPERATURE = 0.2

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # paths work from any working directory
LOG_DIR = os.path.join(BASE_DIR, "logs")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
PROMPTS_FILE = os.path.join(BASE_DIR, "data", "prompts.json")
