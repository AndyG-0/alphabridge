"""SimpleFIN Bridge: exchange a one-time setup token for an access URL (stored encrypted), then pull
account balances. Balances are account-level totals, so each account becomes one holding; negative
balances (cards, loans) are skipped because debts live under Liabilities."""

import base64
import os
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import requests

import db
from models import SimpleFinConfig
from services import ingestion
from services.crypto import decrypt, encrypt
from services.ingestion import ParsedRow, ParseResult, money

TIMEOUT = 20


def _config() -> SimpleFinConfig:
    s = db.session()
    cfg = s.query(SimpleFinConfig).first()
    if cfg is None:
        cfg = SimpleFinConfig()
        s.add(cfg)
        s.flush()
    return cfg


ALLOWED_HOSTS = ("bridge.simplefin.org",)


def _allowed_hosts() -> tuple[str, ...]:
    """Claim URLs come from user input (SSRF), so only known SimpleFIN hosts are contacted. Self-hosted bridges are added with
    SIMPLEFIN_HOSTS=host1,host2."""
    extra = tuple(h.strip().lower() for h in os.getenv("SIMPLEFIN_HOSTS", "").split(",") if h.strip())
    return ALLOWED_HOSTS + extra


def _check_public_https(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in _allowed_hosts() or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Claim URL must be https on a known SimpleFIN host (set SIMPLEFIN_HOSTS for a self-hosted bridge)")
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def claim(setup_token: str) -> str:
    """Setup token = base64(claim URL). POSTing to it returns the access URL (credentials embedded)."""
    try:
        url = base64.b64decode(setup_token.strip(), validate=True).decode()
    except Exception as e:
        raise ValueError("Setup token is not valid base64") from e
    url = _check_public_https(url)
    r = requests.post(url, timeout=TIMEOUT)
    if r.status_code != 200 or not r.text.startswith("https://"):
        raise ValueError(f"SimpleFIN claim failed (HTTP {r.status_code}); setup tokens are single-use")
    return r.text.strip()


def connect(setup_token: str) -> None:
    cfg = _config()
    cfg.access_url_encrypted = encrypt(claim(setup_token))
    cfg.last_status = "connected"
    db.session().commit()


def disconnect() -> None:
    s = db.session()
    s.query(SimpleFinConfig).delete()
    s.commit()


def status() -> dict:
    cfg = db.session().query(SimpleFinConfig).first()
    return {
        "connected": bool(cfg and cfg.access_url_encrypted),
        "last_sync": cfg.last_sync.isoformat() if cfg and cfg.last_sync else None,
        "last_status": cfg.last_status if cfg else "",
    }


def fetch_accounts(access_url: str) -> dict:
    parts = urlsplit(access_url)
    auth = (parts.username or "", parts.password or "")
    host = (parts.hostname or "") + (f":{parts.port}" if parts.port else "")
    base = urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    r = requests.get(f"{base}/accounts", params={"balances-only": 1}, auth=auth, timeout=TIMEOUT)
    if r.status_code in (402, 403):
        raise ValueError("SimpleFIN access was refused; reconnect with a new setup token")
    r.raise_for_status()
    return r.json()


def to_parse_result(payload: dict) -> ParseResult:
    res = ParseResult(parser="simplefin", source="simplefin")
    for msg in payload.get("errors") or []:
        res.warnings.append(f"SimpleFIN: {msg}")
    for a in payload.get("accounts") or []:
        org = (a.get("org") or {}).get("name") or (a.get("org") or {}).get("domain") or "SimpleFIN"
        label = f"{org} {a.get('name', '')}".strip()
        sid = str(a.get("id", ""))
        try:
            bal = float(a.get("balance"))
        except (TypeError, ValueError):
            res.row_errors.append({"line": 0, "symbol": sid[-4:], "level": "error", "error": f"{label}: unreadable balance; skipped"})
            continue
        if a.get("currency", "USD") != "USD":
            res.row_errors.append({"line": 0, "symbol": sid[-4:], "level": "error", "error": f"{label}: {a['currency']} not converted; skipped"})
            continue
        if bal < 0:
            res.row_errors.append(
                {"line": 0, "symbol": sid[-4:], "level": "warn", "error": f"{label}: negative balance skipped (track debts under Liabilities)"}
            )
            continue
        res.rows.append(
            ParsedRow(
                symbol=f"SF-{sid[-6:].upper() or 'ACCT'}",
                name=label,
                shares=bal,
                price=1.0,
                market_value=bal,
                asset_class="MONEY_MARKET",
                account_name=label,
                needs_mapping=False,
            )
        )
    res.warnings.append("SimpleFIN gives account totals, so each account is one cash-class holding; split investment accounts by importing positions instead.")
    return res


def sync() -> dict:
    cfg = _config()
    url = decrypt(cfg.access_url_encrypted)
    if not url:
        raise ValueError("SimpleFIN is not connected")
    try:
        result = to_parse_result(fetch_accounts(url))
    except Exception as e:
        cfg.last_status = f"error: {type(e).__name__}"[:100]
        db.session().commit()
        raise
    out = ingestion.apply_parse(result, "simplefin", None, None) if result.rows else {"rows": 0, "accounts": [], "unchanged": []}
    cfg.last_sync = datetime.now(UTC)
    cfg.last_status = f"ok: {len(result.rows)} accounts"
    db.session().commit()
    return {**out, "row_errors": result.row_errors, "warnings": result.warnings, "money_check": money(sum(r.market_value for r in result.rows))}
