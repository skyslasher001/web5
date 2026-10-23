"""Budget caps (SPEC §3 "cost-effective", ARCHITECTURE.md §1.5). PROTECTED CORE.

Every model call is in `usage_ledger`. Local calls cost $0 but count. The monthly cap applies to money;
at 50 % and 80 % of it you get a warning, at 100 % paid calls stop. Caps change only from your UI session.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from universe_common.timeutil import utcnow

CAP_KEY = "budget.monthly_cap_usd"
WARN_AT = (0.5, 0.8)


class BudgetCaps(BaseModel):
    monthly_cap_usd: float = Field(ge=0, le=10_000)


class UsageRow(BaseModel):
    key: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    calls: int


class BudgetStatus(BaseModel):
    month: str
    monthly_cap_usd: float
    spent_usd: float
    tokens_in: int
    tokens_out: int
    calls: int
    by_agent: list[UsageRow]
    by_model: list[UsageRow]


def month_start(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.strftime("%Y-%m-01T00:00:00.000Z")


class Budget:
    def __init__(self, conn: sqlite3.Connection, audit: Any, publish: Any) -> None:
        self._conn = conn
        self._audit = audit
        self._publish = publish
        self._warned: set[tuple[str, float]] = set()

    @property
    def cap(self) -> float:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (CAP_KEY,)).fetchone()
        return float(row["value"]) if row else 0.0  # $0: local models only, which cost nothing

    def set_caps(self, caps: BudgetCaps, *, actor: str = "user") -> None:
        if actor != "user":
            raise PermissionError("only you can change budget caps")
        self._conn.execute(
            "INSERT INTO settings (key, value, protected, updated_at) VALUES (?, ?, 1, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (CAP_KEY, str(caps.monthly_cap_usd), utcnow()),
        )
        self._audit(
            actor=actor,
            action="setting.changed",
            target_type="setting",
            target_id=CAP_KEY,
            details={"value": caps.monthly_cap_usd},
        )

    def set_caps_from(self, body: dict[str, Any], *, actor: str = "user") -> None:
        """Validate a request body (raises ValueError) and set the caps."""
        self.set_caps(BudgetCaps.model_validate(body), actor=actor)

    def spent(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_ledger WHERE ts >= ?", (month_start(),)
        ).fetchone()
        return float(row[0])

    def allows(self, estimate_usd: float = 0.0) -> tuple[bool, str]:
        """Before a model call. A free call is always within budget."""
        if estimate_usd <= 0:
            return True, ""
        cap, spent = self.cap, self.spent()
        if spent + estimate_usd > cap:
            self._publish("budget.cap_reached", {"cap_usd": cap, "spent_usd": round(spent, 4)})
            return False, f"The monthly budget of ${cap:.2f} is used up (${spent:.2f} spent)"
        for level in WARN_AT:
            key = (month_start(), level)
            if spent + estimate_usd >= cap * level and key not in self._warned:
                self._warned.add(key)
                self._publish("budget.warning", {"level": level, "cap_usd": cap, "spent_usd": round(spent, 4)})
        return True, ""

    def status(self) -> BudgetStatus:
        since = month_start()

        def grouped(column: str) -> list[UsageRow]:
            return [
                UsageRow(
                    key=r["key"] or "-", tokens_in=r["ti"], tokens_out=r["to_"], cost_usd=r["cost"], calls=r["calls"]
                )
                for r in self._conn.execute(
                    f"SELECT {column} AS key, SUM(tokens_in) AS ti, SUM(tokens_out) AS to_,"  # noqa: S608
                    f" SUM(cost_usd) AS cost, COUNT(*) AS calls FROM usage_ledger WHERE ts >= ? GROUP BY {column}"
                    " ORDER BY calls DESC",
                    (since,),
                )
            ]

        total = self._conn.execute(
            "SELECT COALESCE(SUM(tokens_in), 0) AS ti, COALESCE(SUM(tokens_out), 0) AS to_,"
            " COALESCE(SUM(cost_usd), 0) AS cost, COUNT(*) AS calls FROM usage_ledger WHERE ts >= ?",
            (since,),
        ).fetchone()
        return BudgetStatus(
            month=since[:7],
            monthly_cap_usd=self.cap,
            spent_usd=total["cost"],
            tokens_in=total["ti"],
            tokens_out=total["to_"],
            calls=total["calls"],
            by_agent=grouped("agent_id"),
            by_model=grouped("model"),
        )
