## 2. Cost and latency by configuration

**A. Always frontier (the status quo)**
Model: claude-opus-5.5 (₹352 / 1M in, ₹1,760 / 1M out)
- Input: 50M × 352 = ₹17,600
- Output: 10M × 1,760 = ₹17,600
- Total: ₹35,200
- p95 latency: ~7.5 s (heavy reasoning models take longer on every workload)

**B. Always cheapest**
Model: gemini-2.5-flash-lite (₹8.8 / 1M in, ₹35 / 1M out)
- Input: 50M × 8.8 = ₹440
- Output: 10M × 35 = ₹350
- Total: ₹790
- p95 latency: ~4.1 s
- The catch: high failure rate and poor comprehension on Indian scripts and complex documents

**C. The router (optimised mix + classifier)**

| Tier | Calculation | Cost |
|---|---|---|
| Cheap (60%) | 30M × 8.8 + 6M × 35 | ₹474 |
| Indic (15%) | 7.5M × 29.28 + 1.5M × 73.2 | ₹329 |
| Mid (15%) | 7.5M × 66 + 1.5M × 330 | ₹990 |
| Frontier (10%) | 5M × 352 + 1M × 1,760 | ₹3,520 |
| **Total** | | **₹5,313** |

- p95 latency: ~2.4 s blended (100 ms local classification + fast paths for the 90% of traffic that is not frontier)

## 3. Summary

| Configuration | Monthly cost (₹) | Saved vs frontier | Blended p95 latency | Quality / compliance profile |
|---|---|---|---|---|
| 1. Always frontier | ₹35,200 | 0% | ~7.5 s | maximum quality, unsustainable bills |
| 2. Always cheapest | ₹790 | 97.7% | ~4.1 s | fails on Indic context and complex extraction |
| 3. Router | ₹5,313 | 84.9% | ~2.4 s | enterprise grade, maintains 99%+ accuracy |


For the cost of the model router mDeBERTa-v3, is a small text classification model which requires less than 1 GB of VRAM to run.
renting a whole dedicated T4 instance just to run mDeBERTa will costs roughly ₹33,400 a month on-demand. But this model will hardly take 6% of  GPU's memory and compute capacity. Instead enterprise VPC or air-gapped setup, the customers already have larger open-weight models, so mDeBERTa can be loaded in that same space (it will bring the cost to 0).
If the customer uses APIs then instead of GPU customer can go with the CPU which will cost less but the latency would increase. GPU takes around 150ms but the CPU's would take 300ms to 500ms 