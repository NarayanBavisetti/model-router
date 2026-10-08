# Model Router

Send each prompt to the cheapest model that is still good enough, and prove it with real API calls.
Every request is measured for cost (₹ and $), latency (router + model, p95) and quality.

## Stack

- Python 3.11+, FastAPI, httpx. One plain HTML/JS page (`static/index.html`), no frontend framework.
- OpenRouter is used **only as a delivery pipe**: every call names the exact model id from `config.py`. The OpenRouter auto-router is never used. Sarvam-105B is called directly on the Sarvam API.
- Reasoning / thinking is **off** on every call. Gemini 3.8 Flash, Sonnet 5.5 and Opus 5.5 reject `effort: none` on OpenRouter ("Reasoning is mandatory for this endpoint"), so they get `effort: minimal`, which was measured at 0 reasoning tokens; flash-lite takes `none`; Sarvam takes `reasoning_effort: null` (its default is medium, which spent 61 reasoning tokens on a one-word answer in the probe). Reasoning can be switched on only for the frontier tier, per request, and the benchmark never does.
- Keys in `.env`: `OPENROUTER_API_KEY`, `SARVAM_API_KEY` (see `.env.example`).

| Tier | Model | Provider | Price $ / 1M tokens (in / out) | Price ₹ / 1M tokens (in / out) | Context | Thinking | Timeout | Measured latency (mean / p95) | Used for |
|---|---|---|---|---|---|---|---|---|---|
| cheap | google/gemini-2.5-flash-lite | OpenRouter | 0.10 / 0.40 | 8.8 / 35 | 1M | off (`effort: none`) | 20 s | 2.2 s / 4.1 s | Easy tasks: labels, yes/no, sentiment, one-line summaries |
| indic | sarvam-105b | Sarvam API (direct) | 0.33 / 0.83 | 29.28 / 73.2 (published in ₹) | 128K | off (`reasoning_effort: null`) | 30 s | 1.0 s / 2.0 s | Hindi, Tamil, Telugu and Hinglish prompts that are not hard |
| mid | google/gemini-3.8-flash | OpenRouter | 0.75 / 3.75 | 66 / 330 | 1M | off (`effort: minimal`, 0 reasoning tokens) | 30 s | 2.7 s / 3.1 s | Medium tasks: summaries, JSON extraction, translation. Also the LLM judge |
| upper_mid | anthropic/claude-sonnet-5.5 | OpenRouter | 2.00 / 10.00 | 176 / 880 | 1M | off (`effort: minimal`) | 60 s | ~3 s (dry run only) | Hard tasks in cost_first mode; fallback target above mid |
| frontier | anthropic/claude-opus-5.5 | OpenRouter | 4.00 / 20.00 | 352 / 1,760 | 1M | off by default; the only tier allowed to enable it per request | 90 s | 3.7 to 9.0 s (dry run only) | Hard tasks: financial calculation, conflicting legal clauses, translation with terminology notes |

Prices verified on 2026-10-08 against the live OpenRouter models API and the Sarvam pricing page; the cost computed from these prices matched OpenRouter's billed `usage.cost` on every call. FX 1 USD = ₹88 (`config.USD_TO_INR`). Price spread between cheap and frontier is 40x on input and 50x on output. Latency is one sequential pass, 30 prompts, thinking off; router overhead (0.05 ms for rules) is included. Indic is cheaper than mid, so routing Indian-language prompts to Sarvam saves money as well as improving fluency.

