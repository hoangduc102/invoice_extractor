"""
Measure extraction accuracy against hand-labelled ground truth.

    python -m evaluation.evaluate                                   # LLM_PROVIDER / LLM_MODEL from .env
    python -m evaluation.evaluate --model gemini/gemini-3.5-flash-lite --runs 3 --delay 4 --update-readme
    python -m evaluation.evaluate --model ollama/llava --model openai/gpt-4.1-mini   # compare side by side
    python -m evaluation.evaluate --rescore evaluation/results/llava-20261122-1530.json

For every document it records the FIRST-pass extraction and the FINAL result after the
LangGraph self-correction loop, so the report shows how much the retry step actually helps.
With --runs > 1 it also measures consistency: how often the model gives the same answer
for the same field on the same document (LLM output is non-deterministic even at temperature 0).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.scoring import is_missing, score_document, summarize  # noqa: E402

GROUND_TRUTH = Path(__file__).with_name("ground_truth.json")
RESULTS_DIR = Path(__file__).with_name("results")
DOCS_DIR = ROOT / "example_docs"
README = ROOT / "README.md"
README_START, README_END = "<!-- EVAL:START -->", "<!-- EVAL:END -->"


def load_ground_truth() -> dict[str, Any]:
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))


# ------------------------------- Running ------------------------------------
def parse_model_spec(spec: str | None) -> tuple[str, str]:
    """'gemini/gemini-3.5-flash-lite' -> ('gemini', ...); a bare name uses LLM_PROVIDER.

    Only a known provider prefix is split off, so Ollama tags like 'qwen3-vl:2b' stay intact.
    """
    from core.llm import PROVIDERS, default_model, get_provider

    if spec and "/" in spec and spec.split("/", 1)[0] in PROVIDERS:
        provider, model = spec.split("/", 1)
        return provider, model
    provider = get_provider().name
    return provider, spec or default_model(provider)


def extract_with_trace(path: Path, provider: str, model: str) -> dict[str, Any]:
    """Run the graph on one file, keeping first-pass and final fields."""
    from core.invoice_pipeline import build_graph, file_to_base64_pages, initial_state

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    started = time.perf_counter()
    pages = file_to_base64_pages(path.read_bytes(), mime)
    state: dict[str, Any] = dict(initial_state(pages, model, provider))
    first_pass: dict[str, str] | None = None
    for event in build_graph().stream(state):
        for node, update in event.items():
            state.update(update)
            if node == "parse_fields" and first_pass is None:
                first_pass = dict(update["structured_data"])
    return {
        "first_pass": first_pass or {},
        "final": {k: v for k, v in state.get("structured_data", {}).items() if not k.startswith("_")},
        "retry_count": state.get("retry_count", 0),
        "seconds": round(time.perf_counter() - started, 2),
    }


def run_model(spec: str | None, runs: int, docs: list[dict[str, Any]], delay: float = 0) -> dict[str, Any]:
    provider, model = parse_model_spec(spec)
    label = f"{provider}/{model}"
    records = []
    for run in range(1, runs + 1):
        for doc in docs:
            path = DOCS_DIR / doc["file"]
            if records and delay:
                time.sleep(delay)  # stay under free-tier requests-per-minute limits
            print(f"[{label}] run {run}/{runs}  {doc['file']} ...", end=" ", flush=True)
            try:
                rec = extract_with_trace(path, provider, model)
                rec["error"] = None
                print(f"{rec['seconds']}s, retries={rec['retry_count']}")
            except Exception as exc:  # keep going; an error counts as all fields missing
                rec = {"first_pass": {}, "final": {}, "retry_count": 0, "seconds": 0, "error": str(exc)}
                print(f"ERROR: {exc}")
            records.append({"file": doc["file"], "run": run, **rec})
    return {
        "model": label,
        "provider": provider,
        "runs": runs,
        "created": datetime.now().isoformat(timespec="seconds"),
        "records": records,
    }


# ------------------------------- Scoring ------------------------------------
def score_results(results: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    expected_by_file = {d["file"]: d["expected"] for d in truth["documents"]}
    fields = truth["fields"]
    labelled = [r for r in results["records"] if r["file"] in expected_by_file]
    # A failed call (Ollama down, model missing) says nothing about accuracy: an empty
    # result would score "correct" on every absent field. Report errors, don't score them.
    records = [r for r in labelled if not r.get("error")]
    if not records:
        raise SystemExit(
            f"All {len(labelled)} extractions failed (first error: {labelled[0]['error'] if labelled else 'n/a'})."
        )

    final_scored = [score_document(r["final"], expected_by_file[r["file"]]) for r in records]
    first_scored = [score_document(r["first_pass"], expected_by_file[r["file"]]) for r in records]

    report = summarize(final_scored, fields)
    report["first_pass_accuracy"] = summarize(first_scored, fields)["overall_accuracy"]
    report["documents"] = len({r["file"] for r in records})
    report["errors"] = len(labelled) - len(records)
    report["avg_retries"] = round(statistics.mean(r["retry_count"] for r in records), 2) if records else 0
    report["avg_seconds"] = round(statistics.mean(r["seconds"] for r in records), 1) if records else 0
    report["consistency"] = consistency(records, fields) if results.get("runs", 1) > 1 else None
    report["per_document"] = [
        {"file": r["file"], "run": r["run"], "outcomes": s, "retry_count": r["retry_count"]}
        for r, s in zip(records, final_scored, strict=True)
    ]
    return report


def consistency(records: list[dict[str, Any]], fields: list[str]) -> float:
    """Share of (document, field) pairs where every run returned the same value."""
    by_file: dict[str, list[dict[str, str]]] = {}
    for r in records:
        by_file.setdefault(r["file"], []).append(r["final"])
    agree = total = 0
    for outputs in by_file.values():
        if len(outputs) < 2:
            continue
        for field in fields:
            values = {"N/A" if is_missing(o.get(field)) else " ".join(str(o[field]).split()).lower() for o in outputs}
            agree += len(values) == 1
            total += 1
    return round(agree / total, 4) if total else 1.0


# ------------------------------- Reporting ----------------------------------
def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def markdown_report(reports: list[dict[str, Any]], fields: list[str]) -> str:
    models = [r["model"] for r in reports]
    lines = [
        f"_Last run: {datetime.now():%Y-%m-%d} on {reports[0]['documents']} labelled invoices in `example_docs/` "
        f"(ground truth: `evaluation/ground_truth.json`). Reproduce with "
        f"`python -m evaluation.evaluate {' '.join('--model ' + m for m in models)}"
        f"{' --runs ' + str(reports[0]['runs']) if reports[0]['runs'] > 1 else ''}`._",
        "",
        "| Field | " + " | ".join(f"`{m}`" for m in models) + " |",
        "| :--- | " + " | ".join("---:" for _ in models) + " |",
    ]
    for field in fields:
        lines.append(f"| {field} | " + " | ".join(pct(r["per_field"][field]["accuracy"]) for r in reports) + " |")
    rows = [
        ("**Overall (after self-correction)**", lambda r: f"**{pct(r['overall_accuracy'])}**"),
        ("First pass only (no retry)", lambda r: pct(r["first_pass_accuracy"])),
        ("Hallucinated fields", lambda r: f"{r['hallucinations']} / {r['field_count']}"),
        ("Fully correct documents", lambda r: f"{r['perfect_documents']} / {len(r['per_document'])}"),
        ("Avg self-correction retries", lambda r: str(r["avg_retries"])),
        ("Avg seconds / document", lambda r: str(r["avg_seconds"])),
    ]
    if reports[0]["consistency"] is not None:
        rows.append((f"Run-to-run consistency ({reports[0]['runs']} runs)", lambda r: pct(r["consistency"])))
    if any(r["errors"] for r in reports):
        rows.append(("Failed extractions (not scored)", lambda r: str(r["errors"])))
    for label, fmt in rows:
        lines.append(f"| {label} | " + " | ".join(fmt(r) for r in reports) + " |")
    lines += [
        "",
        "Scoring: amounts compared numerically, dates parsed (all plausible day/month readings), "
        "invoice numbers compared on alphanumerics, names by normalized fuzzy match. "
        "A value returned for a field that is not on the document counts as a hallucination. "
        "Multi-page PDFs are sent in full (up to `MAX_PDF_PAGES`), so totals on later pages are expected to be found.",
    ]
    return "\n".join(lines)


def update_readme(block: str) -> None:
    text = README.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        raise SystemExit(f"README.md needs {README_START} ... {README_END} markers")
    head, rest = text.split(README_START, 1)
    _, tail = rest.split(README_END, 1)
    README.write_text(f"{head}{README_START}\n{block}\n{README_END}{tail}", encoding="utf-8")
    print("README.md updated.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--model",
        action="append",
        help="provider/model, e.g. gemini/gemini-3.5-flash-lite or ollama/llava (repeatable). "
        "A bare model name uses LLM_PROVIDER. Default: LLM_PROVIDER + LLM_MODEL from .env",
    )
    parser.add_argument("--delay", type=float, default=0, help="Seconds to wait between documents (rate limits)")
    parser.add_argument("--runs", type=int, default=1, help="Repeat each document N times to measure consistency")
    parser.add_argument("--only", nargs="*", help="Evaluate only these file names")
    parser.add_argument("--rescore", nargs="*", type=Path, help="Re-score saved results JSON files (no LLM calls)")
    parser.add_argument("--update-readme", action="store_true", help="Write the results table into README.md")
    args = parser.parse_args(argv)

    truth = load_ground_truth()
    docs = [d for d in truth["documents"] if not args.only or d["file"] in args.only]

    if args.rescore:
        all_results = [json.loads(p.read_text(encoding="utf-8")) for p in args.rescore]
    else:
        RESULTS_DIR.mkdir(exist_ok=True)
        all_results = []
        for spec in args.model or [None]:
            results = run_model(spec, args.runs, docs, delay=args.delay)
            safe = results["model"].replace(":", "_").replace("/", "_")
            out = RESULTS_DIR / f"{safe}-{datetime.now():%Y%m%d-%H%M}.json"
            out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Saved raw predictions -> {out.relative_to(ROOT)}")
            all_results.append(results)

    reports = []
    for results in all_results:
        report = score_results(results, truth)
        report.update(model=results["model"], runs=results.get("runs", 1))
        reports.append(report)

    block = markdown_report(reports, truth["fields"])
    print("\n" + block)
    if args.update_readme:
        update_readme(block)


if __name__ == "__main__":
    main()
