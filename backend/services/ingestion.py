"""Fidelity / NetBenefits / Nationwide statement parsing (deterministic first, LLM fallback)."""

import contextlib
import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from pydantic import BaseModel

import db
from models import Account, Holding, IngestionLog, Liability, NetWorthSnapshot, Pension, TaxLot
from services import doc_reader, institutions, validate_parse

MMF_SYMBOLS = {"SPAXX", "FDRXX", "FZFXX", "FZDXX", "SPRXX", "VMFXX", "FCASH", "CORE", "FDLXX", "SWVXX", "CASH"}

ALIASES = {
    "account": ["account name", "account", "plan name"],
    "symbol": ["symbol", "ticker", "cusip", "investment symbol", "instrument"],
    "name": ["description", "fund name", "investment", "investment option", "security name", "fund", "name", "security description", "investment name"],
    "shares": ["quantity", "shares", "units", "shares/units", "number of units", "units/shares", "qty #", "qty"],
    "price": ["last price", "price", "unit value", "share price", "nav", "unit price", "last price $", "current price"],
    "value": [
        "current value",
        "value",
        "market value",
        "balance",
        "ending balance",
        "total value",
        "current balance",
        "mkt val (market value)",
        "value $",
        "equity",
    ],
    "cost": ["cost basis total", "cost basis", "total cost basis", "cost"],
    "currency": ["currency", "currency code"],
}


@dataclass
class ParsedRow:
    symbol: str
    name: str
    shares: float
    price: float
    market_value: float
    cost_basis_total: float = 0.0
    asset_class: str = "US_EQUITY"
    account_name: str | None = None
    needs_mapping: bool = False
    currency: str = "USD"  # statement currency; price/value/cost above are already converted to USD
    fx_rate: float = 1.0


@dataclass
class ParsedPension:
    holder_name: str  # as printed on the statement
    plan_name: str
    as_of: date | None
    beginning: float
    interest_credits: float
    pay_credits: float
    excess_credits: float
    ending: float
    pay_credit_pct: float  # decimal
    months: int  # length of the statement period

    @property
    def interest_rate(self) -> float:
        """Annualized from the statement's own interest credits (the printed rate's period is unclear)."""
        return self.interest_credits / self.beginning * 12 / self.months if self.beginning > 0 and self.months > 0 else 0.0

    @property
    def covered_pay(self) -> float:
        """Annualized pay the credits were earned on: YTD pay credits / credit rate."""
        return self.pay_credits / self.pay_credit_pct * 12 / self.months if self.pay_credit_pct > 0 and self.months > 0 else 0.0


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    pension: ParsedPension | None = None
    parser: str = ""
    warnings: list[str] = field(default_factory=list)
    source: str = "csv"  # text | ocr | vision | csv
    checks: list[dict] = field(default_factory=list)
    confidence: str = "high"
    row_errors: list[dict] = field(default_factory=list)  # {"line", "symbol", "level": error|warn, "error"}; errors were skipped

    @property
    def needs_review(self) -> bool:
        """AI/OCR-derived parses are shown for confirmation before anything is written."""
        return self.parser == "pdf_llm"


