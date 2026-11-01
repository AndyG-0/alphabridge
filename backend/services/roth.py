"""Roth conversion explorer: a year-by-year conversion ladder priced through the same tax/ACA code as the withdrawal simulator.

Each conversion year the amount is chosen by bisection so the year stays under a limit (top of a tax bracket, the ACA
MAGI target, or the first IRMAA tier). The conversion is ordinary income, so it flows through tax.total_tax, Social Security
taxability and the ACA subsidy; the tax it creates is paid from the household's other money (the bridge), never from the
converted dollars. Converted dollars are locked for five years while the owner is under 59½ (10% penalty on converted principal
withdrawn inside the 5-year clock); existing Roth balances are treated as seasoned.

Real (today's) dollars, constant real returns, no I/O. Comparison is against the same plan with no conversions."""

from dataclasses import replace

from services import aca, rmd
from services import tax as tax_svc
from services import withdrawals as wd

MODES = ("FILL_BRACKET", "ACA_MAGI", "IRMAA")
LABELS = {
    "NONE": "No conversions",
    "FILL_BRACKET": "Fill the tax bracket",
    "ACA_MAGI": "Stay under the ACA MAGI target",
    "IRMAA": "Stay under the first IRMAA tier",
}
SEASON_YEARS = 5
PENALTY_FREE_AGE = 59.5
_SOLVE_ITERS = 12


def irmaa_limit(status: str, year: int) -> float:
    """MAGI at which the first Medicare surcharge tier starts."""
    return float(tax_svc.table(year)["irmaa"]["tiers"][tax_svc._status(status)][0][0])


def _limit(work: wd.Inputs, mode: str, y: int, year: int) -> tuple[str, float]:
    """(metric key in the year row, ceiling) for this mode and year."""
    if mode == "ACA_MAGI" and y < len(work.aca_benchmark) and work.aca_benchmark[y] > 0:
        return "magi", aca.target_magi(work.household_size, margin=work.magi_margin)
    if mode == "IRMAA":
        return "agi", irmaa_limit(work.status, year)
    return "ordinary_plus_ss", wd._bracket_top(work, year)  # bracket fill, and ACA mode once off the marketplace


def _metric(row: dict, key: str) -> float:
    return row["ordinary_income"] + row["taxable_social_security"] if key == "ordinary_plus_ss" else row[key]


def _locked(ledger: list[dict], year: int, age: float) -> float:
    if age >= PENALTY_FREE_AGE:
        return 0.0
    return sum(c["amount"] for c in ledger if year - c["year"] < SEASON_YEARS)


def _pretax_at(rows: list[dict], inp: wd.Inputs, age: int) -> float:
    """Pre-tax balance at the start of the year the primary turns `age`."""
    prior = [r for r in rows if r["age"] == age - 1]
    if prior:
        return prior[0]["balances"]["pretax"]
    return inp.pretax if rows and age <= rows[0]["age"] else 0.0


