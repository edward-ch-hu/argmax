# Onboarding

Say "onboard me" (or "continue onboarding") to your agent in your private argmax copy. The agent follows this file.
It works the same in Claude Code, Codex and Grok; where they differ it points to `docs/agents/<agent>.md`.

---

You are onboarding a new argmax user. Read `AGENTS.md` first. Rules for the whole session:
- One step at a time. Explain what the step is for in one or two lines, do it, check it, record it, then ask before
  moving on. Adapt: skip what the user already has, but check it.
- Progress lives in `.argmax/onboarding.json` (gitignored, no secrets): `uv run scripts/onboarding.py` shows it,
  `uv run scripts/onboarding.py next` gives the next step, `uv run scripts/onboarding.py set <step> <done|pending|
  skipped> "<short note>"` records one. Before uv exists (step a), keep notes in chat and record them once it does.
  On "continue onboarding", run `uv run scripts/onboarding.py` and resume at the first step not done or skipped.
- Never echo secrets (developer token, client secret, refresh token, API keys) back in chat, and never write them
  anywhere but `google-ads.yaml`, `client_secret*.json` or environment variables (all gitignored). If the user
  pastes one in chat, put it where it belongs and tell them you will not repeat it.
- Never read CRM names or emails: only the header row and the list of status values (`crm.py inspect`).
- Never run installers, `gh auth login`, or anything that changes the Google Ads account without asking.
- `uv run scripts/doctor.py` (add `--offline` before credentials exist) is the checklist: run it whenever you are
  unsure what is missing. No em-dashes in anything you write.

