"""
Framework-agnostic invoice extraction pipeline (LangGraph + a vision LLM).

The LLM backend (Ollama, Gemini, OpenAI, Anthropic) is chosen in core/llm.py.

Shared by the Streamlit UI (invoice_extractor.py) and the REST API (api/).
Nothing in this module imports Streamlit or FastAPI.
"""

from __future__ import annotations

import base64
import io
import os
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from PIL import Image

from core.llm import default_model, get_chat_model, get_provider
from core.pdf import render_pdf_pages

load_dotenv()

# ----------------------------- Configuration ---------------------------------
DEFAULT_PROVIDER = get_provider().name
DEFAULT_MODEL_NAME = default_model()
MISSING_VALUE = "N/A"
MAX_RETRIES = 2
# Multi-page PDFs: totals usually sit on the last page. Capped to bound image tokens per request.
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "5"))

INVOICE_FIELDS = [
    "INVOICE_NUMBER",
    "DATE",
    "DUE_DATE",
    "VENDOR_NAME",
    "VENDOR_ADDRESS",
    "CUSTOMER_NAME",
    "CUSTOMER_ADDRESS",
    "SUBTOTAL",
    "TAX",
    "TOTAL",
    "CURRENCY",
    "PAYMENT_TERMS",
    "LINE_ITEMS",
    "NOTES",
]
CRITICAL_FIELDS = ["INVOICE_NUMBER", "VENDOR_NAME", "TOTAL", "DATE"]

_GROUNDING_RULES = (
    "Rules:\n"
    "- Copy values exactly as printed on the document. Never calculate, sum, convert, or infer a value.\n"
    "- Do not add up line items to get a subtotal or total, and do not derive a due date from payment terms.\n"
    "- If a field is not printed anywhere on the document, answer N/A. N/A is a correct answer, not a failure.\n"
    "- The document may have several pages (images in page order). Totals are often on the last page.\n\n"
)

_OUTPUT_FORMAT = (
    "Return data in this EXACT format (use 'N/A' if not printed):\n\n"
    "INVOICE_NUMBER: ...\nDATE: ...\nDUE_DATE: ...\nVENDOR_NAME: ...\n"
    "VENDOR_ADDRESS: ...\nCUSTOMER_NAME: ...\nCUSTOMER_ADDRESS: ...\n"
    "SUBTOTAL: ...\nTAX: ...\nTOTAL: ...\nCURRENCY: ...\n"
    "PAYMENT_TERMS: ...\nLINE_ITEMS: item1 (qty x price) | item2 (qty x price) | ...\n"
    "NOTES: ..."
)

EXTRACTION_PROMPT = (
    "You are an expert invoice data extractor. Extract the information printed on this invoice.\n"
    + _GROUNDING_RULES
    + _OUTPUT_FORMAT
)


def build_correction_prompt(missing_fields: list[str]) -> str:
    """Second look at ONLY the fields that came back empty, without pressuring the model to invent them."""
    return (
        "You are an expert invoice data extractor. A first pass returned N/A for these fields: "
        f"{', '.join(missing_fields)}.\n"
        "Look again carefully at every page, including headers, footers, small print, rotated text and "
        "the last page. Report a value only if it is actually printed. Some documents (estimates, "
        "truncated or multi-page samples) genuinely lack these fields; then N/A is the right answer.\n"
        + _GROUNDING_RULES
        + "Return ONLY these fields, one per line, as FIELD_NAME: value\n"
        + "\n".join(f"{field}: ..." for field in missing_fields)
    )


# ----------------------------- Workflow State --------------------------------
class InvoiceState(TypedDict):
    images_b64: list[str]  # one PNG per page, in order
    provider: str
    model_name: str
    raw_text: str
    structured_data: dict[str, str]
    retry_count: int
    missing_fields: list[str]
    stalled: bool  # a retry found nothing new -> further retries would just repeat it


# ---------------------------- Pure Helper Logic -------------------------------
def _png_b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def file_to_base64_pages(file_bytes: bytes, mime_type: str, max_pages: int = MAX_PDF_PAGES) -> list[str]:
    """PDF -> one base64 PNG per page (up to max_pages); image -> a single base64 PNG."""
    if mime_type == "application/pdf":
        return [_png_b64(page) for page in render_pdf_pages(file_bytes, max_pages=max_pages)]
    return [_png_b64(Image.open(io.BytesIO(file_bytes)))]


def file_bytes_to_base64_png(file_bytes: bytes, mime_type: str) -> str:
    """First page only (kept for callers that need a single preview image)."""
    return file_to_base64_pages(file_bytes, mime_type, max_pages=1)[0]


def parse_invoice_fields(raw_text: str) -> dict[str, str]:
    """Parse `FIELD_NAME: value` lines from model output; missing fields become N/A."""
    fields: dict[str, str] = {}
    for line in raw_text.strip().splitlines():
        if ":" not in line:
            continue
        raw_key, raw_value = line.split(":", 1)
        # Models often decorate keys, e.g. "**TOTAL**" or "- TOTAL".
        key = raw_key.strip().strip("*-# ").upper().replace(" ", "_")
        if key in INVOICE_FIELDS:
            fields[key] = raw_value.strip().strip("*").strip() or MISSING_VALUE

    for required_key in INVOICE_FIELDS:
        fields.setdefault(required_key, MISSING_VALUE)
    return fields


def find_missing_critical(fields: dict[str, str]) -> list[str]:
    return [k for k in CRITICAL_FIELDS if fields.get(k, MISSING_VALUE) in ("", MISSING_VALUE)]


