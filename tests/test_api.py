"""API tests. The LLM pipeline is replaced by FakeExtractor (see conftest.py)."""

from __future__ import annotations

from api.main import DEFAULT_PROVIDER
from core.llm import LLMConfigError

PNG = ("invoice.png", b"\x89PNG fake bytes", "image/png")


def upload(client, file=PNG, **form):
    return client.post("/invoices/extract", files={"file": file}, data=form)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_extract_persists_and_returns_invoice(client, fake_extractor):
    resp = upload(client, model_name="qwen3-vl:2b")
    assert resp.status_code == 201
    body = resp.json()

    assert body["invoice_number"] == "INV-001"
    assert body["vendor_name"] == "Acme Corp"
    assert body["total_raw"] == "$1,234.50"
    assert body["total_amount"] == "1234.50"
    assert body["status"] == "complete"
    assert body["model_name"] == f"{DEFAULT_PROVIDER}/qwen3-vl:2b"  # provider recorded with the model
    assert "_VALIDATION" not in body["fields"]
    assert fake_extractor.calls == [(b"\x89PNG fake bytes", "image/png", "qwen3-vl:2b")]

    fetched = client.get(f"/invoices/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["fields"]["CURRENCY"] == "USD"


def test_missing_fields_marked_incomplete_and_stored_as_null(client, fake_extractor):
    fake_extractor.fields.pop("TOTAL")
    fake_extractor.missing = ["TOTAL"]
    fake_extractor.retry_count = 2

    body = upload(client).json()
    assert body["status"] == "incomplete"
    assert body["missing_fields"] == ["TOTAL"]
    assert body["retry_count"] == 2
    assert body["total_raw"] is None
    assert body["total_amount"] is None


def test_content_type_falls_back_to_extension(client, fake_extractor):
    resp = upload(client, file=("scan.pdf", b"%PDF-1.4", "application/octet-stream"))
    assert resp.status_code == 201
    assert fake_extractor.calls[0][1] == "application/pdf"


def test_rejects_unsupported_type(client, fake_extractor):
    resp = upload(client, file=("notes.txt", b"hello", "text/plain"))
    assert resp.status_code == 415
    assert fake_extractor.calls == []


def test_rejects_empty_file(client):
    assert upload(client, file=("a.png", b"", "image/png")).status_code == 422


def test_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr("api.main.MAX_UPLOAD_BYTES", 10)
    assert upload(client, file=("a.png", b"x" * 11, "image/png")).status_code == 413


def test_backend_failure_returns_502_and_saves_nothing(client, fake_extractor):
    fake_extractor.error = ConnectionError("Ollama unreachable")
    resp = upload(client)
    assert resp.status_code == 502
    assert client.get("/invoices").json()["total"] == 0


def test_list_filters_and_pagination(client, fake_extractor):
    for vendor in ["Acme Corp", "Globex", "acme labs"]:
        fake_extractor.fields["VENDOR_NAME"] = vendor
        upload(client)
    fake_extractor.fields["VENDOR_NAME"] = "Initech"
    fake_extractor.missing = ["DATE"]
    upload(client)

    all_items = client.get("/invoices").json()
    assert all_items["total"] == 4
    assert all_items["items"][0]["vendor_name"] == "Initech"  # newest first

    acme = client.get("/invoices", params={"vendor": "ACME"}).json()
    assert {i["vendor_name"] for i in acme["items"]} == {"Acme Corp", "acme labs"}

    incomplete = client.get("/invoices", params={"status": "incomplete"}).json()
    assert [i["vendor_name"] for i in incomplete["items"]] == ["Initech"]

    page = client.get("/invoices", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 4 and len(page["items"]) == 2

    assert client.get("/invoices", params={"limit": 0}).status_code == 422
    assert client.get("/invoices", params={"status": "bogus"}).status_code == 422


def test_stats_aggregates_by_vendor(client, fake_extractor):
    for total in ["$100.00", "$50.25"]:
        fake_extractor.fields["TOTAL"] = total
        upload(client)
    fake_extractor.fields.update(VENDOR_NAME="Globex", TOTAL="N/A")
    fake_extractor.missing = ["TOTAL"]
    upload(client)

    stats = client.get("/invoices/stats").json()
    assert stats["invoice_count"] == 3
    assert stats["complete_count"] == 2
    assert stats["incomplete_count"] == 1
    assert stats["top_vendors"][0] == {
        "vendor_name": "Acme Corp",
        "invoice_count": 2,
        "total_amount": "150.25",
    }


def test_get_and_delete_404(client):
    assert client.get("/invoices/999").status_code == 404
    assert client.delete("/invoices/999").status_code == 404


def test_delete(client):
    invoice_id = upload(client).json()["id"]
    assert client.delete(f"/invoices/{invoice_id}").status_code == 204
    assert client.get(f"/invoices/{invoice_id}").status_code == 404


def test_config_reports_backend(client):
    body = client.get("/config").json()
    assert body["provider"] == DEFAULT_PROVIDER
    assert body["default_model"]


def test_missing_api_key_returns_503(client, fake_extractor):
    fake_extractor.error = LLMConfigError("GOOGLE_API_KEY is not set. Add it to .env to use LLM_PROVIDER=gemini.")
    resp = upload(client)
    assert resp.status_code == 503
    assert "GOOGLE_API_KEY" in resp.json()["detail"]


def test_corrupt_pdf_returns_422_without_calling_the_llm(client):
    """Real pipeline (no fake): PDF rendering fails before any model call."""
    from api.main import app, get_extractor
    from core.invoice_pipeline import run_extraction

    app.dependency_overrides[get_extractor] = lambda: run_extraction
    resp = upload(client, file=("broken.pdf", b"%PDF-1.4 truncated", "application/pdf"))
    assert resp.status_code == 422
    assert "valid PDF or image" in resp.json()["detail"]
