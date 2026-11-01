"""Withdrawal-policy library and safe-spend solver (real dollars, vectorised Monte Carlo, seeded).

One pooled portfolio, lognormal real returns shared by every policy so comparisons are paired. Each policy turns the
state (portfolio value, year, household income such as Social Security) into a portfolio draw. `S0` is the initial
total household spending target; the portfolio funds whatever income does not. Success means every year's draw met
that year's spending floor (`floor_frac` x S0, less income) and the portfolio was never exhausted.
"""

from dataclasses import dataclass, field

import numpy as np

POLICIES = ("fixed_real", "pct_portfolio", "guyton_klinger", "ratcheting", "floor_ceiling", "vpw", "bucket")
LABELS = {
    "fixed_real": "Fixed real (4% style)",
    "pct_portfolio": "Percent of portfolio",
    "guyton_klinger": "Guyton-Klinger guardrails",
    "ratcheting": "Ratcheting",
    "floor_ceiling": "Floor and ceiling",
    "vpw": "Variable percentage (VPW)",
    "bucket": "Cash bucket",
}
# lowest share of the target a policy may fall to before the plan counts as failed (flexible policies: half the target)
DEFAULT_FLOOR = {"fixed_real": 1.0, "bucket": 1.0, "ratcheting": 1.0, "guyton_klinger": 0.5, "pct_portfolio": 0.5, "floor_ceiling": 0.85, "vpw": 0.5}


@dataclass
class Setup:
    portfolio: float
    years: int
    mu: float = 0.04  # real arithmetic mean return
    sigma: float = 0.11
    income: list[float] = field(default_factory=list)  # real household income per retirement year (e.g. Social Security)
    n_sims: int = 2000
    seed: int = 42
    # policy parameters
    gk_band: float = 0.20
    gk_step: float = 0.10
    gk_no_cut_last: int = 15
    ratchet_trigger: float = 0.5
    ratchet_step: float = 0.10
    ceiling_frac: float = 1.25
    vpw_rate: float = 0.03
    bucket_years: float = 3.0
    cash_real: float = 0.0


def _income(setup: Setup, t: int) -> float:
    return setup.income[t] if t < len(setup.income) else (setup.income[-1] if setup.income else 0.0)


def real_returns(setup: Setup) -> np.ndarray:
    rng = np.random.default_rng(setup.seed)
    loc = np.log1p(setup.mu) - 0.5 * setup.sigma**2
    return np.exp(rng.normal(loc, setup.sigma, (setup.n_sims, setup.years))) - 1.0


def _pmt_rate(rate: float, n: int) -> float:
    """Share of the portfolio an n-year level real annuity would draw this year."""
    n = max(n, 1)
    return 1.0 / n if abs(rate) < 1e-12 else rate / (1 - (1 + rate) ** -n)


