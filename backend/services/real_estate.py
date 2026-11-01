"""Home as an asset and a lever (P12): equity projection, downsizing and relocation.

Pure math in nominal dollars unless noted. The section 121 exclusion comes from data/real_estate.json. Selling costs and appreciation are
user-editable assumptions. Gain above the exclusion is taxed as long-term capital gain through `tax.total_tax` (incremental over `other_income`)."""

import json
from functools import lru_cache
from pathlib import Path

from services import tax

DATA = Path(__file__).resolve().parents[1] / "data" / "real_estate.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text())


def defaults() -> dict:
    d = _data()
    return {
        "appreciation": d["default_appreciation"],
        "selling_cost_pct": d["default_selling_cost_pct"],
        "source_url": d["source_url"],
        "retrieved_on": d["retrieved_on"],
        "notes": d["notes"],
    }


def exclusion(status: str) -> float:
    return float(_data()["exclusion"].get((status or "SINGLE").upper(), 250_000))


def mortgage_balance_path(balance: float, apr: float, payment: float, years: int) -> list[float]:
    """Year-end mortgage balance for each of `years` years (never below zero)."""
    out, b, r = [], max(balance, 0.0), apr / 12
    for _ in range(years):
        for _ in range(12):
            b = max(b * (1 + r) - payment, 0.0) if payment > 0 else b * (1 + r)
        out.append(b)
    return out


def equity_projection(home_value: float, appreciation: float, mortgages: list[dict], years: int, start_year: int) -> list[dict]:
    """Home value, mortgage balance and equity by year. `mortgages` are dicts with balance, apr, monthly_payment (any of them may be empty)."""
    paths = [mortgage_balance_path(m["balance"], m["apr"], m["monthly_payment"], years) for m in mortgages]
    rows = []
    for k in range(years):
        value = home_value * (1 + appreciation) ** (k + 1)
        owed = sum(p[k] for p in paths)
        rows.append({"year": start_year + k + 1, "value": value, "mortgage": owed, "equity": value - owed})
    return rows


def downsize(
    *,
    sale_price: float,
    mortgage: float,
    cost_basis: float,
    new_home_price: float,
    status: str,
    year: int,
    selling_cost_pct: float | None = None,
    other_income: float = 0.0,
    old_upkeep_pct: float = 0.01,
    new_upkeep_pct: float = 0.01,
    state: str | None = None,
) -> dict:
    """Cash freed by selling and buying smaller: net proceeds, section 121 tax, and the annual upkeep change."""
    sc = _data()["default_selling_cost_pct"] if selling_cost_pct is None else selling_cost_pct
    costs = sale_price * sc
    gain = max(sale_price - costs - cost_basis, 0.0)
    taxable_gain = max(gain - exclusion(status), 0.0)
    t = 0.0
    if taxable_gain > 0:
        t = (
            tax.total_tax(ordinary=other_income, qualified=taxable_gain, status=status, year=year, state=state)["total"]
            - tax.total_tax(ordinary=other_income, status=status, year=year, state=state)["total"]
        )
    net = sale_price - costs - mortgage - t
    cash_freed = net - new_home_price
    return {
        "sale_price": sale_price,
        "selling_costs": costs,
        "mortgage_payoff": mortgage,
        "gain": gain,
        "exclusion": exclusion(status),
        "taxable_gain": taxable_gain,
        "tax": max(t, 0.0),
        "net_proceeds": net,
        "new_home_price": new_home_price,
        "cash_freed": cash_freed,
        "upkeep_change_annual": new_home_price * new_upkeep_pct - sale_price * old_upkeep_pct,
    }


def cost_of_living(
    annual_spend: float,
    current_index: float,
    target_index: float,
    income: float = 0.0,
    status: str = "SINGLE",
    year: int = 2026,
    from_state: str | None = None,
    to_state: str | None = None,
) -> dict:
    """Relocation: spending scaled by a cost-of-living index ratio (e.g. 100 -> 85) plus the flat state income-tax difference on `income`."""
    if current_index <= 0 or target_index <= 0:
        raise ValueError("cost-of-living indices must be positive")
    scaled = annual_spend * target_index / current_index
    taxable = max(income - tax.standard_deduction(status, year), 0.0)
    tax_old, tax_new = tax.state_tax(taxable, from_state), tax.state_tax(taxable, to_state)
    return {
        "current_spend": annual_spend,
        "new_spend": scaled,
        "spend_change": scaled - annual_spend,
        "state_tax_change": tax_new - tax_old,
        "annual_saving": (annual_spend - scaled) + (tax_old - tax_new),
        "ratio": target_index / current_index,
    }
