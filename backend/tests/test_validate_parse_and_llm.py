import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from services import llm_router, validate_parse
from services.validate_parse import check_rows, confidence


def row(symbol="AAPL", shares=10, mv=1000.0, needs_mapping=False):
    return SimpleNamespace(symbol=symbol, shares=shares, market_value=mv, needs_mapping=needs_mapping)


def levels(checks):
    return [c["level"] for c in checks]


def test_matching_row_and_total_is_high_confidence():
    c = check_rows([row()], {0: 100.0}, 1000.0)
    assert levels(c) == ["ok", "ok"] and confidence(c) == "high"


def test_shares_times_price_mismatch_fails():
    c = check_rows([row()], {0: 50.0}, 1000.0)
    assert "fail" in levels(c) and confidence(c) == "low"


def test_rounding_within_tolerance_ok():
    assert levels(check_rows([row(mv=1005.0)], {0: 100.0}, 1005.0)) == ["ok", "ok"]


def test_missing_price_total_and_odd_ticker_warn():
    c = check_rows([row(symbol="bad-sym")], {})
    assert set(levels(c)) == {"warn"} and confidence(c) == "medium"
    assert not any("standard ticker" in x["message"] for x in check_rows([row(symbol="bad-sym", needs_mapping=True)], {}))


def test_nonpositive_value_and_total_mismatch_fail():
    c = check_rows([row(mv=0.0)], {}, 500.0)
    assert levels(c).count("fail") == 2


def test_tolerance_constant_is_one_percent():
    assert validate_parse.TOLERANCE == 0.01


@pytest.mark.parametrize(
    "text",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'Sure! Here you go: {"a": 1} hope that helps', '```\n{"a": 1}\n```'],
)
def test_extract_json_variants(text):
    assert llm_router._extract_json(text) == {"a": 1}


def test_extract_json_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        llm_router._extract_json("no json here")


def test_user_content_with_images():
    assert llm_router._user_content("hi", None) == "hi"
    parts = llm_router._user_content("hi", [b"\x89PNG"])
    assert parts[0] == {"type": "text", "text": "hi"} and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.fixture
def fake_llm(app, monkeypatch):
    """Replace litellm.completion; yields the call log and a reply queue."""
    import litellm

    state = SimpleNamespace(calls=[], replies=[])

    def completion(**kw):
        state.calls.append(kw)
        content = state.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))])

    monkeypatch.setattr(litellm, "completion", completion)
    for env in llm_router.PROVIDER_ENV.values():
        monkeypatch.delenv(env, raising=False)
    return state


def _set_key(app, key="k"):
    import db
    from services import crypto

    cfg = llm_router.get_config()
    cfg.api_key_encrypted = crypto.encrypt(key)
    db.session().commit()


def test_complete_requires_key(app, fake_llm):
    with app.app_context(), pytest.raises(llm_router.LLMNotConfigured):
        llm_router.complete("fast", "s", "u")
    assert fake_llm.calls == []


def test_complete_routes_models_and_key(app, fake_llm):
    fake_llm.replies = ["a", "b"]
    with app.app_context():
        _set_key(app, "sk-1")
        cfg = llm_router.get_config()
        assert llm_router.complete("fast", "s", "u") == "a"
        assert llm_router.complete("reasoning", "s", "u") == "b"
    assert fake_llm.calls[0]["model"] == cfg.fast_model and fake_llm.calls[1]["model"] == cfg.reasoning_model
    assert fake_llm.calls[0]["api_key"] == "sk-1"


def test_env_key_fallback(app, fake_llm, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    fake_llm.replies = ["ok"]
    with app.app_context():
        llm_router.get_config().provider = "anthropic"
        assert llm_router.complete("fast", "s", "u") == "ok"
    assert fake_llm.calls[0]["api_key"] == "env-key"


class Out(BaseModel):
    n: int


def test_structured_retries_once_then_succeeds(app, fake_llm):
    fake_llm.replies = ["not json", '{"n": 3}']
    with app.app_context():
        _set_key(app)
        assert llm_router.complete_structured("fast", "s", "u", Out).n == 3
    assert "previous reply was invalid" in fake_llm.calls[1]["messages"][1]["content"]


def test_structured_gives_up(app, fake_llm):
    fake_llm.replies = ["x", "y"]
    with app.app_context():
        _set_key(app)
        with pytest.raises(ValueError, match="invalid structured output"):
            llm_router.complete_structured("fast", "s", "u", Out)


def test_chat_passes_history(app, fake_llm):
    fake_llm.replies = ["hello"]
    with app.app_context():
        _set_key(app)
        assert llm_router.chat("fast", "sys", [{"role": "user", "content": "hi"}]) == "hello"
    assert [m["role"] for m in fake_llm.calls[0]["messages"]] == ["system", "user"]


def test_litellm_imported_offline():
    assert "litellm" in sys.modules or __import__("litellm")
