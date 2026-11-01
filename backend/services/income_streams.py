"""Taxed non-portfolio income events (P11): SPIA/annuity, part-time work, rental, equity compensation, inheritance, business/property sale.

Each event becomes (ordinary income, qualified gains, tax-free cash) for a year; the tax is the INCREMENTAL federal+state tax
(`tax.total_tax`, P1) over the household's other ordinary income, so it stacks on the right brackets. Amounts are today's dollars.

Event field use (no extra columns beyond `basis`):
  ANNUITY   amount = monthly payment; basis = premium paid. Exclusion-ratio approximation: basis / `expected_years` is tax-free each year until recovered.
  PARTTIME  amount = annual gross pay, runs start_year..repeat_until_year. Ordinary income; payroll/self-employment tax is NOT modelled.
  RENTAL    amount = annual net cash flow before depreciation; basis = annual depreciation (shelters taxable rent; passive-loss limits ignored).
  EQUITY    amount = value at vest/exercise (RSU, NSO, ESPP disqualifying disposition). Ordinary income. ISO AMT is NOT modelled.
  INHERIT   amount = cash received. Not income; basis steps up at death so no tax.
  BIZSALE   amount = sale price, basis = cost basis. Gain is long-term capital gain (no recapture/installment treatment).
"""

from services import tax

STREAM_KINDS = ("ANNUITY", "PARTTIME", "RENTAL", "EQUITY", "INHERIT", "BIZSALE")
RECURRING = ("ANNUITY", "PARTTIME", "RENTAL")  # paid every year from start_year (like PENSION)
EXPECTED_YEARS = 20  # annuity exclusion-ratio horizon when no life expectancy is given


def components(kind: str, amount: float, basis: float = 0.0, years_paid: int = 0, expected_years: int = EXPECTED_YEARS) -> dict:
    """Gross cash, ordinary income and qualified gain for one year of one event."""
    if kind == "ANNUITY":
        gross = amount * 12
        excluded = min(basis / max(expected_years, 1), gross) if years_paid < expected_years else 0.0
        return {"cash": gross, "ordinary": gross - excluded, "qualified": 0.0}
    if kind == "PARTTIME" or kind == "EQUITY":
        return {"cash": amount, "ordinary": amount, "qualified": 0.0}
    if kind == "RENTAL":
        return {"cash": amount, "ordinary": max(amount - basis, 0.0), "qualified": 0.0}
    if kind == "INHERIT":
        return {"cash": amount, "ordinary": 0.0, "qualified": 0.0}
    if kind == "BIZSALE":
        return {"cash": amount, "ordinary": 0.0, "qualified": max(amount - basis, 0.0)}
    raise ValueError(f"unknown stream kind: {kind}")


def incremental_tax(ordinary: float, qualified: float, base_ordinary: float, status: str, year: int, state: str | None = None) -> float:
    """Extra tax caused by adding these streams on top of `base_ordinary` income."""
    if ordinary <= 0 and qualified <= 0:
        return 0.0
    with_ = tax.total_tax(ordinary=base_ordinary + ordinary, qualified=qualified, status=status, year=year, state=state)["total"]
    without = tax.total_tax(ordinary=base_ordinary, status=status, year=year, state=state)["total"]
    return max(with_ - without, 0.0)


def after_tax(parts: list[dict], base_ordinary: float, status: str, year: int, state: str | None = None) -> dict:
    """Net cash for one year from the summed `components` of several events."""
    cash = sum(p["cash"] for p in parts)
    o, q = sum(p["ordinary"] for p in parts), sum(p["qualified"] for p in parts)
    t = incremental_tax(o, q, base_ordinary, status, year, state)
    return {"cash": cash, "ordinary": o, "qualified": q, "tax": t, "net": cash - t}
