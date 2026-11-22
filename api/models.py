"""ORM models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base

# JSONB on PostgreSQL (indexable, queryable), plain JSON elsewhere (SQLite in tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    # Upload metadata
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str] = mapped_column(String(100))

    # Promoted columns: the fields people filter/sort on.
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    vendor_name: Mapped[str | None] = mapped_column(String(255))
    invoice_date: Mapped[str | None] = mapped_column(String(50))  # as written on the invoice
    currency: Mapped[str | None] = mapped_column(String(20))
    total_raw: Mapped[str | None] = mapped_column(String(100))  # e.g. "$1,234.50"
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # parsed, for math/sorting

    # Extraction quality
    status: Mapped[str] = mapped_column(String(20))  # "complete" | "incomplete"
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_fields: Mapped[list[str]] = mapped_column(JsonType, default=list)

    # Full payload
    fields: Mapped[dict[str, Any]] = mapped_column(JsonType)
    raw_text: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_invoices_vendor_name", "vendor_name"),)