def simulate(policy: str, s0: float, setup: Setup, floor_frac: float | None = None, rets: np.ndarray | None = None) -> dict:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    ff = DEFAULT_FLOOR[policy] if floor_frac is None else floor_frac
    rets = real_returns(setup) if rets is None else rets
    n, yrs = rets.shape
    w = np.full(n, max(setup.portfolio, 0.0))
    d0 = max(s0 - _income(setup, 0), 0.0)
    rate0 = d0 / setup.portfolio if setup.portfolio > 0 else np.inf
    mult = np.ones(n)  # GK / ratchet multiplier on the spending target
    last_raise = w.copy()
    cash = np.minimum(w, setup.bucket_years * d0) if policy == "bucket" else np.zeros(n)
    risky = w - cash if policy == "bucket" else w
    spend = np.zeros((n, yrs))
    ok = np.ones(n, bool)
    for t in range(yrs):
        inc = _income(setup, t)
        if policy == "bucket":
            w = cash + risky
        base = np.maximum(mult * s0 - inc, 0.0)
        if policy == "fixed_real" or policy == "bucket":
            want = np.full(n, max(s0 - inc, 0.0))
        elif policy == "pct_portfolio":
            want = rate0 * w
        elif policy == "guyton_klinger":
            if t > 0:
                rate = np.where(w > 0, base / np.maximum(w, 1e-9), np.inf)
                if yrs - t > setup.gk_no_cut_last:  # the published rule: no cuts in the final 15 years
                    mult = np.where(rate > rate0 * (1 + setup.gk_band), mult * (1 - setup.gk_step), mult)
                mult = np.where(rate < rate0 * (1 - setup.gk_band), mult * (1 + setup.gk_step), mult)
                base = np.maximum(mult * s0 - inc, 0.0)
            want = base
        elif policy == "ratcheting":
            up = w > last_raise * (1 + setup.ratchet_trigger)
            mult = np.where(up, mult * (1 + setup.ratchet_step), mult)
            last_raise = np.where(up, w, last_raise)
            want = np.maximum(mult * s0 - inc, 0.0)
        elif policy == "floor_ceiling":
            want = np.clip(rate0 * w, ff * d0, setup.ceiling_frac * d0)
        else:  # vpw: scale so year 0 spends d0
            k = d0 / (_pmt_rate(setup.vpw_rate, yrs) * setup.portfolio) if setup.portfolio > 0 else 0.0
            want = k * _pmt_rate(setup.vpw_rate, yrs - t) * w
        paid = np.minimum(want, w)
        need_floor = max(ff * s0 - inc, 0.0) if policy != "floor_ceiling" else ff * d0
        ok &= paid >= need_floor - 1e-6
        spend[:, t] = paid + inc
        if policy == "bucket":
            from_cash = np.minimum(cash, paid)
            cash = cash - from_cash
            risky = risky - np.minimum(risky, paid - from_cash)
            risky = risky * (1 + rets[:, t])
            cash = cash * (1 + setup.cash_real)
            refill = np.where(rets[:, t] > 0, np.minimum(risky, np.maximum(setup.bucket_years * d0 - cash, 0.0)), 0.0)
            risky, cash = risky - refill, cash + refill
            w = risky + cash
        else:
            w = (w - paid) * (1 + rets[:, t])
        w = np.maximum(w, 0.0)
    return {"success": ok, "spend": spend, "ending": w}


def summarize(policy: str, s0: float, setup: Setup, floor_frac: float | None = None, rets: np.ndarray | None = None) -> dict:
    sim = simulate(policy, s0, setup, floor_frac, rets)
    sp = sim["spend"]
    pct = np.percentile(sp, [10, 50, 90], axis=0)
    return {
        "policy": policy,
        "label": LABELS[policy],
        "initial_spend": s0,
        "success_rate": float(sim["success"].mean()),
        "floor_frac": DEFAULT_FLOOR[policy] if floor_frac is None else floor_frac,
        "median_ending": float(np.median(sim["ending"])),
        "p10_ending": float(np.percentile(sim["ending"], 10)),
        "avg_spend_median": float(np.median(sp.mean(axis=1))),
        "worst_year_spend_p10": float(np.percentile(sp.min(axis=1), 10)),
        "bands": [{"year": t, "p10": float(pct[0, t]), "p50": float(pct[1, t]), "p90": float(pct[2, t])} for t in range(sp.shape[1])],
    }


def solve_spend(policy: str, setup: Setup, target: float = 0.90, floor_frac: float | None = None, iters: int = 30) -> float:
    """Largest initial spend S0 whose success rate is >= target (same paired returns every trial, so it is monotone)."""
    rets = real_returns(setup)

    def ok(s):
        return simulate(policy, s, setup, floor_frac, rets)["success"].mean() >= target

    lo, hi = 0.0, max(setup.portfolio * 0.05, 1_000.0)
    if not ok(1.0):
        return 0.0
    while ok(hi) and hi < setup.portfolio * 2 + 1e6:
        lo, hi = hi, hi * 2
    for _ in range(iters):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def compare(setup: Setup, targets=(0.90, 0.95), policies=POLICIES, detail: bool = True) -> dict:
    """For each policy: max initial spend at each target success rate and a flex band at the 90% spend level."""
    rets = real_returns(setup)
    rows = []
    for p in policies:
        solved = {f"{int(t * 100)}": solve_spend(p, setup, t) for t in targets}
        anchor = solved[f"{int(targets[0] * 100)}"]
        s = summarize(p, anchor, setup, None, rets)
        if not detail:
            s.pop("bands")
        s["safe_spend"] = solved
        s["safe_rate"] = {k: (v / setup.portfolio if setup.portfolio else 0.0) for k, v in solved.items()}
        rows.append(s)
    return {
        "portfolio": setup.portfolio,
        "years": setup.years,
        "mu": setup.mu,
        "sigma": setup.sigma,
        "n_sims": setup.n_sims,
        "seed": setup.seed,
        "targets": list(targets),
        "policies": rows,
        "note": "Real dollars. Success = the spending floor was met every year. Flexible policies trade a lower worst-year spend for a higher starting spend.",
    }
