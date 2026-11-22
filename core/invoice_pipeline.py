"""
Framework-agnostic invoice extraction pipeline (LangGraph + Ollama).

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
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from PIL import Image

load_dotenv()

# ----------------------------- Configuration ---------------------------------
DEFAULT_MODEL_NAME = os.getenv("DEFAULT_MODEL", "llava")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MISSING_VALUE = "N/A"
MAX_RETRIES = 2

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

_OUTPUT_FORMAT = (
    "Return data in this EXACT format (use 'N/A' if not found):\n\n"
    "INVOICE_NUMBER: ...\nDATE: ...\nDUE_DATE: ...\nVENDOR_NAME: ...\n"
    "VENDOR_ADDRESS: ...\nCUSTOMER_NAME: ...\nCUSTOMER_ADDRESS: ...\n"
    "SUBTOTAL: ...\nTAX: ...\nTOTAL: ...\nCURRENCY: ...\n"
    "PAYMENT_TERMS: ...\nLINE_ITEMS: item1 (qty x price) | item2 (qty x price) | ...\n"
    "NOTES: ..."
)

EXTRACTION_PROMPT = (
    "You are an expert invoice data extractor. Analyze this invoice image and "
    "extract ALL information. " + _OUTPUT_FORMAT
)


def build_correction_prompt(missing_fields: list[str]) -> str:
    return (
        "You are an expert invoice data extractor. In your previous attempt, you missed "
        f"these critical fields: {', '.join(missing_fields)}.\n"
        "Please analyze this invoice image carefully again and extract all information. "
        "Especially, make sure to find the missing fields.\n" + _OUTPUT_FORMAT
    )


# ----------------------------- Workflow State --------------------------------
class InvoiceState(TypedDict):
    image_b64: str
    model_name: str
    raw_text: str
    structured_data: dict[str, str]
    retry_count: int
    missing_fields: list[str]


# ---------------------------- Pure Helper Logic -------------------------------
def file_bytes_to_base64_png(file_bytes: bytes, mime_type: str) -> str:
    """Convert a PDF (first page) or image upload into base64-encoded PNG."""
    if mime_type == "application/pdf":
        from pdf2image import convert_from_bytes  # needs Poppler; import lazily

        image = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=200)[0]
    else:
        image = Image.open(io.BytesIO(file_bytes))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


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
        "All critical fields found"
        if not missing
        else f"Missing critical fields: {', '.join(missing)}"
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
def _call_vision_model(model_name: str, prompt: str, image_b64: str) -> str:
    llm = ChatOllama(model=model_name, temperature=0, base_url=OLLAMA_BASE_URL)
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
    )
    return normalize_model_output(llm.invoke([message]).content)


def extract_text_node(state: InvoiceState) -> dict[str, str]:
    """Step 1: Send invoice image to Ollama vision model."""
    return {"raw_text": _call_vision_model(state["model_name"], EXTRACTION_PROMPT, state["image_b64"])}


def parse_fields_node(state: InvoiceState) -> dict[str, dict[str, str]]:
    """Step 2: Convert model text output into a structured dictionary."""
    return {"structured_data": parse_invoice_fields(state["raw_text"])}


def validate_output_node(state: InvoiceState) -> dict[str, Any]:
    """Step 3: Validate extracted fields and flag missing critical data."""
    validated = add_validation_message(state["structured_data"])
    return {"structured_data": validated, "missing_fields": find_missing_critical(validated)}


def should_retry(state: InvoiceState) -> str:
    """Route to correct_extraction if critical fields are missing and retries remain."""
    if state.get("missing_fields") and state.get("retry_count", 0) < MAX_RETRIES:
        return "correct_extraction"
    return "end"


def correct_extraction_node(state: InvoiceState) -> dict[str, Any]:
    """Step 4: Prompt the LLM again, instructing it to find the missing fields."""
    prompt = build_correction_prompt(state["missing_fields"])
    return {
        "raw_text": _call_vision_model(state["model_name"], prompt, state["image_b64"]),
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


def initial_state(image_b64: str, model_name: str) -> InvoiceState:
    return {
        "image_b64": image_b64,
        "model_name": model_name,
        "raw_text": "",
        "structured_data": {},
        "retry_count": 0,
        "missing_fields": [],
    }


def run_extraction(file_bytes: bytes, mime_type: str, model_name: str) -> InvoiceState:
    """Run the full pipeline synchronously and return the final graph state."""
    image_b64 = file_bytes_to_base64_png(file_bytes, mime_type)
    return build_graph().invoke(initial_state(image_b64, model_name))
