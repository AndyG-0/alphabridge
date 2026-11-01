import json

import pypdfium2
import pytest
import responses

import db
import seed
from models import Holding, LLMConfig
from services import export
from services.crypto import encrypt


@pytest.fixture
def seeded(app):
    seed.seed(app)
    return app


def _snapshot(s):
    d = export.export_json(s)
    d.pop("exported_at")
    return json.loads(json.dumps(d))


def test_json_round_trip(seeded):
    with seeded.app_context():
        s = db.session()
        before = _snapshot(s)
        assert before["tables"]["holding"]
        s.query(Holding).delete()
        s.commit()
        assert _snapshot(s) != before
        export.import_json(s, json.loads(json.dumps(export.export_json(s) | {"tables": before["tables"]})))
        s.commit()
        assert _snapshot(s) == before


def test_export_excludes_secrets(seeded):
    with seeded.app_context():
        s = db.session()
        cfg = s.query(LLMConfig).first() or LLMConfig()
        cfg.api_key_encrypted = encrypt("sk-secret")
        s.add(cfg)
        s.commit()
        blob = json.dumps(export.export_json(s))
        assert "sk-secret" not in blob and "llm_config" not in blob


def test_import_rejects_foreign_file(seeded):
    with seeded.app_context(), pytest.raises(ValueError):
        export.import_json(db.session(), {"tables": {}})


def test_pdf_and_csv_report(seeded):
    with seeded.app_context():
        d = export.report_data()
        pdf = export.make_pdf(export.report_lines(d) * 3)
        doc = pypdfium2.PdfDocument(pdf)
        assert len(doc) >= 1
        assert "Net worth" in doc[0].get_textpage().get_text_range()
        rows = export.report_csv(d).splitlines()
        assert rows[0].startswith("AlphaBridge plan report") and any("FSPSX" in r for r in rows)


def test_pdf_escapes_parentheses():
    pdf = export.make_pdf(["a (b) \\ c"])
    assert len(pypdfium2.PdfDocument(pdf)) == 1


def test_share_token(seeded):
    with seeded.app_context():
        t = export.make_share_token(1, now=1000)["token"]
        assert export.verify_share_token(t, now=1500)
        assert not export.verify_share_token(t, now=1000 + 86400 + 1)
        exp, sig = t.split(".")
        assert not export.verify_share_token(f"{int(exp) + 999999}.{sig}", now=1500)
        assert not export.verify_share_token("garbage", now=1500)
        assert export.make_share_token(999, now=0)["token"].startswith(str(30 * 86400))


def test_share_link_is_scoped_to_report(seeded):
    from app import create_app

    app = create_app({"DATABASE_URL": "sqlite://", "ACCESS_TOKEN": "tok", "TESTING": True, "APP_SECRET": "s"})
    c = app.test_client()
    h = {"Authorization": "Bearer tok"}
    token = c.post("/api/export/share", json={}, headers=h).get_json()["token"]
    assert c.get(f"/api/share/{token}/report.csv").status_code == 200
    assert c.get(f"/api/share/{token}/report.pdf").data.startswith(b"%PDF")
    assert c.get(f"/api/share/{token}/report.xlsx").status_code == 401  # not a share path
    assert c.get("/api/share/bad.token/report.csv").status_code == 404
    assert c.get("/api/profile").status_code == 401
    assert c.get("/api/export/json").status_code == 401


def test_import_route_requires_confirm(client):
    assert client.post("/api/export/import", json={"data": {}}).status_code == 400
    assert client.post("/api/export/import", json={"confirm": True, "data": {"nope": 1}}).status_code == 400


def test_local_backup_encrypted_and_restorable(seeded, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DEST", "local")
    monkeypatch.setenv("BACKUP_PATH", str(tmp_path))
    monkeypatch.setenv("BACKUP_KEEP", "2")
    with seeded.app_context():
        s = db.session()
        paths = [export.run_backup(s) for _ in range(3)]
        files = sorted(tmp_path.glob("*.json.enc"))
        assert len(files) == 2
        raw = files[-1].read_bytes()
        assert b"FSPSX" not in raw
        assert export.decrypt_backup(raw)["tables"]["holding"]
        with pytest.raises(ValueError):
            export.decrypt_backup(b"not-a-token")
    assert paths


@responses.activate
def test_webdav_backup(seeded, monkeypatch):
    monkeypatch.setenv("BACKUP_DEST", "webdav")
    monkeypatch.setenv("WEBDAV_URL", "https://dav.example.com/ab")
    responses.add(responses.PUT, "https://dav.example.com/ab/x.enc", status=201)
    with seeded.app_context():
        assert export.write_backup(b"x", "x.enc") == "https://dav.example.com/ab/x.enc"


def test_backup_route_needs_destination(client, monkeypatch):
    monkeypatch.delenv("BACKUP_DEST", raising=False)
    assert client.post("/api/export/backup").status_code == 400
