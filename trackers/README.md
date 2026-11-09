# Tracker backends

The routines report and ask for approvals through a tracker. AGENTS.md and the prompts only use the verbs below;
each backend file says exactly how to do them. The agent reads `trackers/<tracker.backend>.md` (from `argmax.yaml`).

| Backend | Needs | Good for |
|---|---|---|
| [github-issues](github-issues.md) | `gh` CLI, logged in | the default: your private copy already lives on GitHub |
| [files](files.md) | nothing | zero setup, local-only, or any git host |
| [clickup](clickup.md) | ClickUp MCP connector | teams already on ClickUp |
| [notion](notion.md) | Notion MCP connector | teams already on Notion |
| [linear](linear.md) | Linear MCP connector | teams already on Linear |

## The verbs (every backend implements all of them)

1. **create report**: one item per weekly or monthly run. Title `<YYYY-MM-DD> Google Ads weekly` or
   `<YYYY-MM> Google Ads monthly`; body = the 5-line header from AGENTS.md, then the log entry.
2. **comment on the newest weekly report**: the daily scout's NOTIFY lines.
3. **create decision**: title `Needs yes: ...`, `Unless you say no: ...` or `Done, reply reverse to undo: ...`; a
   due date; assigned to the owner; body = the 4-line format:
   ```
   What: <one line>
   Why: <one or two lines, with the key number>
   If you don't reply by <date>: <the default, or "nothing happens">
   Reply: "yes" or "no" (or the named alternative, e.g. "keep reporting")
   ```
4. **list open decisions**, each with its due date, kind, status and all comments.
5. **comment on a decision** (a question back, or a note).
6. **set status**: `waiting` (on the owner), `replied` (the owner answered; the next run acts), `resolved`.
7. **resolve a decision**: comment `Resolved <date>: <approved and done / declined / default applied / expired, not
   done>` and close it.

## Shared rules

- Every comment the agent writes starts with `[argmax]`. Any other comment on a decision is the owner's reply,
  whatever the item's status (owner and agent often share one account in automation).
- Never create a duplicate decision: list open decisions first; if the same decision is open, comment on it.
- Never write CRM names or emails, secrets, or em-dashes into any tracker.
- The daily scout only comments; it never creates items.

## Add your own backend

Copy the closest file (an MCP one for an app, `files.md` for anything git-based), keep the seven verb headings,
replace the how-to under each, add any ids it needs under `tracker.<name>` in `argmax.yaml`, and add the name to
`TRACKERS` in `scripts/config.py`. Until then, `files` works with no setup.
