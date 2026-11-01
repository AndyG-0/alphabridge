"""Deterministic cross-checks on OCR/LLM-extracted rows. The model only copies printed numbers; arithmetic is here."""

import re

TOLERANCE = 0.01  # 1%: statements round shares/prices


def _close(a: float, b: float, tol: float = TOLERANCE) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1.0)


def check_rows(rows, printed_prices: dict[int, float], document_total: float = 0.0) -> list[dict]:
    """rows: ParsedRow-like objects. printed_prices: row index -> price as printed (absent when the document had none).
    Returns [{level: ok|warn|fail, message}]."""
    checks: list[dict] = []

    def add(level: str, message: str):
        checks.append({"level": level, "message": message})

    for i, r in enumerate(rows):
        px = printed_prices.get(i)
        if px and r.shares:
            if _close(r.shares * px, r.market_value):
                add("ok", f"{r.symbol}: {r.shares:g} × ${px:,.2f} = ${r.shares * px:,.2f} matches printed value")
            else:
                add("fail", f"{r.symbol}: {r.shares:g} × ${px:,.2f} = ${r.shares * px:,.2f}, but the document shows ${r.market_value:,.2f}")
        elif r.shares:
            add("warn", f"{r.symbol}: no printed price to verify shares × price")
        if r.market_value <= 0:
            add("fail", f"{r.symbol}: value is zero or negative")
        if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", r.symbol) and not r.needs_mapping:
            add("warn", f"{r.symbol}: not a standard ticker")
    total = sum(r.market_value for r in rows)
    if document_total:
        if _close(total, document_total):
            add("ok", f"Holdings sum ${total:,.2f} matches the document total")
        else:
            add("fail", f"Holdings sum ${total:,.2f} differs from the document total ${document_total:,.2f} - a row may be missing")
    else:
        add("warn", "No document total printed to reconcile against")
    return checks


def confidence(checks: list[dict]) -> str:
    levels = {c["level"] for c in checks}
    return "low" if "fail" in levels else "medium" if "warn" in levels else "high"
