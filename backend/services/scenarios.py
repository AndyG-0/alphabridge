"""Scenarios, presets, tornado sensitivity and the reverse solver (P14).

A scenario is a set of profile-field overrides plus an optional first-retirement-year market shock. Everything is run by the existing
Monte Carlo (`planner.run_fire`) with a fixed seed, so differences between scenarios come from the inputs, not sampling noise.
Pure helpers here (no DB): override building, diffing, tornado ranking and the bisection solver over a `success(overrides) -> float` callable."""

from __future__ import annotations

from collections.abc import Callable

# Survivor/benefit assumptions below are project illustrations, not sourced figures; P15 models the survivor properly.
SS_CUT_DEFAULT = 0.77  # share of scheduled Social Security still payable after a trust-fund shortfall (illustrative; verify against the Trustees Report)


def preset_names() -> list[str]:
    return list(PRESETS)


def _retire_at(p, n=None):
    return {"target_retirement_age": float(n if n is not None else p.target_retirement_age + 2)}, 0.0


def _spend(factor):
    return lambda p, n=None: ({"monthly_expenses_retirement": p.monthly_expenses_retirement * (factor if n is None else float(n))}, 0.0)


def _crash(p, n=None):
    return {}, -abs(float(n)) if n is not None else -0.30


def _ss_cut(p, n=None):
    f = float(n) if n is not None else SS_CUT_DEFAULT
    return {"social_security_monthly": p.social_security_monthly * f, "spouse_social_security_monthly": p.spouse_social_security_monthly * f}, 0.0


def _spouse_death(p, n=None):
    # Survivor keeps the larger of the two benefits; the spouse's income and retirement age drop out. A rough stand-in for P15.
    return {
        "spouse_age": 0.0,
        "spouse_annual_income": 0.0,
        "spouse_target_retirement_age": 0.0,
        "spouse_social_security_monthly": 0.0,
        "social_security_monthly": max(p.social_security_monthly, p.spouse_social_security_monthly),
    }, 0.0


def _job_loss(p, n=None):
    return {"target_retirement_age": float(max(p.current_age + (float(n) if n is not None else 0.0), p.current_age))}, 0.0


PRESETS: dict[str, tuple[str, Callable]] = {
    "retire_at": ("Retire at age N (default +2 years)", _retire_at),
    "spend_up_10": ("Retirement spending +10%", _spend(1.10)),
    "spend_down_10": ("Retirement spending -10%", _spend(0.90)),
    "crash_30": ("Market falls 30% in the first retirement year", _crash),
    "ss_cut": ("Social Security cut to 77% of scheduled", _ss_cut),
    "spouse_death": ("Spouse dies before retirement", _spouse_death),
    "job_loss": ("Job loss: stop working in N years (default now)", _job_loss),
}


def presets_public() -> list[dict]:
    return [{"name": k, "label": v[0]} for k, v in PRESETS.items()]


def preset(name: str, profile, n: float | None = None) -> dict:
    if name not in PRESETS:
        raise ValueError(f"unknown preset: {name}")
    label, fn = PRESETS[name]
    overrides, shock = fn(profile, n)
    return {"name": name, "label": label, "overrides": overrides, "shock": shock}


def diff(base: dict, other: dict, keys: tuple[str, ...]) -> dict:
    """Numeric differences other - base for the listed metric keys (None when either side is missing)."""
    return {k: (other[k] - base[k]) if isinstance(other.get(k), (int, float)) and isinstance(base.get(k), (int, float)) else None for k in keys}


def tornado(base_success: float, results: list[dict]) -> list[dict]:
    """Rank inputs by how far success swings. Each result: {input, low_label, high_label, low, high} with success rates."""
    rows = [{**r, "low_delta": r["low"] - base_success, "high_delta": r["high"] - base_success, "swing": abs(r["high"] - r["low"])} for r in results]
    return sorted(rows, key=lambda r: r["swing"], reverse=True)


def bisect(success: Callable[[float], float], lo: float, hi: float, target: float, increasing: bool, iters: int = 12) -> float | None:
    """Value in [lo, hi] where `success` crosses `target`. `increasing`: success rises with the value (savings); else it falls (spend).
    Returns the best feasible end (hi for spend, lo for savings) and None when even the easiest end misses the target."""
    easy, hard = (hi, lo) if increasing else (lo, hi)
    if success(easy) < target:
        return None
    if success(hard) >= target:
        return hard
    a, b = easy, hard  # a satisfies the target, b does not
    for _ in range(iters):
        m = (a + b) / 2
        a, b = (m, b) if success(m) >= target else (a, m)
    return a
