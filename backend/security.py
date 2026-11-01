"""App-level hardening: response headers, auth-failure rate limit, log redaction, upload validation."""

import logging
import re
import threading
import time
from pathlib import PurePosixPath, PureWindowsPath

from flask import Flask, jsonify, request

ALLOWED_UPLOAD_EXTS = (".csv", ".txt", ".ofx", ".qfx", ".qif", ".pdf", ".png", ".jpg", ".jpeg")
MAGIC: dict[str, tuple[bytes, ...]] = {".pdf": (b"%PDF-",), ".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",)}
MAX_PDF_PAGES = 60
MAX_IMAGE_PIXELS = 50_000_000  # decompression-bomb guard for PIL

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    # The API only returns JSON: nothing in a response may load or run anything.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


class AuthRateLimiter:
    """Sliding-window limit on failed auth attempts per client address (in memory; one worker)."""

    def __init__(self, max_failures: int = 10, window_s: float = 60.0):
        self.max_failures, self.window_s = max_failures, window_s
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.window_s]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key, time.monotonic())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._recent(key, now)
            self._fails.setdefault(key, []).append(now)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()


_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b((?:api[_-]?key|token|secret|password|passwd|webhook)\w*\s*[=:]\s*)[^\s,;&\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(https://(?:discord(?:app)?\.com)/api/webhooks/\d+/)[\w-]+"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "sk-[REDACTED]"),
    (re.compile(r"\b\d{6,}(\d{4})\b"), r"******\1"),  # account numbers: keep the last 4
]


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def safe_filename(name: str | None) -> str:
    """Display/log name only (uploads are never written to disk under this name): strip any directory part."""
    base = PurePosixPath(PureWindowsPath(name or "").name).name
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .")
    return (base or "upload")[:150]


def validate_upload(filename: str, data: bytes) -> str | None:
    """Return an error message, or None when the file is acceptable."""
    low = (filename or "").lower()
    ext = next((e for e in ALLOWED_UPLOAD_EXTS if low.endswith(e)), None)
    if ext is None:
        return f"Unsupported file type; allowed: {', '.join(ALLOWED_UPLOAD_EXTS)}"
    if not data:
        return "File is empty"
    magic = MAGIC.get(ext)
    if magic and not data.startswith(magic):
        return f"File content does not look like a {ext[1:].upper()}"
    return None


def init_security(app: Flask) -> AuthRateLimiter:
    limiter = AuthRateLimiter(app.config["AUTH_MAX_FAILURES"], app.config["AUTH_WINDOW_SECONDS"])
    for name in ("alphabridge", "werkzeug"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in lg.filters):
            lg.addFilter(RedactingFilter())
    if app.config["TRUST_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)  # type: ignore[method-assign]

    @app.after_request
    def _headers(resp):
        for k, v in HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp

    @app.errorhandler(429)
    def _too_many(_e):
        return jsonify(error="too many failed attempts; try again later"), 429

    return limiter


def client_key() -> str:
    return request.remote_addr or "unknown"
