import pytest

from services import market_data, notifier, planner, scheduler
from services import research_pipeline as rp


def test_start_scheduler_registers_jobs(app):
    sched = scheduler.start_scheduler(app)
    try:
        assert {j.id for j in sched.get_jobs()} == {"weekly_screen", "daily_checks"}
    finally:
        sched.shutdown(wait=False)


def test_weekly_screen_notifies_top_three_passed(app, monkeypatch):
    rows = [{"symbol": s, "score": 90 - i, "passed": s != "BBB"} for i, s in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"])]
    monkeypatch.setattr(rp, "run_screener", lambda: rows)
    monkeypatch.setattr(rp, "apply_macro_overlay", lambda top, sectors: top)
    monkeypatch.setattr(market_data, "sector_strength", lambda: [])
    sent = []
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: sent.append(a))
    scheduler.weekly_screen(app)
    assert "BBB" not in sent[0][1] and sent[0][1].count("**") == 6 and "EEE" not in sent[0][1]


def test_weekly_screen_silent_when_nothing_passes(app, monkeypatch):
    monkeypatch.setattr(rp, "run_screener", lambda: [{"symbol": "A", "score": 1, "passed": False}])
    monkeypatch.setattr(rp, "apply_macro_overlay", lambda top, sectors: top)
    monkeypatch.setattr(market_data, "sector_strength", lambda: [])
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: pytest.fail("should not notify"))
    scheduler.weekly_screen(app)


def test_weekly_screen_swallows_notify_failure(app, monkeypatch):
    monkeypatch.setattr(rp, "run_screener", lambda: [{"symbol": "A", "score": 1, "passed": True}])
    monkeypatch.setattr(rp, "apply_macro_overlay", lambda top, sectors: top)
    monkeypatch.setattr(market_data, "sector_strength", lambda: [])
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no channel")))
    scheduler.weekly_screen(app)


@pytest.mark.parametrize(("signal", "deploy", "expect_notify"), [("HOLD_MMF", 0, False), ("DCA", 0, False), ("DCA", 5000, True), ("AGGRESSIVE", 12000, True)])
def test_daily_checks_only_notifies_on_actionable_signal(app, monkeypatch, signal, deploy, expect_notify):
    monkeypatch.setattr(market_data, "market_inputs", lambda key: (None, []))
    monkeypatch.setattr(planner, "cash_recommendation", lambda *a: {"signal": signal, "deploy_now": deploy, "keep_in_mmf": 1.0, "score": 70, "reasons": ["r"]})
    sent = []
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: sent.append(a))
    scheduler.daily_checks(app)
    assert bool(sent) is expect_notify
    if sent:
        assert sent[0][0] == "Cash deployment trigger"
