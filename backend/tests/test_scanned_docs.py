import io
import json

import pytest

from services import doc_reader, ingestion, validate_parse


def _image_only_pdf() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 600), "white")
    ImageDraw.Draw(img).text((40, 40), "Balance letter PRU 9 115.21 1,036.89", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def _llm(total=1036.89, price=115.21, value=1036.89):
    out = ingestion._PdfRows(
        account_name="Computershare - Prudential Financial (PRU)",
        as_of="27-Oct-2026",
        document_total=total,
        holdings=[ingestion._PdfRow(symbol="PRU", fund_name="Prudential Financial Inc", shares=9, price=price, market_value=value)],
    )
    return lambda sys, usr: out


def test_image_only_pdf_has_no_text_but_yields_page_image(monkeypatch):
    monkeypatch.setattr(doc_reader, "ocr_image", lambda png: "")
    doc = doc_reader.read_pdf(_image_only_pdf())
    assert not doc.text.strip() and len(doc.images) == 1 and doc.source == "vision"


def test_ocr_text_used_when_available(monkeypatch):
    monkeypatch.setattr(doc_reader, "ocr_image", lambda png: "PRU 9 shares")
    doc = doc_reader.read_pdf(_image_only_pdf())
    assert doc.source == "ocr" and doc.text == "PRU 9 shares" and not doc.images


def test_scanned_balance_letter_extracted_and_checked(monkeypatch):
    monkeypatch.setattr(doc_reader, "ocr_image", lambda png: "")
    r = ingestion.parse_pdf(_image_only_pdf(), llm_structured=_llm())
    assert r.needs_review and r.source == "vision" and r.confidence == "high"
    row = r.rows[0]
    assert (row.symbol, row.shares, row.price, row.market_value) == ("PRU", 9, 115.21, 1036.89)
    assert row.account_name.startswith("Computershare") and not row.needs_mapping
    assert all(c["level"] == "ok" for c in r.checks)


def test_checks_flag_inconsistent_numbers(monkeypatch):
    monkeypatch.setattr(doc_reader, "ocr_image", lambda png: "")
    r = ingestion.parse_pdf(_image_only_pdf(), llm_structured=_llm(price=151.21, total=2000))
    assert r.confidence == "low"
    assert sum(c["level"] == "fail" for c in r.checks) == 2  # row math and document total


def test_confidence_levels():
    assert validate_parse.confidence([]) == "high"
    assert validate_parse.confidence([{"level": "warn", "message": ""}]) == "medium"


def test_known_layout_still_deterministic():
    doc = doc_reader.DocContent(text="Ally Bank\nEnding Balance\nOnline Savings x1234 $100.00 $250.00", source="text")
    r = ingestion.parse_content(doc, llm_structured=lambda *a: pytest.fail("LLM must not be called"))
    assert r.parser == "ally_bank_pdf" and not r.needs_review


def test_preview_then_confirm_flow(client, monkeypatch):
    monkeypatch.setattr(doc_reader, "ocr_image", lambda png: "")
    import services.llm_router as lr

    out = _llm()(None, None)
    monkeypatch.setattr(lr, "complete_structured", lambda *a, **k: out)
    pre = client.post("/api/ingest", data={"file": (io.BytesIO(_image_only_pdf()), "prudential.pdf")}, content_type="multipart/form-data")
    body = pre.get_json()
    assert pre.status_code == 200 and body["preview"] and body["rows"][0]["symbol"] == "PRU"
    assert client.get("/api/portfolio").get_json()["accounts"] == []  # nothing written yet

    done = client.post(
        "/api/ingest",
        data={"filename": "prudential.pdf", "rows": json.dumps({"rows": body["rows"], "source": body["source"]})},
        content_type="multipart/form-data",
    )
    assert done.status_code == 201
    acct = client.get("/api/portfolio").get_json()["accounts"][0]
    assert acct["name"].startswith("Computershare") and acct["institution"] == "COMPUTERSHARE"
    assert acct["holdings"][0]["market_value"] == pytest.approx(1036.89)
