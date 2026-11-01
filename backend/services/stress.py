"""Sequence-of-returns stress tests on top of the withdrawal-policy simulator (real dollars).

Every method is labelled in its output. Historical data: data/historical_returns.json (Damodaran / NYU Stern, 1928-2025).
"""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

from services import withdrawal_strategies as ws

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "historical_returns.json"
DEFAULT_STARTS = (1929, 1966, 1973, 2000, 2008)
METHODS = {
    "historical": "Replays the actual calendar-year returns from a start year (annual rebalancing). One path per start year.",
    "rolling": (
        "Every historical start year with a full horizon; the share of those paths that succeed. "
        "Overlapping windows, so far fewer independent samples than the count suggests."
    ),
    "bootstrap": "Moving-block bootstrap of historical real returns (blocks keep short-run momentum and crashes together).",
    "fat_tail": "Student-t (4 d.f.) annual returns with the same mean and volatility as the plain model: same average, more extreme years.",
    "regime": "Two-state Markov regime model (calm / crisis) with illustrative parameters, not fitted to data.",
}


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA_FILE.read_text())


def retrieved_on() -> date:
    return date.fromisoformat(_data()["retrieved_on"])


def real_series(equity: float = 0.6) -> tuple[list[int], np.ndarray]:
    """Annually rebalanced stock/10-yr-bond mix, deflated by CPI. Returns (years, real returns)."""
    d = _data()["years"]
    yrs = sorted(int(y) for y in d)
    r = np.array([(1 + equity * d[str(y)]["stocks"] + (1 - equity) * d[str(y)]["bonds"]) / (1 + d[str(y)]["inflation"]) - 1 for y in yrs])
    return yrs, r


def _run(policy: str, s0: float, setup: ws.Setup, rets: np.ndarray, floor_frac: float | None = None) -> dict:
    return ws.simulate(policy, s0, setup, floor_frac, rets)


def historical(setup: ws.Setup, s0: float, equity: float = 0.6, starts=DEFAULT_STARTS, policy: str = "fixed_real") -> list[dict]:
    yrs, r = real_series(equity)
    out = []
    for st in starts:
        if st not in yrs:
            continue
        i = yrs.index(st)
        path = r[i : i + setup.years]
        complete = len(path) == setup.years
        if len(path) == 0:
            continue
        sub = ws.Setup(**{**setup.__dict__, "years": len(path), "n_sims": 1})
        sim = _run(policy, s0, sub, path[None, :])
        bal = _balance_path(policy, s0, sub, path)
        out.append(
            {
                "start_year": st,
                "complete": complete,
                "years_covered": len(path),
                "success": bool(sim["success"][0]) and complete,
                "ending_real": float(sim["ending"][0]),
                "lowest_balance_real": float(bal.min()),
                "first_5yr_annualized_real": float(np.prod(1 + path[:5]) ** (1 / min(5, len(path))) - 1),
            }
        )
    return out


def _balance_path(policy: str, s0: float, setup: ws.Setup, path: np.ndarray) -> np.ndarray:
    """Portfolio value after each year for a single path (fixed-real style draws; used for the 'lowest balance' column)."""
    w = setup.portfolio
    out = []
    for t, r in enumerate(path):
        inc = setup.income[t] if t < len(setup.income) else (setup.income[-1] if setup.income else 0.0)
        w = max((w - min(max(s0 - inc, 0.0), w)) * (1 + r), 0.0)
        out.append(w)
    return np.array(out)


def rolling(setup: ws.Setup, s0: float, equity: float = 0.6, policy: str = "fixed_real") -> dict:
    yrs, r = real_series(equity)
    n = len(r) - setup.years + 1
    if n <= 0:
        return {"windows": 0, "success_rate": None}
    paths = np.array([r[i : i + setup.years] for i in range(n)])
    sub = ws.Setup(**{**setup.__dict__, "n_sims": n})
    sim = _run(policy, s0, sub, paths)
    worst = int(np.argmin(sim["ending"] + sim["success"] * 1e18))
    return {"windows": n, "success_rate": float(sim["success"].mean()), "first_start": yrs[0], "last_start": yrs[n - 1], "worst_start": yrs[worst]}


