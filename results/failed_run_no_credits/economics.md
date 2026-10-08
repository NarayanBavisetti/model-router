# Economics: 50M input + 10M output tokens / month

Generated 2026-10-08. Prices as listed in `config.py` on that date. FX: 1 USD = ₹88.0.

| Config | Monthly cost (USD) | Monthly cost (INR) | Saved vs always_frontier | Basis |
|---|---:|---:|---:|---|
| always_cheapest | $9 | ₹792 | 97.8% | 100% cheap tier list price |
| always_frontier | $400 | ₹35,200 | 0.0% | 100% frontier tier list price |
| router_balanced | $78 | ₹6,885 | 80.4% | measured blended $/M (routing mix incl. fallback retries) |
| router_cost_first | $160 | ₹14,120 | 59.9% | measured blended $/M (routing mix incl. fallback retries) |
| router_quality_first | $27 | ₹2,386 | 93.2% | measured blended $/M (routing mix incl. fallback retries) |
| router_deberta | $30 | ₹2,650 | 92.5% | measured blended $/M (routing mix incl. fallback retries) |
| router_hybrid | $34 | ₹3,036 | 91.4% | measured blended $/M (routing mix incl. fallback retries) |

## Cost per resolved business outcome

A request is resolved when the judge scores it >= 8/10. This is the number to show client teams: not price per token, but what one usable result costs.

| Config | Resolved rate | Cost per resolved outcome (₹) | Mean quality |
|---|---:|---:|---:|
| always_cheapest | 83% | 0.0141 | 8.73 |
| always_frontier | 23% | 0.7757 | 2.33 |
| router_balanced | 53% | 0.0372 | 6.65 |
| router_cost_first | 57% | 0.1282 | 7 |
| router_quality_first | 53% | 0.0088 | 5.27 |
| router_deberta | 33% | 0.0306 | 4.42 |
| router_hybrid | 50% | 0.0192 | 5.62 |

## Measured routing mix (share of prompts by final tier)

| Config | cheap | indic | mid | upper_mid | frontier | fallback rate | mean quality |
|---|---:|---:|---:|---:|---:|---:|---:|
| always_cheapest | 100% | 0% | 0% | 0% | 0% | 0% | 8.73 |
| always_frontier | 0% | 0% | 0% | 0% | 100% | 0% | 2.33 |
| router_balanced | 10% | 43% | 17% | 3% | 27% | 3% | 6.65 |
| router_cost_first | 30% | 43% | 0% | 3% | 23% | 23% | 7 |
| router_quality_first | 0% | 43% | 10% | 0% | 47% | 20% | 5.27 |
| router_deberta | 10% | 40% | 7% | 7% | 37% | 7% | 4.42 |
| router_hybrid | 10% | 43% | 10% | 10% | 27% | 10% | 5.62 |

## Tier list prices used (USD per 1M tokens)

| Tier | Model | Input | Output | Monthly if used for 100% |
|---|---|---:|---:|---:|
| cheap | google/gemini-2.5-flash-lite | $0.1 | $0.4 | $9 |
| indic | sarvam-105b | $0.3327 | $0.8318 | $25 |
| mid | google/gemini-3.8-flash | $0.75 | $3.75 | $75 |
| upper_mid | anthropic/claude-sonnet-5.5 | $2.0 | $10.0 | $200 |
| frontier | anthropic/claude-opus-5.5 | $4.0 | $20.0 | $400 |

## Assumptions

- Volume: 50M input + 10M output tokens per month (5:1 input/output split as given in the brief).
- Prices: OpenRouter list prices and Sarvam published INR prices as of 2026-10-08; Sarvam converted at the FX rate above.
- FX: 1 USD = ₹88.0 (config.USD_TO_INR).
- Router cost = token-weighted blended price measured in this benchmark (sum of serving cost / sum of tokens), so it already includes fallback retries. The prompt mix of the benchmark is assumed representative of production traffic.
- Judge (LLM-as-judge) cost is an evaluation cost and is excluded from all monthly figures.
- No prompt caching, batch discounts or volume discounts assumed.
- Quality floor for fallback = 5/10; judge = mid tier.
