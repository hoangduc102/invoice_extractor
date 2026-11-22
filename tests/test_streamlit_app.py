"""Smoke test: the Streamlit app renders and its History tab reads from the database."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import api.database as database  # noqa: E402
from api.repository import save_extraction  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parent.parent / "invoice_extractor.py")


@pytest.fixture
def memory_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    database.init_db()
    yield session_factory
    engine.dispose()


def test_history_tab_lists_saved_invoices(memory_db):
    with memory_db() as db:
        save_extraction(
            db,
            {"structured_data": {"VENDOR_NAME": "Acme Corp", "INVOICE_NUMBER": "INV-42", "TOTAL": "$99.00"}},
            filename="a.png",
            content_type="image/png",
            model_name="llava",
        )

    app = AppTest.from_file(APP_PATH, default_timeout=30).run()

    assert not app.exception
    history = app.dataframe[0].value
    assert list(history["Vendor Name"]) == ["Acme Corp"]
    assert list(history["Invoice Number"]) == ["INV-42"]
    assert list(history["Total"]) == ["$99.00"]


def test_empty_history_shows_hint(memory_db):
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not app.exception
    assert any("No extraction history" in info.value for info in app.info)
