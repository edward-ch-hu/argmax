# Setup (manual reference)

The fastest path is your agent: say "onboard me" (`prompts/onboarding.md`). This file is the same setup by hand.
`uv run scripts/doctor.py` shows what is still missing at any point.

## 0. Your private copy
argmax keeps logs, reports and decisions about your account in the repo, so run it from a private copy of this
template: `gh repo create my-argmax --private --template edward-ch-hu/argmax --clone`, then add the public repo as a
read-only `upstream` (`BOOTSTRAP.md`, `docs/updating.md`). Install `git`, `uv` (https://docs.astral.sh/uv/) and,
for GitHub, `gh`. Then `uv sync && uv run pytest -q`.

## 1. Google Ads API access
1. **Manager account (MCC)**: https://ads.google.com/home/tools/manager-accounts/ . Link your ad account
   (Accounts, +, Link existing account) and accept the link in the ad account (Admin, Access and security, Managers).
2. **Developer token**: in the manager account, Admin, API Center. It starts with Test access (test accounts only);
   apply for Basic access for live accounts (a few business days).
3. **Google Cloud project**: https://console.cloud.google.com , new project; APIs and Services, Library: enable
   **Google Ads API** (and **Google Sheets API** if your CRM is a Google Sheet).
4. **OAuth consent screen**: External, add your Google account as a test user.
5. **OAuth client**: Credentials, Create credentials, OAuth client ID, **Desktop app**. Download the JSON into the
   repo root as `client_secret.json` (gitignored).

## 2. Credentials
```bash
cp google-ads.example.yaml google-ads.yaml        # gitignored
# fill in developer_token, client_id, client_secret, login_customer_id (manager id, 10 digits)
uv run scripts/get_refresh_token.py client_secret.json   # browser sign-in; saves refresh_token
uv run scripts/accounts.py                        # the accounts you can reach, with currency and time zone
```

## 3. argmax.yaml
```bash
cp argmax.example.yaml argmax.yaml                # or: uv run scripts/init.py (asks), or --answers <file>
```
Set at least: `account` (customer_id, login_customer_id, currency, timezone: take them from `accounts.py`),
`limits.daily_budget_cap`, `topics`, `winning_topics`, `ad_group_topics`, `conversions.lead_signals` and
`noise_signals`, `website.base_url` (or `ad_tests.enabled: false`), `crm`, `tracker.backend`. Every field is
commented in `argmax.example.yaml`. Then:
```bash
uv run scripts/check_connection.py                # config OK, account reachable, currency and time zone match
```
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
`GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`,
`GOOGLE_ADS_LOGIN_CUSTOMER_ID`, `GOOGLE_ADS_USE_PROTO_PLUS=True`, plus `GH_TOKEN` for the github-issues tracker and
optionally `ARGMAX_CONFIG_YAML`.

The routines commit their memory (`log/`, `reports/`, `decisions/`) to your private copy with `git add -f`, because
those paths are gitignored in the public template. That is what lets the next run read the last one.

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
