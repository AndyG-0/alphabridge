"""Interactive Brokers Activity Statement CSV: sectioned rows `Section,Header|Data,...`.
Only the Open Positions section is read. Layout follows IBKR's documented Activity Statement export."""

import csv
import io

from services import validate_parse
from services.ingestion import ParsedRow, ParseResult, bad_number, guess_asset_class, money


def is_ibkr(rows: list[list[str]]) -> bool:
    return any(len(r) > 2 and r[0] == "Open Positions" and r[1] == "Header" for r in rows[:200])


def parse_ibkr(text: str, fx=None) -> ParseResult:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    res = ParseResult(parser="ibkr_activity")
    acct = next((r[3] for r in rows if len(r) > 3 and r[0] == "Account Information" and r[2] == "Account"), "")
    label = f"Interactive Brokers {acct[-4:]}".strip()
    cols: dict[str, int] = {}
    printed: dict[int, float] = {}
    for n, r in enumerate(rows, start=1):
        if len(r) < 3 or r[0] != "Open Positions":
            continue
        if r[1] == "Header":
            cols = {h.strip().lower(): i for i, h in enumerate(r)}
            continue
        if r[1] != "Data" or not cols or r[cols.get("datadiscriminator", 2)] != "Summary":
            continue

        def get(k, r=r):
            i = cols.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""

        sym = get("symbol").upper()
        if any(bad_number(get(k)) for k in ("quantity", "close price", "value")):
            res.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": "Not a number in a position; row skipped"})
            continue
        cur = get("currency").upper() or "USD"
        rate = 1.0
        if cur != "USD":
            from services.ingestion import _default_fx

            rate = (fx or _default_fx)(cur) or 0.0
            if not rate:
                res.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": f"No USD exchange rate for {cur}; row skipped"})
                continue
        shares, px, val, cost = money(get("quantity")), money(get("close price")) * rate, money(get("value")) * rate, money(get("cost basis")) * rate
        if shares < 0 or val < 0:
            res.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": "Short or negative position; row skipped"})
            continue
        mult = money(get("mult")) or 1.0
        if mult != 1.0:  # options/futures: value already includes the multiplier; skip the shares x price check
            px = val / shares if shares else px
        res.rows.append(
            ParsedRow(
                symbol=sym,
                name=sym,
                shares=shares,
                price=px,
                market_value=val,
                cost_basis_total=cost,
                asset_class=guess_asset_class(sym, ""),
                account_name=label,
                needs_mapping=not sym.replace(".", "").isalpha() or len(sym) > 5,
                currency=cur,
                fx_rate=rate,
            )
        )
        printed[len(res.rows) - 1] = px
    if not res.rows:
        res.warnings.append("No Open Positions rows found")
    res.checks = validate_parse.check_rows(res.rows, printed)
    res.confidence = validate_parse.confidence(res.checks)
    return res
