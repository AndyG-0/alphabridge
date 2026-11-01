"""Ask-the-AI chat. The model calls read-only tools; the math stays in Python."""

from flask import Blueprint, jsonify, request
from sqlalchemy import func

import db
from models import ChatMessage, ChatSession, utcnow
from schemas import ChatMessageIn, ChatSessionPatch
from services import chat_tools, llm_router
from services.llm_router import LLMNotConfigured, chat_with_tools

bp = Blueprint("chat", __name__, url_prefix="/api")

SYSTEM = (
    "You are AlphaBridge's planning assistant for one household whose goals are to maximize long-run growth and retire early. "
    "Never guess at the user's data: call the provided tools (profile, accounts, holdings, allocation, FIRE simulation and what-ifs, "
    "planned events, pensions, debts and payoff schedule, household timeline, early-access/Rule of 55/SEPP, state Medicaid and HSA "
    "rules, plan menus, imports, screener, sectors, cash signal, market, stocks). Before saying data is missing, call get_data_gaps. "
    "Quote tool numbers; never do your own arithmetic beyond trivial comparisons, and use run_fire_scenario to test any what-if. "
    "If a tool shows an input is missing or zero (income, expenses, spouse age, plan menu) say so and tell the user "
    "where to enter it. Be concise and concrete, show trade-offs, and mention taxes and penalties where relevant (59.5 rule, "
    "Rule of 55, SEPP, capital gains). You are read-only: you cannot change data or place trades. You are not a licensed advisor."
)


HISTORY_LIMIT = 30
TITLE_SYSTEM = "Write a 3-6 word title for this conversation about household finance. Reply with the title only: no quotes, no trailing period."


def _fallback_title(text: str) -> str:
    t = " ".join(text.split())
    return t if len(t) <= 50 else t[:49].rstrip() + "…"


def _auto_title(first_user: str, reply: str) -> str:
    try:
        raw = llm_router.complete("fast", TITLE_SYSTEM, f"User: {first_user[:500]}\nAssistant: {reply[:500]}", max_tokens=30)
        title = raw.strip().splitlines()[0].strip().strip("\"'`*#").rstrip(".") if raw.strip() else ""
    except Exception:
        title = ""
    return title[:80] or _fallback_title(first_user)


def _get(sid: int) -> ChatSession | None:
    return db.session().get(ChatSession, sid)


@bp.get("/chat/sessions")
def session_list():
    s = db.session()
    counts = dict(s.query(ChatMessage.session_id, func.count(ChatMessage.id)).group_by(ChatMessage.session_id).all())
    rows = s.query(ChatSession).order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()).all()
    return jsonify([r.to_dict() | {"message_count": counts.get(r.id, 0)} for r in rows])


@bp.post("/chat/sessions")
def session_create():
    s = db.session()
    c = ChatSession()
    s.add(c)
    s.commit()
    return jsonify(c.to_dict() | {"messages": []}), 201


@bp.get("/chat/sessions/<int:sid>")
def session_get(sid):
    c = _get(sid)
    if c is None:
        return jsonify(error="not found"), 404
    return jsonify(c.to_dict() | {"messages": [m.to_dict() for m in c.messages]})


@bp.patch("/chat/sessions/<int:sid>")
def session_rename(sid):
    data = ChatSessionPatch.model_validate(request.get_json(force=True))
    c = _get(sid)
    if c is None:
        return jsonify(error="not found"), 404
    c.title, c.title_source = data.title.strip(), "user"
    db.session().commit()
    return jsonify(c.to_dict())


@bp.delete("/chat/sessions/<int:sid>")
def session_delete(sid):
    c = _get(sid)
    if c is None:
        return jsonify(error="not found"), 404
    s = db.session()
    s.delete(c)
    s.commit()
    return "", 204


@bp.post("/chat/sessions/<int:sid>/messages")
def session_send(sid):
    body = ChatMessageIn.model_validate(request.get_json(force=True))
    c = _get(sid)
    if c is None:
        return jsonify(error="not found"), 404
    history = [{"role": m.role, "content": m.content} for m in c.messages][-HISTORY_LIMIT:]
    history.append({"role": "user", "content": body.content})
    try:
        reply, used = chat_with_tools("reasoning", SYSTEM, history, chat_tools.SCHEMAS, chat_tools.dispatch, max_steps=8)
    except LLMNotConfigured as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=f"LLM call failed: {e}"), 502
    s = db.session()
    first = not c.messages
    user_msg = ChatMessage(session_id=c.id, role="user", content=body.content)
    bot_msg = ChatMessage(session_id=c.id, role="assistant", content=reply, tools_used=sorted(set(used)))
    s.add_all([user_msg, bot_msg])
    c.updated_at = utcnow()
    if first and c.title_source == "auto":
        c.title = _auto_title(body.content, reply)
    s.commit()
    return jsonify(session=c.to_dict(), user=user_msg.to_dict(), assistant=bot_msg.to_dict())
