import json
from types import SimpleNamespace

from services import chat_tools, llm_router


def _call(id_, name, args):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _msg(content=None, calls=None):
    return SimpleNamespace(
        content=content,
        tool_calls=calls,
        model_dump=lambda exclude_none=True: {
            "role": "assistant",
            "content": content,
            "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in (calls or [])],
        },
    )


def test_tool_loop_runs_tools_then_answers(client, monkeypatch):
    import litellm

    replies = iter([_msg(calls=[_call("1", "get_profile", {}), _call("2", "run_fire_scenario", {"retire_age": 52})]), _msg("done")])
    seen = []

    def fake(**kw):
        seen.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(replies))])

    monkeypatch.setattr(litellm, "completion", fake)
    monkeypatch.setattr(llm_router, "_api_key", lambda cfg: "k")
    with client.application.app_context():
        text, used = llm_router.chat_with_tools("reasoning", "sys", [{"role": "user", "content": "hi"}], chat_tools.SCHEMAS, chat_tools.dispatch)
    assert text == "done" and used == ["get_profile", "run_fire_scenario"]
    tool_msgs = [m for m in seen[1]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 2 and "success_rate" in tool_msgs[1]["content"]


def test_tools_are_read_only_and_robust(client):
    with client.application.app_context():
        assert {n for n, _, _ in chat_tools.TOOLS} == set(chat_tools.HANDLERS)
        assert "error" in json.loads(chat_tools.dispatch("nope", {}))
        assert "error" in json.loads(chat_tools.dispatch("grade_401k_menu", {"account_id": 999}))
        assert "spouse_age" in json.loads(chat_tools.dispatch("get_profile", {}))
        scen = json.loads(chat_tools.dispatch("run_fire_scenario", {"monthly_expenses_retirement": 5000}))
        assert scen["assumptions_used"]["monthly_expenses_retirement"] == 5000


def _fake_llm(monkeypatch, replies, title=None):
    import litellm

    it = iter(replies)
    monkeypatch.setattr(litellm, "completion", lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=next(it))]))
    monkeypatch.setattr(llm_router, "_api_key", lambda cfg: "k")

    def complete(*a, **k):
        if title is None:
            raise RuntimeError("down")
        return title

    monkeypatch.setattr(llm_router, "complete", complete)


def test_session_crud_and_validation(client):
    sid = client.post("/api/chat/sessions").get_json()["id"]
    assert client.get("/api/chat/sessions").get_json()[0]["id"] == sid
    assert client.get("/api/chat/sessions/999").status_code == 404
    assert client.post(f"/api/chat/sessions/{sid}/messages", json={"content": ""}).status_code == 400
    assert client.post("/api/chat/sessions/999/messages", json={"content": "x"}).status_code == 404
    r = client.patch(f"/api/chat/sessions/{sid}", json={"title": "  My plan  "})
    assert r.get_json()["title"] == "My plan" and r.get_json()["title_source"] == "user"
    assert client.delete(f"/api/chat/sessions/{sid}").status_code == 204
    assert client.get(f"/api/chat/sessions/{sid}").status_code == 404


def test_send_persists_history_and_titles(client, monkeypatch):
    _fake_llm(monkeypatch, [_msg(calls=[_call("1", "get_profile", {})]), _msg("You are on track."), _msg("Yes still.")], title='"Retirement Readiness Check."')
    sid = client.post("/api/chat/sessions").get_json()["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "Am I on track?"}).get_json()
    assert r["assistant"]["content"] == "You are on track." and r["assistant"]["tools"] == ["get_profile"]
    assert r["session"]["title"] == "Retirement Readiness Check"
    client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "And now?"})
    got = client.get(f"/api/chat/sessions/{sid}").get_json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant", "user", "assistant"]
    assert client.get("/api/chat/sessions").get_json()[0]["message_count"] == 4


def test_title_fallback_and_user_rename_kept(client, monkeypatch):
    _fake_llm(monkeypatch, [_msg("a")])  # title LLM raises -> first message, truncated
    sid = client.post("/api/chat/sessions").get_json()["id"]
    long = "Should I move my idle cash into the market given where rates and valuations are today?"
    t = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": long}).get_json()["session"]["title"]
    assert t.endswith("…") and len(t) <= 50
    sid2 = client.post("/api/chat/sessions").get_json()["id"]
    client.patch(f"/api/chat/sessions/{sid2}", json={"title": "Mine"})
    _fake_llm(monkeypatch, [_msg("b")], title="Generated")
    assert client.post(f"/api/chat/sessions/{sid2}/messages", json={"content": "hi"}).get_json()["session"]["title"] == "Mine"


def test_send_without_llm_key_is_400(client):
    sid = client.post("/api/chat/sessions").get_json()["id"]
    assert client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "hi"}).status_code == 400
    assert client.get(f"/api/chat/sessions/{sid}").get_json()["messages"] == []


