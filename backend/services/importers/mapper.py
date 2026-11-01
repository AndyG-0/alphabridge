"""Generic CSV mapper: the user names which header holds which field; the mapping can be saved as a template."""

import csv
import io
import re

from pydantic import BaseModel, Field, model_validator

from services import validate_parse
from services.ingestion import ParsedRow, ParseResult, bad_number, guess_asset_class, money

FIELDS = ("symbol", "name", "shares", "price", "value", "cost", "account", "currency")


class Mapping(BaseModel):
    columns: dict[str, str]  # field -> header text in the file (case-insensitive)
    skip_rows: int = Field(default=0, ge=0, le=100)  # lines above the header row
    account_name: str = ""  # used when the file has no account column
    asset_class: str = ""  # forced class; blank = guess from symbol/name

    @model_validator(mode="after")
    def _check(self):
        bad = set(self.columns) - set(FIELDS)
        if bad:
            raise ValueError(f"unknown field(s): {', '.join(sorted(bad))}")
        if "value" not in self.columns and not {"shares", "price"} <= self.columns.keys():
            raise ValueError("map a value column, or both shares and price")
        if not {"symbol", "name"} & self.columns.keys():
            raise ValueError("map a symbol or name column")
        return self


def parse_with_mapping(text: str, m: Mapping, fx=None) -> ParseResult:
    from services.ingestion import _default_fx

    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    res = ParseResult(parser="mapped_csv")
    if m.skip_rows >= len(rows):
        res.warnings.append("skip_rows is past the end of the file")
        return res
    header = [h.strip().lower() for h in rows[m.skip_rows]]
    idx: dict[str, int] = {}
    for k, h in m.columns.items():
        if h.strip().lower() not in header:
            res.warnings.append(f"Column '{h}' (for {k}) not found in the header row")
            return res
        idx[k] = header.index(h.strip().lower())
    printed: dict[int, float] = {}
    for n, r in enumerate(rows[m.skip_rows + 1 :], start=m.skip_rows + 2):
        if not any(c.strip() for c in r):
            if res.rows:
                break
            continue

        def get(k, r=r):
            i = idx.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""

        sym, name = get("symbol").rstrip("*").upper(), get("name")
        label = sym or name[:30]
        if not (sym or name) or name.lower() in ("total", "account total"):
            continue
        if bad := [k for k in ("value", "shares", "price", "cost") if bad_number(get(k))]:
            res.row_errors.append({"line": n, "symbol": label, "level": "error", "error": f"Not a number in: {', '.join(bad)}; row skipped"})
            continue
        shares, price, value, cost = money(get("shares")), money(get("price")), money(get("value")), money(get("cost"))
        cur, rate = (get("currency").upper() or "USD"), 1.0
        if cur != "USD":
            rate = (fx or _default_fx)(cur) or 0.0
            if not rate:
                res.row_errors.append({"line": n, "symbol": label, "level": "error", "error": f"No USD exchange rate for {cur}; row skipped"})
                continue
            price, value, cost = price * rate, value * rate, cost * rate
        if shares < 0 or value < 0:
            res.row_errors.append({"line": n, "symbol": label, "level": "error", "error": "Negative shares or value; row skipped"})
            continue
        if not value and shares and price:
            value = shares * price
        if not price and shares:
            price = value / shares
        needs_mapping = not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", sym)
        if needs_mapping:
            sym = re.sub(r"[^A-Z0-9]+", "-", (name or sym).upper()).strip("-")[:38]
        ac = m.asset_class or guess_asset_class(sym, name)
        res.rows.append(
            ParsedRow(
                symbol=sym,
                name=name or sym,
                shares=shares,
                price=price,
                market_value=value,
                cost_basis_total=cost,
                asset_class=ac,
                account_name=get("account") or m.account_name or None,
                needs_mapping=needs_mapping and ac != "MONEY_MARKET",
                currency=cur,
                fx_rate=rate,
            )
        )
        if get("price") and shares:
            printed[len(res.rows) - 1] = price
    res.checks = validate_parse.check_rows(res.rows, printed)
    res.confidence = validate_parse.confidence(res.checks)
    return res
