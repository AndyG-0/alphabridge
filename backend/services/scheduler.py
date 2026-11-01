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


def start_scheduler(app) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(weekly_screen, CronTrigger(day_of_week="sun", hour=14), args=[app], id="weekly_screen", replace_existing=True)
    sched.add_job(daily_checks, CronTrigger(hour=21, minute=30, day_of_week="mon-fri"), args=[app], id="daily_checks", replace_existing=True)
    sched.start()
    app.extensions["scheduler"] = sched
    return sched
