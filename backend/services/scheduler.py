"""APScheduler jobs: weekly screening + daily cash/drift checks. Enable with ENABLE_SCHEDULER=1 (one worker only)."""

import functools
import logging
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("alphabridge.scheduler")

RUNS: dict[str, dict] = {}  # job id -> {last_run, status, error}; in memory, one worker


def _tracked(job_id):
    """Record each run's outcome so the Settings panel can show whether the background jobs actually work."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(app):
            RUNS[job_id] = {"last_run": datetime.now(UTC).isoformat(), "status": "running", "error": None}
            try:
                fn(app)
                RUNS[job_id]["status"] = "ok"
            except Exception as e:
                RUNS[job_id].update(status="error", error=f"{type(e).__name__}: {e}"[:300])
                log.exception("scheduled job %s failed", job_id)

        return wrapper

    return deco


@_tracked("weekly_screen")
def weekly_screen(app):
    with app.app_context():
        from services import market_data, notifier
        from services import research_pipeline as rp

        top = rp.apply_macro_overlay(rp.run_screener(), market_data.sector_strength())
        passed = [t for t in top if t["passed"]][:3]
        if passed:
            try:
                notifier.notify("Weekly screener picks", "\n".join(f"**{t['symbol']}** score {t['score']}" for t in passed), "buy")
            except RuntimeError as e:
                log.warning("notify failed: %s", e)


@_tracked("daily_checks")
def daily_checks(app):
    with app.app_context():
        import db
        from routes._helpers import get_profile
        from services import market_data, notifier, planner

        s = db.session()
        p = get_profile()
        market, _ = market_data.market_inputs(app.config["FRED_API_KEY"])
        rec = planner.cash_recommendation(s, p, p.current_money_market_yield, market)
        if rec["signal"] != "HOLD_MMF" and rec["deploy_now"] > 0:
            try:
                notifier.notify(
                    "Cash deployment trigger",
                    "\n".join(rec["reasons"]),
                    "buy",
                    [
                        ("Signal", rec["signal"]),
                        ("Score", str(rec["score"])),
                        ("Deploy", f"${rec['deploy_now']:,.0f}"),
                        ("Keep in MMF", f"${rec['keep_in_mmf']:,.0f}"),
                    ],
                )
            except RuntimeError as e:
                log.warning("notify failed: %s", e)
        _rebalance_alert(s, p)
        _dca_reminder(s, p)
        _research_alerts(s)


def _rebalance_alert(s, profile):
    """Notify when any asset class drifts past the threshold from the target allocation (no-op without a target)."""
    from models import Account
    from services import notifier, rebalance

    if not profile.target_allocation:
        return
    d = rebalance.drift(rebalance.class_values([h for a in s.query(Account).all() for h in a.holdings]), profile.target_allocation)
    if not d["breached"]:
        return
    rows = [r for r in d["rows"] if r["breach"]]
    try:
        notifier.notify(
            "Rebalance needed",
            "Allocation has drifted past your threshold.",
            "warn",
            [(r["asset_class"], f"{r['current']:.0%} vs target {r['target']:.0%}") for r in rows],
        )
    except RuntimeError as e:
        log.warning("notify failed: %s", e)


def _dca_reminder(s, profile):
    """One reminder per DCA tranche that has come due; remembered so it isn't repeated."""
    from datetime import date

    from services import ladder, notifier

    plan = profile.dca_plan or None
    due = ladder.due_tranches(plan, date.today())
    if not plan or not due:
        return
    try:
        notifier.notify(
            "DCA tranche due",
            "A scheduled deployment from cash is due.",
            "buy",
            [(t["on"], f"${t['amount']:,.0f}") for t in due],
        )
    except RuntimeError as e:
        log.warning("notify failed: %s", e)
        return
    profile.dca_plan = {**plan, "notified": [*plan.get("notified", []), *[t["on"] for t in due]]}
    s.commit()


def _research_alerts(s):
    """Valuation alerts for the watchlist (once a day per symbol) and thesis invalidation (flagged once, then stays flagged)."""
    from datetime import date

    from models import ThesisRecord, WatchlistItem
    from services import notifier, research_watch

    today = date.today()
    fields: list[tuple[str, str]] = []
    for row in research_watch.watchlist_view(s):
        w = s.get(WatchlistItem, row["id"])
        if row["alerts"] and w is not None and w.last_alerted_on != today:
            fields.extend((row["symbol"], a) for a in row["alerts"])
            w.last_alerted_on = today
    for v in research_watch.theses_view(s):
        t = s.get(ThesisRecord, v["id"])
        if v["broken"] and t is not None and t.status == "ACTIVE":
            t.status, t.invalidated_on = "INVALIDATED", today
            fields.extend((v["symbol"], f"Thesis invalidated: {c.get('text') or c['metric']} ({c['current']})") for c in v["broken"])
    if not fields:
        return
    try:
        notifier.notify("Research alerts", "Watchlist valuation or thesis conditions changed.", "warn", fields)
    except RuntimeError as e:
        log.warning("notify failed: %s", e)
    s.commit()


@_tracked("net_worth_snapshot")
def net_worth_snapshot(app):
    """Daily snapshot so the history has points even when no file is imported (idempotent per UTC day)."""
    with app.app_context():
        import db
        from services import ingestion

        s = db.session()
        ingestion.snapshot_net_worth(s)
        s.commit()


@_tracked("simplefin_sync")
def simplefin_sync(app):
    """Daily balance pull when SimpleFIN is connected; a no-op otherwise."""
    with app.app_context():
        from services import simplefin

        if simplefin.status()["connected"]:
            simplefin.sync()


@_tracked("backup")
def backup(app):
    """Nightly encrypted backup when BACKUP_DEST is configured; a no-op otherwise."""
    with app.app_context():
        import db
        from services import export

        if export.destination():
            export.run_backup(db.session())


def start_scheduler(app) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(weekly_screen, CronTrigger(day_of_week="sun", hour=14), args=[app], id="weekly_screen", replace_existing=True)
    sched.add_job(daily_checks, CronTrigger(hour=21, minute=30, day_of_week="mon-fri"), args=[app], id="daily_checks", replace_existing=True)
    sched.add_job(net_worth_snapshot, CronTrigger(hour=22, minute=0), args=[app], id="net_worth_snapshot", replace_existing=True)
    sched.add_job(simplefin_sync, CronTrigger(hour=12, minute=0), args=[app], id="simplefin_sync", replace_existing=True)
    sched.add_job(backup, CronTrigger(hour=3, minute=0), args=[app], id="backup", replace_existing=True)
    sched.start()
    app.extensions["scheduler"] = sched
    return sched
