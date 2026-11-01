"""Debt statement ingestion: generic CSV (deterministic) and PDF (LLM extraction of printed numbers only)."""

import csv
import io
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

import db
from models import IngestionLog, Liability
from services import doc_reader
from services.ingestion import money, snapshot_net_worth

KINDS = ("MORTGAGE", "AUTO", "CARD", "STUDENT", "HELOC", "OTHER")

ALIASES = {
    "name": ["account name", "loan name", "account", "loan", "description", "name", "lender", "creditor"],
    "balance": ["current balance", "principal balance", "outstanding balance", "statement balance", "new balance", "balance", "payoff amount"],
    "apr": ["apr", "interest rate", "rate", "purchase apr"],
    "payment": ["monthly payment", "minimum payment", "min payment", "regular payment", "payment", "payment amount"],
    "escrow": ["escrow", "escrow payment", "escrow amount"],
    "kind": ["type", "loan type", "kind"],
}

_KIND_HINTS = [
    ("MORTGAGE", ("mortgage", "home loan")),
    ("HELOC", ("heloc", "home equity")),
    ("AUTO", ("auto", "car ", "vehicle", "motor")),
    ("STUDENT", ("student", "navient", "nelnet", "mohela", "edfinancial")),
    ("CARD", ("card", "visa", "mastercard", "amex", "american express", "discover", "credit")),
]


@dataclass
class ParsedDebt:
    name: str
    kind: str
    balance: float
    apr: float = 0.0  # decimal
    monthly_payment: float = 0.0  # principal + interest (or minimum payment for cards)
    escrow_monthly: float = 0.0


@dataclass
class DebtParse:
    debts: list[ParsedDebt] = field(default_factory=list)
    parser: str = ""
    warnings: list[str] = field(default_factory=list)


def guess_kind(text: str) -> str:
    t = f" {text.lower()} "
    for kind, words in _KIND_HINTS:
        if any(w in t for w in words):
            return kind
    return "OTHER"


def to_apr(v: float) -> float:
    """Statements print 6.5 or 6.5%; the database stores 0.065. Values below 1 are taken as already decimal."""
    return v / 100 if v >= 1 else v


def _cols(headers: list[str]) -> dict[str, int]:
    norm = [h.strip().lower() for h in headers]
    out: dict[str, int] = {}
    for key, names in ALIASES.items():
        for alias in names:
            if alias in norm:
                out[key] = norm.index(alias)
                break
    return out


def parse_csv(text: str) -> DebtParse:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    res = DebtParse(parser="debt_csv")
    hi = next((i for i, r in enumerate(rows[:30]) if {"name", "balance"} <= _cols(r).keys()), None)
    if hi is None:
        res.warnings.append("No header row with a name and a balance column")
        return res
    cols = _cols(rows[hi])

    def get(row, key):
        i = cols.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows[hi + 1 :]:
        name = get(row, "name")
        bal = abs(money(get(row, "balance")))  # some exports show owed amounts as negatives
        if not name or name.lower().startswith("total") or bal == 0:
            continue
        kind = get(row, "kind").upper()
        res.debts.append(
            ParsedDebt(
                name=name,
                kind=kind if kind in KINDS else guess_kind(f"{name} {get(row, 'kind')}"),
                balance=bal,
                apr=to_apr(money(get(row, "apr"))),
                monthly_payment=money(get(row, "payment")),
                escrow_monthly=money(get(row, "escrow")),
            )
        )
    return res


class _PdfDebt(BaseModel):
    name: str  # lender/product plus the last 4 digits of the account, e.g. "Chase Freedom 1234"
    kind: str = "OTHER"
    balance: float
    apr_percent: float = 0  # as printed, e.g. 6.5; 0 if not shown
    principal_and_interest_payment: float = 0  # the loan payment excluding escrow; for cards the minimum payment due
    escrow_payment: float = 0


