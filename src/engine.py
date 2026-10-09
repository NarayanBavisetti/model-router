"""Run one request end to end: route -> call -> score -> (maybe) fallback one tier up -> log.
Configs: always_cheapest / always_frontier (fixed tier, no fallback) and router (policy + fallback)."""
import csv, json, os, time, uuid
from datetime import datetime, timezone
from config import USD_TO_INR, QUALITY_FLOOR, LOG_DIR, PROMPTS_FILE, MODELS, FAILOVER_TIER
from providers import call_model, cost_usd, looks_like_refusal
from router import route, next_tier
from quality import score as score_answer
import health

LOG_FIELDS = ["timestamp", "run_id", "prompt_id", "domain", "workload", "priority", "config", "classifier", "route", "why", "model", "language",
              "difficulty", "hidden_difficulty", "input_tokens", "output_tokens", "cost_usd", "cost_inr",
              "provider_cost_usd", "router_overhead_ms", "model_latency_ms", "total_latency_ms", "quality_score",
              "quality_method", "fallback_fired", "fallback_reason", "precheck_skipped", "server_side_fallback", "retries", "error", "judge_cost_usd", "judge_tokens",
              "reasoning_used", "answer"]


def _read_source(rel: str) -> str:
    """Long-form inputs live as real files under data/: PDFs (text extracted with PyMuPDF, the way a
    document pipeline would feed a model) or .txt call transcripts. Cached per process."""
    if rel in _SOURCE_CACHE:
        return _SOURCE_CACHE[rel]
    path = os.path.join(os.path.dirname(PROMPTS_FILE), rel)
    if path.lower().endswith(".pdf"):
        import pymupdf
        with pymupdf.open(path) as doc:
            text = "\n".join(f"--- page {i + 1} ---\n" + page.get_text() for i, page in enumerate(doc))
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    _SOURCE_CACHE[rel] = text.strip()
    return _SOURCE_CACHE[rel]


_SOURCE_CACHE: dict[str, str] = {}


def load_prompts():
    """prompts.json entries may carry `source_file` (relative to data/); the file's text is appended to
    the instruction so the model, the classifier and the judge all see the full document."""
    with open(PROMPTS_FILE, encoding="utf-8") as f:
        items = json.load(f)
    for p in items:
        if p.get("source_file"):
            p["prompt"] = p["prompt"].rstrip() + "\n\n" + _read_source(p["source_file"])
    return items


