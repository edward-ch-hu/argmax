# Tracker: files (no external app)

Reports and decisions are markdown files in this repo, committed by the routines. Works with zero setup, on any
git host, and offline. The owner reads them on the git host's web UI (or locally) and replies by editing a line.

Config: `tracker.backend: files`. No ids. Needs only git.

Folders (git-tracked in your private copy with `git add -f`, see AGENTS.md):
- `reports/weekly/<YYYY-MM-DD>.md`, `reports/monthly/<YYYY-MM>.md`: reports.
- `decisions/<YYYY-MM-DD>-<slug>.md`: one file per decision; `decisions/closed/` once resolved.

## create report
Write `reports/weekly/<YYYY-MM-DD>.md` (or `reports/monthly/<YYYY-MM>.md`): first line `# <title>`, then the 5-line
header, a blank line, then the log entry. Commit it with the run.

## comment on the newest weekly report
Append to the newest `reports/weekly/*.md`:
```
## [adgrad] Daily scout <data date> (run <today>)
<NOTIFY lines as-is, then one sentence per ALERT>
```

## create decision
Write `decisions/<YYYY-MM-DD>-<slug>.md` (date = creation date, slug = a few words in kebab-case):
```
# Needs yes: <decision>
Due: <YYYY-MM-DD>
Status: waiting
Assignee: owner

What: <one line>
Why: <one or two lines>
If you don't reply by <date>: <default>
Reply: "yes" or "no"

Owner reply: 

## Comments
```
Tell the owner in the run's report that the file exists (path).

## list open decisions
Every `decisions/*.md` (not `decisions/closed/`). Due date from `Due:`, kind from the title prefix, status from
`Status:`. The owner's reply is the `Owner reply:` line plus any comment under `## Comments` that does not start
with `[adgrad]`. Also read review comments on any open pull request that touches `decisions/` (`gh pr view
--comments` when the host is GitHub), which some owners prefer.

## comment on a decision
Append under `## Comments`: `- [adgrad] <date>: <text>`.

## set status
Edit the `Status:` line: `waiting`, `replied` or `resolved`. A non-empty `Owner reply:` means `replied`.

## resolve a decision
Append `- [adgrad] Resolved <date>: <how>`, set `Status: resolved`, and `git mv` the file to `decisions/closed/`.

## Notes
- The owner replies by editing `Owner reply:` on the web UI and committing to the default branch, or locally and
  pushing. The routines `git pull --rebase` before reading, so a reply pushed before the run counts.
- No notifications: point the owner at `decisions/` (a watch on the repo, or the weekly report listing open files).
