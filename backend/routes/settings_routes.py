import os

from flask import Blueprint, jsonify, request

import db
from schemas import LLMConfigIn, NotificationConfigIn
from services import notifier
from services.crypto import encrypt
from services.llm_router import PROVIDER_ENV, LLMNotConfigured, complete, get_config

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


def llm_view(cfg) -> dict:
    return {
        "provider": cfg.provider,
        "fast_model": cfg.fast_model,
        "reasoning_model": cfg.reasoning_model,
        "api_base": cfg.api_base,
        "api_key_set": bool(cfg.api_key_encrypted or os.getenv(PROVIDER_ENV.get(cfg.provider, ""), "")),
        "providers": [*list(PROVIDER_ENV), "ollama"],
    }


@bp.get("/llm")
def llm_get():
    return jsonify(llm_view(get_config()))


@bp.put("/llm")
def llm_put():
    data = LLMConfigIn.model_validate(request.get_json(force=True))
    cfg = get_config()
    for k in ("provider", "fast_model", "reasoning_model", "api_base"):
        v = getattr(data, k)
        if v is not None:
            setattr(cfg, k, v)
    if data.api_key:  # never blank an existing key by omission
        cfg.api_key_encrypted = encrypt(data.api_key)
    db.session().commit()
    return jsonify(llm_view(cfg))


@bp.post("/llm/test")
def llm_test():
    try:
        out = complete("fast", "You are a connectivity test.", "Reply with the single word: pong", max_tokens=20)
    except LLMNotConfigured as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:300]), 502
    return jsonify(ok=True, reply=out.strip()[:50])


def notif_view(cfg) -> dict:
    return {
        "discord_configured": bool(cfg.discord_webhook_encrypted),
        "smtp_host": cfg.smtp_host,
        "smtp_port": cfg.smtp_port,
        "smtp_user": cfg.smtp_user,
        "smtp_to": cfg.smtp_to,
        "smtp_password_set": bool(cfg.smtp_password_encrypted),
    }


@bp.get("/notifications")
def notif_get():
    return jsonify(notif_view(notifier.get_config()))


@bp.put("/notifications")
def notif_put():
    data = NotificationConfigIn.model_validate(request.get_json(force=True))
    cfg = notifier.get_config()
    for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_to"):
        v = getattr(data, k)
        if v is not None:
            setattr(cfg, k, v)
    if data.discord_webhook is not None:
        cfg.discord_webhook_encrypted = encrypt(data.discord_webhook)
    if data.smtp_password:
        cfg.smtp_password_encrypted = encrypt(data.smtp_password)
    db.session().commit()
    return jsonify(notif_view(cfg))


@bp.post("/notifications/test")
def notif_test():
    try:
        channel = notifier.notify("AlphaBridge test", "Your alert channel is working.", "info")
    except RuntimeError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, channel=channel)
