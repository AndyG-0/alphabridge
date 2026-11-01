"""Action center: a prioritized to-do feed computed from live data.

Every generator is a pure function of already-computed engine output (so it is unit-testable) and returns dicts with a stable `key`.
Thresholds and the year-end checklist live in data/action_rules.json. User state (snooze/done) and notification dedupe are stored on
`ActionItem` rows keyed by `key`; keys carry a period suffix so a finished item can legitimately come back next month or next year."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from models import Account, ActionItem, IngestionLog, UserProfile
from services import rebalance, tax_lots
from services import rmd as rmd_svc
from services import savings as sav_svc

log = logging.getLogger("alphabridge.actions")
_RULES = Path(__file__).resolve().parents[1] / "data" / "action_rules.json"


def rules() -> dict[str, Any]:
    return json.loads(_RULES.read_text())


def _score(kind: str, dollars: float = 0.0, urgency: float = 0.0) -> float:
    """0-100: a base weight per kind, plus up to 20 for the dollars at stake and up to 20 for urgency (0-1)."""
    return round(min(100.0, rules()["base_priority"][kind] + min(dollars / 1000.0, 20.0) + 20.0 * max(min(urgency, 1.0), 0.0)), 1)


def _item(kind: str, key: str, title: str, detail: str, priority: float, where: str, dollars: float | None = None) -> dict[str, Any]:
    return {"key": key, "kind": kind, "title": title, "detail": detail, "priority": priority, "where": where, "dollars": dollars}


def match_capture_items(profile: UserProfile, today: date) -> list[dict[str, Any]]:
    rate, cap = float(profile.employer_match_rate or 0), float(profile.employer_match_cap_pct or 0)
    salary = float(profile.annual_income or 0)
    if rate <= 0 or cap <= 0 or salary <= 0:
        return []
    deferral = float(profile.monthly_contribution or 0) * 12  # the savings waterfall funds the 401(k) match first
    m = sav_svc.match_capture(salary, deferral, rate, cap)
    if m["fully_captured"]:
        return []
    pct = m["deferral_to_capture_all"] / salary
    left = m["left_on_table"]
    return [
        _item(
            "match",
            f"match:{today.year}",
            "Capture your full employer match",
            f"You are leaving about ${left:,.0f} a year of match unclaimed. Defer at least {pct:.0%} of pay "
            f"(${m['deferral_to_capture_all']:,.0f}/yr) to get all ${m['max_match']:,.0f}.",
            _score("match", left, 0.5),
            "/plan",
            left,
        )
    ]


def roth_items(roth: dict[str, Any], today: date) -> list[dict[str, Any]]:
    best = next((p for p in roth.get("plans", []) if p["strategy"] == roth.get("best")), None)
    if not best or not best.get("total_converted"):
        return []
    first = next((y for y in best.get("years") or [] if y.get("conversion", 0) > 1), None)
    if not first or first["year"] > today.year + int(rules()["roth_lead_years"]):
        return []
    return [
        _item(
            "roth",
            f"roth:{first['year']}",
            f"Convert about ${first['conversion']:,.0f} to Roth in {first['year']}",
            f"The best Roth plan ({best['label']}) starts converting at age {first['age']}, adding about ${first['conversion_tax']:,.0f} of tax now "
            f"and lowering lifetime cost by ${max(best['vs_none']['lifetime_cost'] - best['lifetime_cost'], 0):,.0f} versus no conversions.",
            _score("roth", max(best["vs_none"]["lifetime_cost"] - best["lifetime_cost"], 0), 1.0 if first["year"] <= today.year else 0.3),
            "/plan",
            first["conversion"],
        )
    ]


def rebalance_items(rb: dict[str, Any], today: date) -> list[dict[str, Any]]:
    d = rb.get("drift")
    if not d or not d.get("breached"):
        return []
    rows = [r for r in d["rows"] if r["breach"]]
    moves = sum(abs(t.get("dollars", 0)) for t in rb.get("trades", []))
    names = ", ".join(f"{r['asset_class'].replace('_', ' ').lower()} {r['current']:.0%} vs {r['target']:.0%}" for r in rows[:3])
    return [
        _item(
            "rebalance",
            f"rebalance:{today:%Y-%m}",
            "Rebalance back to your target allocation",
            f"{names}. About {d['total_drift']:.0%} of the portfolio would move; estimated tax on the trades ${rb.get('est_tax', 0):,.0f}.",
            _score("rebalance", moves, min(d["total_drift"] * 5, 1.0)),
            "/portfolio",
            moves or None,
        )
    ]


def harvest_items(lots: dict[str, Any], today: date) -> list[dict[str, Any]]:
    h = lots.get("harvest")
    if not h or h.get("total_est_savings", 0) < rules()["harvest_min_savings"] or not h.get("candidates"):
        return []
    return [
        _item(
            "harvest",
            f"harvest:{today:%Y-%m}",
            f"Harvest ${h['total_loss']:,.0f} of tax losses",
            f"{len(h['candidates'])} lots are below cost, saving roughly ${h['total_est_savings']:,.0f} of federal tax. "
            "Check the wash-sale warnings before selling.",
            _score("harvest", h["total_est_savings"], 0.6 if today.month >= 10 else 0.2),
            "/portfolio",
            h["total_est_savings"],
        )
    ]


def stale_statement_items(s: Session, today: date) -> list[dict[str, Any]]:
    limit = int(rules()["stale_statement_days"])
    out = []
    for a in s.query(Account).all():
        if not any(h.market_value > 0 for h in a.holdings):
            continue
        last = (
            s.query(IngestionLog)
            .filter(IngestionLog.account_id == a.id, IngestionLog.status == "OK", IngestionLog.undone_at.is_(None))
            .order_by(IngestionLog.created_at.desc())
            .first()
        )
        if last is None:
            continue  # never imported (manual or synced accounts): nothing to be stale against
        age = (today - last.created_at.date()).days
        if age > limit:
            out.append(
                _item(
                    "stale",
                    f"stale:{a.id}:{today:%Y-%m}",
                    f"Refresh {a.name}",
                    f"The last import was {age} days ago, so balances and drift may be out of date. Download a fresh export and drop it on the Portfolio page.",
                    _score("stale", 0, min(age / 90, 1.0)),
                    "/portfolio",
                )
            )
    return out


def year_end_items(s: Session, profile: UserProfile, today: date) -> list[dict[str, Any]]:
    cfg = rules()["year_end"]
    if today.month < cfg["start_month"]:
        return []
    birth = profile.birth_date
    at_rmd = today.year - birth.year >= rmd_svc.start_age(birth.year)
    has_taxable = any(a.tax_bucket == "TAXABLE_BROKERAGE" for a in s.query(Account).all())
    days = (date(today.year, 12, 31) - today).days
    out = []
    for it in cfg["items"]:
        if it["applies"] == "rmd_age" and not at_rmd:
            continue
        if it["applies"] == "taxable" and not has_taxable:
            continue
        out.append(
            _item(
                "year_end",
                f"year_end:{today.year}:{it['id']}",
                it["title"],
                f"{it['detail']} ({days} days left in {today.year}.)",
                _score("year_end", 0, 1 - days / 92),
                "/plan",
            )
        )
    return out


def generate(s: Session, profile: UserProfile, today: date | None = None, *, roth: dict | None = None) -> list[dict[str, Any]]:
    """Every action that applies right now, highest priority first, before the user's snooze/done state is applied."""
    from services import planner  # local: planner pulls in the whole simulation stack

    today = today or date.today()
    items = match_capture_items(profile, today)
    try:
        roth = roth if roth is not None else planner.roth_plan(profile, detail=True)
        items += roth_items(roth, today)
    except Exception:  # a failure in one engine must not hide the other actions
        log.exception("roth action generator failed")
    items += rebalance_items(rebalance.report(s, profile), today)
    items += harvest_items(tax_lots.report(s, profile, today), today)
    items += stale_statement_items(s, today)
    items += year_end_items(s, profile, today)
    return sorted(items, key=lambda i: -i["priority"])


