"""Deterministic financial math. No I/O, no LLM — everything here is unit-testable."""

import math
from dataclasses import dataclass

import numpy as np

# Long-run capital-market assumptions (annual, nominal). Overridable per call.
ASSET_ASSUMPTIONS = {
    "US_EQUITY": (0.075, 0.17),
    "INTL_EQUITY": (0.07, 0.19),
    "SECTOR_ETF": (0.08, 0.22),
    "INDIVIDUAL_STOCK": (0.085, 0.30),
    "BOND": (0.04, 0.06),
    "MONEY_MARKET": (0.03, 0.01),
}
INFLATION = 0.025
CORR_EQUITY = 0.8  # between equity-like classes
CORR_OTHER = 0.2  # equity vs bonds


def expected_return_vol(weights: dict[str, float]) -> tuple[float, float]:
    """Blend asset-class assumptions with an assumed 0.8 equity cross-correlation / 0.2 vs bonds."""
    total = sum(weights.values())
    if total <= 0:
        return 0.0, 0.0
    w = {k: v / total for k, v in weights.items()}
    mu = sum(ASSET_ASSUMPTIONS.get(k, (0.06, 0.15))[0] * v for k, v in w.items())
    keys = list(w)
    var = 0.0
    for a in keys:
        for b in keys:
            rho = 1.0 if a == b else (CORR_EQUITY if "EQUITY" in a + b or "STOCK" in a + b or "ETF" in a + b else CORR_OTHER)
            if "MONEY" in a or "MONEY" in b:
                rho = 0.0 if a != b else 1.0
            var += w[a] * w[b] * rho * ASSET_ASSUMPTIONS.get(a, (0, 0.15))[1] * ASSET_ASSUMPTIONS.get(b, (0, 0.15))[1]
    return mu, float(np.sqrt(var))


@dataclass
class FireInputs:
    current_age: float
    retire_age: float
    taxable: float  # taxable brokerage + cash + Roth principal (bridge-eligible)
    pretax: float  # 401(k)/IRA, locked until 59.5 (unless Rule of 55)
    annual_contribution_bridge: float  # to taxable until retirement
    annual_contribution_pretax: float
    retirement_spend: float  # today's dollars / yr, pre-tax need
    tax_rate: float
    mu_taxable: float
    sigma_taxable: float
    mu_pretax: float
    sigma_pretax: float
    end_age: float = 95
    unlock_age: float = 59.5
    rule_of_55: bool = False
    inflation: float = INFLATION
    other_income_after: float = 0.0  # e.g. Social Security (today's $) from 67
    other_income_start: float = 67
    other_income_spouse: float = 0.0  # spouse Social Security (today's $/yr)
    other_income_spouse_start: float = 67  # in the *primary's* age terms (primary age when the spouse turns 67)
    pretax_spouse: float = 0.0  # spouse's 401(k)/IRA, locked until the spouse reaches 59.5
    pretax_other: float = 0.0  # primary plans outside the Rule of 55 (not the current employer's): locked until unlock_age even when rule_of_55
    spouse_unlock_age: float | None = None  # in the *primary's* age terms; None -> unlocks with the primary
    debt_service_by_year: list[float] | None = None  # nominal fixed P&I per simulation year (not inflated); after-tax $
    # per-year household flows (today's $), see services/household.py; None = not used
    extra_spend_by_year: list[float] | None = None  # health, purchases, upkeep, LTC; before retirement drawn from taxable
    income_by_year: list[float] | None = None  # inflows, pensions, a working spouse's pay; before retirement saved
    contrib_bridge_by_year: list[float] | None = None  # when set, replace the flat contribution amounts
    contrib_pretax_by_year: list[float] | None = None
    contrib_pretax_spouse_by_year: list[float] | None = None
    first_year_shock: float = 0.0  # deterministic return (e.g. -0.30) applied to every pool in the first year of retirement; 0 = off
    guardrails: bool = False  # Guyton-Klinger style: trim/raise the base spend when the withdrawal rate drifts 20%


