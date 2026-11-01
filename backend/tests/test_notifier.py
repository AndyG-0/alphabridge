import smtplib
from types import SimpleNamespace

import pytest
import requests

import db
from services import crypto, notifier


def _configure(app, **kw):
    with app.app_context():
        cfg = notifier.get_config()
        for k, v in kw.items():
            setattr(cfg, k, crypto.encrypt(v) if k.endswith("_encrypted") else v)
        db.session().commit()


def test_build_embed_truncates_and_defaults_kind():
    e = notifier.build_embed("t" * 300, "d" * 5000, "nope", [("n" * 300, ""), *[("a", "b")] * 30])
    assert len(e["title"]) == 256 and len(e["description"]) == 4000
    assert e["color"] == notifier.COLORS["info"] and len(e["fields"]) == 25
    assert e["fields"][0]["value"] == "-" and len(e["fields"][0]["name"]) == 256


def test_no_channel_raises(app):
    with app.app_context(), pytest.raises(RuntimeError, match="No notification channel"):
        notifier.notify("t", "d")


def test_discord_used_first(app, monkeypatch):
    _configure(app, discord_webhook_encrypted="https://hook")
    sent = []
    monkeypatch.setattr(notifier, "send_discord", lambda url, embed: sent.append((url, embed["title"])))
    with app.app_context():
        assert notifier.notify("hello", "d") == "discord"
    assert sent == [("https://hook", "hello")]


def test_discord_failure_falls_back_to_email(app, monkeypatch):
    _configure(app, discord_webhook_encrypted="https://hook", smtp_host="smtp.x", smtp_to="a@b.c")

    def bad(*a, **k):
        raise requests.ConnectionError("down")

    mails = []
    monkeypatch.setattr(notifier, "send_discord", bad)
    monkeypatch.setattr(notifier, "send_email", lambda cfg, subj, body: mails.append((subj, body)))
    with app.app_context():
        assert notifier.notify("T", "desc", fields=[("k", "v")]) == "email"
    assert mails[0][0] == "[AlphaBridge] T" and "k: v" in mails[0][1]


def test_both_fail_reports_both_errors(app, monkeypatch):
    _configure(app, discord_webhook_encrypted="https://hook", smtp_host="smtp.x", smtp_to="a@b.c")
    monkeypatch.setattr(notifier, "send_discord", lambda *a: (_ for _ in ()).throw(requests.ConnectionError("d-down")))
    monkeypatch.setattr(notifier, "send_email", lambda *a: (_ for _ in ()).throw(smtplib.SMTPException("m-down")))
    with app.app_context(), pytest.raises(RuntimeError) as ei:
        notifier.notify("t", "d")
    assert "d-down" in str(ei.value) and "m-down" in str(ei.value)


def test_send_discord_posts_embed(monkeypatch):
    calls = {}

    def post(url, json, timeout):
        calls.update(url=url, json=json)
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(notifier.requests, "post", post)
    notifier.send_discord("https://hook", {"title": "x"})
    assert calls == {"url": "https://hook", "json": {"embeds": [{"title": "x"}]}}


def test_send_email_logs_in_and_sends(app, monkeypatch):
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            log.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            log.append("tls")

        def login(self, user, pw):
            log.append(("login", user, pw))

        def send_message(self, msg):
            log.append(("send", msg["Subject"], msg["To"]))

    monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
    _configure(app, smtp_host="smtp.x", smtp_port=587, smtp_user="me@x", smtp_to="you@x", smtp_password_encrypted="pw")
    with app.app_context():
        notifier.send_email(notifier.get_config(), "subj", "body")
    assert log == [("connect", "smtp.x", 587), "tls", ("login", "me@x", "pw"), ("send", "subj", "you@x")]


def test_format_stock_pitch():
    r = SimpleNamespace(
        symbol="AAA", recommended_action="BUY_SATELLITE", bull_case_md="b" * 900, quant_score=71.6, valuation_grade="A", growth_grade="B", moat_grade="C"
    )
    title, desc, kind, fields = notifier.format_stock_pitch(r)
    assert title == "AAA: BUY SATELLITE" and len(desc) == 700 and kind == "buy" and fields[0] == ("Quant score", "72/100")
