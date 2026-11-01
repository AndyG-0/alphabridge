"""Series for the dashboard charts that are not already exposed elsewhere. All arithmetic lives here, never in the browser."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from models import Liability, UserProfile
from services import tax


def bracket_fill(magi: float, status: str, year: int | None = None) -> dict[str, Any]:
    """Ordinary-income bracket bands with how much of each is filled by `magi` after the standard deduction.

    MAGI is treated as ordinary income for this picture; capital gains and the Social Security taxable share are not separated here."""
    year = tax.rules_year(year or date.today().year)
    status = status if status in tax.STATUSES else "SINGLE"
    ded = tax.standard_deduction(status, year)
    taxable = max(float(magi) - ded, 0.0)
    br = tax._brackets(status, year)
    bands = []
    for i, (lo, rate) in enumerate(br):
        hi = br[i + 1][0] if i + 1 < len(br) else None
        filled = max(min(taxable, hi if hi is not None else taxable) - lo, 0.0)
        bands.append({"from": lo, "to": hi, "rate": rate, "filled": filled})
    t = tax.table(year)
    total, marginal = tax.ordinary_tax(taxable, status, year)
    return {
        "year": year,
        "status": status,
        "magi": float(magi),
        "standard_deduction": ded,
        "taxable_income": taxable,
        "tax": total,
        "marginal_rate": marginal,
        "bands": bands,
        "source_url": t.get("source_url"),
        "retrieved_on": t.get("retrieved_on"),
    }


def cash_flow(s: Session, p: UserProfile) -> dict[str, Any]:
    """Where this year's gross household income goes: tax, spending, debt payments, savings, and what is left over (or the shortfall)."""
    year = date.today().year
    gross = float(p.annual_income or 0) + float(p.spouse_annual_income or 0)
    rate = tax.effective_rate_estimate(gross, p.tax_filing_status, year, p.state) if gross > 0 else 0.0
    taxes = gross * rate
    spending = float(p.monthly_expenses_current or 0) * 12
    debt = sum(((r.monthly_payment or 0) + (r.extra_monthly_payment or 0)) * 12 for r in s.query(Liability).all())
    saving = float(p.monthly_contribution or 0) * 12
    left = gross - taxes - spending - debt - saving
    parts = [("Taxes", taxes), ("Spending", spending), ("Debt payments", debt), ("Savings", saving), ("Left over", max(left, 0.0))]
    links = [{"source": "Income", "target": name, "value": v} for name, v in parts if v > 0]
    return {
        "year": year,
        "gross_income": gross,
        "effective_tax_rate": rate,
        "nodes": ["Income", *[name for name, v in parts if v > 0]],
        "links": links,
        "shortfall": max(-left, 0.0),
        "note": "Tax is an estimate from the effective-rate model; spending excludes debt payments, which are shown separately.",
    }
