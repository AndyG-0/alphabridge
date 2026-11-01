"""Money-market vs. equity deployment signal — fully deterministic."""

from dataclasses import dataclass


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _scale(x, lo, hi):
    """Linear map of x in [lo, hi] -> [0, 100]."""
    return _clamp((x - lo) / (hi - lo) * 100)


@dataclass
class MarketInputs:
    tbill_3m: float  # decimal, e.g. 0.046
    ten_year: float
    cpi_yoy: float
    sp500_pe: float
    vix: float
    sp500_vs_200dma: float  # e.g. -0.08 = 8% below


def deployment_score(m: MarketInputs) -> dict:
    """Score 0-100: higher = stronger case to deploy cash into equities.

    Weights: real risk-free hurdle 30%, equity risk premium 40%, fear/drawdown 30%.
    """
    real_yield = m.tbill_3m - m.cpi_yoy
    erp = 1.0 / m.sp500_pe - m.ten_year
    # High real cash yield -> raises hurdle -> lowers score. Real yield -1%..+3%.
    s_real = 100 - _scale(real_yield, -0.01, 0.03)
    # ERP: -1% (expensive) .. +3% (cheap)
    s_erp = _scale(erp, -0.01, 0.03)
    # Fear: VIX 12..35 (contrarian: higher VIX = better entry), plus drawdown 0..-15% below 200DMA
    s_vix = _scale(m.vix, 12, 35)
    s_dd = _scale(-m.sp500_vs_200dma, -0.05, 0.15)
    s_fear = 0.5 * s_vix + 0.5 * s_dd
    score = 0.30 * s_real + 0.40 * s_erp + 0.30 * s_fear
    return {
        "score": round(score, 1),
        "components": {"real_yield": round(s_real, 1), "erp": round(s_erp, 1), "fear": round(s_fear, 1)},
        "real_yield": real_yield,
        "erp": erp,
    }


def signal_label(score: float) -> str:
    if score >= 70:
        return "AGGRESSIVE_BUY"
    if score >= 45:
        return "DCA"
    return "HOLD_MMF"


def deploy_fraction(score: float) -> float:
    """Share of the investable surplus to deploy this month for a given score (0 under the DCA threshold)."""
    label = signal_label(score)
    frac = {"HOLD_MMF": 0.0, "DCA": 0.25 + 0.25 * (score - 45) / 25, "AGGRESSIVE_BUY": 0.6 + 0.3 * (score - 70) / 30}[label]
    return _clamp(frac * 100, 0, 100) / 100


def recommend(
    cash_total: float,
    monthly_expenses: float,
    emergency_months: float,
    mmf_yield: float,
    market: MarketInputs,
    max_deploy_fraction: float = 1.0,
    high_apr_debt: float = 0.0,
) -> dict:
    """How much cash to keep parked vs. deploy, and in how many tranches."""
    buffer = monthly_expenses * emergency_months
    surplus = max(cash_total - buffer, 0.0)
    pay_down = min(surplus, max(high_apr_debt, 0.0))  # a guaranteed 8%+ return beats any deployment signal
    surplus -= pay_down
    sc = deployment_score(market)
    label = signal_label(sc["score"])
    # Fraction of surplus to deploy this month scales with score; floor by label.
    frac = deploy_fraction(sc["score"]) * max_deploy_fraction
    deploy = round(surplus * frac, 2)
    tranches = {"HOLD_MMF": 0, "DCA": 3, "AGGRESSIVE_BUY": 2}[label] if deploy > 0 else 0
    keep = round(cash_total - deploy, 2)
    annual_interest_forgone = deploy * mmf_yield
    reasons = []
    ry = sc["real_yield"]
    reasons.append(f"Real cash yield is {ry:+.1%} ({'high hurdle for stocks' if ry > 0.015 else 'modest hurdle'}).")
    reasons.append(f"Equity risk premium is {sc['erp']:+.1%} vs 10Y Treasury ({'stocks look rich' if sc['erp'] < 0.005 else 'stocks reasonably priced'}).")
    reasons.append(f"VIX {market.vix:.0f}; S&P 500 is {market.sp500_vs_200dma:+.1%} vs its 200-day average.")
    if pay_down > 0:
        reasons.append(f"${pay_down:,.0f} of surplus cash goes to high-APR debt first.")
    if surplus == 0 and pay_down == 0:
        reasons.append("Cash is at or below your emergency-fund target; nothing is investable.")
    return {
        "signal": label,
        "score": sc["score"],
        "components": sc["components"],
        "cash_total": cash_total,
        "emergency_buffer": buffer,
        "investable_surplus": surplus,
        "pay_down_debt": round(pay_down, 2),
        "keep_in_mmf": keep,
        "deploy_now": deploy,
        "tranches": tranches,
        "tranche_amount": round(deploy / tranches, 2) if tranches else 0.0,
        "mmf_yield": mmf_yield,
        "annual_interest_forgone": round(annual_interest_forgone, 2),
        "reasons": reasons,
    }