class _PdfDebts(BaseModel):
    debts: list[_PdfDebt]


_SYSTEM = (
    "Extract each loan or credit account from this statement text. Copy numbers exactly as printed; never compute, "
    "estimate or convert them. balance is the amount currently owed (principal balance for loans, new/statement "
    "balance for cards). apr_percent is the interest rate as printed (the purchase APR for cards). If a mortgage "
    "statement itemises principal, interest and escrow, report principal+interest and escrow separately; if only a "
    "total payment is printed, put it in principal_and_interest_payment and leave escrow_payment 0. "
    "kind is one of MORTGAGE, AUTO, CARD, STUDENT, HELOC, OTHER. Omit totals."
)


def debts_from_text(text: str, llm_structured=None, images: list[bytes] | None = None) -> DebtParse:
    res = DebtParse(parser="debt_pdf_llm")
    if not text.strip() and not images:
        res.warnings.append("No extractable text or image content in the file")
        return res
    if llm_structured is None:
        from services.llm_router import complete_structured

        llm_structured = lambda sys, usr: complete_structured("fast", sys, usr, _PdfDebts, images=images)
    for d in llm_structured(_SYSTEM, text[:30000] or "The document is in the attached image(s).").debts:
        kind = d.kind.upper()
        res.debts.append(
            ParsedDebt(
                name=re.sub(r"\s+", " ", d.name).strip()[:160] or "Imported debt",
                kind=kind if kind in KINDS else guess_kind(d.name),
                balance=abs(d.balance),
                apr=to_apr(d.apr_percent),
                monthly_payment=d.principal_and_interest_payment,
                escrow_monthly=d.escrow_payment,
            )
        )
    res.warnings.append("Values were read by the AI fallback; check APR and payment against your statement.")
    return res


def parse_pdf(data: bytes, llm_structured=None) -> DebtParse:
    doc = doc_reader.read_pdf(data)
    return debts_from_text(doc.text, llm_structured, doc.images or None)


def parse_image(data: bytes, llm_structured=None) -> DebtParse:
    doc = doc_reader.read_image(data)
    return debts_from_text(doc.text, llm_structured, doc.images or None)


def _last4(name: str) -> str | None:
    m = re.search(r"(\d{4})\D*$", name)
    return m.group(1) if m else None


def _match(existing: list[Liability], d: ParsedDebt) -> Liability | None:
    for x in existing:
        if x.name.strip().lower() == d.name.strip().lower():
            return x
    last4 = _last4(d.name)
    if last4:
        for x in existing:
            if x.kind == d.kind and _last4(x.name) == last4:
                return x
    return None


def apply_parse(result: DebtParse, filename: str) -> dict:
    """Upsert by name (or kind + last 4 digits). Re-uploading a statement updates, never duplicates.
    Hand-entered payoff date, owner, and any rate/payment the statement omitted are kept."""
    s = db.session()
    existing = s.query(Liability).all()
    created, updated = [], []
    for d in result.debts:
        x = _match(existing, d)
        if x is None:
            x = Liability(name=d.name, kind=d.kind, balance=d.balance, apr=d.apr, monthly_payment=d.monthly_payment, escrow_monthly=d.escrow_monthly)
            s.add(x)
            existing.append(x)
            created.append(d.name)
            continue
        x.balance = d.balance
        if d.apr > 0:
            x.apr = d.apr
        if d.monthly_payment > 0:
            x.monthly_payment = d.monthly_payment
        if d.escrow_monthly > 0:
            x.escrow_monthly = d.escrow_monthly
        updated.append(x.name)
    s.add(IngestionLog(filename=filename, parser=result.parser, rows_parsed=len(result.debts), status="OK", message="; ".join(result.warnings)))
    s.flush()
    snapshot_net_worth(s)
    s.commit()
    return {"parser": result.parser, "rows": len(result.debts), "created": created, "updated": updated, "warnings": result.warnings}
