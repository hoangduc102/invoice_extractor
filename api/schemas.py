"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class InvoiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    filename: str
    invoice_number: str | None
    vendor_name: str | None
    invoice_date: str | None
    currency: str | None
    total_raw: str | None
    total_amount: Decimal | None
    status: str


class InvoiceDetail(InvoiceSummary):
    content_type: str
    model_name: str
    retry_count: int
    missing_fields: list[str]
    fields: dict[str, Any]
    raw_text: str


class InvoiceList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[InvoiceSummary]


class VendorStats(BaseModel):
    vendor_name: str
    invoice_count: int
    total_amount: Decimal | None


class Stats(BaseModel):
    invoice_count: int
    complete_count: int
    incomplete_count: int
    top_vendors: list[VendorStats]