def money(v) -> float:
    if v is None:
        return 0.0
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if s in ("", "--", "n/a", "N/A"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except ValueError:
        return 0.0
    return -x if neg else x


def bad_number(v) -> bool:
    """A non-empty cell that is not a number (money() would silently read it as 0)."""
    s = str(v or "").strip().replace("$", "").replace(",", "").replace("%", "").strip("()")
    if s in ("", "--", "n/a", "N/A"):
        return False
    try:
        float(s)
    except ValueError:
        return True
    return False


def guess_asset_class(symbol: str, name: str) -> str:
    sym = symbol.upper().rstrip("*")
    n = name.lower()
    if sym in MMF_SYMBOLS or "money market" in n or "government cash" in n or "stable value" in n:
        return "MONEY_MARKET"
    if sym in {"QQQ", "SPY", "SPYM", "VOO", "VTI", "IVV"}:
        return "US_EQUITY"
    if "adr" in n.split() or "sponsored" in n:
        return "INDIVIDUAL_STOCK"
    if any(k in n for k in ("bond", "treasury", "income", "fixed", "aggregate", "tips")):
        return "BOND"
    if any(k in n for k in ("international", "intl", "foreign", "emerging", "ex-us", "ex us", "global")):
        return "INTL_EQUITY"
    if any(k in n for k in ("sector", "technology", "health care", "healthcare", "energy", "semiconductor", "financial select")):
        return "SECTOR_ETF"
    if any(k in n for k in (" etf", "index", "fund", "trust", "target", "500", "total market", "pool", "portfolio")):
        return "US_EQUITY"
    return "INDIVIDUAL_STOCK"


def _map_headers(headers: list[str]) -> dict[str, int]:
    norm = [h.strip().lower() for h in headers]
    out: dict[str, int] = {}
    for field_, names in ALIASES.items():
        for alias in names:
            if alias in norm:
                out[field_] = norm.index(alias)
                break
    return out


def _find_header_row(rows: list[list[str]]) -> int | None:
    for i, r in enumerate(rows[:30]):
        m = _map_headers(r)
        if "value" in m and ("name" in m or "symbol" in m):
            return i
    return None


def detect_layout(rows: list[list[str]], hi: int) -> str:
    """Name the export a positions CSV came from, by its header/preamble. Layouts are matched from
    published column names (not verified against live exports); unknown files keep the generic parser."""
    head = {h.strip().lower() for h in rows[hi]}
    pre = " ".join(" ".join(r) for r in rows[:hi]).lower()
    if "positions for account" in pre or "gain/loss $" in head or "% of account" in head:
        return "schwab_positions"
    if "price paid $" in head or "qty #" in head:
        return "etrade_positions"
    if "investment name" in head and "share price" in head:
        return "vanguard_positions"
    if "instrument" in head and "equity" in head:
        return "robinhood_positions"
    if "empower" in pre or ("ticker" in head and "empower" in " ".join(h for r in rows[:3] for h in r).lower()):
        return "empower_positions"
    return ""


def _preamble_account(rows: list[list[str]], hi: int) -> str | None:
    """Schwab-style title line: 'Positions for account Individual ...1234 as of ...'."""
    for r in rows[:hi]:
        m = re.search(r"positions for account\s+(.+?)(?:\s+as of\b|$)", " ".join(r), re.I)
        if m:
            return m.group(1).strip().strip('"')
    return None


def _is_bank_activity(header: list[str], cols: dict[str, int]) -> bool:
    """Checking/savings activity export (Date/Description/Amount/Balance): transactions, not positions."""
    norm = {h.strip().lower() for h in header}
    return "symbol" not in cols and "shares" not in cols and "amount" in norm and bool(norm & {"posting date", "date"})


def _parse_bank_activity(rows: list[list[str]], hi: int, res: ParseResult) -> ParseResult:
    """Collapse an activity CSV to one cash holding at the most recent running balance."""
    header = [h.strip().lower() for h in rows[hi]]
    date_i = header.index("posting date") if "posting date" in header else header.index("date")
    bal_i = header.index("balance") if "balance" in header else None
    res.parser = "bank_activity"
    if bal_i is None:
        res.warnings.append("Bank activity file has no Balance column")
        return res
    best = None  # (date, balance); on date ties the first (newest-first export) row wins
    for r in rows[hi + 1 :]:
        if len(r) <= max(date_i, bal_i) or not r[bal_i].strip():
            continue
        try:
            d = datetime.strptime(r[date_i].strip(), "%m/%d/%Y")
        except ValueError:
            continue
        if best is None or d > best[0]:
            best = (d, money(r[bal_i]))
    if best is None:
        res.warnings.append("No dated rows with a balance found")
        return res
    bal = best[1]
    res.warnings.append(f"Used balance as of {best[0]:%Y-%m-%d}")
    res.rows.append(
        ParsedRow(
            symbol="BANK-BALANCE", name="Bank balance", shares=bal, price=1.0, market_value=bal, asset_class="MONEY_MARKET", account_name="Chase Checking"
        )
    )
    return res


LOT_ALIASES = {
    "account": ["account name", "account", "account number"],
    "symbol": ["symbol", "ticker"],
    "acquired": ["date acquired", "acquired", "acquisition date", "purchase date", "open date", "trade date"],
    "shares": ["quantity", "shares", "units"],
    "cost": ["cost basis total", "total cost basis", "cost basis", "cost"],
    "value": ["current value", "market value", "value"],
}


@dataclass
class LotRow:
    symbol: str
    acquired: date
    shares: float
    cost_basis_total: float
    current_value: float = 0.0
    account_name: str | None = None


@dataclass
class LotParse:
    rows: list[LotRow] = field(default_factory=list)
    row_errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _lot_cols(headers: list[str]) -> dict[str, int]:
    norm = [h.strip().lower() for h in headers]
    return {k: norm.index(a) for k, names in LOT_ALIASES.items() for a in names if a in norm}


def _lot_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for i, r in enumerate(rows[:30]):
        c = _lot_cols(r)
        if {"symbol", "acquired", "shares", "cost"} <= c.keys():
            return i, c
    return None


def is_lot_export(text: str) -> bool:
    """True for a per-lot cost-basis file (has a Date Acquired column), which must not be imported as positions."""
    return _lot_header(list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))) is not None


