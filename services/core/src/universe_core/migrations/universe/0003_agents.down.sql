-- Reverts 0003_agents.

DROP TABLE mcp_servers;
DROP TABLE usage_ledger;
DROP TRIGGER memories_au;
DROP TRIGGER memories_ad;
DROP TRIGGER memories_ai;
DROP TABLE memories_fts;
DROP TABLE memories;
DROP TABLE permission_rules;
DROP TABLE approvals;
DROP TABLE task_steps;
DROP TABLE agent_tasks;
