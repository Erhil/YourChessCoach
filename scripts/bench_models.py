"""Run the bench set through each candidate model: VRAM, time, validator pass rate, Cyrillic share.

Run: python scripts/bench_models.py [--models a,b,...] [--limit N]
Results: data/bench/<YYYYmmdd-HHMMSS>.json
"""

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.coach.prompt import build_messages
from app.coach.schema import CoachFacts
from app.coach.templates import explain
from app.coach.validator import to_display, validate
from app.config import settings
from app.llm.client import LLMError, OllamaClient

MODELS = "qwen3.5:4b,qwen3.5:2b,gemma4:e2b,gemma4:e4b"
BENCH = ROOT / "backend" / "tests" / "fixtures" / "bench.json"


def vram_mib() -> int | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    return int(out.split()[0]) if out.strip() else None


def unload_all(url: str) -> None:
    try:
        for m in httpx.get(url + "/api/ps", timeout=5).json().get("models", []):
            httpx.post(
                url + "/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60
            )
    except httpx.HTTPError:
        pass
    time.sleep(3)


def measure_vram_gb(url: str, model: str) -> float | None:
    """Memory growth after one short call, with all models unloaded before."""
    unload_all(url)
    base = vram_mib()
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"num_ctx": 4096, "num_predict": 8},
        "messages": [{"role": "user", "content": "Привет"}],
    }
    httpx.post(url + "/api/chat", json=body, timeout=300).raise_for_status()
    time.sleep(1)
    now = vram_mib()
    return None if base is None or now is None else round((now - base) / 1024, 2)


def cyrillic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return (
        sum("а" <= c.lower() <= "я" or c.lower() == "ё" for c in letters) / len(letters)
        if letters
        else 0.0
    )


def run_model(client: OllamaClient, model: str, items: list[dict]) -> list[dict]:
    answers = []
    for i, item in enumerate(items, 1):
        facts = CoachFacts.model_validate(item["facts"])
        system, user = build_messages(facts)
        t0 = time.monotonic()
        try:
            text = client.chat(system, user, model)
            reasons = validate(text, facts)
        except LLMError as e:
            text, reasons = "", [f"llm error: {e}"]
        secs = round(time.monotonic() - t0, 2)
        answers.append(
            {
                "id": item["id"],
                "text": text,
                "display_text": to_display(text) if text and not reasons else "",
                "seconds": secs,
                "valid": not reasons,
                "reasons": reasons,
                "cyrillic": round(cyrillic_share(text), 3),
            }
        )
        print(f"  {model} {i}/{len(items)} {secs}s valid={not reasons}", flush=True)
    return answers


def run_template(items: list[dict]) -> list[dict]:
    answers = []
    for item in items:
        text = explain(CoachFacts.model_validate(item["facts"]))
        answers.append(
            {
                "id": item["id"],
                "text": text,
                "display_text": text,
                "seconds": 0,
                "valid": True,
                "reasons": [],
                "cyrillic": round(cyrillic_share(text), 3),
            }
        )
    return answers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=MODELS)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    items = json.loads(BENCH.read_text(encoding="utf-8"))[: args.limit]
    url = settings.llm_base_url
    client = OllamaClient(url, 120)
    results = {}
    for model in args.models.split(","):
        print(model, flush=True)
        vram = measure_vram_gb(url, model)
        results[model] = {"vram_gb": vram, "answers": run_model(client, model, items)}
    unload_all(url)
    results["template"] = {"vram_gb": None, "answers": run_template(items)}

    out_dir = ROOT / "data" / "bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = out_dir / f"{now:%Y%m%d-%H%M%S}.json"
    data = {"created": now.isoformat(timespec="seconds"), "items": items, "results": results}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'model':<14}{'VRAM GB':>8}{'mean s':>8}{'median s':>9}{'valid %':>8}{'cyr':>6}")
    for model, r in results.items():
        a = r["answers"]
        secs = [x["seconds"] for x in a]
        row = (
            r["vram_gb"],
            statistics.mean(secs),
            statistics.median(secs),
            100 * sum(x["valid"] for x in a) / len(a),
            statistics.mean(x["cyrillic"] for x in a),
        )
        vram = "n/a" if row[0] is None else f"{row[0]:.2f}"
        print(f"{model:<14}{vram:>8}{row[1]:>8.1f}{row[2]:>9.1f}{row[3]:>8.0f}{row[4]:>6.2f}")
    print(path)


if __name__ == "__main__":
    main()
