"""Batch benchmark. Runs every prompt SEQUENTIALLY through each config so latency numbers stay honest.
Usage: python run_benchmark.py [--limit 3] [--all-modes]
Writes results/summary.csv, results/economics.md and prints a table per config."""
import argparse, csv, os, statistics, time, uuid
from collections import Counter
from datetime import date
from config import MODELS, USD_TO_INR, TIER_ORDER, RESULTS_DIR, QUALITY_FLOOR, JUDGE_TIER, RESOLVED_SCORE
from engine import load_prompts, run_request
import health

CONFIGS = [("always_cheapest", None), ("always_frontier", None), ("router", None)]
EXTRA = [("router", "speed"), ("router", "cost"), ("router", "quality")]  # force one priority for every prompt
CLASSIFIERS = [("router_rules", None), ("router_hybrid", None)]            # same policy, keyword classifier instead of DeBERTa


def p95(xs):
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * len(xs))) - 1)] if xs else 0


def summarise(name, recs):
    n = len(recs)
    scored = [r["quality_score"] for r in recs if r["quality_score"] is not None]
    mix = Counter(r["route"] for r in recs)
    cost = sum(r["cost_usd"] for r in recs)
    in_tok, out_tok = sum(r["input_tokens"] for r in recs), sum(r["output_tokens"] for r in recs)
    acc = [r["difficulty"] == r["hidden_difficulty"] for r in recs if r["hidden_difficulty"]]
    wacc = [r["workload"] == r["hidden_workload"] for r in recs if r["hidden_workload"]]
    resolved = sum(1 for s in scored if s >= RESOLVED_SCORE)
    return {
        "config": name, "n": n,
        "cost_usd": round(cost, 4), "cost_inr": round(cost * USD_TO_INR, 2),
        "input_tokens": in_tok, "output_tokens": out_tok,
        "blended_in_usd_per_m": round(sum(r["cost_in_usd"] for r in recs) / in_tok * 1e6, 4) if in_tok else 0,
        "blended_out_usd_per_m": round(sum(r["cost_out_usd"] for r in recs) / out_tok * 1e6, 4) if out_tok else 0,
        "mean_latency_ms": round(statistics.mean(r["total_latency_ms"] for r in recs), 0),
        "p95_latency_ms": round(p95([r["total_latency_ms"] for r in recs]), 0),
        "mean_router_overhead_ms": round(statistics.mean(r["router_overhead_ms"] for r in recs), 3),
        "mean_quality": round(statistics.mean(scored), 2) if scored else None,
        "resolved_rate": round(resolved / n, 3),
        "cost_per_resolved_inr": round(cost * USD_TO_INR / resolved, 4) if resolved else None,
        "fallback_rate": round(sum(r["fallback_fired"] for r in recs) / n, 3),
        "error_rate": round(sum(r["error"] != "none" for r in recs) / n, 3),
        "routing_accuracy": round(sum(acc) / len(acc), 3) if acc else None,
        "workload_accuracy": round(sum(wacc) / len(wacc), 3) if wacc else None,
        "judge_cost_usd": round(sum(r["judge_cost_usd"] for r in recs), 4),
        **{f"mix_{t}": round(mix[t] / n, 3) for t in TIER_ORDER},
    }


def print_table(s):
    print(f"\n=== {s['config']} (n={s['n']}) ===")
    print(f"  total serving cost : ₹{s['cost_inr']:.2f}  (${s['cost_usd']:.4f})   judge cost (separate): ${s['judge_cost_usd']:.4f}")
    print(f"  latency mean / p95 : {s['mean_latency_ms']:.0f} ms / {s['p95_latency_ms']:.0f} ms  (router overhead {s['mean_router_overhead_ms']:.3f} ms)")
    print(f"  mean quality (0-10): {s['mean_quality']}    fallback rate: {s['fallback_rate']:.0%}    error rate: {s['error_rate']:.0%}")
    print(f"  resolved (>= {RESOLVED_SCORE}/10): {s['resolved_rate']:.0%}    cost per resolved outcome: ₹{s['cost_per_resolved_inr']}")
    print(f"  routing mix        : " + ", ".join(f"{t} {s['mix_' + t]:.0%}" for t in TIER_ORDER if s['mix_' + t]))
    print(f"  routing accuracy   : difficulty {s['routing_accuracy']}, workload {s['workload_accuracy']}  (vs hidden labels)")


