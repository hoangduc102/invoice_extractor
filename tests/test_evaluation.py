"""Tests for the accuracy-evaluation scoring (no LLM calls)."""

from __future__ import annotations

import json

import pytest

from evaluation import evaluate
from evaluation.scoring import candidate_dates, score_field


@pytest.mark.parametrize(
    "field, predicted, expected, outcome",
    [
        # amounts
        ("TOTAL", "$6,950.00", 6950.0, "correct"),
        ("TOTAL", "2.809,30 EUR", 2809.30, "correct"),
        ("TOTAL", "$6,590.00", 6950.0, "wrong"),
        ("TOTAL", "N/A", 6950.0, "missed"),
        ("TOTAL", "N/A", None, "correct"),
        ("TOTAL", "$100.00", None, "hallucinated"),
        ("TAX", "N/A", [0, None], "correct"),
        ("TAX", "$0.00", [0, None], "correct"),
        # dates in many formats
        ("DATE", "23.05.2021", "2021-05-23", "correct"),
        ("DATE", "October 12, 2021", "2021-10-12", "correct"),
        ("DATE", "Sept 7th, 2028", "2028-09-07", "correct"),
        ("DATE", "10-02-2023", "2023-10-02", "correct"),
        ("DATE", "02/10/2023", "2023-10-02", "correct"),  # ambiguous: either reading accepted
        ("DATE", "2021-05-24", "2021-05-23", "wrong"),
        # invoice numbers
        ("INVOICE_NUMBER", "#INV-2023-001", "INV-2023-001", "correct"),
        ("INVOICE_NUMBER", "NP 00183", "NP#00183", "correct"),
        ("INVOICE_NUMBER", "INV-0012820", "0012820", "correct"),
        ("INVOICE_NUMBER", "12", "0012820", "wrong"),
        ("INVOICE_NUMBER", "ESTIMATE-1", None, "hallucinated"),
        # names
        ("VENDOR_NAME", "Ted’s Small Business", "Ted's Small Business", "correct"),
        ("VENDOR_NAME", "Bioplex - we love chemistry", "Bioplex", "correct"),
        ("VENDOR_NAME", "Zencorporation", "Zencorporations", "correct"),
        ("VENDOR_NAME", "Sally Yessler", "Ted's Small Business", "wrong"),
        ("CUSTOMER_NAME", "Awthentikz", ["Caitlin Roberts", "Awthentikz"], "correct"),
        # currency
        ("CURRENCY", "€", "EUR", "correct"),
        ("CURRENCY", "USD ($)", "USD", "correct"),
        ("CURRENCY", "$", ["USD", "$"], "correct"),
        ("CURRENCY", "EUR", "NZD", "wrong"),
    ],
)
def test_score_field(field, predicted, expected, outcome):
    assert score_field(field, predicted, expected) == outcome


def test_candidate_dates_rejects_garbage():
    assert candidate_dates("next Tuesday") == set()


def test_ground_truth_is_well_formed():
    truth = evaluate.load_ground_truth()
    files = {p.name for p in evaluate.DOCS_DIR.iterdir()}
    for doc in truth["documents"]:
        assert doc["file"] in files, doc["file"]
        assert set(doc["expected"]) == set(truth["fields"]), doc["file"]


def test_rescore_end_to_end(tmp_path, capsys):
    """Fabricated predictions: perfect first doc, one hallucination + one retry fix on the second."""
    truth = evaluate.load_ground_truth()
    doc_a, doc_b = truth["documents"][5], truth["documents"][11]  # hourly template, garden repairs

    def as_prediction(expected):
        out = {}
        for field, value in expected.items():
            value = value[0] if isinstance(value, list) else value
            out[field] = "N/A" if value is None else str(value)
        return out

    perfect_a = as_prediction(doc_a["expected"])
    final_b = as_prediction(doc_b["expected"]) | {"TAX": "$15.00"}  # TAX not on doc -> hallucinated
    first_b = final_b | {"TOTAL": "N/A"}  # fixed by the retry loop
    results = {
        "model": "fake",
        "runs": 2,
        "records": [
            {
                "file": doc_a["file"],
                "run": run,
                "first_pass": perfect_a,
                "final": perfect_a,
                "retry_count": 0,
                "seconds": 1,
            }
            for run in (1, 2)
        ]
        + [
            {"file": doc_b["file"], "run": run, "first_pass": first_b, "final": final_b, "retry_count": 1, "seconds": 3}
            for run in (1, 2)
        ],
    }
    path = tmp_path / "fake.json"
    path.write_text(json.dumps(results), encoding="utf-8")

    report = evaluate.score_results(results, truth)
    assert report["hallucinations"] == 2  # TAX on doc_b, in both runs
    assert report["per_field"]["TAX"]["hallucinated"] == 2
    assert report["perfect_documents"] == 2
    assert report["first_pass_accuracy"] < report["overall_accuracy"]
    assert report["consistency"] == 1.0
    assert report["avg_retries"] == 0.5

    evaluate.main(["--rescore", str(path)])
    out = capsys.readouterr().out
    assert "| TOTAL | 100% |" in out
    assert "Hallucinated fields | 2 / 36" in out


def test_update_readme_replaces_only_the_marked_block(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{evaluate.README_START}\nold table\n{evaluate.README_END}\noutro\n", encoding="utf-8")
    monkeypatch.setattr(evaluate, "README", readme)

    evaluate.update_readme("| new | table |")

    assert readme.read_text(encoding="utf-8") == (
        f"intro\n{evaluate.README_START}\n| new | table |\n{evaluate.README_END}\noutro\n"
    )


def test_real_readme_has_eval_markers():
    text = evaluate.README.read_text(encoding="utf-8")
    assert evaluate.README_START in text and evaluate.README_END in text


def test_failed_extractions_are_reported_not_scored():
    truth = evaluate.load_ground_truth()
    doc = truth["documents"][5]
    ok = {k: ("N/A" if v is None else str(v[0] if isinstance(v, list) else v)) for k, v in doc["expected"].items()}
    results = {
        "model": "fake",
        "runs": 1,
        "records": [
            {"file": doc["file"], "run": 1, "first_pass": ok, "final": ok, "retry_count": 0, "seconds": 1},
            {
                "file": truth["documents"][0]["file"],
                "run": 1,
                "first_pass": {},
                "final": {},
                "retry_count": 0,
                "seconds": 0,
                "error": "connection refused",
            },
        ],
    }
    report = evaluate.score_results(results, truth)
    assert report["errors"] == 1
    assert report["overall_accuracy"] == 1.0  # the errored document is excluded, not counted as N/A answers

    results["records"] = results["records"][1:]
    with pytest.raises(SystemExit, match="All 1 extractions failed"):
        evaluate.score_results(results, truth)