def bootstrap_paths(setup: ws.Setup, equity: float = 0.6, block: int = 5) -> np.ndarray:
    _, r = real_series(equity)
    rng = np.random.default_rng(setup.seed)
    n, yrs = setup.n_sims, setup.years
    nb = -(-yrs // block)
    starts = rng.integers(0, len(r), (n, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % len(r)  # wraps around the end of the sample
    return r[idx.reshape(n, -1)[:, :yrs]]


def fat_tail_paths(setup: ws.Setup, df: float = 4.0) -> np.ndarray:
    rng = np.random.default_rng(setup.seed)
    t = rng.standard_t(df, (setup.n_sims, setup.years)) * np.sqrt((df - 2) / df)  # unit variance
    return np.maximum(setup.mu + setup.sigma * t, -0.95)


def regime_paths(setup: ws.Setup, calm=(0.06, 0.10), crisis=(-0.12, 0.24), p_stay=(0.93, 0.60)) -> np.ndarray:
    rng = np.random.default_rng(setup.seed)
    n, yrs = setup.n_sims, setup.years
    state = np.zeros(n, int)
    out = np.empty((n, yrs))
    mus, sig = np.array([calm[0], crisis[0]]), np.array([calm[1], crisis[1]])
    stay = np.array(p_stay)
    for t in range(yrs):
        out[:, t] = np.maximum(mus[state] + sig[state] * rng.standard_normal(n), -0.95)
        flip = rng.random(n) > stay[state]
        state = np.where(flip, 1 - state, state)
    return out


def success_by_first5(paths: np.ndarray, success: np.ndarray, buckets: int = 5) -> list[dict]:
    """Success rate within quantile buckets of each path's annualised first-five-year return."""
    k = min(5, paths.shape[1])
    ann = np.prod(1 + paths[:, :k], axis=1) ** (1 / k) - 1
    edges = np.quantile(ann, np.linspace(0, 1, buckets + 1))
    rows = []
    for b in range(buckets):
        m = (ann >= edges[b]) & ((ann <= edges[b + 1]) if b == buckets - 1 else (ann < edges[b + 1]))
        rows.append(
            {
                "bucket": b + 1,
                "first5_lo": float(edges[b]),
                "first5_hi": float(edges[b + 1]),
                "n": int(m.sum()),
                "success_rate": float(success[m].mean()) if m.any() else None,
            }
        )
    return rows


def run_methods(setup: ws.Setup, s0: float, equity: float = 0.6, policy: str = "fixed_real", block: int = 5) -> list[dict]:
    gens = {"bootstrap": bootstrap_paths(setup, equity, block), "fat_tail": fat_tail_paths(setup), "regime": regime_paths(setup)}
    res = []
    for name, paths in gens.items():
        sim = _run(policy, s0, setup, paths)
        res.append(
            {
                "method": name,
                "description": METHODS[name],
                "success_rate": float(sim["success"].mean()),
                "p10_ending": float(np.percentile(sim["ending"], 10)),
                "median_ending": float(np.median(sim["ending"])),
                "by_first5": success_by_first5(paths, sim["success"]),
            }
        )
    return res


def bucket_test(setup: ws.Setup, s0: float, equity: float = 0.6, block: int = 5) -> dict:
    """Same bootstrap paths, plain fixed-real draws versus a cash bucket that is spent first and refilled only after up years."""
    paths = bootstrap_paths(setup, equity, block)
    plain = _run("fixed_real", s0, setup, paths)
    buck = _run("bucket", s0, setup, paths)
    return {
        "method": "bootstrap",
        "bucket_years": setup.bucket_years,
        "plain": {"success_rate": float(plain["success"].mean()), "by_first5": success_by_first5(paths, plain["success"])},
        "bucket": {"success_rate": float(buck["success"].mean()), "by_first5": success_by_first5(paths, buck["success"])},
        "improvement": float(buck["success"].mean() - plain["success"].mean()),
    }


def stress(setup: ws.Setup, s0: float, equity: float = 0.6, policy: str = "fixed_real", starts=DEFAULT_STARTS) -> dict:
    d = _data()
    return {
        "inputs": {
            "portfolio": setup.portfolio,
            "initial_spend": s0,
            "years": setup.years,
            "equity_weight": equity,
            "policy": policy,
            "n_sims": setup.n_sims,
            "seed": setup.seed,
        },
        "data": {"source_url": d["source_url"], "retrieved_on": d["retrieved_on"], "first_year": d["first_year"], "last_year": d["last_year"]},
        "methods": METHODS,
        "historical": historical(setup, s0, equity, starts, policy),
        "rolling": rolling(setup, s0, equity, policy),
        "simulated": run_methods(setup, s0, equity, policy),
        "bucket": bucket_test(setup, s0, equity),
        "note": (
            "Real dollars. Historical stock/bond returns are index returns before fees and taxes; "
            "the past is not a forecast, and the 20th-century US sample is one favourable history."
        ),
    }
