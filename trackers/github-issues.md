# Tracker: GitHub Issues (recommended default)

Reports and decisions are issues in your private copy of the repo. The owner gets GitHub's notifications and
replies with a comment, from the web or the mobile app.

Config: `tracker.backend: github-issues`, optional `tracker.github.repo` (`owner/name`, empty = the checkout's
repo) and `tracker.github.assignee` (the owner's login). Needs the `gh` CLI, logged in (`gh auth login` locally;
`GH_TOKEN` in the cloud or CI, a token with Issues read/write on this repo only).

In the commands below, add `--repo <owner/name>` when `tracker.github.repo` is set.

## One-time setup (onboarding does this)
```bash
gh label create argmax:weekly        --color 0E8A16 --description "argmax weekly report"   --force
gh label create argmax:monthly       --color 1D76DB --description "argmax monthly report"  --force
gh label create argmax:decision      --color D93F0B --description "argmax decision"        --force
gh label create needs-yes            --color B60205 --description "silence means not done" --force
gh label create unless-no            --color FBCA04 --description "silence applies the default" --force
gh label create done-reversible      --color C5DEF5 --description "applied; reply reverse to undo" --force
gh label create owner-replied        --color 5319E7 --description "the owner answered; next run acts" --force
```

## create report
```bash
gh issue create --title "<YYYY-MM-DD> Google Ads weekly" --label argmax:weekly \
  --assignee "<assignee>" --body-file reports/weekly-issue.md
```
(`argmax:monthly` and `<YYYY-MM> Google Ads monthly` for the monthly.) Write the body to a temp file first: the
5-line header, then the log entry. Close the previous weekly report issue with `gh issue close <n>` so only the
newest stays open. The monthly's client message goes in one extra comment: `gh issue comment <n> --body-file <f>`.

## comment on the newest weekly report
```bash
n=$(gh issue list --label argmax:weekly --state all --limit 1 --json number --jq '.[0].number')
gh issue comment "$n" --body "[argmax] Daily scout <data date> (run <today>): ..."
```

## create decision
GitHub issues have no due date: it goes in the title and the body's first line.
```bash
gh issue create --title "Unless you say no: <decision> (due <YYYY-MM-DD>)" \
  --label argmax:decision --label unless-no --assignee "<assignee>" --body-file decision.md
```
Labels by kind: `Needs yes:` gets `needs-yes`, `Unless you say no:` gets `unless-no`, `Done, reply reverse to
undo:` gets `done-reversible`. Body: `Due: <YYYY-MM-DD>` on the first line, a blank line, then the 4-line format.

## list open decisions
```bash
gh issue list --label argmax:decision --state open --limit 100 \
  --json number,title,body,labels,url,createdAt
gh issue view <n> --json comments --jq '.comments[] | {author: .author.login, createdAt, body}'
```
The owner's reply is any comment not starting with `[argmax]`.

## comment on a decision
`gh issue comment <n> --body "[argmax] <text>"`

## set status
`waiting` = open without `owner-replied`; `replied` = `gh issue edit <n> --add-label owner-replied`;
set back to waiting with `--remove-label owner-replied` (e.g. after asking a clarifying question).

## resolve a decision
```bash
gh issue close <n> --comment "[argmax] Resolved <YYYY-MM-DD>: <how>"
```

## Notes
- Private repo only: issues hold spend numbers and decisions about your account.
- In GitHub Actions, the built-in `GITHUB_TOKEN` with `issues: write` permission is enough (see
  `.github/workflows/`). In Claude Code cloud routines, give the environment a `GH_TOKEN` secret.
