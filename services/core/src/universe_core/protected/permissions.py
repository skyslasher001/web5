"""Permission rules (ARCHITECTURE.md §4.1 `permission_rules`, §7.3). PROTECTED CORE.

Rules are written only through this store, from your UI session, never by an agent. A rule matches an
agent (or `*`) and a tool name or glob (`vault.*`) and says allow, ask or deny.
"""

import json
import sqlite3
from fnmatch import fnmatchcase
from typing import Any, Literal

from pydantic import BaseModel, Field

from universe_common.ids import uuid7
from universe_common.timeutil import utcnow

RuleDecision = Literal["allow", "ask", "deny"]


class PermissionRule(BaseModel):
    id: str
    agent_id: str
    tool: str
    decision: RuleDecision
    applies_when_tainted: bool
    created_at: str
    expires_at: str | None


class RuleRequest(BaseModel):
    agent_id: str = Field(default="*", pattern=r"^(\*|[a-z][a-z0-9-]{1,31})$")
    tool: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_.*-]+$")
    decision: RuleDecision
    applies_when_tainted: bool = False
    expires_at: str | None = None


def _rule(row: sqlite3.Row) -> PermissionRule:
    return PermissionRule(
        id=row["id"],
        agent_id=row["agent_id"],
        tool=row["tool"],
        decision=row["decision"],
        applies_when_tainted=bool(row["applies_when_tainted"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def _specificity(rule: PermissionRule) -> tuple[int, int, int]:
    # An exact agent beats `*`; an exact tool beats a glob; a longer glob beats a shorter one.
    return (int(rule.agent_id != "*"), int("*" not in rule.tool), len(rule.tool))


class PermissionStore:
    def __init__(self, conn: sqlite3.Connection, audit: Any) -> None:
        self._conn = conn
        self._audit = audit

    def list(self) -> list[PermissionRule]:
        return [_rule(r) for r in self._conn.execute("SELECT * FROM permission_rules ORDER BY created_at")]

    def add(self, request: RuleRequest, *, actor: str = "user") -> PermissionRule:
        if not actor == "user":
            raise PermissionError("only you can change permission rules")
        row = self._conn.execute(
            "INSERT INTO permission_rules (id, agent_id, tool, decision, scope, applies_when_tainted, created_at,"
            " expires_at) VALUES (?, ?, ?, ?, '{}', ?, ?, ?) RETURNING *",
            (
                uuid7(),
                request.agent_id,
                request.tool,
                request.decision,
                int(request.applies_when_tainted),
                utcnow(),
                request.expires_at,
            ),
        ).fetchone()
        rule = _rule(row)
        self._audit(
            actor=actor,
            action="permission.changed",
            target_type="permission_rule",
            target_id=rule.id,
            details={"op": "add", **json.loads(request.model_dump_json())},
        )
        return rule

    def add_from(self, body: dict[str, Any], *, actor: str = "user") -> PermissionRule:
        """Validate a request body (raises ValueError) and add the rule."""
        return self.add(RuleRequest.model_validate(body), actor=actor)

    def remove(self, rule_id: str, *, actor: str = "user") -> bool:
        if not actor == "user":
            raise PermissionError("only you can change permission rules")
        removed = bool(self._conn.execute("DELETE FROM permission_rules WHERE id = ?", (rule_id,)).rowcount)
        if removed:
            self._audit(
                actor=actor,
                action="permission.changed",
                target_type="permission_rule",
                target_id=rule_id,
                details={"op": "remove"},
            )
        return removed

    def match(self, agent_id: str, tool: str) -> PermissionRule | None:
        now = utcnow()
        candidates = [
            r
            for r in self.list()
            if (r.agent_id in ("*", agent_id))
            and fnmatchcase(tool, r.tool)
            and (r.expires_at is None or r.expires_at > now)
        ]
        if not candidates:
            return None
        best = max(_specificity(r) for r in candidates)
        tied = [r for r in candidates if _specificity(r) == best]
        # Between equally specific rules the strictest wins: deny > ask > allow.
        order = {"deny": 0, "ask": 1, "allow": 2}
        return min(tied, key=lambda r: order[r.decision])
