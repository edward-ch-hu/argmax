# Setup (manual reference)

The fastest path is your agent: say "onboard me" (`prompts/onboarding.md`). This file is the same setup by hand.
`uv run scripts/doctor.py` shows what is still missing at any point.

## 0. Your private copy
argmax keeps logs, reports and decisions about your account in the repo, so run it from a private copy: clone the
public repo, keep it as a read-only `upstream`, and push to a new private repo (`BOOTSTRAP.md`):
```bash
git clone https://github.com/edward-ch-hu/argmax my-argmax && cd my-argmax
git remote rename origin upstream && git remote set-url --push upstream DISABLED
gh repo create my-argmax --private --source . --remote origin --push
```
Never a GitHub fork (always public). The shared history makes updates a plain merge (`docs/updating.md`). Install
`git`, `uv` (https://docs.astral.sh/uv/) and, for GitHub, `gh`. Then `uv sync && uv run pytest -q`.

## 1. Google Ads API access
Since September 9, 2026 you need no developer token and no manager account: API access belongs to the Google Cloud
project that owns your OAuth client, and your own Google login (the one that opens the ad account) signs in.
1. **Google Cloud project**: https://console.cloud.google.com , new project.
2. **Enable the Google Ads API**: APIs and Services, Library, "Google Ads API", Enable (also **Google Sheets API** if
   your CRM is a Google Sheet). This alone gives the project **Test** access: test accounts only.
3. **OAuth consent screen** (Google Auth Platform): External, app name "argmax", your email. Then, under Audience,
   set **Publishing status: In production** ("Publish app"). This matters: an External app left in "Testing" gets
   refresh tokens that expire after 7 days, and every routine then fails with `invalid_grant`. A personal app in
   production needs no Google verification for your own use; the consent page will say "Google hasn't verified this
   app". That warning is expected for an app you made yourself and safe to click through (Advanced, Go to argmax).
4. **OAuth client**: Credentials, Create credentials, OAuth client ID, **Desktop app**. Download the JSON into the
   repo root as `client_secret.json` (gitignored).
5. **Apply for Explorer**: the Google Ads API Overview page, https://console.cloud.google.com/google/ads-apis/overview
   (same project). Check the current level says Test, expand "Upgrade access level", check the next level says
   Explorer, click "Apply for access". It is usually approved automatically. Explorer is enough for argmax (see
   "API access levels and quota" below); put the level you see there in `argmax.yaml` as `api.access_level`.

<details>
<summary>Already have a developer token or a manager account?</summary>

They keep working. An existing developer token may stay in `google-ads.yaml` (or `GOOGLE_ADS_DEVELOPER_TOKEN`):
Google ignores it now and will reject it in a future major API version, so you can also delete it. Your token's
access level was moved to the Cloud project that owns your OAuth client, if that project used it in the 90 days
before the sunset; read the level on that project's Overview page. A manager account is needed only to manage
several accounts through the API. Set `account.login_customer_id` to the manager's id only when you reach the ad
account through that manager; when your login has direct access to the ad account, leave it empty (Google then
uses the ad account itself as the login customer).
</details>

## 2. Credentials
```bash
cp google-ads.example.yaml google-ads.yaml        # gitignored
# client_id and client_secret come from client_secret.json; get_refresh_token.py fills them in when they are
# still placeholders (and creates google-ads.yaml from the example when it is missing)
uv run scripts/get_refresh_token.py client_secret.json   # browser sign-in with the login that opens the ad account
# no browser on this machine (server, container, SSH)? add --console: it prints a URL to open on any device
uv run scripts/accounts.py                        # the accounts you can reach, with currency and time zone
```
The Python library needs no developer token from google-ads 32.0.0 on (`pyproject.toml` asks for 32 or later).
`get_refresh_token.py` writes the token into `google-ads.yaml` and never prints it, so it stays out of terminal logs
and agent transcripts. For cloud runs, copy it from that file into the `GOOGLE_ADS_REFRESH_TOKEN` secret yourself.

## 3. argmax.yaml
```bash
cp argmax.example.yaml argmax.yaml                # or: uv run scripts/init.py (asks), or --answers <file>
uv run scripts/init.py --answers <file> --derive --dry-run   # sizes the money limits from your account
```
Money limits (`limits.daily_budget_cap`, `bid_floor`, `bid_ceiling`, `negatives.min_cost`, `held_notify_cost`,
`keyword_review.min_pause_cost`, `match_type_review.min_off_intent_spend`) are in the account currency. The example's
values suit a USD account with a CPC of about 2; `init.py --derive` sizes them from your 30-day average Search CPC,
highest bid and today's budgets (the multiples are in `scripts/init.py`), or `--cpc <amount>` from a CPC you give.
Set at least: `account` (customer_id, currency, timezone from `accounts.py`; login_customer_id only for an
account listed "via manager"), `api.access_level` (from the Overview page),
`business` (the profile below), `limits.daily_budget_cap`, `topics`, `winning_topics`, `ad_group_topics`,
`conversions.lead_signals` and `noise_signals`, `website.base_url` (or `ad_tests.enabled: false`), `crm`,
`tracker.backend`. Every field is commented in `argmax.example.yaml`. Then:
```bash
uv run scripts/check_connection.py                # config OK, account reachable, currency and time zone match
```
The business profile (`business:`) is what every report and decision is shaped by:
- `goal` (leads, sales, roas, calls or awareness) and a one-line `goal_description`; it must fit the strategy's
  "Fits goals" line (`doctor.py` warns otherwise).
- `primary_kpi` (what success is counted in) and `kpi_conversions` (the `conversions.lead_signals` that stand for it;
  empty means all of them).
- `markets`: name, countries, ad `language` (a site locale code) and an optional `campaign_prefix`. They are the one
  source for `website.locales` and `ad_tests.campaign_locales`: leave those out and they are derived.
- `report_language` (default English): reports, decisions and, unless set apart, the client update.
- `deal_currency` (default the account currency). When the CRM's deal values are in another currency, set
  `crm.deal_value_fx` to how much one unit of it is in the account currency (ROI = deal value x fx / spend).
- `bidding_end_state`: `smart_bidding` (a last phase hands bids to Google) or `manual_cpc` (the agent keeps Manual
  CPC for good; `guard.expected_bidding` must then be MANUAL_CPC). It must match STRATEGY.md's "Bidding end state"
  line; `doctor.py` checks.
Config sources, first match wins: `ARGMAX_CONFIG_YAML` (the whole YAML as text), `ARGMAX_CONFIG` (a path),
`argmax.yaml`. `ARGMAX_CUSTOMER_ID` and `ARGMAX_LOGIN_CUSTOMER_ID` override the ids. `argmax.yaml` holds no
secrets: in your private copy, commit it with `git add -f argmax.yaml` so cloud runs find it.

## 4. Strategy
`cp strategies/<template>.md STRATEGY.md` (see `strategies/README.md`) or run `prompts/strategy-interview.md`.
Check it with `uv run scripts/strategy_check.py`.

## 5. CRM
- `none` (default): no lead or win data; reports say so.
- `csv`: `crm.csv_path`, a file with a header row (export from your CRM on a schedule).
- `google_sheets`: `crm.sheet_id` and `crm.sheet_range`; read with the same Google login (the refresh token above
  includes read-only Sheets access).
Map `crm.columns` (lead_date and status required) and `crm.statuses`. `uv run scripts/crm.py inspect --csv <path>
--status-column Status` shows the headers and status values only, never names or emails. Optional:
`docs/ref-codes.md`.

## 6. Tracker
`tracker.backend`: `github-issues` (recommended, needs `gh auth login`), `files` (zero setup), `clickup`,
`notion`, `linear` (MCP connectors). Each has a how-to in `trackers/`.

## 7. Ad library (optional, for ad copy tests)
Copy `docs/ad_library.example.json` to `docs/ad_library.json` and replace it with exact quotes from your own site
and assets built on them. `uv run scripts/claims_check.py` checks it against the live site. Without it, ad tests
simply do not start.

## 8. Scheduling
| Routine | When (account time zone) | Prompt |
|---|---|---|
| Daily scout | 08:00 Tuesday to Sunday | `prompts/daily-scout.md` |
| Weekly review | 09:00 Monday | `prompts/weekly-review.md` |
| Monthly review | 10:00 on the 1st | `prompts/monthly-review.md` |

- Claude Code: cloud scheduled tasks via `/schedule` (`docs/agents/claude-code.md`).
- Codex or Grok: GitHub Actions (`.github/workflows/*.example`) or cron with the headless CLI
  (`docs/agents/codex.md`, `docs/agents/grok.md`).

Environment variables for cloud and CI runs (never commit these):
`GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN` (required), plus `GH_TOKEN` for
the github-issues tracker and `ARGMAX_CONFIG_YAML` (recommended: the guardrails lock, below). Optional: `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (only for an
account reached through a manager), `GOOGLE_ADS_DEVELOPER_TOKEN` (an old token, ignored by Google),
`GOOGLE_ADS_USE_PROTO_PLUS` (defaults to True). Empty values are ignored.

The routines commit their memory (`log/`, `reports/`, `decisions/`) to your private copy with `git add -f`, because
those paths are gitignored in the public repo. That is what lets the next run read the last one.

## Guardrails lock
The scripts refuse anything outside the limits, and no argument at run time changes that. What keeps the limits
themselves out of the agent's reach is the run environment, not the agent's good will: a routine agent works in a
checkout it can write to, so it could edit `argmax.yaml` or a script before running it. Three things close that:
1. **Config in the environment.** Put the whole config in `ARGMAX_CONFIG_YAML` (a GitHub Actions secret or
   variable, the cloud task's environment, or the cron environment). `config.py` reads it before any file, so with
   it set `argmax.yaml` in the repo is advisory: keep it as a readable copy, but the scripts never read limits from
   it. `doctor.py` says "config locked by ARGMAX_CONFIG_YAML" and warns when the file and the variable differ. To
   change a limit, you change the variable; the agent cannot.
2. **A headless allowlist.** Routines may run `uv run scripts/*`, `uv sync`, the git commands that commit their
   files and the tracker's `gh` commands, and edit only `log/`, `reports/`, `decisions/`, `.argmax/tmp/` and
   `STRATEGY.md` where the agent supports path rules (Claude Code does; `docs/agents/<agent>.md` has each agent's
   exact list and what it cannot scope). Never `uv *` (it allows `uv run python -c`, a direct API call), never edits
   to `scripts/` or `argmax.yaml`. The workflow examples also fail the run, and commit nothing, when the engine or
   the config changed.
3. **Visible drift.** `doctor.py` prints "argmax.yaml and scripts/ last changed <date> <commit> by <author>", and
   every weekly report copies it into its header. A change you did not make is the first thing to look at.
Without the lock (a local run, an agent with no allowlist) the limits still hold against every run that uses the
scripts, but nothing stops a determined agent from editing them first. Review such runs.

## 9. Manual commands worth knowing
```bash
uv run scripts/daily_guard.py                     # read-only checks for yesterday
uv run scripts/performance_snapshot.py 7          # JSON snapshot of the last 7 days
uv run scripts/gaql.py "SELECT campaign.name, metrics.clicks FROM campaign WHERE segments.date DURING LAST_7_DAYS"
uv run scripts/keyword_review.py                  # writes reports/keyword-review-<date>.md and .json
uv run scripts/apply_keyword_review.py reports/keyword-review-<date>.json          # validate only
uv run scripts/apply_keyword_review.py reports/keyword-review-<date>.json --apply  # makes the changes
uv run scripts/topic_table.py                     # rolling 90 days per topic
```

## API access levels and quota
Access levels belong to the Cloud project that owns the OAuth client (Google's page:
https://developers.google.com/google-ads/api/docs/api-policy/access-levels). argmax cannot read the level from the
API, so `api.access_level` in `argmax.yaml` records what the Overview page shows; `doctor.py` prints it against the
estimate below ("api quota" line).

| Level | How you get it | Live accounts | What it leaves out |
|---|---|---|---|
| Test | enable the Google Ads API | none (test accounts only) | everything live |
| Explorer | "Apply for access" on the Overview page, usually automatic | 2,880 operations a day | Keyword Planning, account creation, user management, billing |
| Basic | brand verification of the Cloud project first, then apply; reviewed automatically in minutes | 15,000 a day | nothing argmax uses |
| Standard | manual review, about 10 business days | unlimited | argmax does not need it |

**Explorer is enough for argmax.** The only feature it loses is Keyword Planner ideas in the weekly
`keyword_review.py`: with `api.access_level: explorer` (or `test`) and `keyword_review.ideas: auto` they are skipped
with a NOTE line, and if Google refuses the call anyway (access level or quota) the review prints a NOTE and carries
on with negatives, positives and pauses. `keyword_review.ideas: off` never asks. Apply for Basic only if you want
keyword ideas or you hit the daily limit (an operations quota error in a run).

How the estimate was counted: Google counts every Search or SearchStream request as 1 operation (whatever the
number of rows), every operation inside a mutate request as 1, other requests as 1, and failed requests too
(https://developers.google.com/google-ads/api/docs/best-practices/quotas). Counting the GAQL queries and mutate
operations in each script the routines run, and counting validate-only mutates too (Google's page does not say
whether they count, so the estimate assumes they do):

| Run | Operations | Made of |
|---|---|---|
| Daily scout (Tue to Sun) | about 40, up to 60 | `daily_scout.py` 7 queries (guard 4, topic spend and search terms 3) plus 2 to 3 with ref codes; `daily_bids.py` 5 queries plus 1 per stepped group; `daily_negatives.py` 4 to 5 queries plus up to `negatives.max_per_day` (10) negatives. Each missed day it backfills adds about 10 |
| Weekly review (Monday) | about 250 to 300, budget 400 | doctor 1; daily scout and bids about 25; snapshot 12; ad hoc `gaql.py` about 10; topic table 2; ad tests about 25; keyword review 4 queries; keyword ideas 3 + 1 per campaign + 1 per ad group (Basic only, about 30); keyword, match type and bid/budget changes validated then applied (each row twice, about 150 for 75 rows) |
| Monthly review (the 1st) | under 50 | `monthly_report.py` and the topic table, about 10 queries, on top of that day's daily scout |
| One-off | about 90 once | the first run with ref codes on collects 90 days of clicks (1 query per day) |

The busiest day (Monday) stays under 400 operations, about 14% of Explorer's 2,880, so Explorer is enough. Ad hoc
sessions with your agent (many `gaql.py` queries) share the same daily quota.

## Troubleshooting
- **invalid_grant, "Token has been expired or revoked"** (`doctor.py`, `check_connection.py` or a routine): the
  refresh token no longer works. Usual cause: the OAuth consent screen is still in "Testing", where Google expires
  refresh tokens after 7 days. Open Google Auth Platform, Audience, and click "Publish app" (Publishing status: In
  production; the "unverified app" warning on the consent page is expected for a personal app and safe to click
  through). Then run `get_refresh_token.py` again and update `GOOGLE_ADS_REFRESH_TOKEN` wherever the routines run.
  Other causes: you removed argmax's access in your Google account, or the token went unused for 6 months.
- **CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION** (older API versions: ACTION_NOT_PERMITTED; with an old token:
  DEVELOPER_TOKEN_NOT_APPROVED): the project has Test access only. Apply for Explorer (step 1.5). An approved token
  that was never used with a project did not move to it: apply for Explorer on the project that owns your OAuth client.
- **AUTHORIZATION_ERROR on live accounts right after upgrading** (known Google issue for projects upgraded after
  September 9, 2026: the upgrade is not honoured yet): create a new Cloud project, enable the Google Ads API, make a
  new Desktop OAuth client there, apply for Explorer, and run `get_refresh_token.py` again with the new
  `client_secret.json` (the refresh token belongs to the OAuth client).
- **Explorer or Basic rejected** ("does not meet the eligibility criteria", or "requires a successfully verified
  OAuth brand profile"), known Google issue: the project is on the Google Cloud Free Trial or its billing account is
  suspended or disabled. Upgrade to a paid billing account, wait a few minutes and apply again, or apply from another
  Cloud project that is already brand verified.
- **USER_PERMISSION_DENIED**: the Google login you signed in with cannot open that account. Sign in with one that
  can (`get_refresh_token.py`), or set `account.login_customer_id` to the manager account you reach it through.
- **A quota error** (RESOURCE_EXHAUSTED) mid-run: the project used its operations for the day (Explorer 2,880). The
  run stops; the next one catches up. If it happens more than once, apply for Basic.
