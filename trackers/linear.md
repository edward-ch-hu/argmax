# Tracker: Linear (MCP connector)

Reports and decisions are Linear issues in one team (optionally one project), told apart by labels. The owner
replies with an issue comment.

Config (`argmax.yaml`):
```yaml
tracker:
  backend: linear
  linear: {team_id: "...", project_id: "", assignee: "<user id or email>"}
```
Create labels `argmax-weekly`, `argmax-monthly`, `argmax-decision`, `needs-yes`, `unless-no`, `done-reversible`
in that team (onboarding does it through the connector).

Connector: Linear's hosted MCP server, `https://mcp.linear.app/mcp` (OAuth, or `Authorization: Bearer <Linear API
key>`, which also works headless; checked 2026-11-09, https://linear.app/docs/mcp). Setup per agent:
`docs/agents/<agent>.md`, section "MCP connectors". In CI, pass the API key from a secret as the bearer header.

Linear does not publish the tool names; they change between versions (for example `list_issues`, `list_comments`,
and `save_issue` / `save_comment` or the older `create_issue` / `create_comment`). Ask the connector for its tool
list once and use the equivalents below.

## create report
Create an issue in `team_id` (and `project_id` if set): title `<YYYY-MM-DD> Google Ads weekly`, label
`argmax-weekly` (or `argmax-monthly`), assignee the owner, description = the header lines from AGENTS.md, then the log entry.
Close the previous weekly report issue (move it to a completed state). The monthly's client update goes in one
comment.

## comment on the newest weekly report
List issues with label `argmax-weekly`, newest first; comment on the first: `[argmax] Daily scout ...`.

## create decision
Create an issue: title with the kind prefix, labels `argmax-decision` plus the kind label, due date = the
decide-by date, assignee the owner, description = the 4-line format.

## list open decisions
List issues with label `argmax-decision` that are not in a completed or canceled state, with their comments. The
owner's reply is any comment not starting with `[argmax]` whose author is the owner (the decision's assignee) or a
workspace member with edit access; ignore others and name them in the report (AGENTS.md).

## comment on a decision
Create a comment: `[argmax] <text>`.

## set status
`waiting` = the team's "Todo" (unstarted) state, `replied` = "In Progress" (started), `resolved` = "Done".

## resolve a decision
Comment `[argmax] Resolved <date>: <how>`, then move the issue to "Done".