def test_new_tools_return_json(client):
    with client.application.app_context():
        for name, args in [
            ("get_pensions", {}),
            ("get_early_access", {}),
            ("get_withdrawal_plan", {}),
            ("get_social_security_plan", {"haircut": 0.2, "haircut_year": 2034}),
            ("get_roth_conversion_plan", {}),
            ("get_rmd_projection", {"qcd_annual": 5000}),
            ("get_inherited_rmd", {"balance": 400000, "beneficiary_age": 50, "death_year": 2026}),
            ("get_sepp_payment", {"balance": 500000, "age": 52}),
            ("get_sepp_payment", {"balance": 500000, "age": 52, "method": "annuitization", "rate": 0.05}),
            ("get_roth_withdrawal_order", {"withdraw": 30000, "age": 50, "year": 2030, "roth_open_year": 2020, "contributions": 20000, "earnings": 5000}),
            ("get_state_health_rules", {}),
            ("get_hsa_limits", {"year": 2026, "family": True, "age": 56}),
            ("get_tax_estimate", {"ordinary": 90000, "year": 2026}),
            ("get_household_timeline", {}),
            ("get_debt_payoff_schedule", {}),
            ("get_plan_menu", {"account_id": 1}),
            ("get_ingestion_log", {}),
            ("get_data_gaps", {}),
            ("get_screener_results", {}),
            ("get_notification_status", {}),
        ]:
            out = json.loads(chat_tools.dispatch(name, args))
            assert not (isinstance(out, dict) and "error" in out), (name, out)
        assert json.loads(chat_tools.dispatch("get_data_gaps", {}))["gap_count"] > 0
        scen = json.loads(chat_tools.dispatch("run_fire_scenario", {"state": "ca", "ltc_years": 0, "health_oop_annual": 1000}))
        assert "success_rate" in scen


def test_every_read_route_family_has_a_chat_tool(client):
    """New GET endpoints should be reachable by the agent: add a tool and list the route in `covered`, or justify it in `excluded`."""
    covered = {
        "/api/profile",
        "/api/portfolio",
        "/api/portfolio/xray",
        "/api/planner/fire",
        "/api/planner/events",
        "/api/planner/barbell",
        "/api/planner/cash",
        "/api/planner/cash/plan",
        "/api/planner/cash/backtest",
        "/api/research/dcf/<sym>",
        "/api/research/watchlist",
        "/api/research/insiders/<sym>",
        "/api/research/theses",
        "/api/planner/menu-grade/<int:aid>",
        "/api/planner/debt",
        "/api/planner/withdrawals",
        "/api/planner/roth",
        "/api/planner/social-security",
        "/api/planner/savings",
        "/api/planner/strategies",
        "/api/planner/spending",
        "/api/planner/event-templates",
        "/api/planner/healthcare",
        "/api/planner/scenarios",
        "/api/planner/scenarios/compare",
        "/api/planner/tornado",
        "/api/planner/solve",
        "/api/planner/real-estate",
        "/api/planner/survivor",
        "/api/planner/assumptions",
        "/api/planner/fee-drag",
        "/api/planner/health",
        "/api/planner/income-streams",
        "/api/planner/stress",
        "/api/rmd",
        "/api/spending/actuals",
        "/api/onboarding",
        "/api/actions",
        "/api/charts/brackets",
        "/api/charts/cashflow",
        "/api/rmd/inherited",
        "/api/liabilities",
        "/api/pensions",
        "/api/early-access",
        "/api/early-access/sepp",
        "/api/tax/estimate",
        "/api/research/reports",
        "/api/research/screener",
        "/api/research/sectors",
        "/api/research/symbol/<sym>",
        "/api/scheduler/status",
        "/api/ingest/log",
        "/api/networth/history",
        "/api/networth/summary",
        "/api/performance",
        "/api/rebalance",
        "/api/portfolio/risk",
        "/api/tax-lots",
        "/api/tax-lots/list",
        "/api/tax-lots/sell",
        "/api/cashflows",
        "/api/accounts/<int:aid>/menu",
        "/api/holdings/unmapped",
        "/api/settings/notifications",
    }
    excluded = {
        "/api/institutions",
        "/api/export/json",
        "/api/export/report.<fmt>",
        "/api/share/<token>/report.<fmt>",
        "/api/ingest/templates",
        "/api/simplefin",
        "/api/spending/transactions",
        "/api/spending/rules",
        "/api/liabilities/help",
        "/api/settings/llm",
        "/api/health",
        "/api/ready",
        "/api/chat/sessions",
        "/api/chat/sessions/<int:sid>",
    }
    gets = {r.rule for r in client.application.url_map.iter_rules() if r.rule.startswith("/api/") and "GET" in r.methods}
    assert gets - covered - excluded == set()
