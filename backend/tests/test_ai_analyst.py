import hashlib
import json
from types import SimpleNamespace

import litellm
import pytest

from models import LLMConfig
from services import chat_tools, llm_router, prompts


def _msg(content=None, calls=None):
    return SimpleNamespace(
        content=content,
        tool_calls=calls,
        model_dump=lambda exclude_none=True: {"role": "assistant", "content": content, "tool_calls": []},
    )


def _llm(monkeypatch, replies):
    it = iter(replies)
    seen = []

    def fake(**kw):
        seen.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(it))])

    monkeypatch.setattr(litellm, "completion", fake)
    monkeypatch.setattr(llm_router, "_api_key", lambda cfg: "k")
    return seen


def _call(id_, name, args=None):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=name, arguments=json.dumps(args or {})))


def _session(client):
    return client.post("/api/chat/sessions").get_json()["id"]


def test_prompt_version_tracks_prompt_text():
    # Editing prompts.SYSTEM changes this hash: bump PROMPT_VERSION and update both pins together.
    pinned = {"2026-10-31.1": "2708a091a884"}
    assert prompts.PROMPT_VERSION in pinned and pinned[prompts.PROMPT_VERSION] == prompts.prompt_hash()
    assert hashlib.sha256(prompts.SYSTEM.encode()).hexdigest().startswith(prompts.prompt_hash())


def test_system_prompt_requires_citations_and_forbids_arithmetic():
    assert "never do arithmetic" in prompts.SYSTEM and "[run_fire_scenario.success_rate]" in prompts.SYSTEM


@pytest.mark.parametrize("q", ["what's 15% of 340k?", "1200 * 12 =", "what is 5000 plus 250", "3,400 / 12"])
def test_arithmetic_questions_detected(q):
    assert prompts.looks_like_arithmetic(q)


@pytest.mark.parametrize("q", ["Can I retire at 52?", "How does the Rule of 55 work?", "Show my allocation"])
def test_ordinary_questions_not_flagged(q):
    assert not prompts.looks_like_arithmetic(q)


def test_arithmetic_answer_without_tool_output_is_replaced_by_refusal(client, monkeypatch):
    _llm(monkeypatch, [_msg("15% of 340k is 51,000.")])
    sid = _session(client)
    r = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "what's 15% of 340k?"}).get_json()
    assert r["assistant"]["content"] == prompts.ARITHMETIC_REFUSAL
    assert "51,000" not in r["assistant"]["content"]


def test_arithmetic_answer_grounded_in_a_tool_result_passes(client, monkeypatch):
    client.put("/api/profile", json={"annual_income": 150000})
    _llm(monkeypatch, [_msg(calls=[_call("1", "get_profile")]), _msg("Your income is 150000 [get_profile.annual_income].")])
    sid = _session(client)
    r = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "what is 150000 / 12"}).get_json()["assistant"]
    assert r["content"].startswith("Your income is 150000")
    assert r["citations"] == [{"ref": "get_profile.annual_income", "ok": True}]


def test_citations_are_checked_against_tool_output():
    results = {"get_profile": json.dumps({"annual_income": 1, "items": [{"a": 1}]})}
    reply = "A [get_profile.annual_income] B [get_profile.items[0].a] C [get_profile.nope] D [run_fire_scenario.success_rate]"
    got = {c["ref"]: c["ok"] for c in prompts.check_citations(reply, results)}
    assert got == {
        "get_profile.annual_income": True,
        "get_profile.items[0].a": True,
        "get_profile.nope": False,
        "run_fire_scenario.success_rate": False,
    }


