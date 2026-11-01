"""LiteLLM wrapper: task-based model routing with Pydantic-enforced JSON output."""

import json
import re
from typing import TypeVar

from pydantic import BaseModel

import db
from models import LLMConfig
from services.crypto import decrypt

T = TypeVar("T", bound=BaseModel)

PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class LLMNotConfigured(RuntimeError):
    pass


def get_config() -> LLMConfig:
    s = db.session()
    cfg = s.get(LLMConfig, 1)
    if cfg is None:
        cfg = LLMConfig(id=1)
        s.add(cfg)
        s.commit()
    return cfg


def _api_key(cfg: LLMConfig) -> str:
    import os

    return decrypt(cfg.api_key_encrypted) or os.getenv(PROVIDER_ENV.get(cfg.provider, ""), "")


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _user_content(user: str, images: list[bytes] | None):
    if not images:
        return user
    import base64

    parts = [{"type": "text", "text": user}]
    parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode()}} for i in images]
    return parts


def complete(task: str, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 4000, images: list[bytes] | None = None) -> str:
    """task: 'fast' or 'reasoning'. `images` are PNG bytes for vision-capable models."""
    import litellm

    cfg = get_config()
    key = _api_key(cfg)
    if not key and cfg.provider != "ollama":
        raise LLMNotConfigured("No API key configured for the active LLM provider (Settings -> LLM Router).")
    model = cfg.fast_model if task == "fast" else cfg.reasoning_model
    kwargs = dict(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": _user_content(user, images)}],
        max_tokens=max_tokens,
        api_key=key or None,
        timeout=120,
    )
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    if json_mode and cfg.provider in ("openai", "openrouter"):
        kwargs["response_format"] = {"type": "json_object"}
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


def chat(task: str, system: str, messages: list[dict], max_tokens: int = 1500) -> str:
    """Multi-turn free-text completion. `messages` are {role: user|assistant, content}."""
    import litellm

    cfg = get_config()
    key = _api_key(cfg)
    if not key and cfg.provider != "ollama":
        raise LLMNotConfigured("No API key configured for the active LLM provider (Settings -> LLM Router).")
    kwargs = dict(
        model=cfg.fast_model if task == "fast" else cfg.reasoning_model,
        messages=[{"role": "system", "content": system}, *messages],
        max_tokens=max_tokens,
        api_key=key or None,
        timeout=120,
    )
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    return litellm.completion(**kwargs).choices[0].message.content or ""


def chat_with_tools(
    task: str, system: str, messages: list[dict], schemas: list[dict], dispatch, max_steps: int = 6, max_tokens: int = 1800
) -> tuple[str, list[str]]:
    """Tool-calling loop: the model may call read-only tools; returns (final text, names of tools used)."""
    import litellm

    cfg = get_config()
    key = _api_key(cfg)
    if not key and cfg.provider != "ollama":
        raise LLMNotConfigured("No API key configured for the active LLM provider (Settings -> LLM Router).")
    msgs = [{"role": "system", "content": system}, *messages]
    used: list[str] = []
    for step in range(max_steps + 1):
        kwargs = dict(model=cfg.fast_model if task == "fast" else cfg.reasoning_model, messages=msgs, max_tokens=max_tokens, api_key=key or None, timeout=120)
        if step < max_steps:
            kwargs["tools"] = schemas
        if cfg.api_base:
            kwargs["api_base"] = cfg.api_base
        msg = litellm.completion(**kwargs).choices[0].message
        calls = getattr(msg, "tool_calls", None)
        if not calls:
            return msg.content or "", used
        msgs.append(msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else dict(msg))
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            used.append(c.function.name)
            msgs.append({"role": "tool", "tool_call_id": c.id, "content": dispatch(c.function.name, args)})
    return "I couldn't finish within the tool-call limit; try a narrower question.", used


def complete_structured(task: str, system: str, user: str, schema: type[T], retries: int = 1, images: list[bytes] | None = None) -> T:
    """Ask for JSON matching `schema`; validate with Pydantic and retry once on failure."""
    sys_prompt = f"{system}\n\nRespond with ONLY a JSON object matching this JSON Schema. No prose.\n{json.dumps(schema.model_json_schema())}"
    last_err = None
    for _ in range(retries + 1):
        raw = complete(task, sys_prompt, user, json_mode=True, images=images)
        try:
            return schema.model_validate(_extract_json(raw))
        except Exception as e:
            last_err = e
            user = f"{user}\n\nYour previous reply was invalid ({e}). Return valid JSON only."
    raise ValueError(f"LLM returned invalid structured output: {last_err}")