def _state(s: Session, profile: UserProfile) -> dict[str, ActionItem]:
    return {r.key: r for r in s.query(ActionItem).filter(ActionItem.user_id == profile.id).all()}


def feed(s: Session, profile: UserProfile, today: date | None = None, *, include_hidden: bool = False, items: list[dict] | None = None) -> dict[str, Any]:
    """Generated actions merged with the user's snooze/done state. Hidden (snoozed or done) items are returned only on request."""
    today = today or date.today()
    gen = items if items is not None else generate(s, profile, today)
    state = _state(s, profile)
    out, hidden = [], 0
    for it in gen:
        row = state.get(it["key"])
        status = "open"
        if row and row.status == "done":
            status = "done"
        elif row and row.status == "snoozed" and row.snooze_until and row.snooze_until > today:
            status = "snoozed"
        if status != "open":
            hidden += 1
            if not include_hidden:
                continue
        out.append({**it, "status": status, "snooze_until": row.snooze_until.isoformat() if row and status == "snoozed" and row.snooze_until else None})
    threshold = rules()["notify_priority"]
    return {"items": out, "hidden": hidden, "high_priority": sum(1 for i in out if i["status"] == "open" and i["priority"] >= threshold)}


def mark(s: Session, profile: UserProfile, key: str, status: str, days: int = 7, today: date | None = None) -> ActionItem:
    if status not in ("open", "snoozed", "done"):
        raise ValueError(f"bad status {status}")
    today = today or date.today()
    row = s.query(ActionItem).filter_by(user_id=profile.id, key=key).first()
    if row is None:
        row = ActionItem(user_id=profile.id, key=key, kind=key.split(":")[0])
        s.add(row)
    row.status = status
    row.snooze_until = today + timedelta(days=max(days, 1)) if status == "snoozed" else None
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    s.commit()
    return row


def notify_new(s: Session, profile: UserProfile, today: date | None = None, *, items: list[dict] | None = None) -> list[str]:
    """Send one notification per high-priority open action that has not been announced before. Returns the keys sent."""
    from services import notifier

    sent: list[str] = []
    state = _state(s, profile)
    for it in feed(s, profile, today, items=items)["items"]:
        row = state.get(it["key"])
        if it["priority"] < rules()["notify_priority"] or (row and row.notified_at):
            continue
        try:
            notifier.notify(it["title"], it["detail"], "warn", [("Priority", f"{it['priority']:.0f}/100"), ("Where", it["where"])])
        except RuntimeError as e:
            log.warning("action notify failed: %s", e)
            return sent  # no channel configured or all failed: leave notified_at unset so we retry tomorrow
        if row is None:
            row = ActionItem(user_id=profile.id, key=it["key"], kind=it["kind"])
            s.add(row)
        row.notified_at = datetime.now(UTC).replace(tzinfo=None)
        s.commit()
        sent.append(it["key"])
    return sent