def _parse_date(v: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%b-%d-%Y", "%d-%b-%Y"):
        with contextlib.suppress(ValueError):
            return datetime.strptime(v.strip(), fmt).date()
    return None


def parse_lots(text: str) -> LotParse:
    """Fidelity-style lot export: one row per purchase lot. Bad rows are reported and skipped, never guessed."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    out = LotParse()
    found = _lot_header(rows)
    if found is None:
        out.warnings.append("No lot header row (needs Symbol, Date Acquired, Quantity and Cost Basis columns)")
        return out
    hi, cols = found

    def get(r, k):
        i = cols.get(k)
        return r[i].strip() if i is not None and i < len(r) else ""

    for n, r in enumerate(rows[hi + 1 :], start=hi + 2):
        if not any(c.strip() for c in r):
            continue
        sym = get(r, "symbol").rstrip("*").upper()
        if not sym or not get(r, "acquired"):
            if len(r) > 2:  # footer disclaimers have a single long cell
                out.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": "missing symbol or acquisition date"})
            continue
        d = _parse_date(get(r, "acquired"))
        if d is None:
            out.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": f"unreadable date '{get(r, 'acquired')}'"})
            continue
        if d > datetime.now(UTC).date():
            out.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": "acquisition date is in the future"})
            continue
        if bad_number(get(r, "shares")) or bad_number(get(r, "cost")):
            out.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": "unreadable shares or cost basis"})
            continue
        sh, cost = money(get(r, "shares")), money(get(r, "cost"))
        if sh <= 0 or cost < 0:
            out.row_errors.append({"line": n, "symbol": sym, "level": "error", "error": "shares must be positive and cost non-negative"})
            continue
        out.rows.append(LotRow(sym, d, sh, cost, money(get(r, "value")), get(r, "account") or None))
    return out


def apply_lots(s, parsed: LotParse, account_id: int) -> dict:
    """Replace the account's lots for every symbol in the file (re-importing the same file changes nothing)."""
    syms = {r.symbol for r in parsed.rows}
    s.query(TaxLot).filter(TaxLot.account_id == account_id, TaxLot.symbol.in_(syms)).delete(synchronize_session=False)
    for r in parsed.rows:
        s.add(
            TaxLot(
                account_id=account_id, symbol=r.symbol, acquired=r.acquired, shares=r.shares, cost_basis_total=r.cost_basis_total, current_value=r.current_value
            )
        )
    s.commit()
    return {"lots": len(parsed.rows), "symbols": sorted(syms), "row_errors": parsed.row_errors}


def _default_fx(currency: str) -> float | None:
    from services import market_data

    return market_data.fx_rate(currency)


def parse_csv(text: str, fx=None) -> ParseResult:
    """`fx(currency) -> USD per unit` converts non-USD statements; defaults to the cached market-data lookup."""
    text = text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    res = ParseResult(parser="csv")
    hi = _find_header_row(rows)
    if hi is None:
        res.warnings.append("No recognizable header row")
        return res
    cols = _map_headers(rows[hi])
    if _is_bank_activity(rows[hi], cols):
        return _parse_bank_activity(rows, hi, res)
    res.parser = "fidelity_positions" if "symbol" in cols and "account" in cols else "plan_balance"
    layout = detect_layout(rows, hi)
    pre_account = _preamble_account(rows, hi) if layout == "schwab_positions" else None
    if layout and "account" not in cols:
        res.parser = layout

    def get(r, key):
        i = cols.get(key)
        return r[i].strip() if i is not None and i < len(r) else ""

    for line_no, r in enumerate(rows[hi + 1 :], start=hi + 2):
        if not r or all(not c.strip() for c in r):
            if res.rows:
                break  # blank line ends the table; the rest is disclaimers
            continue
        name, symbol = get(r, "name"), get(r, "symbol")
        value = money(get(r, "value"))
        if not (name or symbol) or (value == 0 and not get(r, "shares") and not bad_number(get(r, "value"))):
            continue
        if symbol.lower().startswith("pending") or name.lower() in ("total", "account total") or symbol.lower() in ("account total", "total"):
            continue
        if symbol.lower().startswith("cash & cash") or name.lower().startswith("cash & cash"):
            symbol, name = "CASH", "Cash & cash investments"
        label = symbol.rstrip("*").upper() or name[:30]
        if bad := [k for k in ("value", "shares", "price", "cost") if bad_number(get(r, k))]:
            res.row_errors.append({"line": line_no, "symbol": label, "level": "error", "error": f"Not a number in: {', '.join(bad)}; row skipped"})
            continue
        sym = symbol.rstrip("*").upper()
        shares, price = money(get(r, "shares")), money(get(r, "price"))
        if shares < 0 or value < 0:
            res.row_errors.append({"line": line_no, "symbol": label, "level": "error", "error": "Negative shares or value; row skipped"})
            continue
        cost = money(get(r, "cost"))
        cur, rate = (get(r, "currency").upper() or "USD"), 1.0
        if cur != "USD":
            found = (fx or _default_fx)(cur)
            if not found:
                res.row_errors.append({"line": line_no, "symbol": label, "level": "error", "error": f"No USD exchange rate for {cur}; row skipped"})
                continue
            rate = found
            price, value, cost = price * rate, value * rate, cost * rate
            res.warnings.append(f"{label}: converted from {cur} at {rate:.4f} USD per {cur}")
        if not value and shares and price:
            value = shares * price
        if not price and shares:
            price = value / shares
        if shares and price and value and abs(shares * price - value) / value > 0.05:
            res.row_errors.append({"line": line_no, "symbol": label, "level": "warn", "error": "Shares x price differs from value by more than 5%"})
        needs_mapping = not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", sym) or len(sym) > 5
        if needs_mapping:
            sym = re.sub(r"[^A-Z0-9]+", "-", (name or symbol).upper()).strip("-")[:38]
        res.rows.append(
            ParsedRow(
                symbol=sym,
                name=name or sym,
                shares=shares,
                price=price,
                market_value=value,
                cost_basis_total=cost,
                asset_class=guess_asset_class(sym, name),
                account_name=get(r, "account") or pre_account,
                needs_mapping=needs_mapping and guess_asset_class(sym, name) != "MONEY_MARKET",
                currency=cur,
                fx_rate=rate,
            )
        )
    if layout and res.rows:
        printed = {i: r.price for i, r in enumerate(res.rows) if r.price and r.shares}
        res.checks = validate_parse.check_rows(res.rows, printed)
        res.confidence = validate_parse.confidence(res.checks)
    return res


class _PdfRow(BaseModel):
    symbol: str = ""
    fund_name: str
    shares: float = 0
    price: float = 0  # per-share price exactly as printed; 0 when the document shows none
    market_value: float


class _PdfRows(BaseModel):
    account_name: str = ""  # e.g. "Computershare - Prudential Financial (PRU)"; institution + what the account is
    as_of: str = ""
    document_total: float = 0  # total balance exactly as printed; 0 when none
    holdings: list[_PdfRow]


_EXTRACT_SYSTEM = (
    "Extract every investment holding from this financial document (brokerage or retirement statement, "
    "transfer-agent balance letter, plan summary). Copy numbers exactly as printed; never compute or estimate "
    "values. Omit totals rows but report the printed overall total as document_total. For a single-stock "
    "holding use the stock's ticker as symbol. Set account_name to the institution plus the account or issuer. "
    "If the document shows only one account balance and no holdings, return a single row for that balance; "
    "never turn rate tables, credit percentages or contribution schedules into holdings."
)

_APEX_ROW = re.compile(r"^(?P<name>.+?)\s+(?P<sym>[A-Z]{1,5})\s+[A-Z]\s+(?P<qty>[\d,]+(?:\.\d+)?)\s+\$?(?P<px>[\d,]+\.\d+)\s+\$?(?P<val>[\d,]+\.\d+)")
_ALLY_ACCT = "Ally Invest Brokerage"


def parse_ally_invest_text(text: str) -> ParseResult:
    """Ally Invest statements (cleared by Apex): equity rows `NAME SYM C qty price value ...`
    and the FDIC sweep as `NAME SYMBOL C balance $1.00 balance`."""
    res = ParseResult(parser="ally_invest_pdf")
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("MONEY MARKET FUNDS"):
            section = "mm"
        elif line.startswith("EQUITIES"):
            section = "eq"
        elif line.startswith("Total Equities") or line.startswith("TOTAL PRICED"):
            section = None
        m = _APEX_ROW.match(line) if section else None
        if not m:
            continue
        qty, px, val = money(m["qty"]), money(m["px"]), money(m["val"])
        if section == "mm":
            res.rows.append(
                ParsedRow(
                    symbol="ALLY-SWEEP", name=m["name"].title(), shares=qty, price=px, market_value=val, asset_class="MONEY_MARKET", account_name=_ALLY_ACCT
                )
            )
        else:
            sym = m["sym"]
            res.rows.append(
                ParsedRow(
                    symbol=sym,
                    name=m["name"].title(),
                    shares=qty,
                    price=px,
                    market_value=val,
                    asset_class=guess_asset_class(sym, m["name"]),
                    account_name=_ALLY_ACCT,
                )
            )
    return res


def parse_ally_bank_text(text: str) -> ParseResult:
    res = ParseResult(parser="ally_bank_pdf")
    pat = re.compile(r"^(?P<name>.+?(?:Savings|Checking|Money Market)[^\n$]*?)\s+x+(?P<last>\d{4})\s+\$[\d,]+\.\d{2}\s+\$(?P<end>[\d,]+\.\d{2})\s*$", re.M)
    for m in pat.finditer(text):
        res.rows.append(
            ParsedRow(
                symbol=f"ALLY-{m['last']}",
                name=m["name"].strip(),
                shares=money(m["end"]),
                price=1.0,
                market_value=money(m["end"]),
                asset_class="MONEY_MARKET",
                account_name="Ally Bank Savings",
            )
        )
    return res


_MONEY = r"\$([\d,]+\.\d{2})"


def parse_cash_balance_text(text: str) -> ParseResult:
    """Nationwide / Fidelity cash-balance plan 'Account Balance' statement: one notional balance, no holdings."""
    res = ParseResult(parser="cash_balance_pdf")

    def money_after(label: str) -> float | None:
        m = re.search(label + r"\s+" + _MONEY, text)
        return money(m[1]) if m else None

    ending, beginning = money_after("Ending Balance"), money_after("Beginning Balance")
    if ending is None or beginning is None:
        return res
    interest = money_after(r"Interest Credits") or 0.0
    pay = money_after(r"(?<!Excess )Pay Credits") or 0.0
    excess = money_after(r"Excess Pay Credits") or 0.0
    holder = re.search(r"^([A-Z][A-Z .'-]+?)\s+Data as of ", text, re.M)
    as_of_m = re.search(r"Data as of ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    as_of = None
    if as_of_m:
        with contextlib.suppress(ValueError):
            as_of = datetime.strptime(as_of_m[1], "%B %d, %Y").date()
    per = re.search(r"(\d{1,2})/(\d{2})\s*-\s*(\d{1,2})/(\d{2})", text)
    months = (int(per[4]) - int(per[2])) * 12 + int(per[3]) - int(per[1]) + 1 if per else 12
    pct = re.search(r"(?<!Excess )Pay Credits-Cash Balance - CB\s+([\d.]+)%", text)
    res.pension = ParsedPension(
        holder_name=holder[1].strip().title() if holder else "",
        plan_name="Nationwide Cash Balance Pension",
        as_of=as_of,
        beginning=beginning,
        interest_credits=interest,
        pay_credits=pay,
        excess_credits=excess,
        ending=ending,
        pay_credit_pct=float(pct[1]) / 100 if pct else 0.0,
        months=max(months, 1),
    )
    total = interest + pay + excess
    if abs(beginning + total - ending) <= 0.02:
        res.checks.append({"level": "ok", "message": f"${beginning:,.2f} + ${total:,.2f} credits = ${ending:,.2f} matches the ending balance"})
    else:
        res.checks.append(
            {"level": "fail", "message": f"${beginning:,.2f} + ${total:,.2f} credits = ${beginning + total:,.2f}, but the statement shows ${ending:,.2f}"}
        )
    printed = re.search(r"Beginning Balance\s+" + _MONEY + r"\s*\n\s*" + _MONEY, text)
    if printed and abs(money(printed[2]) - total) > 0.02:
        res.checks.append({"level": "fail", "message": f"Credits sum to ${total:,.2f} but the statement's year-to-date total is ${money(printed[2]):,.2f}"})
    if not pct:
        res.checks.append({"level": "warn", "message": "No pay-credit percentage found; future pay credits will not be projected"})
    res.confidence = validate_parse.confidence(res.checks)
    if as_of:
        res.warnings.append(f"Statement as of {as_of.isoformat()}")
    return res


def _parse_known_pdf(text: str) -> ParseResult | None:
    """Deterministic parsers for known statement layouts; None -> fall back to the LLM."""
    if "Cash Balance" in text and "Ending Balance" in text and "Pay Credits" in text:
        r = parse_cash_balance_text(text)
        return r if r.pension else None
    if "Apex Clearing" in text or "APEX CLEARING" in text:
        r = parse_ally_invest_text(text)
    elif "Ally Bank" in text and "Ending Balance" in text:
        r = parse_ally_bank_text(text)
    else:
        return None
    return r if r.rows else None


def parse_pdf(data: bytes, llm_structured=None) -> ParseResult:
    return parse_content(doc_reader.read_pdf(data), llm_structured)


def parse_image(data: bytes, llm_structured=None) -> ParseResult:
    return parse_content(doc_reader.read_image(data), llm_structured)


def parse_content(doc: doc_reader.DocContent, llm_structured=None) -> ParseResult:
    """Known deterministic layouts first, then generic LLM extraction, then arithmetic checks."""
    known = _parse_known_pdf(doc.text) if doc.text else None
    if known:
        known.source = doc.source
        return known

    res = ParseResult(parser="pdf_llm", source=doc.source, warnings=list(doc.warnings))
    if not doc.readable:
        res.warnings.append("No extractable text or image content in the file")
        return res
    if llm_structured is None:
        from services.llm_router import LLMNotConfigured, complete_structured

        def llm_structured(sys, usr):
            try:
                return complete_structured("fast", sys, usr, _PdfRows, images=doc.images or None)
            except LLMNotConfigured as e:
                if doc.images:
                    raise LLMNotConfigured(f"{e} Scanned documents need an LLM key (vision) or Tesseract installed for OCR.") from e
                raise

    raw = doc.text[:30000] or "The document is in the attached image(s)."
    out = llm_structured(_EXTRACT_SYSTEM, raw)
    prices: dict[int, float] = {}
    for h in out.holdings:
        sym = h.symbol.strip().upper() or re.sub(r"[^A-Z0-9]+", "-", h.fund_name.upper()).strip("-")[:38]
        needs = not re.fullmatch(r"[A-Z]{1,5}", sym)
        if h.price:
            prices[len(res.rows)] = h.price
        res.rows.append(
            ParsedRow(
                symbol=sym,
                name=h.fund_name,
                shares=h.shares,
                price=h.price or ((h.market_value / h.shares) if h.shares else 0),
                market_value=h.market_value,
                asset_class=guess_asset_class(sym, h.fund_name),
                needs_mapping=needs,
                account_name=out.account_name.strip()[:80] or None,
            )
        )
    if out.as_of:
        res.warnings.append(f"Document as of {out.as_of}")
    res.checks = validate_parse.check_rows(res.rows, prices, out.document_total)
    res.confidence = validate_parse.confidence(res.checks)
    return res


def _default_account_attrs(name: str) -> dict:
    n = name.lower()
    attrs = _institution_attrs(n)
    if re.search(r"spouse|wife|husband|partner", n):
        attrs["owner"] = "SPOUSE"
    elif "joint" in n:
        attrs["owner"] = "JOINT"
    return attrs


def _institution_attrs(n: str) -> dict:
    return institutions.attrs_for_name(n)


def find_duplicate(result: ParseResult, exclude_account_id: int | None = None) -> Account | None:
    """An existing account that already holds essentially this data: >=80% of parsed symbols present
    and total value within 5% (statements from nearby dates differ slightly)."""
    syms = {r.symbol for r in result.rows}
    total = sum(r.market_value for r in result.rows)
    if not syms or total <= 0:
        return None
    s = db.session()
    for a in s.query(Account).all():
        if a.id == exclude_account_id or not a.holdings:
            continue
        have = {h.symbol for h in a.holdings}
        a_total = sum(h.market_value for h in a.holdings)
        if len(syms & have) / len(syms) >= 0.8 and a_total > 0 and abs(a_total - total) / max(a_total, total) <= 0.05:
            return a
    return None


DIFF_SHARES_TOL = 0.01
DIFF_VALUE_TOL = 0.50


def diff_against_account(result: ParseResult, account: Account) -> dict:
    """Per-symbol comparison of an import against an existing account, keyed by symbol like `apply_parse`.
    `missing` rows are what a Replace would delete."""
    new: dict[str, dict] = {}
    for r in result.rows:
        d = new.setdefault(r.symbol, {"name": r.name, "shares": 0.0, "market_value": 0.0})
        d["shares"] += r.shares
        d["market_value"] += r.market_value
    old: dict[str, dict] = {}
    for h in account.holdings:
        d = old.setdefault(h.symbol, {"name": h.name, "shares": 0.0, "market_value": 0.0})
        d["shares"] += h.shares
        d["market_value"] += h.market_value

    rows, counts = [], {"same": 0, "changed": 0, "new": 0, "missing": 0}
    for sym in sorted(new.keys() | old.keys()):
        n, o = new.get(sym), old.get(sym)
        if n and o:
            same = abs(n["shares"] - o["shares"]) <= DIFF_SHARES_TOL and abs(n["market_value"] - o["market_value"]) <= DIFF_VALUE_TOL
            status = "same" if same else "changed"
        else:
            status = "new" if n else "missing"
        counts[status] += 1
        rows.append(
            {
                "symbol": sym,
                "name": (n or o or {})["name"],
                "status": status,
                "old_shares": o["shares"] if o else None,
                "new_shares": n["shares"] if n else None,
                "old_value": o["market_value"] if o else None,
                "new_value": n["market_value"] if n else None,
            }
        )
    old_total = sum(d["market_value"] for d in old.values())
    new_total = sum(d["market_value"] for d in new.values())
    return {
        "summary": {
            **counts,
            "symbol_overlap_pct": (len(new.keys() & old.keys()) / len(new) * 100) if new else 0.0,
            "old_total": old_total,
            "new_total": new_total,
            "total_delta_pct": ((new_total - old_total) / old_total * 100) if old_total else 0.0,
        },
        "rows": rows,
    }


class AmbiguousOwner(ValueError):
    """Several accounts share the imported name (e.g. two Fidelity 401(k)s); the caller must say whose it is."""

    def __init__(self, name: str, owners: list[str]):
        super().__init__(f"More than one account is named '{name}'. Choose whose account this is.")
        self.name, self.owners = name, owners


def match_account(s, name: str, owner: str | None) -> Account | None:
    """Existing account for an auto-detected import. Names alone aren't unique: spouses often have
    same-named plans at the same provider, so the owner is part of the match when known."""
    q = s.query(Account).filter(Account.name == name)
    if owner:
        return q.filter(Account.owner == owner).first()
    found = q.all()
    if len({a.owner for a in found}) > 1:
        raise AmbiguousOwner(name, sorted({a.owner for a in found}))
    return found[0] if found else None


def resolve_accounts(result: ParseResult, owner: str | None = None) -> None:
    """Raise AmbiguousOwner before anything is written."""
    s = db.session()
    for nm in {r.account_name or "Imported Account" for r in result.rows}:
        match_account(s, nm, owner)


def rows_hash(items) -> str:
    """Order-independent fingerprint of positions (symbol, shares, value, basis); works on ParsedRow and Holding alike."""
    parts = sorted(f"{i.symbol}|{i.shares:.4f}|{i.market_value:.2f}|{i.cost_basis_total:.2f}" for i in items)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _holding_dict(h: Holding) -> dict:
    d = {c.name: getattr(h, c.name) for c in Holding.__table__.columns if c.name not in ("id", "account_id")}
    d["last_updated"] = h.last_updated.isoformat() if h.last_updated else None
    return d


def apply_parse(result: ParseResult, filename: str, account_id: int | None, owner: str | None = None) -> dict:
    """Snapshot-replace holdings per account, log the import (with a pre-import copy for undo), record a net-worth snapshot.
    Idempotent: an account whose holdings already equal the import is left untouched and not re-logged."""
    s = db.session()
    groups: dict[int, list[ParsedRow]] = {}
    created: set[int] = set()
    for row in result.rows:
        if account_id:
            acct = s.get(Account, account_id)
        else:
            nm = row.account_name or "Imported Account"
            acct = match_account(s, nm, owner)
            if acct is None:
                acct = Account(name=nm, **(_default_account_attrs(nm) | ({"owner": owner} if owner else {})))
                s.add(acct)
                s.flush()
                created.add(acct.id)
        groups.setdefault(acct.id, []).append(row)
    now = datetime.now(UTC)
    batch = uuid.uuid4().hex
    unchanged: list[int] = []
    for aid, rows in groups.items():
        existing = {h.symbol: h for h in s.query(Holding).filter(Holding.account_id == aid)}
        digest = rows_hash(rows)
        if existing and rows_hash(existing.values()) == digest:
            unchanged.append(aid)
            continue
        before = [_holding_dict(h) for h in existing.values()]
        seen = set()
        for r in rows:
            seen.add(r.symbol)
            h = existing.get(r.symbol) or Holding(account_id=aid, symbol=r.symbol)
            if h.id is None:
                s.add(h)
            h.name, h.shares, h.current_price = r.name, r.shares, r.price
            h.market_value, h.cost_basis_total = r.market_value, r.cost_basis_total
            h.asset_class, h.last_updated = r.asset_class, now
            h.currency, h.fx_rate = r.currency, r.fx_rate
        for sym, h in existing.items():
            if sym not in seen:
                s.delete(h)
        msg = "; ".join(result.warnings)
        s.add(
            IngestionLog(
                filename=filename,
                account_id=aid,
                parser=result.parser,
                rows_parsed=len(rows),
                status="OK",
                message=msg,
                content_hash=digest,
                batch_id=batch,
                before=before,
                created_account=aid in created,
            )
        )
    s.flush()
    if len(unchanged) < len(groups):
        snapshot_net_worth(s)
    s.commit()
    return {
        "parser": result.parser,
        "rows": len(result.rows),
        "accounts": list(groups),
        "unchanged": unchanged,
        "batch_id": batch,
        "needs_mapping": [r.symbol for r in result.rows if r.needs_mapping],
        "warnings": result.warnings,
        "row_errors": result.row_errors,
    }


def _latest_active_log(s, account_id: int | None):
    return (
        s.query(IngestionLog)
        .filter(IngestionLog.account_id == account_id, IngestionLog.status == "OK", IngestionLog.undone_at.is_(None))
        .order_by(IngestionLog.id.desc())
        .first()
    )


def can_undo(s, log: IngestionLog) -> bool:
    """Only the newest live import of an account can be undone (otherwise 'before' would resurrect stale data)."""
    if log.status != "OK" or log.undone_at is not None or log.before is None or log.account_id is None:
        return False
    latest = _latest_active_log(s, log.account_id)
    return latest is not None and latest.id == log.id


def undo_import(s, log_id: int) -> dict:
    """Undo the whole upload (batch) containing this log row: restore each account's previous holdings, or remove accounts it created."""
    log = s.get(IngestionLog, log_id)
    if log is None:
        raise LookupError("import not found")
    logs = s.query(IngestionLog).filter(IngestionLog.batch_id == log.batch_id).all() if log.batch_id else [log]
    for lg in logs:
        if not can_undo(s, lg):
            raise ValueError(
                "This import can't be undone: it was already undone, predates undo support, "
                "or a newer import changed the same account. Undo the newer one first."
            )
    now = datetime.now(UTC).replace(tzinfo=None)
    restored: list[int] = []
    for lg in logs:
        aid = lg.account_id
        acct = s.get(Account, aid)
        lg.undone_at, lg.status = now, "UNDONE"
        if acct is None:
            continue
        if lg.created_account:
            for other in s.query(IngestionLog).filter(IngestionLog.account_id == aid):
                other.account_id = None
            s.delete(acct)
            continue
        s.query(Holding).filter(Holding.account_id == aid).delete()
        for d in lg.before or []:
            d = dict(d)
            d["last_updated"] = datetime.fromisoformat(d["last_updated"]) if d.get("last_updated") else now
            s.add(Holding(account_id=aid, **d))
        restored.append(aid)
    s.flush()
    snapshot_net_worth(s)
    s.commit()
    return {"undone": [lg.id for lg in logs], "restored_accounts": restored}


def resolve_pension_owner(pension: ParsedPension, profile, owner: str | None) -> str:
    """SELF or SPOUSE. An explicit owner wins; otherwise the printed name must match exactly one of the
    household's names (first initial + last name, since statements print legal names like ANDREW D)."""
    if owner in ("SELF", "SPOUSE"):
        return owner
    if owner == "JOINT":
        raise ValueError("A pension belongs to one person: choose SELF or SPOUSE")

    def key(n: str) -> tuple[str, str]:
        parts = re.sub(r"[^a-z ]", "", n.lower()).split()
        return (parts[0][:1], parts[-1]) if parts else ("", "")

    want = key(pension.holder_name)
    hits = [k for k, n in (("SELF", profile.name), ("SPOUSE", profile.spouse_name)) if n and key(n) == want]
    if len(hits) != 1:
        raise AmbiguousOwner(pension.holder_name or "this pension", ["SELF", "SPOUSE"])
    return hits[0]


def apply_pension(result: ParseResult, filename: str, owner: str) -> dict:
    """Upsert the owner's Pension. Editable assumptions (start age, payout) survive a re-import."""
    pen = result.pension
    if pen is None:
        raise ValueError("not a pension statement")
    s = db.session()
    row = s.query(Pension).filter(Pension.user_id == 1, Pension.owner == owner).first()
    if row is None:
        row = Pension(user_id=1, owner=owner)
        s.add(row)
    row.name, row.plan_balance, row.as_of = pen.plan_name, pen.ending, pen.as_of
    row.pay_credit_pct, row.covered_pay_annual = pen.pay_credit_pct, pen.covered_pay
    row.interest_credit_rate = pen.interest_rate or row.interest_credit_rate or 0.04
    row.ytd_interest, row.ytd_pay_credits = pen.interest_credits, pen.pay_credits
    s.add(IngestionLog(filename=filename, account_id=None, parser=result.parser, rows_parsed=1, status="OK", message="; ".join(result.warnings)))
    s.commit()
    return {"parser": result.parser, "rows": 0, "accounts": [], "needs_mapping": [], "warnings": result.warnings, "pension": row.to_dict()}


def classify_account(a: Account) -> str:
    if a.tax_bucket == "CASH_MMF":
        return "dry_powder"
    if a.risk_tier == "SAFE_CORE" or a.tax_bucket == "PRE_TAX_401K":
        return "safe_core"
    return "satellite"


def bucket_totals(s) -> dict:
    t = {"safe_core": 0.0, "satellite": 0.0, "dry_powder": 0.0}
    for a in s.query(Account).all():
        for h in a.holdings:
            # MMF holdings inside a brokerage are dry powder, not satellite
            key = "dry_powder" if (h.asset_class == "MONEY_MARKET" and classify_account(a) == "satellite" and a.tax_bucket != "HSA") else classify_account(a)
            t[key] += h.market_value
    return t


def owner_totals(s) -> dict:
    """Assets and debts per owner (SELF / SPOUSE / JOINT)."""
    out = {o: {"assets": 0.0, "liabilities": 0.0} for o in ("SELF", "SPOUSE", "JOINT")}
    for a in s.query(Account).all():
        out.setdefault(a.owner, {"assets": 0.0, "liabilities": 0.0})["assets"] += sum(h.market_value for h in a.holdings)
    for liab in s.query(Liability).all():
        out.setdefault(liab.owner, {"assets": 0.0, "liabilities": 0.0})["liabilities"] += liab.balance
    return out


def cash_total(s) -> float:
    """Deployable cash: MONEY_MARKET holdings outside safe-core accounts (an HSA's cash is earmarked for medical, not deployable)."""
    return sum(
        h.market_value
        for a in s.query(Account).all()
        for h in a.holdings
        if h.asset_class == "MONEY_MARKET" and classify_account(a) != "safe_core" and a.tax_bucket != "HSA"
    )


def net_worth_breakdown(s) -> dict:
    """Assets by account tax bucket and debts by kind, for the snapshot's asset/liability breakdown."""
    assets: dict[str, float] = {}
    for a in s.query(Account).all():
        assets[a.tax_bucket] = assets.get(a.tax_bucket, 0.0) + sum(h.market_value for h in a.holdings)
    debts: dict[str, float] = {}
    for liab in s.query(Liability).all():
        debts[liab.kind] = debts.get(liab.kind, 0.0) + liab.balance
    return {"assets": assets, "liabilities": debts}


def snapshot_net_worth(s, when: datetime | None = None):
    """Record net worth; one row per UTC day (a second call the same day updates it, so imports and the scheduler never double count)."""
    when = when or datetime.now(UTC)
    t = bucket_totals(s)
    debt = sum(liab.balance for liab in s.query(Liability).all())
    day = when.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    row = (
        s.query(NetWorthSnapshot)
        .filter(NetWorthSnapshot.taken_at >= day, NetWorthSnapshot.taken_at < day.replace(hour=23, minute=59, second=59, microsecond=999999))
        .first()
    )
    if row is None:
        row = NetWorthSnapshot(taken_at=when.replace(tzinfo=None))
        s.add(row)
    row.total, row.liabilities, row.breakdown = sum(t.values()) - debt, debt, net_worth_breakdown(s)
    row.safe_core, row.satellite, row.dry_powder = t["safe_core"], t["satellite"], t["dry_powder"]
    return row