def _log(rec: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "requests.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    path = os.path.join(LOG_DIR, "requests.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(rec)


def run_request(prompt_item: dict, mode: str | None = None, config: str = "router", run_id: str = "",
                reasoning: bool = False, judge: bool = True, classifier: str | None = None,
                on_event=None) -> dict:
    """prompt_item needs at least {id, domain, prompt, reference_or_rubric}. hidden_difficulty is copied
    to the log for scoring routing accuracy but is never read by the router.
    on_event(name, payload) is called at each stage (routed, calling, called, judging, judged, fallback)
    so a UI can show progress; it is optional and has no effect on the result."""
    prompt = prompt_item["prompt"]
    emit = on_event or (lambda name, payload: None)
    t_start = time.perf_counter()

    # 1. decide
    if config.startswith("router_"):  # e.g. router_deberta, router_hybrid
        classifier, config = config.split("_", 1)[1], "router"
    if config == "always_cheapest":
        decision = route(prompt, mode, classifier)  # still run detection so language/difficulty are logged
        decision.update(tier="cheap", why="baseline: always cheapest")
        allow_fallback = False
    elif config == "always_frontier":
        decision = route(prompt, mode, classifier)
        decision.update(tier="frontier", why="baseline: always frontier")
        allow_fallback = False
    else:
        decision = route(prompt, mode, classifier)
        allow_fallback = True
    tier = decision["tier"]

    # 1b. pre-check: skip a tier that has been failing in the last 30 s (no latency cost, decided before the call)
    precheck = ""
    if allow_fallback and health.is_unhealthy(tier) and FAILOVER_TIER.get(tier):
        precheck = f"{tier} unhealthy ({health.recent_failures(tier)} failures in last 30 s) -> {FAILOVER_TIER[tier]}"
        decision["why"] += f"; pre-check: {precheck}"
        tier = FAILOVER_TIER[tier]
    emit("routed", {**decision, "tier": tier, "model": MODELS[tier]["model_id"], "precheck": precheck})

    # 2. call (+ score) with at most one escalation
    attempts, fallback_reason = [], ""
    for attempt in range(2):
        emit("calling", {"tier": tier, "model": MODELS[tier]["model_id"], "attempt": attempt + 1})
        res = call_model(tier, prompt, reasoning=reasoning)
        q = {"score": None, "method": "skipped", "reason": "", "judge_cost_usd": 0.0,
             "judge_input_tokens": 0, "judge_output_tokens": 0}
        if res["error"] == "none" and looks_like_refusal(res["text"]):
            res["error"] = "refusal"
        health.record(tier, res["error"] in ("none", "refusal"))  # refusals are the model answering, not an outage
        served = res.get("served_tier") or tier  # OpenRouter may have run our server-side fallback model
        emit("called", {"tier": served, "asked": tier, "model": res.get("served_model") or MODELS[tier]["model_id"],
                        "latency_ms": res["latency_ms"], "error": res["error"], "error_detail": res["error_detail"],
                        "input_tokens": res["input_tokens"], "output_tokens": res["output_tokens"], "retries": res["retries"]})
        if res["error"] == "none" and judge:
            emit("judging", {"tier": served, "method": "exact match or LLM judge"})
            q = score_answer(prompt_item, res["text"])
            emit("judged", {"score": q["score"], "method": q["method"], "reason": q["reason"]})
        attempts.append({"tier": served, "res": res, "q": q, "asked": tier})

        problem = None
        if res["error"] != "none":
            problem = res["error"]
        elif judge and q["score"] is not None and q["score"] < QUALITY_FLOOR:
            problem = f"quality {q['score']} < floor {QUALITY_FLOOR}"
        is_outage = res["error"] in ("timeout", "rate_limit", "overloaded", "api_error")
        up = FAILOVER_TIER.get(tier) if is_outage else next_tier(tier)  # outage: one down; bad answer: one up
        if problem and allow_fallback and attempt == 0 and up:
            fallback_reason = f"{problem} on {tier} -> retry {up}"
            emit("fallback", {"from": tier, "to": up, "reason": fallback_reason, "outage": is_outage})
            tier = up
            continue
        if problem and allow_fallback and attempt == 0 and not up:
            fallback_reason = f"{problem} on {tier} but no higher tier"
        break

    # 3. aggregate: serving cost/latency covers every attempt; quality is the final answer's
    final = attempts[-1]
    in_tok = sum(a["res"]["input_tokens"] for a in attempts)
    out_tok = sum(a["res"]["output_tokens"] for a in attempts)
    serve_usd = sum(cost_usd(a["tier"], a["res"]["input_tokens"], a["res"]["output_tokens"]) for a in attempts)
    model_ms = sum(a["res"]["latency_ms"] for a in attempts)
    provider_cost = [a["res"]["provider_cost_usd"] for a in attempts if a["res"]["provider_cost_usd"] is not None]
    judge_usd = sum(a["q"]["judge_cost_usd"] for a in attempts)
    judge_tok = sum(a["q"]["judge_input_tokens"] + a["q"]["judge_output_tokens"] for a in attempts)
    qscore = final["q"]["score"]
    if final["res"]["error"] != "none" and judge:
        qscore = 0  # an error/refusal served to the user is a zero

    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id or uuid.uuid4().hex[:8],
        "prompt_id": prompt_item.get("id", "custom"), "domain": prompt_item.get("domain", "custom"),
        "mode": decision["priority"] + (" (forced)" if mode else ""), "config": config, "classifier": decision["classifier"],
        "workload": decision["workload"], "hidden_workload": prompt_item.get("domain"), "priority": decision["priority"],
        "detail": decision["detail"],
        "route": final["tier"], "first_route": attempts[0]["asked"], "why": decision["why"],
        "model": final["res"].get("served_model") or MODELS[final["tier"]]["model_id"],
        "precheck_skipped": precheck,
        "server_side_fallback": any(a["tier"] != a["asked"] for a in attempts),
        "language": decision["language"], "is_indic": decision["is_indic"], "difficulty": decision["difficulty"],
        "hidden_difficulty": prompt_item.get("hidden_difficulty"),
        "input_tokens": in_tok, "output_tokens": out_tok,
        "cost_usd": round(serve_usd, 6), "cost_inr": round(serve_usd * USD_TO_INR, 4),
        "provider_cost_usd": round(sum(provider_cost), 6) if provider_cost else None,
        "router_overhead_ms": decision["router_overhead_ms"],
        "model_latency_ms": round(model_ms, 1),
        "total_latency_ms": round(model_ms + decision["router_overhead_ms"], 1),
        "quality_score": qscore, "quality_method": final["q"]["method"], "quality_reason": final["q"]["reason"],
        "fallback_fired": len(attempts) > 1 or bool(precheck) or any(a["tier"] != a["asked"] for a in attempts),
        "fallback_reason": fallback_reason or precheck or ("; ".join(f"OpenRouter ran {a['tier']} instead of {a['asked']}" for a in attempts if a["tier"] != a["asked"])),
        "retries": sum(a["res"]["retries"] for a in attempts),  # same-model retries on rate limit / overload / timeout
        "error": final["res"]["error"], "error_detail": final["res"]["error_detail"],
        "judge_cost_usd": round(judge_usd, 6), "judge_cost_inr": round(judge_usd * USD_TO_INR, 4),
        "judge_tokens": judge_tok,
        "reasoning_used": bool(reasoning and final["tier"] == "frontier"),
        "answer": final["res"]["text"],
        # what this exact request (same token counts) would have cost on every tier, in ₹. Estimate, not a call.
        "cost_if_tier_inr": {t: round(cost_usd(t, in_tok, out_tok) * USD_TO_INR, 4) for t in MODELS},
        "wall_ms": round((time.perf_counter() - t_start) * 1000, 1),  # includes judge time; not a serving metric
    }
    _log(rec)
    return rec