## a. prerequisites
Check `git --version`, `uv --version`, and Python 3.12+ (`uv python find 3.12` or `python3 --version`; uv can
install Python itself with `uv python install 3.12`). If GitHub will be used (repo or tracker), also `gh --version`.
Offer the install command for anything missing and run it only on a yes:
- uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux), `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows), or `brew install uv`
- gh: `brew install gh`, `winget install GitHub.cli`, or https://cli.github.com
Then `uv sync` and `uv run pytest -q` (proves the engine works here). Record `prerequisites done`.

## b. repo
Explain: logs, reports and decisions will hold their ad account data, so argmax runs from their own PRIVATE copy;
the public repo is only a template. Check `git remote -v`:
- `origin` is a private repo of theirs (GitHub: `gh repo view --json visibility -q .visibility` says PRIVATE), and
  `upstream` points at the public template with push DISABLED: done.
- `origin` is the public template itself: they cloned upstream directly. Follow `BOOTSTRAP.md` steps 2 to 4 to make
  the private copy (create the private repo, repoint `origin`, add a read-only `upstream`).
- Local only is fine too (scheduling is then by hand or local cron). Record the choice in the note.

## c. google_ads_api
What this is for: the scripts talk to Google Ads through its API, which needs four things: a developer token
(identifies the app), an OAuth client (identifies the program asking for access), a refresh token (the user's
consent, stored locally), and a manager account (the API's home). Walk through, one at a time, checking each:
1. Manager account (MCC): https://ads.google.com/home/tools/manager-accounts/ , create one with the same Google
   login. In the manager: Accounts, the + button, "Link existing account", enter the ad account's customer id;
   accept the link in the ad account (Admin, Access and security, Managers).
2. Developer token: in the manager account, Admin (gear), API Center. Fill in the form; the token appears there.
   It starts at Test access (works only with test accounts). Live accounts need Basic access: apply from the same
   page; approval takes a few business days. While waiting, finish every other step and record
   `google_ads_api pending "waiting on Basic access"`.
3. Google Cloud project: https://console.cloud.google.com , project picker, New project. Then APIs and Services,
   Library, search "Google Ads API", Enable. If they will use a Google Sheet as CRM, also enable "Google Sheets API".
4. OAuth consent screen: APIs and Services, OAuth consent screen (Google Auth Platform, Branding / Audience): user
   type External, app name "argmax", their email; under Audience add their Google account as a test user.
5. OAuth client: APIs and Services, Credentials, Create credentials, OAuth client ID, application type "Desktop
   app". Download the JSON into the repo root as `client_secret.json` (gitignored).
6. `cp google-ads.example.yaml google-ads.yaml`; the user fills in `developer_token`, `client_id`,
   `client_secret` (from the JSON) and `login_customer_id` (the manager id, 10 digits). Offer to fill client_id and
   client_secret from `client_secret.json` yourself, without printing them.
7. `uv run scripts/get_refresh_token.py client_secret.json`: a browser opens; they sign in with the Google login that
   has access to the manager and accept. It saves the refresh token into `google-ads.yaml`.
8. `uv run scripts/accounts.py` lists the accounts the login reaches. A DEVELOPER_TOKEN_NOT_APPROVED error means
   Basic access is still pending (test accounts only): record pending and go on.
Record `google_ads_api done` once `accounts.py` lists their live account.

## d. account
`uv run scripts/accounts.py --json`. Show the list (id, name, currency, time zone, manager or ad account) and let
them pick the ad account to run. Take currency and time zone from the API, do not ask. If it is reached through a
manager, that manager id is the `login_customer_id`. Write a first answers file in `.argmax/answers.yaml`:
```yaml
account: {customer_id: "<id>", login_customer_id: "<manager id or empty>", name: "<name>", currency: <CUR>, timezone: <Area/City>}
limits: {daily_budget_cap: <current total daily budget of enabled campaigns, rounded up>}
topics: [general]          # placeholder until step g
conversions: {lead_signals: [<a conversion action name>]}
```
(Read the current budgets and conversion action names with `uv run scripts/gaql.py` once `argmax.yaml` exists, or
ask; step h confirms the cap.) Run `uv run scripts/init.py --answers .argmax/answers.yaml --dry-run`, show the
result, and on a yes `uv run scripts/init.py --answers .argmax/answers.yaml` (add `--force` when rewriting). Then
`uv run scripts/check_connection.py`. Keep `.argmax/answers.yaml` up to date in later steps and re-run init with
`--force`; it is the single source the config is built from during onboarding.

## e. tracker
Ask which tool they use for notes or tasks: GitHub Issues, ClickUp, Notion, Linear, other, or none.
- GitHub Issues (`github-issues`): needs `gh auth status` OK and a GitHub `origin`. Create the labels from
  `trackers/github-issues.md`.
- None: `files` backend, decisions and reports as markdown files in the repo. Nothing to set up.
- ClickUp, Notion, Linear: an MCP connector in their agent. Set it up following `docs/agents/<agent>.md` (section
  "MCP connectors") and `trackers/<backend>.md`; collect the list, database or team ids it needs.
- Other (Jira, Trello, Asana...): explain the `files` fallback works today, and that a new backend is a markdown
  file: copy the closest `trackers/*.md`, keep the seven verbs, and add the name to `TRACKERS` in
  `scripts/config.py`. Offer to draft it with them if their agent has a connector for that tool.
Put `tracker: {backend: ..., <backend section>: {...}}` in the answers, re-run init. Test the loop: create a decision
titled "Unless you say no: argmax tracker test" due today with the 4-line body, list open decisions to see it, add
a comment, then resolve and close it. Show the user where it appeared. Record `tracker done`.

## f. crm
Ask where real leads and sales are recorded: nowhere yet (none), a CSV export, or a Google Sheet. For a CRM app
(HubSpot, Pipedrive...), a scheduled CSV or Sheet export works.
- CSV: `uv run scripts/crm.py inspect --csv <path>`; Sheet: `uv run scripts/crm.py inspect --sheet <id> --range
  "<tab>!A1:Z"` (the Sheets API must be enabled, step c3). This prints only the header row.
- Map the columns with them: which header is the lead date (required), status (required), topics or product,
  deal value (and its label, e.g. MRR, order value), name and email (used only for privacy checks), a lead id if
  any. Then run inspect again with `--status-column "<header>"` to list the status values, and map each to talking,
  trial, won, lost_after_trial or lost_no_trial.
- Deal value currency: if it differs from the account currency, set `crm.deal_value_fx` (multiply deal values by it).
- Optional ref codes (`docs/ref-codes.md`): only if they can add a snippet to the site; off by default.
Put `crm: {...}` in the answers, re-run init, then `uv run scripts/doctor.py`: the crm line must be OK (unmapped
statuses show as PENDING). Record `crm done` (or `skipped` for none).

## g. strategy
Run `prompts/strategy-interview.md` with them (pick a template, interview, or port their notes). Then build the
topics from the live account: list ad groups and the top 50 keywords by spend with `uv run scripts/gaql.py` (the
queries are in the interview prompt), propose topics (substrings and whole words), `winning_topics`, and an
`ad_group_topics` map covering every enabled ad group. Update the answers, re-run init, run
`uv run scripts/strategy_check.py`. Record `strategy done`.

## h. guardrails
Confirm in plain language, defaulting to conservative values, and write them into the answers:
- "The agent may never let the total daily budget across campaigns go above <cap> <currency>." (`limits.daily_budget_cap`; default: today's total)
- "It may move any ad group's bid by at most <20>% a week, never below <floor> or above <ceiling>." (`limits.*`; default ceiling: 2x today's highest bid)
- "For the topics that close deals, it may step bids daily by <10>% for <14> days to find the right visibility." (`stepping.*`)
- "It may block up to <10> junk search terms a day." (`negatives.max_per_day`)
- "It may start <1> ad copy test a week, only with claims quoted from your site." (`ad_tests.*`; off without `website.base_url`)
- Autonomy: show AGENTS.md "Autonomy" in five bullets; ask if anything should be stricter or looser and write it
  under "Agent autonomy overrides" in STRATEGY.md.
Re-run init, then `uv run scripts/doctor.py`. Record `guardrails done`.

## i. first_run
Read-only and validate-only, so nothing changes in the account:
1. `uv run scripts/daily_scout.py` and explain its output (topics, winning-topic terms, NOTIFY lines or QUIET).
2. `uv run scripts/daily_bids.py` and `uv run scripts/daily_negatives.py` without `--apply`: what they would do.
3. `uv run scripts/keyword_review.py 7`, then `uv run scripts/topic_table.py`: walk them through the numbers.
4. Write a first weekly log `log/<today>.md` (template in AGENTS.md; "Changes made: none, onboarding run") and
   create a first weekly report and one real decision if the data suggests one (otherwise a sample decision
   "Unless you say no: keep the current daily budget cap" due in 7 days) in their tracker, so they see the loop.
5. Commit their files by path: `git add -f argmax.yaml STRATEGY.md log/ reports/ decisions/ && git commit -m
   "argmax onboarding: config, strategy, first run"`, and push to `origin` (ask first). Record `first_run done`.

## j. scheduling
Read `docs/agents/<their agent>.md` and set up the three routines (daily scout Tuesday to Sunday, weekly review
Monday, monthly review on the 1st, all in the account time zone) the way that agent supports: Claude Code cloud
routines, a GitHub Actions workflow (`.github/workflows/*.example`), cron with a headless CLI, or by hand. Put the
secrets where that doc says (cloud environment variables or GitHub Actions secrets), never in the repo. Run one
routine once by hand to prove it. Record `scheduling done` (or `skipped "runs by hand"`).

## Done
`uv run scripts/onboarding.py` shows every step done or skipped; `uv run scripts/doctor.py` shows no FAIL. Tell
them: what runs when, where reports and decisions appear, how to reply ("yes", "no", "reverse"), and that
"update argmax from upstream" pulls engine updates (`docs/updating.md`).
