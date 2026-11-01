"""ACA marketplace premium tax credit estimate (IRC §36B). Pure math over data/aca/<year>.json.

Refresh the data file each fall from the IRS Rev. Proc. (applicable percentages), HHS poverty guidelines,
and KFF's benchmark premium survey."""

import itertools
import json
import math
from functools import lru_cache
from pathlib import Path

ACA_DIR = Path(__file__).resolve().parents[1] / "data" / "aca"


@lru_cache(maxsize=1)
def _tables() -> dict[int, dict]:
    return {int(p.stem): json.loads(p.read_text()) for p in sorted(ACA_DIR.glob("*.json"))}


def table_years() -> list[int]:
    return sorted(_tables())


def rules_year(year: int | None = None) -> int:
    """Year of the table used for `year` (nearest known; indexing is never extrapolated)."""
    years = table_years()
    return years[-1] if year is None else min(max(year, years[0]), years[-1])


def _cfg() -> dict:
    return _tables()[rules_year()]


def _rows(key: str) -> list[tuple[float, float, float, float]]:
    return [(lo, math.inf if hi is None else hi, p0, p1) for lo, hi, p0, p1 in _cfg()[key]]


# Module-level names kept for callers and tests; all values come from data/aca/<year>.json (newest year).
_c = _cfg()
RULES_YEAR = _c["year"]
ENHANCED = bool(_c["enhanced"])  # flip in the data file if Congress restores the enhanced credits
FPL_BASE = _c["fpl_base"]
FPL_PER_EXTRA_PERSON = _c["fpl_per_extra_person"]
TABLE_ORIGINAL = _rows("applicable_pct_original")
TABLE_ENHANCED = _rows("applicable_pct_enhanced")
MEDICAID_LIMIT = _c["medicaid_limit_fpl"]
BENCHMARK_40_MONTHLY = _c["benchmark_40_monthly"]
AGE_CURVE = [(a, f) for a, f in _c["age_curve"]]


def retrieved_on() -> str:
    return _cfg()["retrieved_on"]


def fpl(household_size: int) -> float:
    return FPL_BASE + FPL_PER_EXTRA_PERSON * max(household_size - 1, 0)


def age_factor(age: float) -> float:
    if age <= AGE_CURVE[0][0]:
        return AGE_CURVE[0][1]
    for (a0, f0), (a1, f1) in itertools.pairwise(AGE_CURVE):
        if age <= a1:
            return f0 + (f1 - f0) * (age - a0) / (a1 - a0)
    return AGE_CURVE[-1][1]


def benchmark_annual(ages: list[float]) -> float:
    """Estimated benchmark silver premium for the enrolled people (today's dollars, per year)."""
    f40 = age_factor(40)
    return sum(BENCHMARK_40_MONTHLY * age_factor(a) / f40 * 12 for a in ages)


def applicable_pct(fpl_ratio: float) -> float | None:
    """Share of income expected toward the benchmark plan; None = above the cliff (no credit)."""
    for lo, hi, p0, p1 in TABLE_ENHANCED if ENHANCED else TABLE_ORIGINAL:
        if lo <= fpl_ratio < hi:
            return p0 + (p1 - p0) * (fpl_ratio - lo) / (hi - lo) if hi != math.inf else p0
    return None


def cliff_magi(household_size: int) -> float | None:
    return None if ENHANCED else 4.0 * fpl(household_size)


def premium(
    magi: float,
    household_size: int,
    benchmark: float,
    *,
    medicaid_limit: float | None = MEDICAID_LIMIT,
    medicaid_blocked: bool = False,
) -> dict:
    """Net annual premium for the benchmark plan after the premium tax credit.

    `household_size` is the tax household (a married couple is 2 even if one spouse is on Medicare);
    `benchmark` is the annual benchmark premium for the people actually enrolling.
    `medicaid_limit` is the state's adult Medicaid ceiling as a share of FPL (None = state didn't expand).
    `medicaid_blocked`: Medicaid-eligible but not meeting the work/community-engagement rule. Such a person is
    also barred from the credit (§1902(xx)(7)(B)), so they pay full price.
    Without expansion, income below 100% FPL gets no credit either (the coverage gap).
    """
    ratio = magi / fpl(household_size) if household_size > 0 else math.inf
    base = {"fpl_ratio": ratio, "medicaid": False, "over_cliff": False, "coverage_gap": False, "engagement_blocked": False}
    if benchmark <= 0:
        return base | {"benchmark": 0.0, "credit": 0.0, "net": 0.0}
    if medicaid_limit is not None and ratio < medicaid_limit and not ENHANCED:
        if medicaid_blocked:
            return base | {"benchmark": benchmark, "credit": 0.0, "net": benchmark, "engagement_blocked": True}
        return base | {"benchmark": benchmark, "credit": benchmark, "net": 0.0, "medicaid": True}
    if medicaid_limit is None and ratio < 1.0:
        return base | {"benchmark": benchmark, "credit": 0.0, "net": benchmark, "coverage_gap": True}
    pct = applicable_pct(ratio)
    if pct is None:
        return base | {"benchmark": benchmark, "credit": 0.0, "net": benchmark, "over_cliff": True}
    expected = pct * max(magi, 0.0)
    credit = max(benchmark - expected, 0.0)
    return base | {"benchmark": benchmark, "credit": credit, "net": benchmark - credit}


def subsidy_schedule(household_size: int, benchmark: float, *, medicaid_limit: float | None = MEDICAID_LIMIT) -> dict:
    """The credit at every breakpoint of the plan year's schedule, so a planner can see where each extra dollar of MAGI stops being cheap.

    Each point is the premium outcome at that MAGI; `cliff_magi` is None when the enhanced schedule (no cliff) is in force."""
    rows = TABLE_ENHANCED if ENHANCED else TABLE_ORIGINAL
    ratios = sorted({r for lo, hi, _, _ in rows for r in (lo, hi) if r != math.inf} | ({medicaid_limit} if medicaid_limit else set()))
    cliff = cliff_magi(household_size)
    points = []
    for r in ratios:
        magi = r * fpl(household_size)
        res = premium(magi, household_size, benchmark, medicaid_limit=medicaid_limit)
        points.append({"fpl_ratio": r, "magi": magi, "net_premium": res["net"], "credit": res["credit"], "medicaid": res["medicaid"]})
    if cliff is not None:  # one dollar over the cliff
        res = premium(cliff + 1, household_size, benchmark, medicaid_limit=medicaid_limit)
        points.append({"fpl_ratio": cliff / fpl(household_size), "magi": cliff + 1, "net_premium": res["net"], "credit": res["credit"], "medicaid": False})
    return {"rules_year": RULES_YEAR, "enhanced": ENHANCED, "fpl": fpl(household_size), "cliff_magi": cliff, "points": points}


def target_magi(household_size: int, *, margin: float = 0.03) -> float:
    """Highest MAGI to aim for to keep the credit: just under the 400% FPL cliff (or 400% FPL as a soft ceiling when the cliff is repealed)."""
    return 4.0 * fpl(household_size) * (1 - margin)
