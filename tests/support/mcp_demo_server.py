"""A real MCP server for tests, built with the official MCP Python SDK (dev-only dependency, ADR-0011).

Run as `python tests/support/mcp_demo_server.py`; it speaks MCP over stdio.
"""

from mcp.server.mcpserver import MCPServer

server = MCPServer("demo")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two whole numbers."""
    return a + b


@server.tool()
def shout(text: str) -> str:
    """Return the text in capitals."""
    return text.upper()


@server.tool()
def broken() -> str:
    """Always fails."""
    raise ValueError("this tool always fails")


if __name__ == "__main__":
    server.run("stdio")
