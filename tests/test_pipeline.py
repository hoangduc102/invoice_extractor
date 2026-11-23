"""Unit tests for the pure helpers and routing logic in core/invoice_pipeline.py."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.invoice_pipeline import (
    MAX_RETRIES,
    MISSING_VALUE,
    add_validation_message,
    find_missing_critical,
    normalize_model_output,
    parse_amount,
    parse_invoice_fields,
    should_retry,
)


def test_parse_fields_basic_and_fills_missing():
    raw = "INVOICE_NUMBER: INV-9\nTOTAL: $10.00\nrandom chatter without colon\nUNKNOWN_KEY: x"
    fields = parse_invoice_fields(raw)
    assert fields["INVOICE_NUMBER"] == "INV-9"
    assert fields["TOTAL"] == "$10.00"
    assert fields["VENDOR_NAME"] == MISSING_VALUE
    assert "UNKNOWN_KEY" not in fields


def test_parse_fields_tolerates_markdown_decoration():
    raw = "**VENDOR_NAME**: **Acme Corp**\n- DATE: 2026-01-01\nInvoice number: A-1"
    fields = parse_invoice_fields(raw)
    assert fields["VENDOR_NAME"] == "Acme Corp"
    assert fields["DATE"] == "2026-01-01"
    assert fields["INVOICE_NUMBER"] == "A-1"


def test_parse_fields_keeps_colons_in_value():
    fields = parse_invoice_fields("NOTES: Pay by: 2026-02-01")
    assert fields["NOTES"] == "Pay by: 2026-02-01"


def test_empty_value_becomes_missing():
    assert parse_invoice_fields("TOTAL:   ")["TOTAL"] == MISSING_VALUE


def test_validation_message_lists_missing_critical():
    fields = parse_invoice_fields("INVOICE_NUMBER: 1\nVENDOR_NAME: A")
    assert find_missing_critical(fields) == ["TOTAL", "DATE"]
    assert add_validation_message(fields)["_VALIDATION"] == "Missing critical fields: TOTAL, DATE"


@pytest.mark.parametrize(
    "missing, retries, expected",
    [
        (["TOTAL"], 0, "correct_extraction"),
        (["TOTAL"], MAX_RETRIES - 1, "correct_extraction"),
        (["TOTAL"], MAX_RETRIES, "end"),
        ([], 0, "end"),
    ],
)
def test_should_retry(missing, retries, expected):
    assert should_retry({"missing_fields": missing, "retry_count": retries}) == expected


def test_normalize_model_output_handles_list_content():
    content = ["a", {"type": "text", "text": "b"}, {"other": 1}]
    assert normalize_model_output(content) == "a\nb\n{'other': 1}"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$1,234.50", Decimal("1234.50")),
        ("1.234,50 EUR", Decimal("1234.50")),
        ("1,500", Decimal("1500")),
        ("12,5", Decimal("12.5")),
        ("1.234.567", Decimal("1234567")),
        ("USD 99", Decimal("99")),
        ("-20.00", Decimal("-20.00")),
        ("Total: 300.", Decimal("300")),
        ("N/A", None),
        ("", None),
        (None, None),
        ("unknown", None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected
