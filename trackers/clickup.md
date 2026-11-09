# Tracker: ClickUp (MCP connector)

Reports and decisions are ClickUp tasks in three lists. The owner gets ClickUp notifications and replies with a
task comment, and can move a decision to "in progress" when they reply.

Config (`argmax.yaml`):
```yaml
tracker:
  backend: clickup
  clickup: {weekly_list_id: "...", monthly_list_id: "...", decisions_list_id: "...", assignee: "<member id or email>"}
```
Create three lists (for example "Google Ads: Weekly Reports", "Google Ads: Monthly Reports", "Google Ads:
Decisions") and copy their ids from the list URL.

Connector: ClickUp's official hosted MCP server, `https://mcp.clickup.com/mcp` (public beta, OAuth only, no API
keys; checked 2026-11-09, https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server). How to
add it to your agent: `docs/agents/<agent>.md`, section "MCP connectors". Because it is OAuth only, it works in
interactive sessions and in Claude Code cloud routines (claude.ai connectors), but not in plain CI jobs: there,
use `github-issues` or `files`.

Tool names below are from ClickUp's MCP tool list (https://developer.clickup.com/docs/mcp-tools); if your
connector names them differently, use the equivalent.

## create report
`clickup_create_task` in `weekly_list_id` (or `monthly_list_id`): name `<YYYY-MM-DD> Google Ads weekly`, assignee
the owner, description = the 5-line header, then the log entry (markdown). The monthly's client update goes in one
comment with `clickup_create_comment`.

## comment on the newest weekly report
`clickup_filter_tasks` on `weekly_list_id`, newest first; `clickup_create_comment` on the first task:
`[argmax] Daily scout <data date> (run <today>): ...`.

## create decision
`clickup_create_task` in `decisions_list_id`: name with the kind prefix, `due_date` = the decide-by date, assignee
the owner, status "to do", description = the 4-line format.

## list open decisions
`clickup_filter_tasks` on `decisions_list_id` with statuses "to do" and "in progress" (both are open), then
`clickup_get_task_comments` for each. The owner's reply is any comment not starting with `[argmax]`.

## comment on a decision
`clickup_create_comment`: `[argmax] <text>`.

## set status
`clickup_update_task` status: `waiting` = "to do", `replied` = "in progress", `resolved` = "complete". If a reply
is unclear, ask in a comment and set it back to "to do".

## resolve a decision
`clickup_create_comment` `[argmax] Resolved <date>: <how>`, then `clickup_update_task` status "complete".
