"""Data ownership: full JSON export/import, CSV and PDF plan report, encrypted backups, read-only share tokens.

* JSON export covers every user table. Secrets (LLM/notification/SimpleFIN credentials, which are Fernet-encrypted
  with this install's APP_SECRET and would be unreadable elsewhere) and rebuildable caches are excluded.
* Backups are the JSON export encrypted with Fernet (APP_SECRET) and written to a local directory, WebDAV or S3.
  Destination settings come from the environment so credentials never sit in the database.
* Share tokens are HMAC-signed `<expiry>.<signature>` strings that unlock only the read-only report routes.
"""

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests
from flask import current_app
from sqlalchemy import Boolean, Date, DateTime, delete, insert, select

from models import Base
from services import chat_tools
from services.crypto import decrypt, encrypt

EXPORT_VERSION = 1
EXCLUDED_TABLES = {"llm_config", "notification_config", "simplefin_config", "market_cache", "screener_result", "run_snapshot"}
MAX_SHARE_DAYS = 30


def _tables():
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_TABLES]


def _jsonable(v):
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def _coerce(col, v):
    if v is None:
        return None
    if isinstance(col.type, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(col.type, Date):
        return date.fromisoformat(v)
    if isinstance(col.type, Boolean):
        return bool(v)
    return v


def export_json(s) -> dict:
    out: dict = {"app": "alphabridge", "version": EXPORT_VERSION, "exported_at": datetime.now(UTC).isoformat(), "tables": {}}
    for t in _tables():
        rows = s.execute(select(t)).mappings().all()
        out["tables"][t.name] = [{k: _jsonable(v) for k, v in r.items()} for r in rows]
    return out


def import_json(s, data: dict) -> dict:
    """Replace all exported tables with the file's contents (one transaction; the caller commits)."""
    if data.get("app") != "alphabridge" or not isinstance(data.get("tables"), dict):
        raise ValueError("not an AlphaBridge export")
    if data.get("version", 0) > EXPORT_VERSION:
        raise ValueError(f"export version {data.get('version')} is newer than this app supports")
    tables = _tables()
    for t in reversed(tables):
        s.execute(delete(t))
    counts: dict[str, int] = {}
    for t in tables:
        rows = data["tables"].get(t.name, [])
        cols = {c.name: c for c in t.columns}
        clean = [{k: _coerce(cols[k], v) for k, v in r.items() if k in cols} for r in rows]
        if clean:
            s.execute(insert(t), clean)
        counts[t.name] = len(clean)
    return counts


# ---- plan report ----------------------------------------------------------------------------------------------------


def _money(v) -> str:
    return f"${float(v or 0):,.0f}"


def report_data() -> dict:
    h = chat_tools.HANDLERS
    alloc = h["get_allocation"]({})
    health = dict(h["get_plan_health"]({})).get("health", {})
    prof = h["get_profile"]({})
    accounts = h["get_accounts_and_holdings"]({})
    return {"generated": date.today().isoformat(), "profile": prof, "allocation": alloc, "health": health, "accounts": accounts}


def report_csv(d: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    a = d["allocation"]
    w.writerow(["AlphaBridge plan report", d["generated"]])
    w.writerow(["Net worth", round(a.get("net_worth", 0), 2)])
    w.writerow(["Assets", round(a.get("assets", 0), 2)])
    w.writerow(["Liabilities", round(a.get("liabilities", 0), 2)])
    if d["health"]:
        w.writerow(["Plan health", d["health"].get("score"), d["health"].get("grade")])
    w.writerow([])
    w.writerow(["Account", "Tax bucket", "Symbol", "Name", "Shares", "Price", "Market value", "Asset class"])
    for acct in d["accounts"]:
        for hld in acct.get("holdings", []):
            w.writerow(
                [
                    acct["name"],
                    acct["tax_bucket"],
                    hld["symbol"],
                    hld["name"],
                    hld["shares"],
                    hld["current_price"],
                    round(hld["market_value"], 2),
                    hld["asset_class"],
                ]
            )
    return buf.getvalue()


def report_lines(d: dict) -> list[str]:
    a = d["allocation"]
    lines = [f"AlphaBridge plan report - {d['generated']}", "", f"Net worth: {_money(a.get('net_worth'))}"]
    lines += [f"Assets: {_money(a.get('assets'))}    Liabilities: {_money(a.get('liabilities'))}", ""]
    for k, v in (a.get("pct") or {}).items():
        lines.append(f"  {k.replace('_', ' ').title()}: {v * 100:.1f}% ({_money(a['totals'].get(k))})")
    hl = d["health"]
    if hl:
        lines += ["", f"Plan health: {hl.get('score')}/100 ({hl.get('grade')})"]
        lines += [f"  {p['name']}: {p['why']}" for p in hl.get("parts", [])]
    lines += ["", "Accounts"]
    for acct in d["accounts"]:
        lines.append(f"  {acct['name']} ({acct['tax_bucket']}): {_money(acct.get('total'))}")
    return lines


def make_pdf(lines: list[str]) -> bytes:
    """Minimal text-only PDF (Helvetica, US Letter, auto-paginated) so no PDF library is needed."""
    per_page, pages = 54, []
    safe = [ln.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in lines]
    for i in range(0, max(len(safe), 1), per_page):
        body = "BT /F1 10 Tf 14 TL 50 750 Td\n" + "".join(f"({ln[:110]}) '\n" for ln in safe[i : i + per_page]) + "ET"
        pages.append(body.encode("latin-1"))
    objs: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for page in pages:
        page_id = len(objs) + 1
        kids.append(f"{page_id} 0 R")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {page_id + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(page) + page + b"\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# ---- share tokens ---------------------------------------------------------------------------------------------------


def _sig(payload: str) -> str:
    key = hashlib.sha256(b"share:" + current_app.config["APP_SECRET"].encode()).digest()
    return base64.urlsafe_b64encode(hmac.new(key, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_share_token(days: int = 7, now: float | None = None) -> dict:
    days = max(1, min(int(days), MAX_SHARE_DAYS))
    expires = int((now if now is not None else time.time()) + days * 86400)
    return {"token": f"{expires}.{_sig(f'report:{expires}')}", "expires": datetime.fromtimestamp(expires, UTC).isoformat()}


def verify_share_token(token: str, now: float | None = None) -> bool:
    exp, _, sig = token.partition(".")
    if not exp.isdigit() or not sig:
        return False
    if not hmac.compare_digest(sig, _sig(f"report:{exp}")):
        return False
    return int(exp) > (now if now is not None else time.time())


# ---- encrypted backup -----------------------------------------------------------------------------------------------


def encrypt_backup(data: dict) -> bytes:
    return encrypt(json.dumps(data)).encode()


def decrypt_backup(blob: bytes) -> dict:
    raw = decrypt(blob.decode())
    if not raw:
        raise ValueError("backup could not be decrypted (wrong APP_SECRET or corrupt file)")
    return json.loads(raw)


def destination() -> str:
    return os.getenv("BACKUP_DEST", "").lower()


def write_backup(blob: bytes, name: str) -> str:
    dest = destination()
    if dest == "local":
        d = Path(os.environ["BACKUP_PATH"])
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(blob)
        _prune(d)
        return str(d / name)
    if dest == "webdav":
        url = os.environ["WEBDAV_URL"].rstrip("/") + "/" + name
        auth = (os.getenv("WEBDAV_USER", ""), os.getenv("WEBDAV_PASSWORD", ""))
        r = requests.put(url, data=blob, auth=auth if auth[0] else None, timeout=60)
        r.raise_for_status()
        return url
    if dest == "s3":
        import boto3

        key = os.getenv("S3_PREFIX", "alphabridge/").lstrip("/") + name
        boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT") or None).put_object(Bucket=os.environ["S3_BUCKET"], Key=key, Body=blob)
        return f"s3://{os.environ['S3_BUCKET']}/{key}"
    raise ValueError("BACKUP_DEST must be local, webdav or s3")


def _prune(d: Path) -> None:
    keep = int(os.getenv("BACKUP_KEEP", "14"))
    files = sorted(d.glob("alphabridge-*.json.enc"))
    for old in files[: max(len(files) - keep, 0)]:
        old.unlink(missing_ok=True)


def run_backup(s) -> str:
    name = f"alphabridge-{datetime.now(UTC):%Y%m%dT%H%M%S%f}Z.json.enc"
    return write_backup(encrypt_backup(export_json(s)), name)
