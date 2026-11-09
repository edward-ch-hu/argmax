# Tracker: Linear (MCP connector)

Reports and decisions are Linear issues in one team (optionally one project), told apart by labels. The owner
replies with an issue comment.

Config (`adgrad.yaml`):
```yaml
tracker:
  backend: linear
  linear: {team_id: "...", project_id: "", assignee: "<user id or email>"}
```
Create labels `adgrad-weekly`, `adgrad-monthly`, `adgrad-decision`, `needs-yes`, `unless-no`, `done-reversible`
in that team (onboarding does it through the connector).

Connector: Linear's hosted MCP server, `https://mcp.linear.app/mcp` (OAuth, or `Authorization: Bearer <Linear API
key>`, which also works headless; checked 2026-11-09, https://linear.app/docs/mcp). Setup per agent:
`docs/agents/<agent>.md`, section "MCP connectors". In CI, pass the API key from a secret as the bearer header.

Linear does not publish the tool names; they change between versions (for example `list_issues`, `list_comments`,
and `save_issue` / `save_comment` or the older `create_issue` / `create_comment`). Ask the connector for its tool
list once and use the equivalents below.

## create report
Create an issue in `team_id` (and `project_id` if set): title `<YYYY-MM-DD> Google Ads weekly`, label
`adgrad-weekly` (or `adgrad-monthly`), assignee the owner, description = the 5-line header, then the log entry.
Close the previous weekly report issue (move it to a completed state). The monthly's client update goes in one
comment.

## comment on the newest weekly report
List issues with label `adgrad-weekly`, newest first; comment on the first: `[adgrad] Daily scout ...`.

## create decision
Create an issue: title with the kind prefix, labels `adgrad-decision` plus the kind label, due date = the
decide-by date, assignee the owner, description = the 4-line format.

## list open decisions
List issues with label `adgrad-decision` that are not in a completed or canceled state, with their comments. The
owner's reply is any comment not starting with `[adgrad]`.

## comment on a decision
Create a comment: `[adgrad] <text>`.

## set status
`waiting` = the team's "Todo" (unstarted) state, `replied` = "In Progress" (started), `resolved` = "Done".

## resolve a decision
Comment `[adgrad] Resolved <date>: <how>`, then move the issue to "Done".
