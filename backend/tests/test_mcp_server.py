import asyncio
import json

import pytest
from starlette.testclient import TestClient

import mcp_server
from app import create_app
from services import chat_tools


@pytest.fixture
def flask_app():
    return create_app({"DATABASE_URL": "sqlite://", "ACCESS_TOKEN": "tok", "TESTING": True})


def test_exposes_exactly_the_chat_tools(flask_app):
    server = mcp_server.build_server(flask_app)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {n for n, _, _ in chat_tools.TOOLS}


def test_no_write_style_tool_names(flask_app):
    for name, _, _ in chat_tools.TOOLS:
        assert not name.startswith(("set_", "create_", "update_", "delete_", "add_", "save_", "import_", "apply_")), name


def test_tool_call_returns_json(flask_app):
    server = mcp_server.build_server(flask_app)
    result = asyncio.run(server.call_tool("get_profile", {"args": {}}))
    text = "".join(getattr(c, "text", "") for c in getattr(result, "content", result))
    assert isinstance(json.loads(text), dict)


def test_http_requires_bearer(flask_app):
    app = mcp_server.http_app(mcp_server.build_server(flask_app), "tok")
    with TestClient(app) as c:
        assert c.post("/mcp", json={}).status_code == 401
        assert c.post("/mcp", json={}, headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.post("/mcp", json={}, headers={"Authorization": "Bearer tok"}).status_code != 401


def test_http_refuses_empty_token(flask_app):
    with pytest.raises(ValueError):
        mcp_server.http_app(mcp_server.build_server(flask_app), "")
