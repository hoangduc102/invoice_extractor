"""Persistence helpers shared by the REST API and the Streamlit app."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Invoice
from core.invoice_pipeline import MISSING_VALUE, parse_amount


def _none_if_missing(value: str | None) -> str | None:
    return None if value in (None, "", MISSING_VALUE) else value


def build_invoice(result: Mapping[str, Any], *, filename: str, content_type: str, model_name: str) -> Invoice:
    """Map a final LangGraph state onto an Invoice row (not yet added to a session)."""
    fields = {k: v for k, v in result.get("structured_data", {}).items() if not k.startswith("_")}
    missing = list(result.get("missing_fields", []))
    return Invoice(
        filename=filename,
        content_type=content_type,
        model_name=model_name,
        invoice_number=_none_if_missing(fields.get("INVOICE_NUMBER")),
        vendor_name=_none_if_missing(fields.get("VENDOR_NAME")),
        invoice_date=_none_if_missing(fields.get("DATE")),
        currency=_none_if_missing(fields.get("CURRENCY")),
        total_raw=_none_if_missing(fields.get("TOTAL")),
        total_amount=parse_amount(fields.get("TOTAL")),
        status="incomplete" if missing else "complete",
        retry_count=result.get("retry_count", 0),
        missing_fields=missing,
        fields=fields,
        raw_text=result.get("raw_text", ""),
    )


def save_extraction(
    db: Session,
    result: Mapping[str, Any],
    *,
    filename: str,
    content_type: str,
    model_name: str,
    skip_if_duplicate: bool = False,
) -> Invoice:
    """Persist an extraction. With skip_if_duplicate, returns the latest row instead of
    inserting when its fields are identical (e.g. the user clicked Extract twice)."""
    invoice = build_invoice(result, filename=filename, content_type=content_type, model_name=model_name)
    if skip_if_duplicate:
        latest = db.scalars(select(Invoice).order_by(Invoice.id.desc()).limit(1)).first()
        if latest is not None and latest.fields == invoice.fields:
            return latest
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def list_recent(db: Session, limit: int = 100) -> list[Invoice]:
    return list(db.scalars(select(Invoice).order_by(Invoice.id.desc()).limit(limit)))