## Run guide

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-deberta.txt   # optional, only for the DeBERTa / hybrid classifier
cp .env.example .env            # add your keys
python run_benchmark.py --limit 3        # dry run: 3 prompts x 3 configs, confirms both APIs work
python run_benchmark.py                  # full run: 30 prompts x 3 configs, sequential
python run_benchmark.py --all-modes      # also router in cost_first and quality_first
python run_benchmark.py --classifiers    # also router with the DeBERTa and hybrid classifiers
uvicorn app:app --reload                 # UI at http://127.0.0.1:8000
```

Files: `config.py` (models, prices, thresholds) · `router.py` (policy) · `providers.py` (HTTP calls) · `quality.py` (scorer) ·
`engine.py` (route → call → score → fallback → log) · `run_benchmark.py` · `app.py` + `static/index.html` · `data/prompts.json`.
Logs: `logs/requests.jsonl` and `logs/requests.csv` (one row per request). Results: `results/summary.csv`, `results/economics.md`.

## Routing policy, in one paragraph

The router looks at the prompt and nothing else. First it decides whether the prompt is Indic: any Indic-script character, three or more romanised Hindi/Tamil/Telugu words (or two if they make up a fifth of the text), or an explicit Indic target language ("translate into Hindi"). Then it decides difficulty from task keywords: classify / label / yes-or-no / sentiment mean easy; summarise / extract / translate / convert mean medium; reason / analyse / compare / step by step / legal / clause / calculate / root cause mean hard, and a prompt over 1,500 characters is bumped one level. Hard beats medium beats easy; a prompt with no keywords is medium. If the prompt is Indic and not hard it goes to Sarvam-105B regardless of mode. Otherwise the mode picks the tier from a 3×3 table: cost_first sends easy and medium to cheap and hard to Sonnet; balanced sends easy to cheap, medium to Gemini Flash and hard to Opus; quality_first sends easy to Gemini Flash, medium to Sonnet and hard to Opus. The decision is logged with a one-line "why", e.g. `hard (hard keywords ['analyse', 'legal']), english, balanced mode -> frontier`. The UI exposes two modes on top of these: **Auto** runs the router in balanced mode; **Custom** lets the user tick cost budget, latency tolerance and accuracy need as low or high. Those ticks map to a base mode (cost low → cost_first; accuracy high → quality_first; both → balanced; neither → balanced) and latency low additionally caps the tier at Gemini Flash, since Sonnet and Opus are the slow tiers. No LLM is involved in routing: it is string matching and a lookup table, about 0.03–0.1 ms, and that time is added to every reported latency. The router makes no API call, so its token cost is zero; if an LLM classifier were ever added, its tokens would be added to `cost_usd` and its time to `router_overhead_ms`.

## Workloads: what each one is really constrained by

Routing everything to a frontier model is the trap; the fix is to name each workload's binding constraint and measure that. These presets are in `config.WORKLOAD_PRESETS` and selectable in the UI's Custom mode, where they fill the cost / latency / accuracy toggles.

| Workload | Main priority | Key parameters to measure | Preset (cost, latency, accuracy) |
|---|---|---|---|
| Real-time voice agents (Indian languages) | Latency and code-switching quality. A pause past ~1.5 s breaks the turn and the caller hangs up. | End-to-end round trip across ASR + LLM + TTS (sub-1.2 s target), Indic token efficiency, robustness to Hinglish and regional mixing | low, low, low → cheap / Sarvam, capped at mid |
| Call centre summarisation | Cost at scale, with high extraction recall. Volume turns small per-token differences into large monthly bills. | Cost per completed summary, recall on action items / complaints / intent tags, compression ratio | low, high, high → balanced |
| Heavy document processing | Accuracy. No tolerance for a wrong number or date in an invoice, chart or contract. | Schema adherence rate, numeric and date extraction accuracy, throughput on long payloads | high, high, high → quality_first |
| Enterprise translation | Nuance and domain fidelity across dialects, at bulk throughput. | Semantic similarity, correct localisation of legal / financial jargon, batch cost per token | low, high, high → balanced, Indic to Sarvam |
| Classification / intent tagging | Volume and latency. One label per request. | Exact-match accuracy, p95 latency, cost per 1,000 labels | low, low, low → cheap, capped at mid |

**Proving the savings.** Client teams do not trust token prices; they trust cost per resolved business outcome. The benchmark therefore reports, per config, the share of requests the judge scores 8/10 or better and the serving cost divided by that count (`cost_per_resolved_inr` in `results/summary.csv` and `results/economics.md`). A small model that completes a structured task cleanly is both cheaper and safer than a frontier model over-reasoning a simple input, and this is the number that shows it.

## Difficulty classifier: rules vs DeBERTa

The difficulty step is pluggable (`config.ROUTER_CLASSIFIER`, also selectable per request in the UI and run as extra benchmark configs with `--classifiers`):

| Classifier | What it is | Accuracy vs hidden labels (30 prompts) | Router overhead | Cost per call |
|---|---|---|---|---|
| rules (default) | keyword lists in `router.py` | 27 / 30 | 0.03 ms | $0 |
| deberta | zero-shot NLI with `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` (Microsoft mDeBERTa-v3 fine-tuned on XNLI), reads the first 400 chars, local, non-generative | 22 / 30 | ~100 ms on Apple MPS, ~1 s on CPU | $0 |
| hybrid | rules decide; DeBERTa only when no task keyword matched | 27 / 30 | 2.7 ms mean (DeBERTa fires on few prompts) | $0 |

Measured offline on 2026-10-08 (no API calls needed). The zero-shot encoder over-calls classification prompts as "hard" and short translations as "medium"; it has never seen a difficulty label, it is inferring from entailment. Rules win on this dataset because the prompts are instruction-led, but they are brittle to new phrasings. The right next step for the encoder is fine-tuning on the benchmark log: each logged row (prompt, cheap-tier judge score) is a training example for "was the cheap model enough", which is how RouteLLM-style routers are trained. A few hundred rows are enough for a first model; 30 are not. Install `requirements-deberta.txt` to use the deberta/hybrid options.

## Timeouts, refusals and fallback

Each tier has its own HTTP timeout (20 s cheap, 30 s indic/mid, 60 s Sonnet, 90 s Opus). A timeout, a non-200 response, an empty reply, a truncated reply (seen live: HTTP 200 with a cut-off answer and zero usage, logged as `error=truncated`), a reply that opens with a refusal phrase ("I can't help", "I'm unable to", …) or a judge score below the quality floor (5/10) triggers **one** retry on the next tier up the ladder (cheap → mid, indic → mid, mid → Sonnet, Sonnet → Opus; Opus has nowhere to go). The log records `fallback_fired=true` and the reason. Serving cost and latency include both attempts; the quality score is that of the answer actually served. The two baselines (`always_cheapest`, `always_frontier`) never fall back, so they stay pure baselines: an error there scores 0.

## Baseline results

_Filled from `results/summary.csv` after the full run; see the table below._

RESULTS_TABLE_PLACEHOLDER

Judge cost is reported separately and is not part of serving cost. Routing accuracy = share of prompts where the router's detected difficulty equals the hidden label in the dataset (the router never reads that label).

## What the quality measure does not capture

- The judge is Gemini 3.8 Flash scoring against a written reference or rubric. It is cheap and consistent but it is one model's opinion; it can be fooled by confident wrong answers and it is not blind to style.
- Rubric match is not business outcome. A summary can hit every rubric point and still be the wrong tone for a customer.
- Exact match on classification ignores near-misses and formatting; a correct label wrapped in a sentence scores 10 only if the sentence is short.
- Indic fluency is judged by a non-Indic-specialist model. Grammar or register errors in Tamil/Telugu may go unnoticed.
- Thirty prompts is a smoke test, not a statistically tight estimate; p95 on 30 samples is one data point.
- Latency is one sequential pass at one time of day from one location; provider load varies.

## Trade-offs considered and dropped

- **Generative LLM classifier instead of rules.** Would route better on fuzzy prompts, but costs a call per request, adds 300–800 ms, and makes "why did it go there" harder to explain. Rules take 0.03 ms and the "why" is a sentence. The hook is there: if one is ever added its tokens go into `cost_usd` and its time into `router_overhead_ms`.
- **Non-generative encoder classifier (DeBERTa).** Built and measured (see above): zero-shot it is less accurate than rules here and adds ~100 ms; fine-tuned on logged traffic it is the long-term answer. Kept as an option, not the default.
- **Embedding router / learned router.** Needs labelled traffic we don't have yet; a good next step once logs accumulate.
- **Parallel benchmark runs.** Faster, but concurrent calls would compete for rate limits and distort p95. Everything runs sequentially.
- **Hedged requests (call two tiers, take the first).** Better tail latency, doubles cost; against the goal.
- **Using OpenRouter's auto-router or provider fallbacks.** Hides the decision; all routing stays in `router.py`.
- **Cascading on judge score for every request in production.** Judging each response costs a mid-tier call; in production the quality floor would be sampled or replaced by cheap heuristics (empty / refusal / JSON-parse failure).

## Scaling inside a customer VPC or air-gapped

The router is a pure function with no network call, so it runs anywhere. Swap `providers.py` endpoints for in-VPC ones: open-weight models (e.g. a Gemma/Llama/Qwen-class small model as cheap, a 70B-class model as mid) served with vLLM, and Sarvam models self-hosted for the indic tier. Prices in `config.py` become per-token GPU cost. The judge runs on the in-VPC mid model. Logs stay in the VPC. Nothing leaves the network; the only change for an air-gapped site is pointing `OPENROUTER_URL` / `SARVAM_URL` at local gateways and dropping the API keys.

## Part 2: economics

See `results/economics.md` (generated by the benchmark): each config scaled to 50M input + 10M output tokens/month, monthly cost in $ and ₹, % saved vs always_frontier, with all assumptions listed.

## Part 3

- Q1: _placeholder_
- Q2: _placeholder_
- Q3: _placeholder_
- Q4: _placeholder_
- Q5: _placeholder_
- Q6: not present in the brief. Assumption taken: the numbering skips 6 by mistake; nothing was answered for it and questions 7 and 8 keep their original numbers.
- Q7: _placeholder_
- Q8: _placeholder_
