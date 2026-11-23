"""End-to-end LangGraph behaviour with a scripted fake LLM (no network).

These pin down the fixes that came out of the accuracy evaluation:
- a retry may fill missing critical fields but never overwrite fields the first pass already read,
- a retry that finds nothing new stops the loop instead of asking again,
- every PDF page is sent to the model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import invoice_pipeline as pipeline

DOCS = Path(__file__).resolve().parent.parent / "example_docs"


def answer(**fields: str) -> str:
    return "\n".join(f"{k}: {v}" for k, v in fields.items())


FIRST_PASS = answer(
    INVOICE_NUMBER="INV-1",
    DATE="23.05.2021",
    DUE_DATE="N/A",
    VENDOR_NAME="Bioplex",
    TOTAL="N/A",
)


@pytest.fixture
def scripted_llm(monkeypatch):
    """Replace the model call with queued answers; record the prompts it received."""
    calls: list[str] = []
    replies: list[str] = []

    def fake_call(state, prompt):
        calls.append(prompt)
        return replies.pop(0)

    monkeypatch.setattr(pipeline, "_call_vision_model", fake_call)
    return replies, calls


def run(images=("page",)):
    return pipeline.build_graph().invoke(pipeline.initial_state(list(images), "fake-model", "ollama"))


def test_no_retry_when_critical_fields_present(scripted_llm):
    replies, calls = scripted_llm
    replies.append(answer(INVOICE_NUMBER="1", DATE="2021-01-01", VENDOR_NAME="A", TOTAL="10"))
    result = run()
    assert len(calls) == 1
    assert result["retry_count"] == 0
    assert result["missing_fields"] == []


def test_retry_fills_missing_field_but_cannot_overwrite_others(scripted_llm):
    replies, calls = scripted_llm
    # The retry finds the total, but also "computes" a due date and changes the vendor.
    replies += [FIRST_PASS, answer(TOTAL="6610.95", DUE_DATE="22.06.2021", VENDOR_NAME="Someone else")]
    result = run()
    data = result["structured_data"]
    assert data["TOTAL"] == "6610.95"  # was missing -> accepted
    assert data["DUE_DATE"] == "N/A"  # not a retried field -> first pass kept
    assert data["VENDOR_NAME"] == "Bioplex"  # already read -> not overwritten
    assert result["missing_fields"] == []
    assert len(calls) == 2


def test_retry_that_finds_nothing_stops_the_loop(scripted_llm):
    replies, calls = scripted_llm
    replies += [FIRST_PASS, answer(TOTAL="N/A")]
    result = run()
    assert len(calls) == 2  # one retry, not MAX_RETRIES
    assert result["retry_count"] == 1
    assert result["stalled"] is True
    assert result["missing_fields"] == ["TOTAL"]


def test_partial_progress_keeps_retrying_up_to_the_limit(scripted_llm):
    replies, calls = scripted_llm
    replies += [
        answer(VENDOR_NAME="A", INVOICE_NUMBER="N/A", DATE="N/A", TOTAL="N/A"),
        answer(INVOICE_NUMBER="7", DATE="N/A", TOTAL="N/A"),  # progress: 3 -> 2 missing
        answer(DATE="2021-01-01", TOTAL="N/A"),  # progress again, but the limit is reached
    ]
    result = run()
    assert result["retry_count"] == pipeline.MAX_RETRIES
    assert len(calls) == 1 + pipeline.MAX_RETRIES
    assert result["missing_fields"] == ["TOTAL"]
    assert result["structured_data"]["INVOICE_NUMBER"] == "7"


def test_correction_prompt_asks_only_for_missing_fields_and_allows_na():
    prompt = pipeline.build_correction_prompt(["TOTAL", "DATE"])
    assert "TOTAL: ..." in prompt and "DATE: ..." in prompt
    assert "VENDOR_NAME: ..." not in prompt
    assert "N/A is the right answer" in prompt
    assert "Never calculate" in prompt


def test_all_pdf_pages_are_sent(monkeypatch):
    seen = []

    class FakeModel:
        def invoke(self, messages):
            seen.append(messages[0].content)

            class Reply:
                content = answer(INVOICE_NUMBER="1", DATE="d", VENDOR_NAME="v", TOTAL="1")

            return Reply()

    monkeypatch.setattr(pipeline, "get_chat_model", lambda *a, **k: FakeModel())
    pages = pipeline.file_to_base64_pages((DOCS / "invoice-7-0.pdf").read_bytes(), "application/pdf")
    assert len(pages) == 3

    pipeline.build_graph().invoke(pipeline.initial_state(pages, "m", "ollama"))
    content = seen[0]
    images = [block for block in content if block["type"] == "image_url"]
    labels = [block["text"] for block in content if block["type"] == "text" and block["text"].startswith("Page ")]
    assert len(images) == 3
    assert labels == ["Page 1 of 3:", "Page 2 of 3:", "Page 3 of 3:"]


def test_page_cap_and_single_image(monkeypatch):
    data = (DOCS / "invoice-7-0.pdf").read_bytes()
    assert len(pipeline.file_to_base64_pages(data, "application/pdf", max_pages=2)) == 2
    png = (DOCS / "hourly_invoice_template.png").read_bytes()
    assert len(pipeline.file_to_base64_pages(png, "image/png")) == 1
