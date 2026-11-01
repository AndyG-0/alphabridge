"""Net-worth history: time series, asset/liability breakdown, milestones and monthly plan-vs-actual drift. Pure Python, no I/O beyond the DB read."""

from datetime import datetime

from models import Holding, NetWorthSnapshot
from services import quant_engine as qe

MILESTONES = (10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 750_000, 1_000_000, 1_500_000, 2_000_000, 3_000_000, 5_000_000, 10_000_000)


def snapshot_dict(r: NetWorthSnapshot) -> dict:
    return {
        "taken_at": r.taken_at.isoformat(),
        "total": r.total,
        "safe_core": r.safe_core,
        "satellite": r.satellite,
        "dry_powder": r.dry_powder,
        "liabilities": r.liabilities,
        "breakdown": r.breakdown or {},
    }


def history(s, limit: int | None = None) -> list[dict]:
    q = s.query(NetWorthSnapshot).order_by(NetWorthSnapshot.taken_at.desc())
    if limit:
        q = q.limit(limit)
    return [snapshot_dict(r) for r in q.all()][::-1]


def milestones(series: list[dict], fi_number: float | None = None) -> dict:
    """Date each round-number (and the FI number) was first reached, plus the next one still ahead. `series` is oldest-first."""
    fi_level = round(fi_number) if fi_number and fi_number > 0 else None
    levels = sorted({*MILESTONES, *([fi_level] if fi_level else [])})
    reached, nxt = [], None
    peak = max((r["total"] for r in series), default=0.0)
    for lv in levels:
        hit = next((r for r in series if r["total"] >= lv), None)
        if hit:
            reached.append({"level": lv, "reached_on": hit["taken_at"][:10], "is_fi": lv == fi_level})
        elif nxt is None:
            nxt = {"level": lv, "remaining": lv - peak, "is_fi": lv == fi_level}
    return {"reached": reached, "next": nxt}


def project_balance(start: float, months: int, annual_return: float, monthly_contribution: float) -> float:
    """Balance after `months` of monthly compounding with end-of-month contributions."""
    if months <= 0:
        return start
    g = annual_return / 12
    if abs(g) < 1e-12:
        return start + monthly_contribution * months
    f = (1 + g) ** months
    return start * f + monthly_contribution * (f - 1) / g


def monthly_drift(series: list[dict], annual_return: float, monthly_contribution: float) -> list[dict]:
    """Per calendar month: last actual net worth vs a projection from the first snapshot at the plan's return and savings rate."""
    if not series:
        return []
    first = series[0]
    t0 = datetime.fromisoformat(first["taken_at"])
    by_month: dict[tuple[int, int], dict] = {}
    for r in series:
        d = datetime.fromisoformat(r["taken_at"])
        by_month[(d.year, d.month)] = r  # series is oldest-first, so the last one in a month wins
    out = []
    for (y, m), r in sorted(by_month.items()):
        k = (y - t0.year) * 12 + (m - t0.month)
        planned = project_balance(first["total"], k, annual_return, monthly_contribution)
        out.append(
            {
                "month": f"{y:04d}-{m:02d}",
                "actual": r["total"],
                "planned": planned,
                "drift": r["total"] - planned,
                "drift_pct": (r["total"] - planned) / planned if planned else None,
            }
        )
    return out


def plan_return(s) -> float:
    """Expected annual return of the current holdings mix (same capital-market assumptions the planner uses)."""
    w: dict[str, float] = {}
    for h in s.query(Holding).all():
        w[h.asset_class] = w.get(h.asset_class, 0.0) + h.market_value
    return qe.expected_return_vol(w)[0] if w else 0.0


def fi_number(profile) -> float | None:
    """Financial-independence target: 25x annual retirement spending (the 4% rule), a milestone marker only, not a plan input."""
    spend = (profile.monthly_expenses_retirement or 0) * 12
    return spend * 25 if spend > 0 else None


def summary(s, profile) -> dict:
    series = history(s)
    r = plan_return(s)
    fi = fi_number(profile)
    return {
        "series": series,
        "latest": series[-1] if series else None,
        "milestones": milestones(series, fi),
        "drift": monthly_drift(series, r, profile.monthly_contribution or 0.0),
        "assumptions": {
            "annual_return": r,
            "monthly_contribution": profile.monthly_contribution or 0.0,
            "baseline": series[0]["taken_at"][:10] if series else None,
        },
    }
