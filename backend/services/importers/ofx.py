"""OFX / QFX (v1 SGML and v2 XML) and QIF statement parsing, stdlib only.

OFX v1 leaves leaf tags unclosed (`<UNITS>10`), so values are read with a tolerant regex instead of an
XML parser. Positions come from INVPOSLIST (joined to SECLIST for ticker/name); bank and cash balances
come from LEDGERBAL / INVBAL. Every row is checked with `validate_parse.check_rows`.
"""

import bisect
import re
from datetime import datetime

from services import validate_parse
from services.ingestion import ParsedRow, ParseResult, bad_number, guess_asset_class, money

_POS_TAGS = ("POSSTOCK", "POSMF", "POSDEBT", "POSOPT", "POSOTHER")
_SEC_TAGS = ("STOCKINFO", "MFINFO", "DEBTINFO", "OPTINFO", "OTHERINFO")
_STMT_TAGS = ("INVSTMTRS", "STMTRS", "CCSTMTRS")


def _blocks(text: str, tags: tuple[str, ...]) -> list[tuple[str, str]]:
    """(tag, body) for each <TAG>...</TAG> in document order. Linear time: one pass indexes the tags, then bodies are
    sliced between each open tag and the next matching close (a regex with a lazy group is polynomial on hostile input)."""
    alt = "|".join(tags)
    opens = [(m.start(), m.end(), m.group(1).upper()) for m in re.finditer(rf"<({alt})>", text, re.I)]
    closes: dict[str, list[int]] = {}
    for m in re.finditer(rf"</({alt})>", text, re.I):
        closes.setdefault(m.group(1).upper(), []).append(m.start())
    out, cursor = [], 0
    for start, end, tag in opens:
        if start < cursor:
            continue  # nested/overlapping open inside a block already taken
        i = bisect.bisect_left(closes.get(tag, []), end)
        if i < len(closes.get(tag, [])):
            out.append((tag, text[end : closes[tag][i]]))
            cursor = closes[tag][i]
    return out


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}>\s*([^<\r\n]*)", block, re.I)
    return m.group(1).strip() if m else ""


def is_ofx(text: str) -> bool:
    head = text[:2000].upper()
    return "<OFX>" in text.upper() or "OFXHEADER" in head


def is_qif(text: str) -> bool:
    return text.lstrip().upper().startswith("!TYPE:")


def _sec_map(text: str) -> dict[str, tuple[str, str]]:
    """UNIQUEID (cusip) -> (ticker, name)."""
    out: dict[str, tuple[str, str]] = {}
    for _, body in _blocks(text, _SEC_TAGS):
        uid = _tag(body, "UNIQUEID")
        if uid:
            out[uid] = (_tag(body, "TICKER").upper(), _tag(body, "SECNAME"))
    return out


def parse_ofx(text: str) -> ParseResult:
    res = ParseResult(parser="ofx")
    secs = _sec_map(text)
    printed: dict[int, float] = {}
    stmts = _blocks(text, _STMT_TAGS) or [("", text)]
    for kind, body in stmts:
        acct_id = _tag(body, "ACCTID")
        last4 = acct_id[-4:] if acct_id else "0000"
        label = f"{_tag(text, 'ORG') or 'OFX'} {last4}".strip()
        for pos_kind, pos in _blocks(body, _POS_TAGS):
            uid = _tag(pos, "UNIQUEID")
            ticker, name = secs.get(uid, ("", ""))
            symbol = ticker or uid.upper()
            units, px, val = _tag(pos, "UNITS"), _tag(pos, "UNITPRICE"), _tag(pos, "MKTVAL")
            if any(bad_number(v) for v in (units, px, val)):
                res.row_errors.append({"line": 0, "symbol": symbol, "level": "error", "error": "Not a number in a position; row skipped"})
                continue
            shares, price, value = money(units), money(px), money(val)
            if pos_kind.upper() == "POSOPT":
                value = value or shares * price * 100
            if shares < 0 or value < 0:
                res.row_errors.append({"line": 0, "symbol": symbol, "level": "error", "error": "Short or negative position; row skipped"})
                continue
            needs_mapping = not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", symbol)
            res.rows.append(
                ParsedRow(
                    symbol=symbol,
                    name=name or symbol,
                    shares=shares,
                    price=price,
                    market_value=value,
                    asset_class=guess_asset_class(symbol, name),
                    account_name=label,
                    needs_mapping=needs_mapping,
                )
            )
            if price:
                printed[len(res.rows) - 1] = price
        cash = _tag(body, "AVAILCASH") if kind.upper() == "INVSTMTRS" else _tag(body, "BALAMT")
        if cash and not bad_number(cash) and money(cash) > 0:
            bal = money(cash)
            res.rows.append(
                ParsedRow(symbol=f"CASH-{last4}", name="Cash", shares=bal, price=1.0, market_value=bal, asset_class="MONEY_MARKET", account_name=label)
            )
    if not res.rows:
        res.warnings.append("No positions or balances found in OFX file")
    res.checks = validate_parse.check_rows(res.rows, printed)
    res.confidence = validate_parse.confidence(res.checks)
    return res


def parse_qif(text: str, account_name: str = "QIF account") -> ParseResult:
    """QIF has no balances, only transactions: the sum of amounts is reported as the cash balance,
    with a warning that it is a net flow, not a statement balance."""
    res = ParseResult(parser="qif")
    total, n, last = 0.0, 0, None
    for line in text.splitlines():
        if line.startswith("T") or line.startswith("U"):
            if bad_number(line[1:]):
                res.row_errors.append({"line": 0, "symbol": "", "level": "error", "error": f"Unreadable amount '{line[1:]}'"})
                continue
            total += money(line[1:])
            n += 1
        elif line.startswith("D"):
            for fmt in ("%m/%d/%Y", "%m/%d'%y", "%m/%d/%y", "%Y-%m-%d"):
                try:
                    last = max(last, datetime.strptime(line[1:].strip(), fmt)) if last else datetime.strptime(line[1:].strip(), fmt)
                    break
                except ValueError:
                    continue
    if n == 0:
        res.warnings.append("No transactions found in QIF file")
        return res
    res.warnings.append(f"QIF has no balances: used the net of {n} transactions as cash. Check it against your statement.")
    if last:
        res.warnings.append(f"Latest transaction {last:%Y-%m-%d}")
    res.rows.append(
        ParsedRow(symbol="QIF-BALANCE", name="QIF net cash", shares=total, price=1.0, market_value=total, asset_class="MONEY_MARKET", account_name=account_name)
    )
    res.confidence = "low"
    return res
