"""Research rigor and cost control: DCF sensitivity, insider/13F signals, narrative-number verification, report cache keys,
token budgets, and watchlist / thesis-invalidation checks. Deterministic; the LLM only narrates. Rules: data/research_rules.json."""

import hashlib
import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from services import quant_engine as qe

RULES_FILE = Path(__file__).resolve().parents[1] / "data" / "research_rules.json"


@lru_cache(maxsize=1)
def rules() -> dict:
    return json.loads(RULES_FILE.read_text())


# ---- DCF sensitivity ------------------------------------------------------------------------------------------------
def dcf_sensitivity(fcf: float | None, shares: float | None, growth: float | None, price: float | None, discount: float = 0.10) -> dict | None:
    if not fcf or fcf <= 0 or not shares or growth is None:
        return None
    r = rules()["dcf"]
    g = min(max(growth, 0.0), 0.30)
    out = qe.dcf_grid(fcf, g, discount, r["growth_steps"], r["discount_steps"], r["terminal_growth"], r["years"], shares)
    out["price"] = price
    out["base_upside"] = (out["base"] / price - 1) if out["base"] and price else None
    out["share_of_cells_above_price"] = (
        sum(1 for row in out["rows"] for v in row["values"] if v is not None and price and v > price)
        / max(sum(1 for row in out["rows"] for v in row["values"] if v is not None), 1)
        if price
        else None
    )
    return out


# ---- Insider (Form 4) and institutional (13F) signals ---------------------------------------------------------------
def insider_signal(trades: list[dict], today: date | None = None) -> dict:
    """trades: [{date: iso, insider, code, shares, price}]. Only open-market buys (P) and sells (S) inside the window count."""
    r = rules()["insider"]
    today = today or date.today()
    cutoff = (today - timedelta(days=r["window_days"])).isoformat()
    buys = sells = 0.0
    buyers: set[str] = set()
    sellers: set[str] = set()
    for t in trades:
        kind = r["open_market_codes"].get(str(t.get("code", "")).upper())
        if kind is None or not (cutoff <= str(t.get("date", "")) <= today.isoformat()):
            continue
        value = float(t.get("shares") or 0) * float(t.get("price") or 0)
        if kind == "buy":
            buys += value
            buyers.add(str(t.get("insider", "?")))
        else:
            sells += value
            sellers.add(str(t.get("insider", "?")))
    net = buys - sells
    label = "BUYING" if net >= r["min_net_value"] else "SELLING" if net <= -r["min_net_value"] else "NEUTRAL"
    return {
        "window_days": r["window_days"],
        "buy_value": round(buys, 2),
        "sell_value": round(sells, 2),
        "net_value": round(net, 2),
        "buyers": len(buyers),
        "sellers": len(sellers),
        "signal": label,
        "note": r["note"],
    }


def institutional_signal(current: dict[str, float], prior: dict[str, float]) -> dict:
    """Per tracked manager {name: shares} this quarter vs. last."""
    thr = rules()["institutional"]["min_change_pct"]
    rows = []
    for name in sorted(set(current) | set(prior)):
        c, p = current.get(name, 0.0), prior.get(name, 0.0)
        change = (c - p) / p if p else (1.0 if c else 0.0)
        action = "NEW" if p == 0 and c > 0 else "EXITED" if c == 0 and p > 0 else "ADDED" if change >= thr else "TRIMMED" if change <= -thr else "HELD"
        rows.append({"manager": name, "shares": c, "prior_shares": p, "change_pct": change, "action": action})
    return {"managers": rows, "tracked": len(rows), "note": rules()["institutional"]["note"]}


# ---- Narrative number verification ----------------------------------------------------------------------------------
_NUM = re.compile(r"(?<![\w.])\$?\(?-?\d[\d,]*(?:\.\d+)?\)?\s*(%|[KMBT]\b|thousand|million|billion|trillion)?", re.IGNORECASE)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9, "t": 1e12, "trillion": 1e12}


def _numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_numbers_in(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_numbers_in(v))
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):
            v = _parse(m)
            if v is not None:
                out.append(v[0])
    return out


def _parse(m: re.Match) -> tuple[float, int, bool] | None:
    """(value, decimals shown, is_percent) for one regex match."""
    raw = re.sub(r"[\s$()%,]", "", m.group(0)).rstrip("KMBTkmbt")
    raw = re.sub(r"(thousand|million|billion|trillion)$", "", raw, flags=re.IGNORECASE)
    try:
        val = float(raw)
    except ValueError:
        return None
    suffix = (m.group(1) or "").lower()
    dec = len(raw.split(".")[1]) if "." in raw else 0
    if suffix == "%":
        return val, dec, True
    return val * _SCALE.get(suffix, 1.0), dec, False


