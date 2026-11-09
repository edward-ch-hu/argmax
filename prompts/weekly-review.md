You run the argmax weekly review of the Google Ads account configured in `argmax.yaml` (Monday morning, account
time zone). This repo (the owner's private copy) is checked out in your working directory. AGENTS.md holds the
rules (Autonomy, decisions, facts, templates); this file holds the steps. For every tracker action, read
`trackers/<tracker.backend>.md` for how. Write the log, the report, decisions and comments in
`business.report_language` (AGENTS.md "Reporting" lists the fixed English parts). Success means
`business.primary_kpi` toward `business.goal`, nothing else.

In CI: if the environment variable `ARGMAX_COMMIT` is `workflow`, skip every git commit, pull and push step: the
workflow commits the runtime files after you finish. Everything else stays the same.

1. Setup: install uv if missing (`pip install uv`), then `uv sync`. Run `uv run scripts/doctor.py`. If the repo
   line FAILs (the repo is public), stop and print only that line: write nothing to the repo or the tracker. If
   config, credentials or API access FAIL, create a report titled "Google Ads agent: setup failed <date>" with the
   doctor output (no secrets), and stop. If onboarding is incomplete, report that and stop. Keep doctor's
   "guardrails" line for the report header.
2. Read, before deciding anything:
   - AGENTS.md (follow it exactly), the business profile (`business:` in argmax.yaml: goal, primary KPI and its
     conversion actions, markets, report language) and STRATEGY.md (phase, Evidence rules, topic spend targets,
     overrides).
   - The 3 newest weekly logs in log/, and the newest log/*-monthly.md with its reports/monthly/<YYYY-MM>.json.
   - The comments on the last 2 weekly reports and on the newest monthly report.
   - Every open decision and its comments, including the ones the monthly raised. Handle each as AGENTS.md
     "Decisions and approvals" says: act on a "yes", drop a "no", apply or expire the overdue ones, then resolve it.
     Topic spend targets: a "Needs yes" set applies only on a "yes"; an "Unless you say no" update applies after
     its due date unless the owner said no. Applying means editing STRATEGY.md's table ("approved <date>") and its
     Change log.
3. If the newest log says changes were prepared but not applied, check the live account and apply what is still
   missing (validate first, then --apply).
4. Data:
   - `uv run scripts/daily_scout.py` (records Sunday, since the daily skips Mondays; it also backfills and prints
     MISSED), then `uv run scripts/daily_bids.py --apply`. Keep both scripts' NOTIFY lines.
   - `uv run scripts/performance_snapshot.py 7 --out reports/snapshot-<date>.json`, plus `uv run scripts/gaql.py
     "<query>"` for anything specific. Compare with last week's log.
   - Read reports/daily/week-<last Monday>.json (one entry per day, Monday to Sunday).
   - `uv run scripts/crm.py --since <last Monday>` (new leads, the funnel, the ref fill rate) and
     `uv run scripts/topic_table.py` (rolling 90 days per topic). Topic-level decisions use only this 90-day view.
4b. Ad tests (skip when `ad_tests.enabled` is false; AGENTS.md "Ad copy tests"):
   - `uv run scripts/claims_check.py`. FAIL lines mean the site changed: do not edit the library or regular ads;
     create one "Needs yes: website changed, library revision session" decision (failed claims, pages, ads that use
     them; check for an open one first). NOTIFY SITE_UNREACHABLE: report it, start no new test this week, go on.
   - Reverse first: for each open "Done, reply reverse to undo" ad test decision with a "reverse" reply, run
     `uv run scripts/ad_test.py reverse <test id>` (validate) and `--apply`, then resolve it. Resolve the ones past
     their due date with no reply as kept.
   - `uv run scripts/ad_test.py evaluate --apply`. Keep its TEST lines for the log. For each test it concluded,
     create a decision "Done, reply reverse to undo: <campaign / ad group> ad test, <winner> won", due in 14 days.
   - `uv run scripts/ad_test.py plan`. With a free slot and an ELIGIBLE group, start at most the configured number
     of new tests this week, winning-topic groups first: one hypothesis from the data (search terms, lead-signal
     terms, what the control says and lacks). Write reports/ad-test-<date>.json with 8 to 15 headline and 2 to 4
     description asset ids from the library and a final URL that is a library page; run `uv run scripts/ad_test.py
     create reports/ad-test-<date>.json` (validate) and `--apply`. If it prints FAIL, fix the file; never work
     around it. Never edit the library.
5. Observe: 3 to 5 observations backed by numbers (what changed vs last week, and the likely cause), judged against
   `business.primary_kpi` (and `business.kpi_conversions` as its Google Ads stand-ins). Always include spend per
   topic vs CRM leads and wins per topic, the ref fill rate (when ref codes are on), and every ref-matched
   lead. Follow STRATEGY.md's Evidence rules: no defunding below the floor, no topic judged on one week or one
   month, noise signals never used as evidence.
6. Optimise, inside AGENTS.md's Autonomy and the current phase in STRATEGY.md:
   - Daily negatives first: list this week's negatives the daily added (ledger lines with routine "daily" and field
     "negative", and the days' `negatives` sections). Undo any that blocks buyer intent with
     `uv run scripts/daily_negatives.py undo "<term>" --campaign "<name>" --reason "<why>"` (validate) and
     `--apply`. Report them all in the log, with the undone ones and why.
   - Keywords: `uv run scripts/keyword_review.py`, decide each row's `approve` in the JSON, then
     `uv run scripts/apply_keyword_review.py <json>` (validate) and `--apply`. Set `approve` false for a term undone
     above. Move a `held_winning` row to `negatives` only when it is clearly off-intent. Winning-topic search terms
     with clicks in the daily files are keyword candidates. A NOTE that keyword ideas were skipped (Explorer access,
     `keyword_review.ideas: off`, or Google refused Keyword Planner) is expected: mention it once in the log, not as
     a failure.
   - Match types, in the first weekly of each month only: `uv run scripts/match_type_review.py`. When it proposes
     anything, create one decision "Unless you say no: Tighten <n> keywords to phrase/exact" (due in 7 days) with
     the top rows and the JSON path. In the first weekly after its due date with no "no": set `approve` true on its
     rows and apply it with `apply_keyword_review.py` (validate, then `--apply`), then resolve the decision.
   - Settled winning groups (their daily bids section says "settled"): read the last 7 days of rank-lost impression
     share and make one move toward `stepping.rank_lost_band`: raise when over it, lower when under it with enough
     impressions, hold when the campaign lost over `stepping.budget_lost_max` to budget (fix the budget instead).
   - Bids, budgets and statuses: write reports/changes-<date>.json (shape in scripts/apply_changes.py) with a reason
     and an expected_effect per item (stated in terms of `business.primary_kpi` where it can be), run `uv run
     scripts/apply_changes.py <json>` (validate) and `--apply`. If it prints FAIL, fix the file; never work around
     it. Move toward the approved topic spend targets using spend-side data only.
   - Anything else (rare): a script under scripts/, validate first, then --apply.
7. Create one decision per new proposal (check for an open duplicate first). Then write log/<YYYY-MM-DD>.md with
   the weekly template in AGENTS.md, including Ad tests, Routine health and Open proposals.
8. Commit by path (runtime files are gitignored on purpose):
   `git add -f log/<YYYY-MM-DD>.md reports/ decisions/ STRATEGY.md && git commit -m "Weekly review <YYYY-MM-DD>"`,
   then `git pull --rebase` and `git push`. If the rebase conflicts: copy this run's files (the log, the snapshot,
   the review and changes JSON files, reports/ad_tests.json, reports/claims_check.json, decisions/, STRATEGY.md and
   this run's lines of reports/changes.jsonl) to `.argmax/tmp/`, `git rebase --abort`, `git reset --hard
   origin/<branch>`, copy them back (append the ledger lines), run `uv run scripts/daily_scout.py <Sunday>` and
   `uv run scripts/daily_bids.py --apply` again (both safe to re-run), commit and push. Do not re-run the other
   apply scripts or ad_test.py: those changes are already live. If pushing is still refused, push a branch and say
   so in the report.
9. Create the weekly report "<YYYY-MM-DD> Google Ads weekly": the header from AGENTS.md (Reporting: 6 lines weekly, 5 monthly), then
   the log entry. Never use em-dashes. Never put CRM names or emails anywhere. Commit messages carry no co-author
   line.