def write_economics(summaries, path):
    IN_M, OUT_M = 50, 10  # million tokens / month
    def monthly(tier):
        m = MODELS[tier]
        return IN_M * m["input_usd_per_m"] + OUT_M * m["output_usd_per_m"]
    rows = []
    for s in summaries:
        if s["config"] == "always_cheapest":
            usd, how = monthly("cheap"), "100% cheap tier list price"
        elif s["config"] == "always_frontier":
            usd, how = monthly("frontier"), "100% frontier tier list price"
        else:
            # measured routing mix (share of prompts per tier, final route) applied to each tier's list price,
            # plus the measured fallback overhead (extra calls / token-weighted) captured by blended $/M.
            usd = IN_M * s["blended_in_usd_per_m"] + OUT_M * s["blended_out_usd_per_m"]
            how = "measured blended $/M (routing mix incl. fallback retries)"
        rows.append((s["config"], usd, how, s))
    frontier = next((r[1] for r in rows if r[0] == "always_frontier"), None)
    lines = [f"# Economics: 50M input + 10M output tokens / month", "",
             f"Generated {date.today().isoformat()}. Prices as listed in `config.py` on that date. FX: 1 USD = ₹{USD_TO_INR}.", "",
             "| Config | Monthly cost (USD) | Monthly cost (INR) | Saved vs always_frontier | Basis |",
             "|---|---:|---:|---:|---|"]
    for name, usd, how, s in rows:
        saved = f"{(1 - usd / frontier):.1%}" if frontier else "n/a"
        lines.append(f"| {name} | ${usd:,.0f} | ₹{usd * USD_TO_INR:,.0f} | {saved} | {how} |")
    lines += ["", "## Cost per resolved business outcome", "",
              f"A request is resolved when the judge scores it >= {RESOLVED_SCORE}/10. This is the number to show client teams: not price per token, but what one usable result costs.", "",
              "| Config | Resolved rate | Cost per resolved outcome (₹) | Mean quality |", "|---|---:|---:|---:|"]
    for name, usd, how, s in rows:
        lines.append(f"| {name} | {s['resolved_rate']:.0%} | {s['cost_per_resolved_inr']} | {s['mean_quality']} |")
    lines += ["", "## Measured routing mix (share of prompts by final tier)", "",
              "| Config | " + " | ".join(TIER_ORDER) + " | fallback rate | mean quality |", "|---|" + "---:|" * (len(TIER_ORDER) + 2)]
    for name, usd, how, s in rows:
        lines.append(f"| {name} | " + " | ".join(f"{s['mix_' + t]:.0%}" for t in TIER_ORDER) + f" | {s['fallback_rate']:.0%} | {s['mean_quality']} |")
    lines += ["", "## Tier list prices used (USD per 1M tokens)", "", "| Tier | Model | Input | Output | Monthly if used for 100% |", "|---|---|---:|---:|---:|"]
    for t in TIER_ORDER:
        m = MODELS[t]
        lines.append(f"| {t} | {m['model_id']} | ${m['input_usd_per_m']} | ${m['output_usd_per_m']} | ${monthly(t):,.0f} |")
    lines += ["", "## Assumptions", "",
              f"- Volume: {IN_M}M input + {OUT_M}M output tokens per month (5:1 input/output split as given in the brief).",
              f"- Prices: OpenRouter list prices and Sarvam published INR prices as of {date.today().isoformat()}; Sarvam converted at the FX rate above.",
              f"- FX: 1 USD = ₹{USD_TO_INR} (config.USD_TO_INR).",
              "- Router cost = token-weighted blended price measured in this benchmark (sum of serving cost / sum of tokens), so it already includes fallback retries. The prompt mix of the benchmark is assumed representative of production traffic.",
              "- Judge (LLM-as-judge) cost is an evaluation cost and is excluded from all monthly figures.",
              "- No prompt caching, batch discounts or volume discounts assumed.",
              f"- Quality floor for fallback = {QUALITY_FLOOR}/10; judge = {JUDGE_TIER} tier.", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only run the first N prompts (dry run)")
    ap.add_argument("--all-modes", action="store_true", help="also run the router with one forced priority (speed / cost / quality)")
    ap.add_argument("--classifiers", action="store_true", help="also run the router with the keyword-rules and hybrid classifiers")
    args = ap.parse_args()
    prompts = load_prompts()[: args.limit or None]
    run_id = uuid.uuid4().hex[:8]
    configs = CONFIGS + (EXTRA if args.all_modes else []) + (CLASSIFIERS if args.classifiers else [])
    os.makedirs(RESULTS_DIR, exist_ok=True)
    from classifier import deberta_difficulty, deberta_workload  # load once so the first prompt's latency is not the model load
    deberta_difficulty("warm up"); deberta_workload("warm up")
    summaries, t0 = [], time.time()
    for config, mode in configs:
        name = config if not (config == "router" and mode) else f"router_{mode}_forced"
        health.reset()
        recs = []
        for i, p in enumerate(prompts, 1):
            r = run_request(p, mode, config, run_id=run_id)
            r["cost_in_usd"] = r["input_tokens"] / 1e6 * MODELS[r["route"]]["input_usd_per_m"] if not r["fallback_fired"] else r["cost_usd"] * 0.5
            r["cost_out_usd"] = r["cost_usd"] - r["cost_in_usd"]
            recs.append(r)
            print(f"[{name}] {i}/{len(prompts)} {p['id']:6s} -> {r['route']:9s} q={r['quality_score']} "
                  f"{r['total_latency_ms']:.0f}ms ${r['cost_usd']:.5f} fb={r['fallback_fired']} err={r['error']}", flush=True)
        s = summarise(name, recs)
        summaries.append(s)
        print_table(s)
        by_dom = {}
        for r in recs:
            by_dom.setdefault(r["domain"], []).append(r)
        print("  per workload       : " + "; ".join(
            f"{d}: ₹{sum(x['cost_usd'] for x in xs) * USD_TO_INR:.3f}, q={statistics.mean(x['quality_score'] for x in xs if x['quality_score'] is not None):.1f}, p95={p95([x['total_latency_ms'] for x in xs]):.0f}ms"
            for d, xs in by_dom.items()))
    with open(os.path.join(RESULTS_DIR, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
        w.writeheader(); w.writerows(summaries)
    write_economics(summaries, os.path.join(RESULTS_DIR, "economics.md"))
    print(f"\nDone in {time.time() - t0:.0f}s. run_id={run_id}. Wrote results/summary.csv and results/economics.md")


if __name__ == "__main__":
    main()
