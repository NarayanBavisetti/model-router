"""FastAPI app: serves the single-page UI and three endpoints. Run: uvicorn app:app --reload"""
import threading, subprocess, sys, os, csv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from config import MODELS, USD_TO_INR, RESULTS_DIR
from engine import load_prompts, run_request

app = FastAPI(title="Model Router")
_bench = {"running": False, "log": [], "returncode": None}


class RunBody(BaseModel):
    prompt: str
    mode: str | None = None  # None = priority derived from the detected workload
    prompt_id: str | None = None
    config: str = "router"
    reasoning: bool = False
    classifier: str | None = None  # rules | deberta | hybrid


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/prompts")
def prompts():
    # hidden_difficulty is stripped so the UI (and the router) never see it
    return [{k: v for k, v in p.items() if k != "hidden_difficulty"} for p in load_prompts()]


@app.get("/models")
def models():
    return {"usd_to_inr": USD_TO_INR, "models": MODELS}


@app.post("/run")
def run(body: RunBody):
    item = next((p for p in load_prompts() if p["id"] == body.prompt_id), None)
    if item is None or item["prompt"] != body.prompt:  # custom / edited prompt: judge needs a rubric, so skip judge
        item = {"id": "custom", "domain": "custom", "prompt": body.prompt, "reference_or_rubric": ""}
        return run_request(item, body.mode, body.config, reasoning=body.reasoning, judge=False,
                           classifier=body.classifier)
    return run_request(item, body.mode, body.config, reasoning=body.reasoning, classifier=body.classifier)


@app.post("/compare")
def compare(body: RunBody):
    """Run the same prompt through the two baselines (real calls, judged) so the router result can be compared."""
    item = next((p for p in load_prompts() if p["id"] == body.prompt_id), None)
    judge = item is not None and item["prompt"] == body.prompt
    if not judge:
        item = {"id": "custom", "domain": "custom", "prompt": body.prompt, "reference_or_rubric": ""}
    return [run_request(item, "balanced", cfg, judge=judge) for cfg in ("always_cheapest", "always_frontier")]


def _run_benchmark(args):
    _bench.update(running=True, log=[], returncode=None)
    proc = subprocess.Popen([sys.executable, "run_benchmark.py", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        _bench["log"].append(line.rstrip())
    proc.wait()
    _bench.update(running=False, returncode=proc.returncode)


@app.post("/benchmark")
def benchmark(limit: int = 0, all_modes: bool = False, classifiers: bool = False):
    if _bench["running"]:
        return {"status": "already running"}
    args = (["--limit", str(limit)] if limit else []) + (["--all-modes"] if all_modes else []) + (["--classifiers"] if classifiers else [])
    threading.Thread(target=_run_benchmark, args=(args,), daemon=True).start()
    return {"status": "started"}


@app.get("/benchmark/status")
def benchmark_status():
    summary = []
    path = os.path.join(RESULTS_DIR, "summary.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            summary = list(csv.DictReader(f))
    return {**_bench, "log": _bench["log"][-40:], "summary": summary}