def simulate_fire(inp: FireInputs, n_sims: int = 5000, seed: int | None = 42) -> dict:
    """Annual-step Monte Carlo with lognormal returns and inflation-indexed spending.

    Accumulation until retire_age; then Phase 1 (bridge) draws only from taxable; once the pre-tax
    account unlocks (59.5, or 55 with Rule of 55 when retiring at/after 55) Phase 2 draws from both.
    """
    rng = np.random.default_rng(seed)
    years = int(np.ceil(inp.end_age - inp.current_age))
    unlock = 55.0 if (inp.rule_of_55 and inp.retire_age >= 55) else inp.unlock_age
    tax = np.full(n_sims, max(inp.taxable, 0.0))
    pre = np.full(n_sims, max(inp.pretax, 0.0))
    pre_s = np.full(n_sims, max(inp.pretax_spouse, 0.0))
    pre_o = np.full(n_sims, max(inp.pretax_other, 0.0))
    unlock_s = unlock if inp.spouse_unlock_age is None else inp.spouse_unlock_age
    # the bridge lasts until the first locked pool opens
    first_unlock = min(unlock, unlock_s) if inp.pretax_spouse > 0 else unlock
    alive = np.ones(n_sims, bool)
    bridge_fail = np.zeros(n_sims, bool)
    first_fail_age = np.full(n_sims, np.nan)
    bridge_funded_at_retire = None
    infl_factor = 1.0
    path_median = []
    s_t = np.log1p(inp.mu_taxable) - 0.5 * inp.sigma_taxable**2
    s_p = np.log1p(inp.mu_pretax) - 0.5 * inp.sigma_pretax**2

    def at(vec, y):
        return vec[y] if vec is not None and y < len(vec) else 0.0

    use_contrib_vec = inp.contrib_bridge_by_year is not None
    spend_mult = np.ones(n_sims)  # guardrail adjustment to the base spend, per path
    init_rate = None  # each path's first-year withdrawal rate
    cut_ever = np.zeros(n_sims, bool)
    for y in range(years):
        age = inp.current_age + y
        r_t = np.exp(rng.normal(s_t, inp.sigma_taxable, n_sims)) - 1
        r_p = np.exp(rng.normal(s_p, inp.sigma_pretax, n_sims)) - 1
        if inp.first_year_shock and inp.retire_age <= age < inp.retire_age + 1:  # draws above are still consumed, so the stream is unchanged
            r_t = r_p = np.full(n_sims, inp.first_year_shock)
        tax = tax * (1 + r_t)
        pre = pre * (1 + r_p)
        pre_s = pre_s * (1 + r_p)
        pre_o = pre_o * (1 + r_p)
        if use_contrib_vec:  # each spouse contributes until their own retirement
            tax += at(inp.contrib_bridge_by_year, y) * infl_factor
            pre += at(inp.contrib_pretax_by_year, y) * infl_factor
            pre_s += at(inp.contrib_pretax_spouse_by_year, y) * infl_factor
        if age < inp.retire_age:
            if not use_contrib_vec:
                tax += inp.annual_contribution_bridge * infl_factor
                pre += inp.annual_contribution_pretax * infl_factor
            net_flow = (at(inp.income_by_year, y) - at(inp.extra_spend_by_year, y)) * infl_factor
            if net_flow:
                tax = np.maximum(tax + net_flow, 0.0)
        else:
            if bridge_funded_at_retire is None:
                bridge_funded_at_retire = float(np.median(tax))
            debt = inp.debt_service_by_year[y] if inp.debt_service_by_year and y < len(inp.debt_service_by_year) else 0.0
            base = inp.retirement_spend * infl_factor
            if inp.guardrails:
                wealth = tax + pre + pre_s + pre_o
                rate = np.where(wealth > 0, base * spend_mult / np.maximum(wealth, 1e-9), np.inf)
                if init_rate is None:
                    init_rate = rate.copy()
                else:
                    cut = alive & (rate > init_rate * 1.2)
                    raise_ = alive & (rate < init_rate * 0.8)
                    spend_mult = np.where(cut, np.maximum(spend_mult * 0.9, 0.5), spend_mult)
                    spend_mult = np.where(raise_, np.minimum(spend_mult * 1.1, 1.5), spend_mult)
                    cut_ever |= cut
                base = base * spend_mult
            need = (base + at(inp.extra_spend_by_year, y) * infl_factor + debt) / max(1 - inp.tax_rate, 0.05)
            need = np.maximum(need - at(inp.income_by_year, y) * infl_factor, 0)
            if age >= inp.other_income_start:
                need = np.maximum(need - inp.other_income_after * infl_factor, 0)
            if age >= inp.other_income_spouse_start:
                need = np.maximum(need - inp.other_income_spouse * infl_factor, 0)
            from_tax = np.minimum(tax, need)
            rest = need - from_tax
            from_pre = np.minimum(pre, rest) if age >= unlock else 0.0
            rest = rest - from_pre
            from_pre_o = np.minimum(pre_o, rest) if age >= inp.unlock_age else 0.0
            rest = rest - from_pre_o
            from_pre_s = np.minimum(pre_s, rest) if age >= unlock_s else 0.0
            short = rest - from_pre_s
            tax = tax - from_tax
            pre = pre - from_pre
            pre_o = pre_o - from_pre_o
            pre_s = pre_s - from_pre_s
            failed_now = alive & (short > 1e-6)
            first_fail_age[failed_now] = age
            bridge_fail |= failed_now & (age < first_unlock)
            alive &= ~failed_now
        infl_factor *= 1 + inp.inflation
        path_median.append((age, float(np.median((tax + pre + pre_s + pre_o) / infl_factor))))
    final_real = (tax + pre + pre_s + pre_o) / infl_factor
    return {
        "success_rate": float(alive.mean()),
        "bridge_success_rate": float(1 - bridge_fail.mean()),
        "median_final_real": float(np.median(final_real)),
        "p10_final_real": float(np.percentile(final_real, 10)),
        "p90_final_real": float(np.percentile(final_real, 90)),
        "median_bridge_capital_at_retirement": bridge_funded_at_retire or float(np.median(tax)),
        "median_path_real": path_median,
        "n_sims": n_sims,
        "guardrail_cut_rate": float(cut_ever.mean()) if inp.guardrails else None,
    }


