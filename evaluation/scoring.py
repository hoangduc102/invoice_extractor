"""
Field-level scoring of extracted invoice data against hand-labelled ground truth.

LLM output is messy ("$1,234.50", "Sept 7, 2028", "#INV-2023-001"), so each field type
is normalized before comparing. Every comparison returns one of:

  correct       prediction matches (or both say "not on the document")
  wrong         field exists, model returned a different value
  missed        field exists, model returned N/A
  hallucinated  field is NOT on the document, model invented a value
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, Literal

from core.invoice_pipeline import MISSING_VALUE, parse_amount

Outcome = Literal["correct", "wrong", "missed", "hallucinated"]

AMOUNT_FIELDS = {"SUBTOTAL", "TAX", "TOTAL"}
DATE_FIELDS = {"DATE", "DUE_DATE"}
ID_FIELDS = {"INVOICE_NUMBER"}
CURRENCY_FIELDS = {"CURRENCY"}

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y/%m/%d",
    "%d.%m.%y",
    "%m/%d/%y",
    "%d/%m/%y",
]
_CURRENCY_ALIASES = {"€": "EUR", "£": "GBP", "¥": "JPY", "₫": "VND", "US$": "USD", "DOLLAR": "$", "DOLLARS": "$"}


def is_missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().upper() in ("", MISSING_VALUE, "NONE", "NULL", "-")
    )


def _text_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).replace("’", "'")
    value = re.sub(r"[^a-z0-9 ]", " ", value.lower())
    return " ".join(value.split())


def candidate_dates(value: str) -> set[date]:
    """All plausible readings of a date string (03/04/2021 is ambiguous: return both)."""
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip(), flags=re.I)
    text = re.sub(r"\bSept\b", "Sep", text, flags=re.I).replace(",", ", ").replace("  ", " ")
    text = re.sub(r"\s+,", ",", text).strip()
    found = set()
    for fmt in _DATE_FORMATS:
        for candidate in (text, text.replace(", ", " ")):
            try:
                found.add(datetime.strptime(candidate, fmt).date())
            except ValueError:
                pass
    return found


def _match_one(field: str, predicted: str, expected: Any) -> bool:
    if field in AMOUNT_FIELDS:
        amount = parse_amount(predicted)
        return amount is not None and abs(float(amount) - float(expected)) < 0.005
    if field in DATE_FIELDS:
        return date.fromisoformat(expected) in candidate_dates(predicted)
    if field in ID_FIELDS:
        strip = lambda s: re.sub(r"[^A-Za-z0-9]", "", s).upper()  # noqa: E731
        p, e = strip(predicted), strip(expected)
        # Allow a printed prefix the model may keep or drop: "INV-0012820" vs "0012820".
        return bool(p) and (p == e or (p.endswith(e) and len(e) >= 4))
    if field in CURRENCY_FIELDS:
        p = predicted.strip().upper()
        p = _CURRENCY_ALIASES.get(p, p)
        e = str(expected).upper()
        return p == e or e in re.findall(r"[A-Z]{3}|\$", p)
    # Free text (names): normalized equality, containment, or high similarity.
    p, e = _text_key(predicted), _text_key(str(expected))
    if not p:
        return False
    if p == e or (len(e) >= 4 and (e in p or p in e)):
        return True
    return SequenceMatcher(None, p, e).ratio() >= 0.85


def score_field(field: str, predicted: Any, expected: Any) -> Outcome:
    """`expected` may be a value, None (absent from document), or a list of acceptable values."""
    options = expected if isinstance(expected, list) else [expected]
    allows_missing = any(o is None for o in options)
    present_options = [o for o in options if o is not None]

    if is_missing(predicted):
        return "correct" if allows_missing else "missed"
    if not present_options:
        return "hallucinated"
    if any(_match_one(field, str(predicted), o) for o in present_options):
        return "correct"
    return "wrong"


def score_document(predicted: dict[str, Any], expected: dict[str, Any]) -> dict[str, Outcome]:
    return {field: score_field(field, predicted.get(field), exp) for field, exp in expected.items()}


def summarize(scored_docs: list[dict[str, Outcome]], fields: list[str]) -> dict[str, Any]:
    """Aggregate outcomes into per-field and overall accuracy."""
    per_field: dict[str, dict[str, int]] = {}
    for field in fields:
        outcomes = [doc[field] for doc in scored_docs if field in doc]
        per_field[field] = {
            "n": len(outcomes),
            **{k: outcomes.count(k) for k in ("correct", "wrong", "missed", "hallucinated")},
        }
        per_field[field]["accuracy"] = round(per_field[field]["correct"] / len(outcomes), 4) if outcomes else 0.0

    total = sum(v["n"] for v in per_field.values())
    correct = sum(v["correct"] for v in per_field.values())
    hallucinated = sum(v["hallucinated"] for v in per_field.values())
    return {
        "per_field": per_field,
        "overall_accuracy": round(correct / total, 4) if total else 0.0,
        "hallucinations": hallucinated,
        "field_count": total,
        "perfect_documents": sum(all(o == "correct" for o in doc.values()) for doc in scored_docs),
    }
