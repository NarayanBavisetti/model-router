"""Non-generative difficulty classifier: zero-shot NLI with multilingual DeBERTa (microsoft/mdeberta-v3-base fine-tuned
on XNLI). Reads the prompt, scores three candidate labels, returns one. Runs locally on CPU/MPS, costs $0 per call.
Loaded lazily on first use (about 560 MB download the first time)."""
import time
from config import DEBERTA_MODEL, DEBERTA_CUT_CHARS, DEBERTA_WORKLOAD_CUT_CHARS

LABELS = {
    "a simple labelling or yes/no question": "easy",
    "a summarisation, extraction or translation task": "medium",
    "a task that needs multi-step reasoning, analysis or calculation": "hard",
}
WORKLOAD_LABELS = {
    "a customer service call transcript to summarise": "call_centre_summary",
    "a document to extract fields from": "document_extraction",
    "text to translate into another language": "translation",
    "a message to classify with a label": "classification",
}
_pipe = None


def _load():
    global _pipe
    if _pipe is None:
        import torch
        from transformers import pipeline
        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else -1)
        _pipe = pipeline("zero-shot-classification", model=DEBERTA_MODEL, device=device)
    return _pipe


def deberta_difficulty(prompt: str) -> tuple[str, str, float]:
    """Returns (easy|medium|hard, reason, ms). Only the first DEBERTA_CUT_CHARS are read: the instruction is at the top."""
    t0 = time.perf_counter()
    r = _load()(prompt[:DEBERTA_CUT_CHARS], candidate_labels=list(LABELS), hypothesis_template="This is {}.")
    level, conf = LABELS[r["labels"][0]], r["scores"][0]
    return level, f"deberta zero-shot {level} (p={conf:.2f})", (time.perf_counter() - t0) * 1000


def deberta_workload(prompt: str) -> tuple[str, str, float]:
    """Returns (workload, reason, ms). Measured 28/30 against the dataset's domain labels, zero-shot."""
    t0 = time.perf_counter()
    r = _load()(prompt[:DEBERTA_WORKLOAD_CUT_CHARS], candidate_labels=list(WORKLOAD_LABELS), hypothesis_template="This is {}.")
    wl, conf = WORKLOAD_LABELS[r["labels"][0]], r["scores"][0]
    return wl, f"deberta {wl} (p={conf:.2f})", (time.perf_counter() - t0) * 1000
