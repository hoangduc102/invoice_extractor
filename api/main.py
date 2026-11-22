"""
REST API for the invoice extractor.

Run locally:  uvicorn api.main:app --reload
Docs:         http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile, status
from PIL import UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import Base, engine, get_db
from api.models import Invoice
from api.schemas import InvoiceDetail, InvoiceList, Stats, VendorStats
from core.invoice_pipeline import DEFAULT_MODEL_NAME, MISSING_VALUE, parse_amount, run_extraction

logger = logging.getLogger("invoice_api")

ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

Extractor = Callable[[bytes, str, str], dict]


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Simple bootstrap; switch to Alembic migrations once the schema starts evolving.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Invoice Extractor API",
    version="1.0.0",
    description="Extract structured invoice data with a self-correcting LangGraph + Ollama pipeline.",
    lifespan=lifespan,
)


def get_extractor() -> Extractor:
    """Dependency so tests can swap the LLM pipeline for a fake."""
    return run_extraction


def _resolve_content_type(upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()
    if content_type in ALLOWED_TYPES:
        return content_type
    # Some clients send application/octet-stream; fall back to the extension.
    guessed, _ = mimetypes.guess_type(upload.filename or "")
    if guessed in ALLOWED_TYPES:
        return guessed
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"Unsupported file type '{content_type or 'unknown'}'. Allowed: PDF, PNG, JPEG, WEBP.",
    )


def _none_if_missing(value: str | None) -> str | None:
    return None if value in (None, "", MISSING_VALUE) else value


def _get_invoice_or_404(db: Session, invoice_id: int) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice


# --------------------------------- Routes -----------------------------------
@app.get("/health", tags=["meta"])
def health(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    db.execute(select(1))
    return {"status": "ok"}


@app.post(
    "/invoices/extract",
    response_model=InvoiceDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
def extract_invoice(
    db: Annotated[Session, Depends(get_db)],
    extractor: Annotated[Extractor, Depends(get_extractor)],
    file: Annotated[UploadFile, File(description="Invoice as PDF or image")],
    model_name: Annotated[str, Form()] = DEFAULT_MODEL_NAME,
) -> Invoice:
    """Upload an invoice, run the extraction graph, and persist the result.

    Declared as a sync `def` so FastAPI runs the blocking LLM call in its threadpool.
    """
    content_type = _resolve_content_type(file)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File larger than 10 MB")
    if not data:
        raise HTTPException(422, "Uploaded file is empty")

    try:
        result = extractor(data, content_type, model_name)
    except (UnidentifiedImageError, ValueError) as exc:
        raise HTTPException(422, f"Could not read document: {exc}") from exc
    except Exception as exc:  # LLM backend down, model not pulled, timeout, ...
        logger.exception("Extraction failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Extraction backend error: {exc}") from exc

    fields = {k: v for k, v in result.get("structured_data", {}).items() if not k.startswith("_")}
    missing = list(result.get("missing_fields", []))

    invoice = Invoice(
        filename=file.filename or "upload",
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
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


@app.get("/invoices", response_model=InvoiceList, tags=["invoices"])
def list_invoices(
    db: Annotated[Session, Depends(get_db)],
    vendor: Annotated[str | None, Query(description="Case-insensitive substring match")] = None,
    status_filter: Annotated[Literal["complete", "incomplete"] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvoiceList:
    query = select(Invoice)
    if vendor:
        query = query.where(Invoice.vendor_name.ilike(f"%{vendor}%"))
    if status_filter:
        query = query.where(Invoice.status == status_filter)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(limit).offset(offset)
    ).all()
    return InvoiceList(total=total, limit=limit, offset=offset, items=list(rows))


@app.get("/invoices/stats", response_model=Stats, tags=["invoices"])
def invoice_stats(db: Annotated[Session, Depends(get_db)]) -> Stats:
    counts = dict(db.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
    vendor_rows = db.execute(
        select(Invoice.vendor_name, func.count(), func.sum(Invoice.total_amount))
        .where(Invoice.vendor_name.is_not(None))
        .group_by(Invoice.vendor_name)
        .order_by(func.count().desc(), Invoice.vendor_name)
        .limit(5)
    ).all()
    return Stats(
        invoice_count=sum(counts.values()),
        complete_count=counts.get("complete", 0),
        incomplete_count=counts.get("incomplete", 0),
        top_vendors=[
            VendorStats(vendor_name=name, invoice_count=count, total_amount=amount)
            for name, count, amount in vendor_rows
        ],
    )


@app.get("/invoices/{invoice_id}", response_model=InvoiceDetail, tags=["invoices"])
def get_invoice(invoice_id: int, db: Annotated[Session, Depends(get_db)]) -> Invoice:
    return _get_invoice_or_404(db, invoice_id)


@app.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["invoices"])
def delete_invoice(invoice_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    db.delete(_get_invoice_or_404(db, invoice_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
