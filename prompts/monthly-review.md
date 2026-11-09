You run the adgrad monthly review of the Google Ads account configured in `adgrad.yaml`. It is read-only: it never
changes the account. It runs on the 1st (account time zone) and reports the month that just ended. This repo (the
owner's private copy) is checked out in your working directory. For every tracker action, read
`trackers/<tracker.backend>.md` for how.

In CI: if the environment variable `ADGRAD_COMMIT` is `workflow`, skip every git commit, pull and push step: the
workflow commits the runtime files after you finish. Everything else stays the same.

1. Setup: install uv if missing (`pip install -q uv`), then `uv sync`, then `uv run scripts/doctor.py`. Stop and
   report if config, credentials or API access FAIL.
2. `uv run scripts/monthly_report.py`. It writes reports/monthly/<YYYY-MM>.json and prints it. Sections: `history`
   (each month with a ready-made line and its CRM funnel), `revisions` (months changed since last month's report),
   `warnings` (wins with no deal value), `crm_stale`, `client_summary`, `rolling_90d_by_topic`, `change_audit`
   (from reports/changes.jsonl) and `month` (this vs last month per campaign, spend per topic, CRM funnel per
   topic, ref matches). If it prints `NOTIFY NO_BASELINE <month>`, say so in the log and treat `revisions` as not
   checked. With `crm_source: none`, the report has spend and the change audit's spend side only: say so.
3. Read AGENTS.md, STRATEGY.md, this month's files in log/, reports/ad_tests.json, the reports/daily/week-*.json
   files covering the month, the comments on the last 2 weekly reports and the last monthly report, and every open
   decision with its comments. Resolve decisions only for things this routine can do (it never changes the
   account); leave the rest for the weekly.
4. Write `log/<YYYY-MM-DD>-monthly.md` (date = run date) with this template:
   ```
   # <YYYY-MM> monthly review
   ## Results (spend, new customers, new value, ROI)
   ## Data (this month vs last month)
   ## Observations
   ## Changes made this month
   ## Did past changes work?
   ## Ad tests
   ## Leads and wins (CRM)
   ## Next month
   ## Open proposals
   ## Client update (external)
   ```
   - Results: every `history[].line` as-is, oldest first. Then one note line: which months were revised and why,
     that "at least" means the month still has open leads that could win, and that ROI = first-month deal value x
     `deal_value_fx` / spend (not lifetime return). If `crm_stale`, say the CRM has not been updated since its last
     entry, so the marked months may still change. List any `warnings` (date and fingerprint only).
   - Data: per campaign spend, clicks, impressions, conversions (lead signals and noise signals apart).
   - Observations: 3 to 5, backed by numbers. Always include spend per topic vs CRM leads and wins per topic. Judge
     topics only on `rolling_90d_by_topic` and STRATEGY.md's Evidence rules (never month vs month, noise never).
   - Changes made this month: summarised from this month's weekly logs.
   - Did past changes work?: from `change_audit`, with its note that before/after counts around one change are noisy.
   - Ad tests: each test concluded or failed this month (group, hypothesis, days, impressions, CTR and lead signals
     per arm, z, the winner or why it failed), what the winning copy says that the loser did not, the tests still
     running. "None this month" when there were none.
   - Leads and wins (CRM): leads, open, wins and deal value per topic; the funnel overall and per topic; the ref
     fill rate and ref-matched leads by campaign, ad group and keyword (ambiguous codes listed apart); CRM last
     entry and days since. No names or emails.
   - Next month: the plan, and proposals. Write STRATEGY.md edits as proposals the weekly applies: a phase change,
     and the topic spend targets set or updated from `rolling_90d_by_topic`. While no set is approved, propose (or
     keep open) the first set as "Needs yes". Once approved, an update where every topic moves 10 percentage points
     or less and the shares sum to 100 is "Unless you say no: Topic spend targets <new> (was <old>)"; a bigger move
     is "Needs yes". Propose an update only when the 90-day table supports it.
   - Open proposals: one line per open decision, including the ones this run creates in step 7.
   - Client update (external), when `report.client_update.enabled`: a message in `report.client_update.language`
     the owner can paste to a client or stakeholder as-is, about 150 to 300 words including the numbers:
     ```
     Hi, here is the Google Ads report for <Month> and the plan for next month.

     Results
     <the client_summary lines as-is: the last 3 months and the year to date>
     ("at least" means that month still has open conversations or trials, so the number can still go up.)

     Highlights
     <2 or 3 short bullets: the month's outcome in plain words>

     What we did
     <3 to 5 sentences: what we saw, what we changed and why, what it means for the business>

     Next month
     <1 or 2 bullets>
     ```
     Allowed: what a client can see or would expect (campaign focus, keyword and targeting clean-up in plain words,
     the result numbers, next month's focus, asks such as pasting ref codes into the CRM, and in plain words that an
     ad copy test ran and which message worked better, only for a concluded test). Forbidden: any mention of
     agents, automation, scripts, routines or AI tools; internal rules (budget cap, autonomy, bid-step rules); ad
     test mechanics; noise signals or conversion-tracking issues; competitor brand search terms; CRM names or
     emails; proposals awaiting approval; internal guesses about causes. Every claim must be backed by the JSON or
     the logs.
5. `uv run scripts/check_external.py log/<YYYY-MM-DD>-monthly.md`. If it fails, rewrite the client update (it prints
   the rule and line number) and run it again until it prints OK.
6. Commit by path: `git add -f reports/monthly/ log/<YYYY-MM-DD>-monthly.md decisions/ && git commit -m "Monthly
   review <YYYY-MM>"`, then `git pull --rebase` and `git push`. If the rebase conflicts: `git rebase --abort`,
   `git reset --hard origin/<branch>`, run step 2 again, write the log again, commit and push.
7. Create the monthly report "<YYYY-MM> Google Ads monthly" (the 5-line monthly header from AGENTS.md, then the log
   entry). Create one decision per new proposal from "Next month" (check for an open duplicate first). Then add one
   comment on the monthly report: a first line "[adgrad] Client update, copy from the next line:" (or "[adgrad]
   Draft, send once the CRM is updated:" when `crm_stale` is true), then only the client update.
8. Never change the Google Ads account, and never create anything other than the monthly report and decisions.
   Never put CRM names or emails anywhere. Never use em-dashes. Commit messages carry no co-author line.
