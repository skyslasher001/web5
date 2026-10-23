"""A hand-written MCP server for tests that need a server to misbehave in a precise way (no SDK).

Run as `python tests/support/mcp_raw_server.py <mode>`; it speaks JSON-RPC over stdio, one message per line.
Modes:
- env        — a normal server with one tool, `env`, that returns the names of its environment variables
- bad-result — answers `initialize` with a result that isn't an object
- bad-error  — answers `initialize` with an error that isn't an object
- silent     — reads requests and never answers (a server that hangs at start)
"""

import json
import os
import sys


def reply(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    mode = sys.argv[1]
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue  # a notification
        rid, method = request["id"], request.get("method")
        if mode == "silent":
            continue
        if mode == "bad-result":
            reply({"jsonrpc": "2.0", "id": rid, "result": ["not", "an", "object"]})
        elif mode == "bad-error":
            reply({"jsonrpc": "2.0", "id": rid, "error": "boom"})
        elif method == "initialize":
            info = {"name": "raw", "version": "1"}
            reply({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-11-25", "serverInfo": info}})
        elif method == "tools/list":
            tool = {"name": "env", "description": "Names of my environment variables", "inputSchema": {}}
            reply({"jsonrpc": "2.0", "id": rid, "result": {"tools": [tool]}})
        elif method == "tools/call":
            text = "\n".join(sorted(os.environ))
            reply({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}]}})
        else:
            reply({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no such method"}})


if __name__ == "__main__":
    main()
