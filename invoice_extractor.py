"""
Invoice Extractor app built with Streamlit + LangGraph + Ollama.

This file is organized for teaching:
1) Configuration and constants
2) Pure helper functions (easy to unit-test)
3) LangGraph nodes (business workflow)
4) Streamlit UI (presentation layer)
"""

from __future__ import annotations

import json
from typing import Any

import streamlit as st
from pdf2image import convert_from_bytes

from api.database import SessionLocal, init_db
from api.repository import list_recent, save_extraction
from core.invoice_pipeline import (
    DEFAULT_MODEL_NAME,
    MISSING_VALUE,
    InvoiceState,
    build_graph,
    file_bytes_to_base64_png,
    initial_state,
)

# ----------------------------- Configuration ---------------------------------
# Extraction logic lives in core/invoice_pipeline.py (shared with the REST API).
APP_TITLE = "Invoice Extractor"
SUPPORTED_UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp"]

CUSTOM_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.result-card {
    background: linear-gradient(135deg, #1a1f2e, #151922);
    border: 1px solid #2a3040;
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
}
.result-card h3 {
    color: #60a5fa;
    margin-bottom: .5rem;
    font-size: .85rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
}
.result-card p { color: #e2e8f0; font-size: 1.1rem; margin: 0; }
.status-badge {
    display: inline-block;
    background: #1e3a5f;
    color: #60a5fa;
    padding: .25rem .75rem;
    border-radius: 20px;
    font-size: .8rem;
    font-weight: 500;
}
</style>
"""


# ----------------------------- History Logic ---------------------------------
# History is stored in the same database as the REST API (DATABASE_URL in .env):
# PostgreSQL in Docker, a local SQLite file otherwise.
@st.cache_resource
def _ensure_db() -> bool:
    init_db()
    return True


def load_history(limit: int = 100) -> list[dict[str, Any]]:
    """Most recent extractions, newest first."""
    _ensure_db()
    with SessionLocal() as db:
        rows = list_recent(db, limit=limit)
    return [
        {
            "id": row.id,
            "timestamp": row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "vendor_name": row.vendor_name or MISSING_VALUE,
            "invoice_number": row.invoice_number or MISSING_VALUE,
            "date": row.invoice_date or MISSING_VALUE,
            "total": row.total_raw or MISSING_VALUE,
            "currency": row.currency or MISSING_VALUE,
            "full_data": row.fields,
        }
        for row in rows
    ]


def save_to_history(result: InvoiceState, filename: str, mime_type: str) -> None:
    """Persist an extraction, skipping it if identical to the latest row."""
    _ensure_db()
    try:
        with SessionLocal() as db:
            save_extraction(
                db,
                result,
                filename=filename,
                content_type=mime_type,
                model_name=result["model_name"],
                skip_if_duplicate=True,
            )
    except Exception as exc:  # keep the UI usable if the DB is down
        st.warning(f"Could not save to history database: {exc}")


# ------------------------------- UI Helpers ----------------------------------
def render_styles() -> None:
    st.markdown(CUSTOM_STYLES, unsafe_allow_html=True)


def render_field_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="result-card">
            <h3>{label.replace("_", " ")}</h3>
            <p>{value}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_field_pair(data: dict[str, str], left_key: str, right_key: str) -> None:
    left_col, right_col = st.columns(2)
    with left_col:
        render_field_card(left_key, data.get(left_key, MISSING_VALUE))
    with right_col:
        render_field_card(right_key, data.get(right_key, MISSING_VALUE))


def render_invoice_preview(file_bytes: bytes, mime_type: str) -> None:
    if mime_type == "application/pdf":
        pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, dpi=150)
        st.image(pages[0], caption="Invoice Preview (Page 1)")
        return
    st.image(file_bytes, caption="Invoice Preview")


def process_invoice(
    file_bytes: bytes, mime_type: str, model_name: str, status: Any, filename: str = "upload"
) -> InvoiceState:
    """Run the end-to-end extraction flow and return final graph state."""
    status.write("Converting uploaded document to image...")
    image_b64 = file_bytes_to_base64_png(file_bytes, mime_type)

    status.write(f"Initializing LangGraph pipeline with model: {model_name}")
    pipeline = build_graph()

    start_state = initial_state(image_b64, model_name)

    result = dict(start_state)
    for event in pipeline.stream(start_state):
        for node_name, state_update in event.items():
            result.update(state_update)
            if node_name == "extract_text":
                status.write("Sent invoice to vision model and received raw text.")
            elif node_name == "parse_fields":
                status.write("Parsed raw text into structured fields.")
            elif node_name == "validate_output":
                missing = result.get("missing_fields", [])
                if missing:
                    status.write(f"Validation warning! Missing critical fields: {', '.join(missing)}")
                else:
                    status.write("Validation successful: All critical fields found.")
            elif node_name == "correct_extraction":
                status.write(
                    "[Self-Correction] Critical fields missing. Re-submitting to LLM to focus on missing data..."
                )

    status.update(label="Extraction complete", state="complete")
    if result.get("structured_data"):
        save_to_history(result, filename, mime_type)
    return result


def render_results(result: InvoiceState) -> None:
    """Render extracted fields, validation, raw output, and JSON download."""
    data = result["structured_data"]
    validation = data.get("_VALIDATION", "")
    export_data = {k: v for k, v in data.items() if k != "_VALIDATION"}

    st.markdown("## Extracted Data")
    if validation:
        st.markdown(f'<span class="status-badge">{validation}</span>', unsafe_allow_html=True)

    key_metrics = ["INVOICE_NUMBER", "DATE", "TOTAL", "CURRENCY"]
    metric_cols = st.columns(len(key_metrics))
    for col, key in zip(metric_cols, key_metrics, strict=True):
        with col:
            render_field_card(key, data.get(key, MISSING_VALUE))

    st.markdown("### Parties")
    render_field_pair(data, "VENDOR_NAME", "CUSTOMER_NAME")
    render_field_pair(data, "VENDOR_ADDRESS", "CUSTOMER_ADDRESS")

    st.markdown("### Financials")
    render_field_pair(data, "SUBTOTAL", "TAX")
    render_field_pair(data, "DUE_DATE", "PAYMENT_TERMS")

    st.markdown("### Line Items")
    render_field_card("LINE_ITEMS", data.get("LINE_ITEMS", MISSING_VALUE))
    render_field_card("NOTES", data.get("NOTES", MISSING_VALUE))

    with st.expander("Raw LLM Output"):
        st.code(result["raw_text"], language="text")

    st.download_button(
        "Download as JSON",
        data=json.dumps(export_data, indent=2),
        file_name="invoice_data.json",
        mime="application/json",
    )


# --------------------------------- App --------------------------------------
def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=":receipt:", layout="wide")
    render_styles()

    st.title(APP_TITLE)
    st.markdown("---")

    with st.sidebar:
        st.subheader("Configuration")
        model_name = st.text_input(
            "Ollama Model",
            value=DEFAULT_MODEL_NAME,
            help="Vision-capable model name (for example: llava, llava:13b, bakllava).",
        )

    tab1, tab2 = st.tabs(["Extract Invoice", "Extraction History"])

    with tab1:
        st.write("Upload a PDF or image invoice to extract structured fields with a local Ollama model.")
        st.markdown("---")
        upload_col, preview_col = st.columns([1, 1])
        with upload_col:
            uploaded_file = st.file_uploader(
                "Drop your invoice here",
                type=SUPPORTED_UPLOAD_TYPES,
                help="Supported types: PDF, PNG, JPG, JPEG, WEBP",
                key="invoice_uploader",
            )

        if uploaded_file:
            file_bytes = uploaded_file.getvalue()
            with preview_col:
                render_invoice_preview(file_bytes, uploaded_file.type)

            st.markdown("---")

            if st.button("Extract Invoice Data", type="primary", use_container_width=True):
                with st.status("Processing invoice...", expanded=True) as status:
                    st.session_state["result"] = process_invoice(
                        file_bytes=file_bytes,
                        mime_type=uploaded_file.type,
                        model_name=model_name,
                        status=status,
                        filename=uploaded_file.name,
                    )

            if "result" in st.session_state:
                render_results(st.session_state["result"])

    with tab2:
        st.subheader("Extraction History")
        history = load_history()
        if not history:
            st.info("No extraction history found yet. Go to the 'Extract Invoice' tab to process a document!")
        else:
            import pandas as pd

            # Show history newest-first
            reversed_history = history  # already newest first
            history_data = []
            for idx, item in enumerate(reversed_history):
                history_data.append(
                    {
                        "No.": idx + 1,
                        "Timestamp": item.get("timestamp"),
                        "Vendor Name": item.get("vendor_name"),
                        "Invoice Number": item.get("invoice_number"),
                        "Date": item.get("date"),
                        "Total": item.get("total"),
                        "Currency": item.get("currency"),
                    }
                )
            df = pd.DataFrame(history_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("View Invoice Details")

            # Build human-readable labels for the selectbox
            labels = [
                f"#{idx + 1} - {item.get('vendor_name')} (Inv: {item.get('invoice_number')}, Total: {item.get('total')})"
                for idx, item in enumerate(reversed_history)
            ]
            selected_idx = st.selectbox(
                "Select a history item to inspect its full structured details:",
                options=range(len(reversed_history)),
                format_func=lambda i: labels[i],
            )

            if selected_idx is not None:
                selected_item = reversed_history[selected_idx]

                st.markdown(f"#### Details for Invoice from **{selected_item.get('vendor_name', 'N/A')}**")

                full_data = selected_item.get("full_data", {})
                st.json(full_data)

                st.download_button(
                    label="Download selected invoice as JSON",
                    data=json.dumps(full_data, indent=2),
                    file_name=f"invoice_{selected_item.get('invoice_number', 'extracted')}.json",
                    mime="application/json",
                    key=f"dl_history_{selected_idx}",
                )


if __name__ == "__main__":
    main()
