"""Model assumptions made visible and editable (P16): defaults with sources, overrides, fee drag, plan health and run-to-run diffs.

Overrides are applied in place to the `quant_engine` constants by `apply()`; with no overrides every value is the documented default, so
results are unchanged. Taxes are not here: rates and brackets come from versioned tables (`services/tax.py`) and the profile."""

from services import quant_engine as qe

CMA = "Project capital-market assumption (services/quant_engine.py); long-run nominal, not a forecast"
CLASSES = list(qe.ASSET_ASSUMPTIONS)
DEFAULT_ASSET = dict(qe.ASSET_ASSUMPTIONS)


def _catalog() -> list[dict]:
    rows = []
    for k, (mu, sd) in DEFAULT_ASSET.items():
        rows.append({"key": f"ret.{k}", "label": f"{k} expected return", "group": "returns", "default": mu, "min": -0.02, "max": 0.20, "source": CMA})
        rows.append({"key": f"vol.{k}", "label": f"{k} volatility", "group": "volatility", "default": sd, "min": 0.0, "max": 0.60, "source": CMA})
    rows += [
        {"key": "inflation", "label": "Inflation", "group": "inflation", "default": 0.025, "min": 0.0, "max": 0.10,
         "source": "Project assumption near the Fed's 2% target plus a margin; compare BLS CPI history"},
        {"key": "corr.equity", "label": "Correlation between equity-like classes", "group": "correlations",
         "default": 0.8, "min": 0.0, "max": 1.0, "source": CMA},
        {"key": "corr.other", "label": "Correlation of equities vs bonds", "group": "correlations", "default": 0.2, "min": -0.5, "max": 1.0, "source": CMA},
        {"key": "fee.expense_ratio", "label": "Average fund expense ratio (fee-drag calculator)", "group": "fees", "default": 0.0010, "min": 0.0, "max": 0.03,
         "source": "Project assumption for index funds; not subtracted from engine returns (see fee_drag)"},
    ]  # fmt: skip
    return rows


CATALOG = _catalog()
BY_KEY = {r["key"]: r for r in CATALOG}


def validate(overrides: dict) -> dict[str, float]:
    out = {}
    for k, v in overrides.items():
        if k not in BY_KEY:
            raise ValueError(f"unknown assumption: {k}")
        if v is None:
            continue
        v = float(v)
        r = BY_KEY[k]
        if not (r["min"] <= v <= r["max"]):
            raise ValueError(f"{k} must be between {r['min']} and {r['max']}")
        out[k] = v
    return out


def effective(overrides: dict[str, float] | None = None) -> dict[str, float]:
    ov = overrides or {}
    return {r["key"]: ov.get(r["key"], r["default"]) for r in CATALOG}


def view(overrides: dict[str, float] | None = None) -> list[dict]:
    ov = overrides or {}
    return [{**r, "value": ov.get(r["key"], r["default"]), "overridden": r["key"] in ov} for r in CATALOG]


def apply(overrides: dict[str, float] | None = None) -> None:
    """Push assumptions into the engine; with None/{} restores the defaults. Idempotent."""
    vals = effective(overrides)
    for k in CLASSES:
        qe.ASSET_ASSUMPTIONS[k] = (vals[f"ret.{k}"], vals[f"vol.{k}"])
    qe.INFLATION = vals["inflation"]
    qe.CORR_EQUITY = vals["corr.equity"]
    qe.CORR_OTHER = vals["corr.other"]


def fee_drag(balance: float, annual_contribution: float, years: int, gross_return: float, fee: float) -> dict:
    """End balance with and without a fee taken from the return each year, and what the fee costs in dollars and percent."""

    def fv(r: float) -> float:
        b = balance
        for _ in range(years):
            b = b * (1 + r) + annual_contribution
        return b

    free, paid = fv(gross_return), fv(gross_return - fee)
    return {"without_fee": free, "with_fee": paid, "cost": free - paid, "cost_pct": (free - paid) / free if free > 0 else 0.0, "fee": fee, "years": years}


def health(metrics: dict, assumptions_changed: int = 0) -> dict:
    """0-100 score from four explained parts; each part states what it measured."""
    success, target = metrics.get("success_rate", 0.0), metrics.get("target_success_rate", 0.85) or 0.85
    bridge = min(metrics.get("bridge_readiness_pct", 0.0), 100.0) / 100
    parts = [
        {"name": "Success vs target", "weight": 55, "score": min(success / target, 1.0), "why": f"{success:.0%} of simulations succeed (target {target:.0%})"},
        {"name": "Bridge funding", "weight": 25, "score": bridge, "why": f"Projected bridge capital covers {bridge:.0%} of what is needed before 59½"},
        {"name": "Spending headroom", "weight": 20, "score": _headroom(metrics), "why": _headroom_why(metrics)},
    ]  # fmt: skip
    total = sum(p["weight"] * p["score"] for p in parts)
    return {
        "score": round(total),
        "grade": "STRONG" if total >= 85 else "OK" if total >= 65 else "WEAK",
        "parts": [{**p, "points": round(p["weight"] * p["score"], 1)} for p in parts],
        "assumptions_changed": assumptions_changed,
    }


def _headroom(m: dict) -> float:
    planned, sustainable = m.get("planned_spend_monthly") or 0.0, m.get("sustainable_spend_monthly")
    if not planned or sustainable is None:
        return 0.5
    return max(min(sustainable / planned, 1.0), 0.0)


def _headroom_why(m: dict) -> str:
    planned, sustainable = m.get("planned_spend_monthly") or 0.0, m.get("sustainable_spend_monthly")
    if not planned or sustainable is None:
        return "No planned retirement spending to compare, so this part is neutral"
    return f"Sustainable spending is {sustainable / planned:.0%} of planned (${sustainable:,.0f} vs ${planned:,.0f} a month)"


METRIC_KEYS = (
    "success_rate",
    "bridge_readiness_pct",
    "sustainable_spend_monthly",
    "earliest_retirement_age",
    "median_final_real",
    "target_success_rate",
    "planned_spend_monthly",
)


def snapshot_metrics(run: dict) -> dict:
    return {k: run.get(k) for k in METRIC_KEYS}


def diff(prev: dict | None, cur: dict) -> dict:
    """Metric changes and assumption changes since a stored snapshot."""
    if not prev:
        return {"has_previous": False, "metrics": [], "assumptions": []}
    metrics = []
    for k in METRIC_KEYS:
        a, b = prev["metrics"].get(k), cur["metrics"].get(k)
        if isinstance(a, int | float) and isinstance(b, int | float) and abs(b - a) > 1e-9:
            metrics.append({"metric": k, "before": a, "after": b, "change": b - a})
    keys = set(prev["assumptions"]) | set(cur["assumptions"])
    ass = [
        {"key": k, "before": prev["assumptions"].get(k), "after": cur["assumptions"].get(k)}
        for k in sorted(keys)
        if prev["assumptions"].get(k) != cur["assumptions"].get(k)
    ]
    return {"has_previous": True, "metrics": metrics, "assumptions": ass}
