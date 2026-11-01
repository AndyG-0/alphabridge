"""Discord webhook embeds with SMTP email fallback."""

import smtplib
from email.message import EmailMessage

import requests

import db
from models import NotificationConfig
from services.crypto import decrypt

COLORS = {"info": 0x3B82F6, "buy": 0x22C55E, "warn": 0xF59E0B, "risk": 0xEF4444}


def get_config() -> NotificationConfig:
    s = db.session()
    cfg = s.get(NotificationConfig, 1)
    if cfg is None:
        cfg = NotificationConfig(id=1)
        s.add(cfg)
        s.commit()
    return cfg


def build_embed(title: str, description: str, kind: str = "info", fields: list[tuple[str, str]] | None = None) -> dict:
    return {
        "title": title[:256],
        "description": description[:4000],
        "color": COLORS.get(kind, COLORS["info"]),
        "fields": [{"name": n[:256], "value": v[:1024] or "-", "inline": True} for n, v in (fields or [])][:25],
        "footer": {"text": "AlphaBridge"},
    }


def send_discord(webhook_url: str, embed: dict) -> None:
    r = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
    r.raise_for_status()


def send_email(cfg: NotificationConfig, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg.smtp_user, cfg.smtp_to
    msg.set_content(body)
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if cfg.smtp_user:
            smtp.login(cfg.smtp_user, decrypt(cfg.smtp_password_encrypted))
        smtp.send_message(msg)


def notify(title: str, description: str, kind: str = "info", fields=None) -> str:
    """Try Discord, fall back to SMTP. Returns channel used or raises if none configured/working."""
    cfg = get_config()
    hook = decrypt(cfg.discord_webhook_encrypted)
    errors = []
    if hook:
        try:
            send_discord(hook, build_embed(title, description, kind, fields))
            return "discord"
        except requests.RequestException as e:
            errors.append(f"discord: {e}")
    if cfg.smtp_host and cfg.smtp_to:
        try:
            body = description + "\n\n" + "\n".join(f"{n}: {v}" for n, v in (fields or []))
            send_email(cfg, f"[AlphaBridge] {title}", body)
            return "email"
        except (OSError, smtplib.SMTPException) as e:
            errors.append(f"email: {e}")
    raise RuntimeError("; ".join(errors) or "No notification channel configured")


def format_stock_pitch(r) -> tuple[str, str, str, list]:
    return (
        f"{r.symbol}: {r.recommended_action.replace('_', ' ')}",
        (r.bull_case_md or "")[:700],
        "buy" if r.recommended_action == "BUY_SATELLITE" else "info",
        [("Quant score", f"{r.quant_score:.0f}/100"), ("Valuation", r.valuation_grade), ("Growth", r.growth_grade), ("Moat", r.moat_grade)],
    )