def _supported(val: float, dec: int, pct: bool, pool: list[float], tol: float) -> bool:
    candidates = [val / 100.0] if pct else []
    candidates.append(val)
    # half a unit of the last displayed digit is the rounding the writer may have applied
    for c in candidates:
        half = 0.5 * 10 ** (-dec) * (0.01 if (pct and c == val / 100.0) else 1.0)
        for p in pool:
            if abs(c - p) <= max(half, abs(p) * tol, 1e-9):
                return True
    return False


def verify_narrative_numbers(text: str, payload: Any) -> list[str]:
    """Numbers in `text` that don't appear (within rounding) in the input `payload`. Years and small unlabelled integers are ignored."""
    cfg = rules()["narrative"]
    pool = _numbers_in(payload)
    pool += [p * 100 for p in pool if abs(p) <= 5]  # fractions the writer may have shown as percents
    bad: list[str] = []
    for m in _NUM.finditer(text or ""):
        parsed = _parse(m)
        if parsed is None:
            continue
        val, dec, is_pct = parsed
        shown = m.group(0).strip()
        if not is_pct and dec == 0 and abs(val) < cfg["ignore_integers_below"]:
            continue
        if not is_pct and dec == 0 and 1900 <= abs(val) <= 2100 and "," not in shown and "$" not in shown:
            continue
        if not _supported(val, dec, is_pct, pool, cfg["relative_tolerance"]) and shown not in bad:
            bad.append(shown)
    return bad


# ---- Cache key and token budget -------------------------------------------------------------------------------------
def input_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def est_tokens(text: str) -> int:
    return -(-len(text) // rules()["budget"]["chars_per_token"])


class BudgetExceeded(RuntimeError):
    pass


class TokenBudget:
    """Shared by every deep dive in one run. limit <= 0 means unlimited."""

    def __init__(self, limit: int = 0):
        self.limit = limit
        self.used = 0

    def remaining(self) -> int | None:
        return None if self.limit <= 0 else max(self.limit - self.used, 0)

    def spend(self, n: int) -> None:
        if self.limit > 0 and self.used + n > self.limit:
            raise BudgetExceeded(f"token budget {self.limit} exhausted ({self.used} used, {n} requested)")
        self.used += n


def fit_to_budget(
    payload: dict, budget_tokens: int | None, trim_keys: tuple[str, ...] = ("risk_factors_excerpt", "mdna_excerpt", "financial_statements")
) -> tuple[dict, bool]:
    """Trim only the long text excerpts so the serialized payload fits; computed metrics are never cut."""
    if not budget_tokens or est_tokens(json.dumps(payload, default=str)) <= budget_tokens:
        return payload, False
    out = dict(payload)
    over = (est_tokens(json.dumps(out, default=str)) - budget_tokens) * rules()["budget"]["chars_per_token"]
    for k in sorted(trim_keys, key=lambda k: -len(str(out.get(k, "")))):
        if over <= 0:
            break
        cur = str(out.get(k, "") or "")
        cut = min(over, max(len(cur) - 200, 0))
        if cut > 0:
            out[k] = cur[: len(cur) - cut]
            over -= cut
    return out, True


# ---- Watchlist and thesis invalidation ------------------------------------------------------------------------------
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}


def check_criteria(criteria: list[dict], values: dict) -> list[dict]:
    """criteria: [{metric, op, value, text}] -> each with `current` and `triggered` (None when the metric is unavailable)."""
    out = []
    for c in criteria:
        cur = values.get(c.get("metric"))
        op = OPS.get(c.get("op", ""))
        triggered = None if cur is None or op is None else bool(op(float(cur), float(c["value"])))
        out.append({**c, "current": cur, "triggered": triggered})
    return out


def watch_alerts(item: dict, price: float | None, dcf_value: float | None, default_upside: float) -> list[str]:
    """Valuation alerts for a watchlist row {buy_below, upside_alert}."""
    msgs: list[str] = []
    if price is None:
        return msgs
    bb = item.get("buy_below")
    if bb and price <= bb:
        msgs.append(f"{item['symbol']} is at {price:,.2f}, at or below your buy-below {bb:,.2f}")
    thr = item.get("upside_alert") or default_upside
    if dcf_value and price > 0 and dcf_value / price - 1 >= thr:
        msgs.append(f"{item['symbol']} trades {dcf_value / price - 1:.0%} under its base DCF value ({dcf_value:,.2f})")
    return msgs
