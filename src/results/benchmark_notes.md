# Benchmark notes (2026-10-09)

Source of truth for every number below: `results/run39_cap2048/` (summary.csv, economics.md, requests.csv/jsonl, run_id 4e96d8b9).
The same files are copied to `results/` and `logs/` as the current results.

## Held-out set: 39 prompts

- 30 short prompts (the original set): call-centre summaries, document extraction, translation, classification; about half Indic.
- 9 long-form prompts added today, each backed by a real file under `data/` (loaded via `source_file` in prompts.json):
  - 5 PDFs in `data/docs/`, rendered from HTML with headless Chrome by `data/make_docs.py`, text extracted with PyMuPDF at load time:
    2-page GST invoice with mixed rates and one deliberate arithmetic error (de_09), 46-transaction bank statement (de_10),
    bilingual Hindi/English motor policy schedule (de_11), home-loan sanction letter with penalty clauses (de_12),
    Hindi complaint letter in Devanagari (de_13).
  - 4 long call transcripts in `data/calls/`, 25-35 turns with filler and corrections: Hinglish collections call (cc_09),
    English broadband call with three issues (cc_10), Hindi UPI dispute call (cc_11), Hinglish health-claim call where the
    customer first reads the wrong policy number (cc_12).
  - Every rubric number (totals, counts, balances) is computed in make_docs.py, not typed by hand.
- Input sizes: short prompts average ~450 chars; long-form 2.3k-5k chars.

## Results: 39 prompts x 3 configs, output cap 2048 tokens

| Config | Serving cost | Mean latency | p95 latency | Mean quality (0-10) | Resolved (>=8) | Cost per resolved | Fallback rate |
|---|---|---|---|---|---|---|---|
| always_cheapest | ₹0.82 | 2.4 s | 4.6 s | 8.54 | 77% | ₹0.028 | 0% |
| always_frontier | ₹60.46 | 10.1 s | 22.6 s | 9.36 | 92% | ₹1.679 | 0% |
| router | ₹14.40 | 5.0 s | 16.4 s | 9.62 | 95% | ₹0.389 | 0% |

Router mix: cheap 10%, indic 38%, mid 23%, upper_mid 20%, frontier 8%. Router overhead (mDeBERTa, local MPS): ~235 ms mean on this set (165 ms on short prompts, 230-400 ms on long ones).
Judge cost is tracked separately (about $0.033 per config) and is NOT in the serving cost.
Projected monthly cost for 50M in / 10M out at measured blended rates: always_cheapest ₹792, always_frontier ₹35,200, router ₹10,228 (70.9% saved). See results/economics.md.

Per-workload (router): call_centre_summary q=9.7, document_extraction q=9.5, translation q=9.4, classification q=10.0.
Where the cheap tier broke on long inputs: loan letter q=1, broadband call q=2, bank statement q=5, invoice q=6. The router sent those to mid (q=10, 10, 10) except the bank statement, which it sent to cheap (q=5: sum of large withdrawals wrong by ₹9,750; all 16 items and balances right).

## What changed between runs (and why the archived numbers differ)

1. `results/run30_short/` (30 prompts, cap 1024): always_cheapest q=8.87 beat always_frontier q=8.67 and the router saved only 43%. Two measurement bugs:
   - Exact-match scorer only looked at the first line. Prompts cl_04 and cl_07 ask for reasoning first and the label last, so every config scored 0 on both. Fixed in quality.py (label accepted on the last line too).
   - MAX_OUTPUT_TOKENS=1024 cut off three frontier answers (finish_reason=length; judge comments say "cut off"). Frontier's low score was the cap, not the model.
2. `results/run39_cap2048/` (39 prompts, cap 2048): the valid run. Two answers still hit the cap on the longest documents (frontier loan letter q=2, frontier bank statement q=5 with the answer otherwise correct), so frontier is slightly under-stated on those two.
3. `results/run39_cap4096_FAILED_budget/` (cap 4096): the OpenRouter key has a $2.00 lifetime budget; it was exceeded at frontier prompt tr_07 and every later call returned HTTP 403 (including the mid-tier judge). Numbers in that folder are invalid. To redo it: raise the key limit at openrouter.ai/settings/keys, then `python run_benchmark.py` from src/.

Genuine model results worth knowing when asked "explain this number":
- cl_07: both cheap and frontier answered P2 where the rubric says P3 (a borderline policy call); the router (upper_mid) answered P3.
- de_10 bank statement: flash-lite lists all 16 withdrawals correctly but mis-adds them; opus gets the sum right.
- The difficulty classifier calls several short 3-bullet summaries "hard", which is why 20-33% of router traffic lands on upper_mid.
- Workload classifier on long instruction-heavy prompts: 32/39 overall; it labels "Return JSON ..." and "List ..." prompts as classification (de_09, de_10, de_12, cc_09, cc_12). An alternative label wording scored 35/39 but was worse on the original 30, so it was not adopted.

## What the quality measure does not capture

Quality is exact match for classification and an LLM judge on the mid tier (task + rubric + answer, integer 0-10) for everything else.
- The judge is a mid-tier model grading its own tier, and a judge weaker than the frontier model cannot see mistakes only the frontier model avoids; the router-vs-frontier gap on hard prompts is probably understated.
- It grades content, not usability: tone, register, Hindi honorifics, CRM-ready formatting and brand voice are invisible to it.
- Translation is scored against one reference; a correct but unnatural rendering, wrong dialect or wrong script choice passes.
- Fabrication is under-penalised: the rubric lists what must be present, so a summary with all required points plus an invented fact can still score 10.
- Classification is binary: a correct label wrapped in prose scores 0 (now mitigated for last-line labels), a wrong label with good reasoning also 0.
- 39 prompts is small: one prompt moves the mean by ~2.5%, scores are integers from a sampled model, and a re-run will not give identical numbers; no confidence intervals.
- Output-token cap is part of the measurement: 1024 and 2048 both truncated long-document answers. The cap is a serving parameter a customer must size per workload.
- Prompts are synthetic. PDF text extraction adds OCR-like artefacts (doubled matras in Devanagari such as "ग्रााहक"), which is realistic but means some Indic errors are the extractor's, not the model's.
- Difficulty labels are mine, so routing accuracy measures agreement with me, not with a customer.
- The judge only works offline: it needs a rubric. The router's in-request quality-floor escalation reuses the same judge, so production would need a reference-free check (refusal detector, sampled human review).
- Latency is from a laptop in India to OpenRouter/Sarvam over the public internet, with the classifier on an Apple GPU; a customer VPC changes both.

## Repo changes made today (uncommitted)

- data/make_docs.py, data/docs/*.pdf, data/calls/*.txt, prompts.json (+9 entries with source_file)
- engine.py: load_prompts reads source_file (PyMuPDF for PDFs); requirements.txt: pymupdf
- quality.py: exact match accepts label on the last line
- config.py: MAX_OUTPUT_TOKENS 1024 -> 4096 (2048 was used for the valid run; set it back to 2048 if you want the README to match exactly, or re-run at 4096 after raising the key budget)
- results/ and logs/ now contain the run39_cap2048 files; archived runs in results/run30_short, results/run39_cap2048, results/run39_cap4096_FAILED_budget
- app.py streaming change was already uncommitted before this session (not mine)

README mismatches to fix by hand: README.md says "30 prompts x 3 configs" and "30 held-out prompts, half Indic" (now 39); the files table should mention data/docs, data/calls and make_docs.py.
