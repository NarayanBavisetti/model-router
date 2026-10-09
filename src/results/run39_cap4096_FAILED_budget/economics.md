# Economics: 50M input + 10M output tokens / month

Generated 2026-10-09. Prices as listed in `config.py` on that date. FX: 1 USD = ₹88.0.

| Config | Monthly cost (USD) | Monthly cost (INR) | Saved vs always_frontier | Basis |
|---|---:|---:|---:|---|
| always_cheapest | $9 | ₹792 | 97.8% | 100% cheap tier list price |
| always_frontier | $400 | ₹35,200 | 0.0% | 100% frontier tier list price |
| router | $25 | ₹2,196 | 93.8% | measured blended $/M (routing mix incl. fallback retries) |

## Cost per resolved business outcome

A request is resolved when the judge scores it >= 8/10. This is the number to show client teams: not price per token, but what one usable result costs.

| Config | Resolved rate | Cost per resolved outcome (₹) | Mean quality |
|---|---:|---:|---:|
| always_cheapest | 77% | 0.0323 | 8.46 |
| always_frontier | 56% | 1.1815 | 5.64 |
| router | 3% | 0.3619 | 0.4 |

## Measured routing mix (share of prompts by final tier)

| Config | cheap | indic | mid | upper_mid | frontier | fallback rate | mean quality |
|---|---:|---:|---:|---:|---:|---:|---:|
| always_cheapest | 100% | 0% | 0% | 0% | 0% | 0% | 8.46 |
| always_frontier | 0% | 0% | 0% | 0% | 100% | 0% | 5.64 |
| router | 23% | 38% | 33% | 5% | 0% | 62% | 0.4 |

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
- Prices: OpenRouter list prices and Sarvam published INR prices as of 2026-10-09; Sarvam converted at the FX rate above.
- FX: 1 USD = ₹88.0 (config.USD_TO_INR).
- Router cost = token-weighted blended price measured in this benchmark (sum of serving cost / sum of tokens), so it already includes fallback retries. The prompt mix of the benchmark is assumed representative of production traffic.
- Judge (LLM-as-judge) cost is an evaluation cost and is excluded from all monthly figures.
- No prompt caching, batch discounts or volume discounts assumed.
- Quality floor for fallback = 5/10; judge = mid tier.
