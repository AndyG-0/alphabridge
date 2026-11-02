"""User-defined health-coverage alternatives to ACA / flat Medicare: eligibility, annual cost and a per-age comparison.

Pure math in today's dollars; `household.build_flows` applies health inflation. Prices live in the user's rows
(`CoverageOption.premium_by_year`), not in code, so no tax or program constants are held here."""

MEDICARE_AGE = 65
CATEGORIES = ("PRE_MEDICARE", "MEDICARE_ADVANTAGE", "MEDIGAP", "DRUG", "OTHER")
MEDICARE_CATEGORIES = ("MEDICARE_ADVANTAGE", "MEDIGAP")


def monthly_premium(opt, year: int) -> float:
    """Monthly premium for `year`: exact year, else the latest earlier year, else the earliest known; 0 when no price is entered."""
    prices = {int(k): float(v) for k, v in (opt.premium_by_year or {}).items()}
    if not prices:
        return 0.0
    usable = [y for y in prices if y <= year]
    p = prices[max(usable)] if usable else prices[min(prices)]
    return p / 12 if opt.premium_period == "ANNUAL" else p


def eligible(opt, age: float, owner: str = "SELF") -> bool:
    if not opt.active or opt.owner not in ("BOTH", owner):
        return False
    if age < (opt.eligibility_min_age or 0):
        return False
    return opt.eligibility_max_age is None or age < opt.eligibility_max_age


def annual_cost(opt, year: int, enrollees: int = 1, drug=None) -> float:
    """Annual premium for one enrollee: PER_HOUSEHOLD prices are split across `enrollees`; a linked drug add-on is included."""
    n = max(enrollees, 1)
    total = 12 * monthly_premium(opt, year) / (n if opt.premium_basis == "PER_HOUSEHOLD" else 1)
    if drug is not None and not opt.includes_drugs:
        total += annual_cost(drug, year, n)
    return total


def compare(options: list, drugs: dict[int, object], ages: dict[str, float], year: int, aca_net: dict[str, float] | None = None) -> list[dict]:
    """One row per person with ACA net (if given) and every active option that person is eligible for."""
    out = []
    for key, age in ages.items():
        medicare = age >= MEDICARE_AGE
        rows = []
        for o in options:
            if o.category == "DRUG" or (o.category in MEDICARE_CATEGORIES) != medicare or not eligible(o, age, key):
                continue
            rows.append({"id": o.id, "name": o.name, "annual": annual_cost(o, year, 1, drugs.get(o.drug_option_id or 0)), "verified": o.verified})
        out.append({"person": key, "age": round(age, 1), "aca_net": (aca_net or {}).get(key), "options": rows})
    return out