def simulate(
    inp: wd.Inputs,
    mode: str | None,
    *,
    draw_strategy: str = "TAXABLE_FIRST",
    start_age: float | None = None,
    until_age: float = 72,
    bracket_rate: float = 0.12,
    max_annual: float = float("inf"),
    rmd_start_age: int = 75,
) -> dict:
    """One conversion plan (`mode` None = no conversions). Returns the withdrawal-simulator summary plus the ladder."""
    if mode is not None and mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    n = max(int(inp.end_age - inp.start_age), 0)
    pad = lambda xs: [*xs, *([0.0] * (n - len(xs)))]
    work = replace(inp, ordinary_income=pad(inp.ordinary_income), other_cash=pad(inp.other_cash), bracket_rate=bracket_rate)
    start = inp.start_age if start_age is None else start_age
    bal = {"taxable": inp.taxable, "pretax": inp.pretax, "roth": inp.roth}
    rows: list[dict] = []
    ledger: list[dict] = []

    def year_row(y: int, convert: float, view: dict, age: float) -> dict:
        work.ordinary_income[y] += convert
        work.other_cash[y] -= convert  # conversion is taxable income but not spendable cash
        try:
            return wd._solve_year(work, draw_strategy, y, view, age)
        finally:
            work.ordinary_income[y] -= convert
            work.other_cash[y] += convert

    for y in range(n):
        age = work.start_age + y
        year = work.start_year + y
        view = {**bal, "roth": max(bal["roth"] - _locked(ledger, year, age), 0.0)}
        convert, row = 0.0, None
        base = year_row(y, 0.0, view, age)
        if mode and start <= age <= until_age and bal["pretax"] > 1.0:
            key, ceiling = _limit(work, mode, y, year)
            # pre-tax dollars drawn that year are no longer available to convert
            hi = min(max(bal["pretax"] - base["draw_pretax"], 0.0), max_annual)
            if hi > 1.0 and _metric(base, key) < ceiling:
                top = year_row(y, hi, view, age)
                if _metric(top, key) <= ceiling and top["shortfall"] <= base["shortfall"] + 1.0:
                    convert, row = hi, top
                else:
                    lo, up = 0.0, hi
                    for _ in range(_SOLVE_ITERS):
                        mid = (lo + up) / 2
                        trial = year_row(y, mid, view, age)
                        ok = _metric(trial, key) <= ceiling and trial["shortfall"] <= base["shortfall"] + 1.0
                        lo, up = (mid, up) if ok else (lo, mid)
                    convert = lo
                    row = year_row(y, convert, view, age) if convert > 1.0 else None
        if row is None:
            convert, row = 0.0, base
        row["conversion"] = convert
        row["conversion_tax"] = row["tax"] - base["tax"] if convert else 0.0
        if convert:
            ledger.append({"year": year, "age": round(age, 1), "amount": convert, "seasoned_year": year + SEASON_YEARS})
        bal["taxable"] -= row["draw_taxable"]
        bal["pretax"] -= row["draw_pretax"] + convert
        bal["roth"] += convert - row["draw_roth"]
        for k in bal:
            bal[k] = max(bal[k], 0.0) * (1 + inp.real_return)
        row["balances"] = dict(bal.items())
        rows.append(row)

    out = wd.summarize(mode or "NONE", rows, bal)
    out["label"] = LABELS[mode or "NONE"]
    ped = _pretax_at(rows, inp, rmd_start_age)
    out.update(
        ladder=ledger,
        total_converted=sum(c["amount"] for c in ledger),
        conversion_tax=sum(r["conversion_tax"] for r in rows),
        pretax_at_rmd_age=ped,
        first_rmd=rmd.rmd(ped, rmd_start_age),
        # bridge: taxable money (plus income) must cover living costs and the conversion tax during seasoning
        bridge_ok=out["shortfall_years"] == 0,
        min_taxable_balance=min((r["balances"]["taxable"] for r in rows), default=0.0),
    )
    return out


def compare(inp: wd.Inputs, modes: tuple[str, ...] = MODES, detail: bool = True, **kw) -> dict:
    """No-conversion baseline plus each mode; `best` = lowest lifetime tax + premiums among plans with no new shortfall."""
    base = simulate(inp, None, **kw)
    results = [simulate(inp, m, **kw) for m in modes]
    ok = [r for r in results if r["shortfall_years"] <= base["shortfall_years"]]
    best = min(ok, key=lambda r: (round(r["lifetime_cost"]), -r["ending_after_tax"]))["strategy"] if ok else None
    if best and next(r for r in results if r["strategy"] == best)["lifetime_cost"] >= base["lifetime_cost"] - 1:
        best = None  # no mode beats doing nothing
    out = []
    for r in [base, *results]:
        row = {k: v for k, v in r.items() if k != "years" or detail}
        row["vs_none"] = {
            "lifetime_cost": r["lifetime_cost"] - base["lifetime_cost"],
            "ending_after_tax": r["ending_after_tax"] - base["ending_after_tax"],
            "first_rmd": r["first_rmd"] - base["first_rmd"],
        }
        out.append(row)
    return {
        "best": best,
        "plans": out,
        "rules_year": tax_svc.rules_year(inp.start_year),
        "aca_rules_year": aca.RULES_YEAR,
        "rmd_start_age": kw.get("rmd_start_age", 75),
        "assumptions": [
            "Real (today's) dollars with constant real returns; tax tables held constant in real terms.",
            "Conversion tax is paid from other money, never from the converted dollars.",
            f"Converted dollars are locked {SEASON_YEARS} years while under 59½; existing Roth balances are treated as seasoned.",
            "IRMAA mode caps AGI at the first surcharge tier every year (Medicare looks back two years); tax-exempt interest is ignored.",
            "ACA mode targets the MAGI that keeps the premium credit; once everyone is on Medicare it fills the bracket instead.",
            "RMD reduction compares the pre-tax balance at the RMD start age; the withdrawal simulator itself does not force RMDs.",
        ],
    }
