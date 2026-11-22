"""Shared fixtures: in-memory SQLite DB and a fake LLM extractor (no Ollama needed)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base, get_db
from api.main import app, get_extractor
from core.invoice_pipeline import INVOICE_FIELDS, MISSING_VALUE


class FakeExtractor:
    """Stands in for run_extraction; records calls and returns a canned graph state."""

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, str]] = []
        self.fields: dict[str, str] = {
            "INVOICE_NUMBER": "INV-001",
            "VENDOR_NAME": "Acme Corp",
            "DATE": "2026-01-15",
            "TOTAL": "$1,234.50",
            "CURRENCY": "USD",
        }
        self.missing: list[str] = []
        self.retry_count = 0
        self.error: Exception | None = None

    def __call__(self, data: bytes, content_type: str, model_name: str) -> dict:
        self.calls.append((data, content_type, model_name))
        if self.error:
            raise self.error
        structured = {k: self.fields.get(k, MISSING_VALUE) for k in INVOICE_FIELDS}
        structured["_VALIDATION"] = "ignored"
        return {
            "structured_data": structured,
            "missing_fields": self.missing,
            "retry_count": self.retry_count,
            "raw_text": "INVOICE_NUMBER: INV-001",
        }


@pytest.fixture
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def client(fake_extractor: FakeExtractor):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_extractor] = lambda: fake_extractor
    # No `with` block: skip the lifespan so the real DATABASE_URL is never touched.
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()