def bridge_capital_needed(
    retire_age: float, annual_spend: float, tax_rate: float, unlock_age: float = 59.5, real_return: float = 0.03, debt_real_by_year: list[float] | None = None
) -> float:
    """PV (retirement-date, today's dollars) of spending from retire_age to unlock_age at a real return.

    `debt_real_by_year[i]` is the after-tax debt service (today's dollars) in the i-th year of retirement.
    """
    years = max(unlock_age - retire_age, 0)
    if years == 0:
        return 0.0
    n = int(np.ceil(years))
    net = max(1 - tax_rate, 0.05)
    debt = list(debt_real_by_year or [])
    flows = [(annual_spend + (debt[i] if i < len(debt) else 0.0)) / net for i in range(n)]
    return float(sum(f / (1 + real_return) ** (i + 1) if abs(real_return) >= 1e-9 else f for i, f in enumerate(flows)))


def earliest_retirement_age(base: FireInputs, target_success: float = 0.85, n_sims: int = 1000, rebuild=None) -> float | None:
    """First whole age at which the plan reaches `target_success`. `rebuild(age)` returns FireInputs for
    that retirement age when the household flows depend on it (health care, contributions, upkeep)."""
    for age in np.arange(max(math.ceil(base.current_age), 35), 70.5, 1.0):
        trial = rebuild(float(age)) if rebuild else FireInputs(**{**base.__dict__, "retire_age": float(age)})
        if simulate_fire(trial, n_sims=n_sims)["success_rate"] >= target_success:
            return float(age)
    return None


