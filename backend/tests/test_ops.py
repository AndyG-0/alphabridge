import json
import logging
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backup as bk

from observability import JsonFormatter, request_id_var
from services import scheduler


def test_ready_reports_checks(client):
    r = client.get("/api/ready")
    body = r.get_json()
    assert r.status_code == 200 and body["status"] == "ready"
    assert body["checks"]["database"]["ok"] and body["checks"]["scheduler"]["disabled"] and body["checks"]["market_data"]["last_refresh"] is None


def test_ready_shows_last_market_refresh(app, client):
    from services import market_data

    with app.app_context():
        market_data.cache_set("k", [1])
    assert client.get("/api/ready").get_json()["checks"]["market_data"]["last_refresh"]


def test_ready_degraded_when_scheduler_enabled_but_not_running(app, client):
    app.config["ENABLE_SCHEDULER"] = True
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.get_json()["status"] == "degraded"


def test_ready_and_health_are_public_but_status_is_not(authed_app):
    c = authed_app.test_client()
    assert c.get("/api/ready").status_code == 200 and c.get("/api/health").status_code == 200
    assert c.get("/api/scheduler/status").status_code == 401


def test_request_id_generated_and_echoed(client):
    assert len(client.get("/api/profile").headers["X-Request-ID"]) == 16
    assert client.get("/api/profile", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    assert client.get("/api/profile", headers={"X-Request-ID": "bad id;"}).headers["X-Request-ID"] != "bad id;"


def test_json_formatter_includes_request_id_and_exception():
    token = request_id_var.set("rid-1")
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed %s", ("job",), sys.exc_info())
        out = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert out["msg"] == "failed job" and out["request_id"] == "rid-1" and out["level"] == "ERROR" and "ValueError" in out["exc"]


def test_scheduler_status_endpoint_and_run_tracking(app, client):
    scheduler.RUNS.clear()

    @scheduler._tracked("t_ok")
    def ok(app):
        pass

    @scheduler._tracked("t_bad")
    def bad(app):
        raise RuntimeError("nope")

    ok(app)
    bad(app)  # must not raise: a failing job is recorded, not fatal
    body = client.get("/api/scheduler/status").get_json()
    assert body["history"]["t_ok"]["status"] == "ok" and body["history"]["t_bad"]["status"] == "error"
    assert "RuntimeError: nope" in body["history"]["t_bad"]["error"] and body["enabled"] is False


# --- backup / restore ---------------------------------------------------------------------------------------------
def _make_db(path: Path, rows=3):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    con.commit()
    return con


def _rows(path: Path):
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT v FROM t ORDER BY id")]
    finally:
        con.close()


def test_backup_is_consistent_while_wal_has_uncheckpointed_writes(tmp_path):
    db = tmp_path / "a.db"
    con = _make_db(db)  # connection stays open: data lives in the -wal file
    assert (tmp_path / "a.db-wal").exists()
    dest = bk.backup(db, tmp_path / "bk")
    con.close()
    assert _rows(dest) == ["row0", "row1", "row2"]


def test_restore_roundtrip_keeps_safety_copy(tmp_path):
    db = tmp_path / "a.db"
    _make_db(db).close()
    snap = bk.backup(db, tmp_path / "bk")
    con = sqlite3.connect(db)
    con.execute("DELETE FROM t")
    con.commit()
    con.close()
    assert _rows(db) == []
    with pytest.raises(FileExistsError):
        bk.restore(snap, db)
    bk.restore(snap, db, force=True)
    assert _rows(db) == ["row0", "row1", "row2"] and (tmp_path / "a.pre-restore").exists()
    assert _rows(tmp_path / "a.pre-restore") == []


def test_backup_retention(tmp_path):
    db = tmp_path / "a.db"
    _make_db(db).close()
    made = [bk.backup(db, tmp_path / "bk", keep=2) for _ in range(4)]
    left = sorted((tmp_path / "bk").glob("a-*.db"))
    assert left == sorted(made)[-2:]


def test_restore_rejects_corrupt_backup(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        bk.restore(bad, tmp_path / "x.db")
    assert not (tmp_path / "x.db").exists()


def test_cli(tmp_path, capsys):
    db = tmp_path / "a.db"
    _make_db(db).close()
    assert bk.main(["backup", "--db", str(db), "--out", str(tmp_path / "o")]) == 0
    assert bk.main(["backup", "--db", str(tmp_path / "missing.db")]) == 1
    assert "error:" in capsys.readouterr().err
