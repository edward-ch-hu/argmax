# Tracker: Notion (MCP connector)

Reports and decisions are pages in three Notion databases. The owner replies with a page comment and can set a
decision's Status to "Replied".

Config (`argmax.yaml`):
```yaml
tracker:
  backend: notion
  notion: {weekly_database_id: "...", monthly_database_id: "...", decisions_database_id: "..."}
```
Create three databases. Weekly and monthly: properties `Name` (title) and `Date` (date). Decisions: `Name` (title),
`Due` (date), `Kind` (select: Needs yes, Unless you say no, Done reversible), `Status` (status or select: Waiting,
Replied, Resolved), `Assignee` (person). Database ids are in the database URL.

Connector: Notion's hosted MCP server, `https://mcp.notion.com/mcp` (OAuth; a bearer token only on Business and
Enterprise plans; checked 2026-11-09, https://developers.notion.com/guides/mcp/get-started-with-mcp). Setup per
agent: `docs/agents/<agent>.md`, section "MCP connectors". OAuth-only setups work interactively and in Claude Code
cloud routines (claude.ai connectors), not in plain CI jobs: there, use `github-issues` or `files`.

Tool names below are the ones the Notion connector exposes in Claude (`notion-search`, `notion-fetch`,
`notion-create-pages`, `notion-update-page`, `notion-create-comment`, `notion-get-comments`); other clients may
name them slightly differently.

## create report
`notion-create-pages` in `weekly_database_id` (or `monthly_database_id`): Name `<YYYY-MM-DD> Google Ads weekly`,
Date = run date, page content = the header lines from AGENTS.md, then the log entry. The monthly's client update goes in one
page comment (`notion-create-comment`).

## comment on the newest weekly report
Query the weekly database sorted by Date descending (`notion-fetch` on the database, or `notion-search` within
it), then `notion-create-comment` on the newest page: `[argmax] Daily scout <data date> (run <today>): ...`.

## create decision
`notion-create-pages` in `decisions_database_id`: Name with the kind prefix, Due, Kind, Status Waiting, Assignee
the owner, content = the 4-line format.

## list open decisions
Fetch the decisions database and keep rows whose Status is not Resolved; `notion-get-comments` for each. The owner's
reply is any comment not starting with `[argmax]` whose author is the owner (the decision's assignee) or a workspace
member with edit access; ignore others and name them in the report (AGENTS.md), plus Status set to Replied by the
owner.

## comment on a decision
`notion-create-comment`: `[argmax] <text>`.

## set status
`notion-update-page` Status: Waiting, Replied or Resolved.

## resolve a decision
`notion-create-comment` `[argmax] Resolved <date>: <how>`, then `notion-update-page` Status Resolved.