def sustainable_spend(inp: FireInputs, target_success: float = 0.85, n_sims: int = 1000, iters: int = 14) -> float:
    """Highest base retirement spend (today's $/yr, after tax, on top of health care, debt and planned
    purchases) that still reaches `target_success`. Same seed each trial, so results move monotonically."""

    def ok(spend):
        return simulate_fire(FireInputs(**{**inp.__dict__, "retirement_spend": spend}), n_sims=n_sims)["success_rate"] >= target_success

    if not ok(0.0):
        return 0.0
    lo, hi = 0.0, max(inp.retirement_spend, 20_000.0)
    while ok(hi) and hi < 5_000_000:
        lo, hi = hi, hi * 2
    for _ in range(iters):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def sharpe_ratio(returns: np.ndarray, rf_annual: float = 0.0, periods: int = 252) -> float:
    r = np.asarray(returns, float)
    r = r[~np.isnan(r)]
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    excess = r - rf_annual / periods
    return float(excess.mean() / r.std(ddof=1) * np.sqrt(periods))


def beta(asset_returns: np.ndarray, market_returns: np.ndarray) -> float:
    a, m = np.asarray(asset_returns, float), np.asarray(market_returns, float)
    n = min(len(a), len(m))
    a, m = a[-n:], m[-n:]
    var = np.var(m, ddof=1)
    return float(np.cov(a, m, ddof=1)[0, 1] / var) if n > 2 and var > 0 else 1.0


def correlation_matrix(returns: dict[str, np.ndarray]) -> dict[str, dict[str, float]]:
    keys = list(returns)
    n = min(len(v) for v in returns.values())
    mat = np.corrcoef(np.vstack([np.asarray(returns[k])[-n:] for k in keys]))
    return {a: {b: float(mat[i, j]) for j, b in enumerate(keys)} for i, a in enumerate(keys)}


def equity_risk_premium(pe_ratio: float, ten_year_yield: float) -> float:
    """Earnings yield minus 10Y Treasury yield (decimals)."""
    return 1.0 / pe_ratio - ten_year_yield


def rsi(prices: np.ndarray, period: int = 14) -> float:
    p = np.asarray(prices, float)
    if len(p) <= period:
        return 50.0
    d = np.diff(p)
    gains, losses = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = gains[:period].mean(), losses[:period].mean()
    for g, ls in zip(gains[period:], losses[period:], strict=True):  # Wilder smoothing
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + ls) / period
    if al == 0:
        return 100.0
    return float(100 - 100 / (1 + ag / al))


def sma_distance(prices: np.ndarray, window: int = 200) -> float | None:
    p = np.asarray(prices, float)
    if len(p) < window:
        return None
    return float(p[-1] / p[-window:].mean() - 1)


def max_drawdown(prices: np.ndarray) -> float:
    p = np.asarray(prices, float)
    peak = np.maximum.accumulate(p)
    return float((p / peak - 1).min())


def simple_dcf(fcf: float, growth: float, discount: float = 0.10, terminal_growth: float = 0.025, years: int = 10, shares: float = 1.0) -> float:
    """Per-share intrinsic value from a two-stage FCF DCF (growth fades linearly to terminal)."""
    if discount <= terminal_growth:
        raise ValueError("discount must exceed terminal growth")
    value, cf = 0.0, fcf
    for t in range(1, years + 1):
        g = growth + (terminal_growth - growth) * (t - 1) / max(years - 1, 1)
        cf *= 1 + g
        value += cf / (1 + discount) ** t
    tv = cf * (1 + terminal_growth) / (discount - terminal_growth) / (1 + discount) ** years
    return (value + tv) / shares


def concentration(exposures: dict[str, float], total: float) -> dict[str, float]:
    return {k: v / total for k, v in exposures.items()} if total > 0 else {}
