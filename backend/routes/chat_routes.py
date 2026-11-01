"""Ask-the-AI chat. The model calls read-only tools; the math stays in Python."""

from flask import Blueprint, jsonify, request
from sqlalchemy import func

import db
from models import ChatMessage, ChatSession, utcnow
from schemas import ChatMessageIn, ChatSessionPatch
from services import chat_tools, llm_router, prompts
from services.llm_router import LLMNotConfigured, chat_with_tools

bp = Blueprint("chat", __name__, url_prefix="/api")

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
    if data.title is not None:
        c.title, c.title_source = data.title.strip(), "user"
    if data.scenario is not None:
        c.scenario = data.scenario.strip()
    if data.memory is not None:
        c.memory = data.memory.strip()
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
    results: dict[str, str] = {}  # latest JSON result per tool, for citation checks and the arithmetic guard

    def dispatch(name: str, args: dict) -> str:
        out = chat_tools.dispatch(name, args)
        results[name] = out
        return out

    try:
        reply, used = chat_with_tools("reasoning", prompts.build_system(c.scenario, c.memory), history, chat_tools.SCHEMAS, dispatch, max_steps=8)
    except LLMNotConfigured as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=f"LLM call failed: {e}"), 502
    reply = prompts.guard_arithmetic(body.content, reply, results) or reply
    s = db.session()
    first = not c.messages
    user_msg = ChatMessage(session_id=c.id, role="user", content=body.content)
    bot_msg = ChatMessage(
        session_id=c.id,
        role="assistant",
        content=reply,
        tools_used=sorted(set(used)),
        prompt_version=prompts.PROMPT_VERSION,
        citations=prompts.check_citations(reply, results),
    )
    s.add_all([user_msg, bot_msg])
    c.updated_at = utcnow()
    if first and c.title_source == "auto":
        c.title = _auto_title(body.content, reply)
    s.commit()
    return jsonify(session=c.to_dict(), user=user_msg.to_dict(), assistant=bot_msg.to_dict())
