import io
import logging

import pytest

import db
import security
from models import IngestionLog


def _post_file(client, name, data, url="/api/ingest"):
    return client.post(url, data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")


# --- headers / CORS ---------------------------------------------------------------------------------------------------
def test_security_headers_on_every_response(client):
    for path in ("/api/health", "/api/profile", "/api/nope"):
        h = client.get(path).headers
        assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"] and h["Cache-Control"] == "no-store"


def test_cors_is_off_by_default(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers


def test_cors_allows_only_configured_origins():
    from app import create_app

    app = create_app({"DATABASE_URL": "sqlite://", "ACCESS_TOKEN": "", "TESTING": True, "CORS_ORIGINS": ["https://good.example"]})
    c = app.test_client()
    assert c.get("/api/health", headers={"Origin": "https://good.example"}).headers["Access-Control-Allow-Origin"] == "https://good.example"
    assert "Access-Control-Allow-Origin" not in c.get("/api/health", headers={"Origin": "https://evil.example"}).headers


# --- auth rate limit ----------------------------------------------------------------------------------------------------
def test_repeated_bad_tokens_get_429_then_valid_token_still_blocked(authed_app):
    c = authed_app.test_client()
    codes = [c.get("/api/profile", headers={"Authorization": "Bearer nope"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    assert c.get("/api/profile", headers={"Authorization": "Bearer s3cret"}).status_code == 429  # lockout covers the client


def test_good_requests_do_not_count_against_the_limit(authed_app):
    c = authed_app.test_client()
    assert all(c.get("/api/profile", headers={"Authorization": "Bearer s3cret"}).status_code == 200 for _ in range(30))


def test_limiter_window_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: now[0])
    lim = security.AuthRateLimiter(max_failures=2, window_s=60)
    lim.record_failure("a")
    lim.record_failure("a")
    assert lim.blocked("a") and not lim.blocked("b")
    now[0] += 61
    assert not lim.blocked("a")


def test_non_ascii_token_does_not_crash(authed_app):
    r = authed_app.test_client().get("/api/profile", headers={"Authorization": "Bearer pässword"})
    assert r.status_code == 401


# --- uploads ----------------------------------------------------------------------------------------------------------
def test_oversize_upload_rejected(client):
    client.application.config["MAX_CONTENT_LENGTH"] = 1024
    assert _post_file(client, "big.csv", b"x" * 5000).status_code == 413


@pytest.mark.parametrize("name", ["evil.exe", "notes.html", "archive.zip", "noext"])
def test_disallowed_extension_415(client, name):
    assert _post_file(client, name, b"hello").status_code == 415
    assert _post_file(client, name, b"hello", "/api/liabilities/ingest").status_code == 415


def test_pdf_extension_with_wrong_content_415(client):
    r = _post_file(client, "x.pdf", b"<html>not a pdf</html>")
    assert r.status_code == 415 and "PDF" in r.get_json()["error"]


def test_empty_file_415(client):
    assert _post_file(client, "x.csv", b"").status_code == 415


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.csv", "passwd.csv"),
        ("..\\..\\win\\sys.csv", "sys.csv"),
        ("/abs/path/a.csv", "a.csv"),
        ("a\x00b<script>.csv", "a_b_script_.csv"),
        ("", "upload"),
        ("..", "upload"),
    ],
)
def test_safe_filename(raw, expected):
    assert security.safe_filename(raw) == expected


def test_traversal_filename_is_logged_as_basename_only(client):
    _post_file(client, "../../../etc/passwd.pdf", b"%PDF-1.4 garbage")
    with client.application.app_context():
        names = [r.filename for r in db.session().query(IngestionLog).all()]
    assert names == ["passwd.pdf"]
    assert names and all("/" not in n and ".." not in n for n in names)


def test_pdf_page_bomb_rejected(monkeypatch):
    from types import SimpleNamespace

    import pdfplumber

    from services import doc_reader

    fake = SimpleNamespace(pages=[object()] * (security.MAX_PDF_PAGES + 1))
    monkeypatch.setattr(pdfplumber, "open", lambda f: SimpleNamespace(__enter__=lambda s: fake, __exit__=lambda *a: False))

    class Ctx:
        def __enter__(self):
            return fake

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pdfplumber, "open", lambda f: Ctx())
    with pytest.raises(ValueError, match="limit"):
        doc_reader.read_pdf(b"%PDF-1.4")


def test_decompression_bomb_image_rejected():
    from PIL import Image

    from services import doc_reader

    big = io.BytesIO()
    Image.new("1", (11000, 10000)).save(big, format="PNG")  # 110 MP
    with pytest.raises(Image.DecompressionBombError):
        doc_reader._normalize_image(big.getvalue())


# --- injection ---------------------------------------------------------------------------------------------------------
SQLI = "'; DROP TABLE holding; --"


def test_sql_injection_strings_are_data_not_code(client):
    r = client.put("/api/profile", json={"name": SQLI})
    assert r.status_code == 200 and client.get("/api/profile").get_json()["name"] == SQLI
    assert client.get(f"/api/research/reports?symbol={SQLI}").status_code in (200, 400, 404)
    assert client.get("/api/portfolio").status_code == 200  # tables still exist


def test_owner_field_is_allowlisted(client):
    r = client.post("/api/ingest", data={"owner": SQLI, "file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")}, content_type="multipart/form-data")
    assert r.status_code == 400


# --- log redaction ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "gone"),
    [
        ("Authorization: Bearer abc.DEF-123", "abc.DEF-123"),
        ("api_key=sk-ant-supersecret1234", "supersecret"),
        ("token: hunter2hunter2", "hunter2"),
        ("posting to https://discord.com/api/webhooks/123456/AbC-dEf_ghi", "AbC-dEf_ghi"),
        ("account 123456789012 failed", "123456789012"),
    ],
)
def test_redact(raw, gone):
    out = security.redact(raw)
    assert (gone not in out and "REDACTED" in out) or "******" in out


def test_redact_keeps_last_four_of_account_numbers():
    assert security.redact("acct 123456789012") == "acct ******9012"


def test_logging_filter_redacts_formatted_args(caplog):
    logger = logging.getLogger("alphabridge")
    logger.addFilter(security.RedactingFilter())
    caplog.set_level(logging.INFO, logger="alphabridge")
    logger.info("request with %s", "Bearer SECRETTOKEN123")
    assert all("SECRETTOKEN123" not in r.getMessage() for r in caplog.records)
