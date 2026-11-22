"""Tests for api/repository.py (shared by the API and the Streamlit app)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from api.database import Base
from api.models import Invoice
from api.repository import list_recent, save_extraction


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def result(vendor: str = "Acme", total: str = "$10.00", missing: list[str] | None = None) -> dict:
    return {
        "structured_data": {"VENDOR_NAME": vendor, "TOTAL": total, "DATE": "N/A", "_VALIDATION": "x"},
        "missing_fields": missing or [],
        "retry_count": 1,
        "raw_text": "raw",
    }


def save(db, res, **kw):
    return save_extraction(db, res, filename="a.png", content_type="image/png", model_name="llava", **kw)


def test_maps_fields_and_drops_internal_keys(db):
    row = save(db, result(missing=["DATE"]))
    assert row.vendor_name == "Acme"
    assert str(row.total_amount) == "10.00"
    assert row.invoice_date is None  # "N/A" stored as NULL
    assert row.status == "incomplete"
    assert "_VALIDATION" not in row.fields


def test_skip_if_duplicate(db):
    first = save(db, result(), skip_if_duplicate=True)
    again = save(db, result(), skip_if_duplicate=True)
    assert again.id == first.id
    save(db, result(vendor="Globex"), skip_if_duplicate=True)
    save(db, result(vendor="Globex"))  # without the flag, duplicates are allowed
    assert db.scalar(select(func.count()).select_from(Invoice)) == 3


def test_list_recent_newest_first(db):
    for vendor in ["A", "B", "C"]:
        save(db, result(vendor=vendor))
    assert [r.vendor_name for r in list_recent(db, limit=2)] == ["C", "B"]