def test_footer_has_disclaimer_assumptions_version_and_flags_bad_citations(client, monkeypatch):
    _llm(monkeypatch, [_msg(calls=[_call("1", "get_profile")]), _msg("Fine [get_profile.made_up_field].")])
    sid = _session(client)
    a = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "hi"}).get_json()["assistant"]
    assert prompts.DISCLAIMER in a["footer"] and "get_profile" in a["footer"]
    assert "Could not verify" in a["footer"] and "get_profile.made_up_field" in a["footer"]
    assert a["prompt_version"] == prompts.PROMPT_VERSION and a["footer"].endswith(f"Prompt {prompts.PROMPT_VERSION}.")
    stored = client.get(f"/api/chat/sessions/{sid}").get_json()["messages"]
    assert stored[1]["prompt_version"] == prompts.PROMPT_VERSION and "footer" in stored[1] and "footer" not in stored[0]


def test_footer_says_when_no_data_was_consulted():
    assert "No planner data was consulted" in prompts.footer([], [])


def test_scenario_memory_is_injected_and_persisted(client, monkeypatch):
    seen = _llm(monkeypatch, [_msg("ok")])
    sid = _session(client)
    r = client.patch(f"/api/chat/sessions/{sid}", json={"scenario": "Retire at 52", "memory": "Spouse keeps working to 55"})
    assert r.status_code == 200 and r.get_json()["scenario"] == "Retire at 52"
    assert client.get(f"/api/chat/sessions/{sid}").get_json()["memory"] == "Spouse keeps working to 55"
    client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "hello"})
    system = seen[0]["messages"][0]["content"]
    assert "Retire at 52" in system and "Spouse keeps working to 55" in system and system.startswith(prompts.SYSTEM)
    # a rename leaves memory alone, and memory edits leave the title alone
    client.patch(f"/api/chat/sessions/{sid}", json={"title": "Plan B"})
    got = client.get(f"/api/chat/sessions/{sid}").get_json()
    assert got["title"] == "Plan B" and got["memory"] == "Spouse keeps working to 55"


def test_other_sessions_do_not_see_memory(client, monkeypatch):
    seen = _llm(monkeypatch, [_msg("ok")])
    a, b = _session(client), _session(client)
    client.patch(f"/api/chat/sessions/{a}", json={"memory": "secret scenario note"})
    client.post(f"/api/chat/sessions/{b}/messages", json={"content": "hello"})
    assert "secret scenario note" not in seen[0]["messages"][0]["content"]


def test_ollama_routes_through_litellm_with_api_base_and_no_key(client, monkeypatch):
    cfg_in = {"provider": "ollama", "fast_model": "ollama/llama3.1", "reasoning_model": "ollama/qwen2.5", "api_base": "http://ollama:11434"}
    assert client.put("/api/settings/llm", json=cfg_in).status_code == 200
    seen = []

    def fake(**kw):
        seen.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=_msg("local reply"))])

    monkeypatch.setattr(litellm, "completion", fake)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with client.application.app_context():
        assert isinstance(llm_router.get_config(), LLMConfig)
        text, _ = llm_router.chat_with_tools("reasoning", "sys", [{"role": "user", "content": "hi"}], [], lambda n, a: "{}")
        assert text == "local reply"
        assert llm_router.complete("fast", "s", "u") == "local reply"
    assert all(k["api_base"] == "http://ollama:11434" and k["api_key"] is None for k in seen)
    assert [k["model"] for k in seen] == ["ollama/qwen2.5", "ollama/llama3.1"]


def test_every_engine_has_a_chat_tool():
    names = {n for n, _, _ in chat_tools.TOOLS}
    required = {
        "get_withdrawal_plan",
        "get_roth_conversion_plan",
        "get_rebalance_plan",
        "get_tax_lot_report",
        "get_spending_actuals",
        "get_action_items",
        "get_onboarding_status",
        "get_chart_data",
        "run_fire_scenario",
        "get_cash_plan",
    }
    assert required <= names


def test_tool_results_are_json_objects(client):
    with client.application.app_context():
        for name in ("get_action_items", "get_onboarding_status", "get_chart_data", "get_rebalance_plan", "get_tax_lot_report"):
            out = json.loads(chat_tools.dispatch(name, {}))
            assert isinstance(out, dict), name
