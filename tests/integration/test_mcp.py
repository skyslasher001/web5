"""Our minimal MCP client against a real MCP server (the official Python SDK), and MCP servers in Core."""

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH
from tests.integration.test_vault_api import BASE
from tests.support.fake_ollama import FakeOllama
from universe_agents.tools import ToolContext
from universe_core.app import create_app
from universe_core.mcp_client import MCPConnection, MCPError
from universe_core.settings import CoreSettings

SERVER = str(Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py")


async def test_client_speaks_mcp_with_the_reference_sdk() -> None:
    connection = MCPConnection("demo", sys.executable, [SERVER], {})
    await connection.start()
    try:
        assert connection.protocol == "2025-11-25" and connection.server_info["name"] == "demo"
        tools = {t["name"]: t for t in await connection.list_tools()}
        assert set(tools) == {"add", "shout", "broken"}
        assert tools["add"]["inputSchema"]["required"] == ["a", "b"]
        assert await connection.call_tool("add", {"a": 2, "b": 3}) == ("5", False)
        assert await connection.call_tool("shout", {"text": "hi"}) == ("HI", False)
        text, is_error = await connection.call_tool("broken", {})
        assert is_error and "broken" in text
        text, is_error = await connection.call_tool("add", {"a": "not a number"})  # the server validates arguments
        assert is_error and text
    finally:
        await connection.close()
    assert not connection.running
    with pytest.raises(MCPError, match="not running"):
        await connection.call_tool("add", {"a": 1, "b": 1})


async def test_a_program_that_isnt_there_is_a_clear_error() -> None:
    with pytest.raises(MCPError, match="cannot start"):
        await MCPConnection("ghost", "/nonexistent/mcp-server", [], {}).start()


@pytest.fixture
def client(make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings()), base_url=BASE) as c:
        yield c


def test_servers_you_add_become_agent_tools(client: TestClient) -> None:
    body = {"name": "demo", "command": sys.executable, "args": [SERVER], "env": {"DEMO_TOKEN": "secret-value"}}
    response = client.post("/api/v1/mcp/servers", json=body, headers=AUTH)
    assert response.status_code == 201, response.text
    server = response.json()
    assert server["running"] and server["tools"] == ["mcp.demo.add", "mcp.demo.broken", "mcp.demo.shout"]
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    tool = ctx.tools.get("mcp.demo.add")
    assert tool.tier == "write" and tool.side_effects and tool.network and tool.ask_first
    assert tool.schema()["function"]["parameters"]["required"] == ["a", "b"]
    assert tool.schema()["function"]["name"] == "mcp__demo__add"
    assert ctx.tools.for_agent(ctx.agents["core"].tools)  # Core is granted mcp.*
    assert "mcp.demo.add" in [t.name for t in ctx.tools.for_agent(ctx.agents["core"].tools)]

    duplicate = client.post("/api/v1/mcp/servers", json=body, headers=AUTH)
    assert duplicate.status_code == 409

    off = client.post(f"/api/v1/mcp/servers/{server['id']}/enabled", json={"enabled": False}, headers=AUTH).json()
    assert not off["running"] and off["tools"] == [] and ctx.tools.get("mcp.demo.add") is None
    on = client.post(f"/api/v1/mcp/servers/{server['id']}/enabled", json={"enabled": True}, headers=AUTH).json()
    assert on["running"] and "mcp.demo.add" in on["tools"]

    audit = client.get("/api/v1/audit", params={"action": "mcp.server_added"}, headers=AUTH).json()
    assert audit[0]["details"]["env_keys"] == ["DEMO_TOKEN"]
    assert "secret-value" not in str(audit)  # env values may be secrets: never logged

    assert client.delete(f"/api/v1/mcp/servers/{server['id']}", headers=AUTH).status_code == 204
    assert client.get("/api/v1/mcp/servers", headers=AUTH).json() == []
    assert ctx.tools.get("mcp.demo.shout") is None


async def test_mcp_tool_output_is_untrusted(
    make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama
) -> None:
    from universe_core.context import CoreContext
    from universe_core.mcp_client import MCPServerRequest

    ctx = CoreContext.build(make_settings())
    try:
        assert ctx.mcp is not None
        info = await ctx.mcp.add(MCPServerRequest(name="demo", command=sys.executable, args=[SERVER]))
        assert info.running
        tool = ctx.tools.get("mcp.demo.shout")
        assert tool is not None
        result = await tool.run(tool.parse({"text": "quiet"}), ToolContext("t", "core", "agent:core", False))
        assert result.content == "QUIET" and result.untrusted and not result.error
    finally:
        await ctx.close()


def test_a_server_that_fails_to_start_reports_why(client: TestClient) -> None:
    body = {"name": "ghost", "command": "/nonexistent/mcp-server"}
    server = client.post("/api/v1/mcp/servers", json=body, headers=AUTH).json()
    assert not server["running"] and "cannot start" in server["error"]