def add_validation_message(fields: dict[str, str]) -> dict[str, str]:
    """Attach a simple validation status based on critical fields."""
    missing = find_missing_critical(fields)
    validated = dict(fields)
    validated["_VALIDATION"] = (
        "All critical fields found" if not missing else f"Missing critical fields: {', '.join(missing)}"
    )
    return validated


def normalize_model_output(content: Any) -> str:
    """Normalize LangChain response content to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


_AMOUNT_RE = re.compile(r"-?\d[\d.,]*")


def parse_amount(value: str | None) -> Decimal | None:
    """
    Turn an LLM-produced money string into a Decimal, or None if unparseable.

    "$1,234.50" -> 1234.50, "1.234,50 EUR" -> 1234.50, "1,500" -> 1500, "N/A" -> None
    """
    if not value or value.strip().upper() == MISSING_VALUE:
        return None
    match = _AMOUNT_RE.search(value.replace(" ", ""))
    if not match:
        return None
    number = match.group(0).rstrip(".,")

    if "," in number and "." in number:
        # Whichever separator comes last is the decimal separator.
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif "," in number:
        head, _, tail = number.rpartition(",")
        # "1,500" / "12,000,000" -> thousands; "12,5" -> decimal comma.
        number = number.replace(",", "") if len(tail) == 3 else f"{head.replace(',', '')}.{tail}"
    elif number.count(".") > 1:
        number = number.replace(".", "")  # "1.234.567" -> thousands separators

    try:
        return Decimal(number)
    except InvalidOperation:
        return None


# ---------------------------- LangGraph Nodes ---------------------------------
def _call_vision_model(state: InvoiceState, prompt: str) -> str:
    llm = get_chat_model(state.get("provider") or DEFAULT_PROVIDER, state["model_name"])
    pages = state["images_b64"]
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for number, image_b64 in enumerate(pages, start=1):
        if len(pages) > 1:
            content.append({"type": "text", "text": f"Page {number} of {len(pages)}:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}})
    return normalize_model_output(llm.invoke([HumanMessage(content=content)]).content)


def extract_text_node(state: InvoiceState) -> dict[str, str]:
    """Step 1: Send every page of the invoice to the vision model."""
    return {"raw_text": _call_vision_model(state, EXTRACTION_PROMPT)}


def parse_fields_node(state: InvoiceState) -> dict[str, dict[str, str]]:
    """Step 2: Convert model text output into a structured dictionary.

    After a retry, only the fields that were missing are taken from the new answer. Fields the
    first pass already read stay untouched, so a retry can fill gaps but never overwrite good values.
    """
    parsed = parse_invoice_fields(state["raw_text"])
    if not state.get("retry_count"):
        return {"structured_data": parsed}
    merged = {k: v for k, v in state["structured_data"].items() if not k.startswith("_")}
    for field in state.get("missing_fields", []):
        merged[field] = parsed.get(field, MISSING_VALUE)
    return {"structured_data": merged}


def validate_output_node(state: InvoiceState) -> dict[str, Any]:
    """Step 3: Validate extracted fields and flag missing critical data."""
    validated = add_validation_message(state["structured_data"])
    missing = find_missing_critical(validated)
    stalled = bool(state.get("retry_count")) and set(missing) == set(state.get("missing_fields", []))
    return {"structured_data": validated, "missing_fields": missing, "stalled": stalled}


def should_retry(state: InvoiceState) -> str:
    """Retry while critical fields are missing, retries remain, and the last retry made progress."""
    if state.get("missing_fields") and state.get("retry_count", 0) < MAX_RETRIES and not state.get("stalled"):
        return "correct_extraction"
    return "end"


def correct_extraction_node(state: InvoiceState) -> dict[str, Any]:
    """Step 4: Ask the LLM to look again for the missing fields only."""
    return {
        "raw_text": _call_vision_model(state, build_correction_prompt(state["missing_fields"])),
        "retry_count": state.get("retry_count", 0) + 1,
    }


@lru_cache(maxsize=1)
def build_graph():
    """Compile the LangGraph pipeline once per process."""
    graph = StateGraph(InvoiceState)
    graph.add_node("extract_text", extract_text_node)
    graph.add_node("parse_fields", parse_fields_node)
    graph.add_node("validate_output", validate_output_node)
    graph.add_node("correct_extraction", correct_extraction_node)

    graph.add_edge(START, "extract_text")
    graph.add_edge("extract_text", "parse_fields")
    graph.add_edge("parse_fields", "validate_output")
    graph.add_conditional_edges(
        "validate_output",
        should_retry,
        {"correct_extraction": "correct_extraction", "end": END},
    )
    graph.add_edge("correct_extraction", "parse_fields")
    return graph.compile()


def initial_state(
    images_b64: str | list[str], model_name: str | None = None, provider: str | None = None
) -> InvoiceState:
    provider = get_provider(provider).name
    return {
        "images_b64": [images_b64] if isinstance(images_b64, str) else list(images_b64),
        "provider": provider,
        "model_name": model_name or default_model(provider),
        "raw_text": "",
        "structured_data": {},
        "retry_count": 0,
        "missing_fields": [],
        "stalled": False,
    }


def run_extraction(
    file_bytes: bytes, mime_type: str, model_name: str | None = None, provider: str | None = None
) -> InvoiceState:
    """Run the full pipeline synchronously and return the final graph state."""
    pages = file_to_base64_pages(file_bytes, mime_type)
    return build_graph().invoke(initial_state(pages, model_name, provider))
