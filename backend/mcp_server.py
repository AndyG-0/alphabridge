"""Read-only MCP server exposing AlphaBridge's deterministic planning tools to MCP clients (Claude Desktop, etc.).

Every tool is one of `services.chat_tools.TOOLS`, which are read-only by project rule (the LLM never writes data or
does arithmetic: results come from the Python engines). Two transports:

  python mcp_server.py                 # stdio (local clients; no network, no token needed)
  python mcp_server.py --http          # streamable HTTP on MCP_HOST:MCP_PORT (default 127.0.0.1:5002), path /mcp

HTTP requires `Authorization: Bearer <ACCESS_TOKEN>` (constant-time compare) and refuses to start without a token.
"""

import hmac
import json
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer


def build_flask_app():
    from app import create_app

    return create_app()


def build_server(flask_app=None) -> MCPServer:
    from services import chat_tools

    flask_app = flask_app or build_flask_app()
    server = MCPServer("alphabridge", instructions="Read-only household planning data and deterministic simulations.")

    def make(name: str, schema: dict):
        def call(args: dict[str, Any] | None = None) -> str:
            with flask_app.app_context():
                return chat_tools.dispatch(name, args or {})

        call.__name__ = name
        return call

    for name, desc, schema in chat_tools.TOOLS:
        props = json.dumps(schema.get("properties", {}))
        server.add_tool(make(name, schema), name=name, description=f"{desc}\n\nPass arguments in `args` as an object with properties: {props}")
    return server


class BearerAuth:
    """ASGI middleware: 401 unless the bearer token matches."""

    def __init__(self, app, token: str):
        if not token:
            raise ValueError("ACCESS_TOKEN must be set to serve MCP over HTTP")
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            supplied = headers.get(b"authorization", b"").decode().removeprefix("Bearer ").strip().encode()
            if not hmac.compare_digest(supplied, self.token):
                body = b'{"error":"unauthorized"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def http_app(server: MCPServer, token: str):
    return BearerAuth(server.streamable_http_app(), token)


def main(argv: list[str]) -> None:
    flask_app = build_flask_app()
    server = build_server(flask_app)
    if "--http" not in argv:
        server.run("stdio")
        return
    import uvicorn

    token = flask_app.config.get("ACCESS_TOKEN") or os.environ.get("ACCESS_TOKEN", "")
    uvicorn.run(http_app(server, token), host=os.environ.get("MCP_HOST", "127.0.0.1"), port=int(os.environ.get("MCP_PORT", "5002")))


if __name__ == "__main__":
    main(sys.argv[1:])
