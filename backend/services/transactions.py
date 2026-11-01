"""Spending actuals (budgeting-lite): import bank/card transaction CSVs, categorize, and compare measured spend with the plan.

Categorization is deterministic (user rules, then the source file's own category, then keyword rules). LLM suggestions only
fill `suggested_category`; nothing is applied until the user confirms. All sums are plain Python.
"""

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

import db
from models import CategoryRule, Transaction
from services.ingestion import bad_number, money

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "transaction_rules.json"
DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d-%b-%Y")


@lru_cache(maxsize=1)
def rules() -> dict:
    return json.loads(DATA_FILE.read_text())


def categories() -> list[str]:
    r = rules()
    return [*r["categories"], *r["excluded_categories"]]


def _date(v: str) -> date | None:
    from datetime import datetime

    for f in DATE_FORMATS:
        try:
            return datetime.strptime(v.strip(), f).date()
        except ValueError:
            continue
    return None


def parse_csv(text: str) -> tuple[list[dict], list[dict]]:
    """Returns (transactions, row_errors). Handles signed Amount (Chase/Monarch), Amount + Transaction Type (Mint) and
    Outflow/Inflow (YNAB) or Debit/Credit columns. Money out is negative."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    hi = next((i for i, r in enumerate(rows[:30]) if _cols(r) is not None), None)
    if hi is None:
        return [], [{"line": 1, "level": "error", "error": "No header with a date, a description and an amount (or outflow/inflow) column"}]
    cols = _cols(rows[hi]) or {}
    out, errs = [], []
    for n, r in enumerate(rows[hi + 1 :], start=hi + 2):
        if not any(c.strip() for c in r):
            continue

        def get(k, r=r):
            i = cols.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""

        d = _date(get("date"))
        if d is None:
            errs.append({"line": n, "level": "error", "error": f"unreadable date '{get('date')}'"})
            continue
        if any(bad_number(get(k)) for k in ("amount", "outflow", "inflow")):
            errs.append({"line": n, "level": "error", "error": "unreadable amount"})
            continue
        if "outflow" in cols or "inflow" in cols:
            amt = money(get("inflow")) - money(get("outflow"))
        else:
            amt = money(get("amount"))
            if get("type").lower() in ("debit", "withdrawal"):
                amt = -abs(amt)
            elif get("type").lower() in ("credit", "deposit"):
                amt = abs(amt)
        if amt == 0:
            continue
        out.append(
            {"tx_date": d, "description": get("description")[:300], "amount": amt, "account_label": get("account")[:120], "file_category": get("category")}
        )
    return out, errs


_ALIASES = {
    "date": ["date", "posting date", "transaction date", "post date"],
    "description": ["description", "payee", "merchant", "name", "memo"],
    "amount": ["amount"],
    "outflow": ["outflow", "debit"],
    "inflow": ["inflow", "credit"],
    "type": ["transaction type", "type"],
    "account": ["account", "account name"],
    "category": ["category"],
}


def _cols(header: list[str]) -> dict[str, int] | None:
    norm = [h.strip().lower() for h in header]
    c = {k: norm.index(a) for k, names in _ALIASES.items() for a in names if a in norm}
    if "date" in c and "description" in c and ("amount" in c or "outflow" in c or "inflow" in c):
        return c
    return None


def tx_hash(t: dict, occurrence: int = 0) -> str:
    key = f"{t['tx_date']}|{t['description']}|{t['amount']:.2f}|{t['account_label']}|{occurrence}"
    return hashlib.sha256(key.encode()).hexdigest()


def categorize(desc: str, file_category: str, user_rules: list[tuple[str, str]], amount: float) -> tuple[str, str]:
    d = desc.lower()
    for pat, cat in user_rules:
        if pat in d:
            return cat, "user"
    r = rules()
    if mapped := r["source_category_map"].get(file_category.strip().lower()):
        return mapped, "file"
    for cat, words in r["keywords"].items():
        if any(w in d for w in words):
            return cat, "rule"
    return ("income", "rule") if amount > 0 else ("", "")


def import_rows(items: list[dict]) -> dict:
    """Idempotent: identical (date, description, amount, account) rows are deduped by hash, repeats within one file kept via occurrence index."""
    s = db.session()
    urules = [(r.pattern.lower(), r.category) for r in s.query(CategoryRule)]
    seen: dict[tuple, int] = defaultdict(int)
    added = dup = 0
    for t in items:
        k = (t["tx_date"], t["description"], round(t["amount"], 2), t["account_label"])
        h = tx_hash(t, seen[k])
        seen[k] += 1
        if s.query(Transaction.id).filter_by(tx_hash=h).first():
            dup += 1
            continue
        cat, src = categorize(t["description"], t.get("file_category", ""), urules, t["amount"])
        s.add(
            Transaction(
                tx_date=t["tx_date"],
                description=t["description"],
                amount=t["amount"],
                account_label=t["account_label"],
                category=cat,
                category_source=src,
                tx_hash=h,
            )
        )
        added += 1
    s.commit()
    return {"added": added, "duplicates": dup, "uncategorized": s.query(Transaction).filter(Transaction.category == "").count()}


def set_category(tx_id: int, category: str, make_rule: bool = False) -> bool:
    if category not in categories():
        raise ValueError(f"unknown category '{category}'")
    s = db.session()
    t = s.get(Transaction, tx_id)
    if t is None:
        return False
    t.category, t.category_source, t.suggested_category = category, "user", ""
    if make_rule:
        pat = t.description.strip().lower()[:120]
        if pat and not s.query(CategoryRule).filter_by(pattern=pat).first():
            s.add(CategoryRule(pattern=pat, category=category))
    s.commit()
    return True


def recategorize_uncategorized() -> int:
    """Re-run rules over uncategorized rows (after the user adds rules)."""
    s = db.session()
    urules = [(r.pattern.lower(), r.category) for r in s.query(CategoryRule)]
    n = 0
    for t in s.query(Transaction).filter(Transaction.category == ""):
        cat, src = categorize(t.description, "", urules, t.amount)
        if cat:
            t.category, t.category_source = cat, src
            n += 1
    s.commit()
    return n


class _Suggestion(BaseModel):
    id: int
    category: str


class _Suggestions(BaseModel):
    suggestions: list[_Suggestion]


def suggest_with_llm(limit: int = 40) -> int:
    """Ask the LLM to label uncategorized merchants. Stored as suggestions only; the user confirms each one."""
    from services import llm_router

    s = db.session()
    todo = s.query(Transaction).filter(Transaction.category == "", Transaction.suggested_category == "").limit(limit).all()
    if not todo:
        return 0
    cats = [c for c in categories() if c != "income"]
    listing = "\n".join(f"{t.id}: {t.description}" for t in todo)
    res = llm_router.complete_structured(
        "categorize",
        f"Assign each transaction description to exactly one of: {', '.join(cats)}. Use only these labels. Do not compute anything.",
        listing,
        _Suggestions,
    )
    valid, n = {t.id: t for t in todo}, 0
    for sg in res.suggestions:
        if sg.id in valid and sg.category in cats:
            valid[sg.id].suggested_category = sg.category
            n += 1
    s.commit()
    return n


def confirm_suggestions(ids: list[int]) -> int:
    s = db.session()
    n = 0
    for t in s.query(Transaction).filter(Transaction.id.in_(ids), Transaction.suggested_category != ""):
        t.category, t.category_source, t.suggested_category = t.suggested_category, "user", ""
        n += 1
    s.commit()
    return n


def monthly_spend(txns: list[Transaction]) -> dict[str, dict[str, float]]:
    """{YYYY-MM: {category: spend}} for spending rows only (money out, excluding transfers/income)."""
    excl = set(rules()["excluded_categories"])
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in txns:
        if t.amount < 0 and t.category not in excl:
            out[f"{t.tx_date:%Y-%m}"][t.category or "uncategorized"] += -t.amount
    return {m: dict(v) for m, v in out.items()}


def actuals(profile, today: date | None = None, months: int = 12) -> dict:
    """Measured monthly spend over the most recent complete months vs the plan assumption, plus a lifestyle-creep flag."""
    today = today or date.today()
    cur = f"{today:%Y-%m}"
    txns = db.session().query(Transaction).all()
    by_month = {m: v for m, v in monthly_spend(txns).items() if m < cur}  # drop the partial current month
    keys = sorted(by_month)[-months:]
    totals = [sum(by_month[m].values()) for m in keys]
    avg = sum(totals) / len(totals) if totals else 0.0
    cat_avg: dict[str, float] = defaultdict(float)
    for m in keys:
        for c, v in by_month[m].items():
            cat_avg[c] += v / len(keys)
    plan = float(profile.monthly_expenses_current or 0)
    cr = rules()["lifestyle_creep"]
    creep: dict[str, object] = {"flag": False, "recent_avg": None, "baseline_avg": None, "change": None, "reason": "Not enough months"}
    if len(totals) >= cr["min_months_total"]:
        recent, base = totals[-cr["recent_months"] :], totals[-(cr["recent_months"] + cr["baseline_months"]) : -cr["recent_months"]]
        if base:
            ra, ba = sum(recent) / len(recent), sum(base) / len(base)
            ch = (ra - ba) / ba if ba else 0.0
            creep = {
                "flag": ch > cr["threshold"],
                "recent_avg": round(ra, 2),
                "baseline_avg": round(ba, 2),
                "change": round(ch, 4),
                "reason": f"threshold {cr['threshold']:.0%}",
            }
    return {
        "months_used": keys,
        "measured_monthly_avg": round(avg, 2),
        "plan_monthly": plan,
        "difference": round(avg - plan, 2),
        "difference_pct": round((avg - plan) / plan, 4) if plan else None,
        "by_category_monthly_avg": {c: round(v, 2) for c, v in sorted(cat_avg.items(), key=lambda kv: -kv[1])},
        "monthly_totals": {m: round(t, 2) for m, t in zip(keys, totals, strict=True)},
        "lifestyle_creep": creep,
        "uncategorized_count": sum(1 for t in txns if not t.category),
        "note": "Profile expenses exclude debt payments; transfers and income rows are excluded here. Review uncategorized rows before trusting the average.",
    }
