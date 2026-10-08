## Stack

It's a Python + FastAPI backend with a plain HTML/JS page. There are four parts:

1. **The Classifier** (`router.py`, `classifier.py`).
  - When a request comes in, the router asks two questions about the prompt: what kind of work is it, and how hard is it. Both are answered by mDeBERTa-v3, a multilingual NLI classifier, running zero-shot (it was not trained on my dataset).
  - For the workload it scores four labels (winner tells the dispatcher what the customer cares about cost, quality or speed): 

    | Workload (from the classifier)  | Priority | Why                                                                       |
    | ------------------------------- | -------- | ------------------------------------------------------------------------- |
    | intent tagging / classification | speed    | stands in for the voice-agent LLM step; a pause past ~1.5 s ends the call |
    | call centre summary             | cost     | high volume, small per-token differences become big bills                 |
    | translation                     | cost     | bulk throughput; Indic prompts go to Sarvam anyway                        |
    | document extraction             | quality  | a wrong number or date is unacceptable                                    |
    | not recognised                  | balanced | safe default                                                              |

  - For the difficulty it scores three labels: 
    - a simple labelling or yes/no question is marked as easy
    - a summarisation, extraction or translation task is marked as medium
    - a task that needs multi-step reasoning or calculation is marked as hard.
  - Why a classifier and not an LLM:
    - We only need a score to pick a model, not generated text.
    - It's cheaper. It runs locally on a small GPU (about 100 ms), so it can sit inside a customer VPC or an air-gapped deployment.
    - It's multilingual.
    - It's fast, so the router overhead stays small.

(I was thinking to use JEV as its a new stack and its a NLP but it can be used in air gapped setup, also the cost and latency would increse)

---

1. **The Model Dispatcher** (`router.py`, `engine.py`, `providers.py`)

Once the classifier has tagged a request with a workload and a difficulty, the dispatcher does three lookups and applies rule.

**Lookup 1: workload → priority.** The workload table in the classifier section gives one word: speed, cost, quality or balanced. That is what this customer cares about.

**Lookup 2: difficulty.** easy, medium or hard, from the classifier.

**Lookup 3: priority row × difficulty column → tier**


| Priority | easy  | medium    | hard      |
| -------- | ----- | --------- | --------- |
| speed    | cheap | cheap     | mid       |
| cost     | cheap | mid       | upper_mid |
| balanced | cheap | mid       | frontier  |
| quality  | mid   | upper_mid | frontier  |


In one sentence: figure out what the customer values, figure out how hard the prompt is, pick the cheapest model that fits both.

**One rules on top**


| Rule  | Fires when                                   | Result                          |
| ----- | -------------------------------------------- | ------------------------------- |
| Indic | prompt is in an Indian language and not hard | skip the table, use Sarvam-105B |


**The tiers**


| Tier      | Model                 | Provider   | ₹ / 1M in / out | Latency mean / p95          |
| --------- | --------------------- | ---------- | --------------- | --------------------------- |
| cheap     | gemini-2.5-flash-lite | OpenRouter | 8.8 / 35        | 2.2 s / 4.1 s               |
| indic     | sarvam-105b           | Sarvam API | 29.28 / 73.2    | 1.0 s / 2.0 s               |
| mid       | gemini-3.8-flash      | OpenRouter | 66 / 330        | 2.7 s / 3.1 s               |
| upper_mid | claude-sonnet-5.5     | OpenRouter | 176 / 880       | ~3 s (dry run only)         |
| frontier  | claude-opus-5.5       | OpenRouter | 352 / 1,760     | 3.7 to 9.0 s (dry run only) |


**What happens when a model fails**

there can be many ways in which the model failure can be handled 

1. Pre check layer - It checks every model every 30 seconds that is that model occupied, busy or bombared then it can change the provider or to a similar model.
2. In request failover - rate limit, outage or error while the call is in flight then it runs the next model from ordered list in the same request


| Layer               | When                                                                 | What happens                                                                                                  | Latency cost to the user    |
| ------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | --------------------------- |
| Pre-check           | the tier had 2+ failures in the last 30 s                            | skip it before calling, one tier up                                                                           | none                        |
| In-request failover | rate limit, outage or error while the call is in flight              | OpenRouter runs the next model from our ordered list in the same request; we bill the model that actually ran | none beyond the call itself |
| Escalation          | refusal, truncated reply, judge score below 5, or both models failed | retry once on the next tier up                                                                                | one extra call              |




## Routing policy (summary)

The router reads the prompt and nothing else. A local mDeBERTa classifier answers two questions: what kind of work is this (call centre summary, document extraction, translation, classification) and how hard is it (easy, medium, hard). The workload tells me what the customer cares about: classification stands in for the voice-agent step so it gets speed, summaries and translation are high volume so they get cost, document extraction gets quality because a wrong number is unacceptable, anything else gets balanced. Priority and difficulty then index a 4x3 table that names the tier. One rule sits on top: if the prompt is in an Indian language (Indic script, romanised Hindi/Tamil/Telugu words, or "translate into Hindi") and it is not hard, it goes to Sarvam-105B, which is cheaper than the mid tier and better at the language. Every decision is logged with a one-line why, for example `document_extraction (quality), hard, english -> frontier`. The classifier runs locally, costs no tokens, and its time is added to every latency I report.

## Trade-offs I considered and dropped

- **Using an LLM as a Classifier:** Considered it for its flexibility, but **dropped**. We only need a probability score for routing, not generated text and it would have introduced unnecessary cost, burns tokens, and adds latency.
- **Using Jev as the NLP Routing Engine:** It was the fastest but had to drop it as it comes with a cost and for the air-gappged setup it cannot be worked out. (data should remain in the self-hosted servers). 
- **Hardcoded If-Else Rule Engines:** considered it becuase of the lowest latency but it fails for the complex or ambiguous enterprise prompts, not every case can be handled in the if else condition.

## Scaling inside a customer VPC or air-gapped

The router and the classifier both run locally, there is no network call in the routing path. The only thing that goes out are the two provider URLs in `providers.py`, so that is the only thing to swap. In a VPC each tier points to a vLLM endpoint inside the customer network (Sarvam self hosted for indic, open weight models for cheap and mid) and the prices in `config.py` become the GPU cost per token. For air gapped it is the same, just copy the model weights once and remove the keys. Two things I would need to fix for scale, the health check is stored in memory so with multiple replicas it needs a shared store, and the in request failover is an OpenRouter feature so the local gateway has to do the same.