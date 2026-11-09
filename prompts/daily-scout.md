You run the argmax daily scout on the Google Ads account configured in `argmax.yaml`. It is read-only except for
the bid steps in step 3 and the exact-match junk negatives in step 4. This repo (the owner's private copy) is
checked out in your working directory. AGENTS.md holds the rules; this file holds the steps.

In CI: if the environment variable `ARGMAX_COMMIT` is `workflow`, skip every git commit, pull and push step: the
workflow commits the runtime files after you finish. Everything else stays the same.

1. Setup: install uv if missing (`pip install -q uv`), then `uv sync`. Google Ads credentials are in GOOGLE_ADS_*
   environment variables (or google-ads.yaml); the config is `argmax.yaml` (or ARGMAX_CONFIG / ARGMAX_CONFIG_YAML).
   Run `uv run scripts/doctor.py --offline`. If config or STRATEGY.md is missing or onboarding is not complete,
   stop: print that setup is incomplete and, if the tracker works, comment that on the newest weekly report. If the
   repo line FAILs (the repo is public), stop and print only that line: write nothing to the repo or the tracker.
2. `uv run scripts/daily_scout.py`. It changes nothing in Google Ads. It adds yesterday to
   reports/daily/week-<Monday>.json, saves the day's clicks for ref code matching (when ref codes are on),
   backfills a missed earlier day (MISSED), and prints NOTIFY lines (ALERT, NEWS, WIN, REF, REF_GAP, MISSED) or QUIET.
3. `uv run scripts/daily_bids.py --apply`. It steps the bids of winning-topic Search ad groups that are still in
   their stepping window, within its own limits, adds a "bids" section to the same day, and prints NOTIFY lines
   (BID, and BUDGET when a group starts being held by its campaign budget). Treat them as NOTIFY lines. If it prints
   FAIL, mention it in step 6. Make no other bid changes.
4. `uv run scripts/daily_negatives.py --apply`. It blocks junk search terms of the last days as exact-match campaign
   negatives (keyword_review's negative rule; winning-topic terms without a junk word are held for the weekly),
   logs them to reports/changes.jsonl, adds a "negatives" section to the same day, and prints NOTIFY lines (NEG,
   NEG_HELD). Treat them as NOTIFY lines. If it prints FAIL, mention it in step 6. Add no other keywords or negatives.
5. Commit only the daily files and the ledger (they are gitignored on purpose, so add them by path):
   `git add -f reports/daily/ reports/changes.jsonl && git commit -m "Daily scout <date>"`, then
   `git pull --rebase` and `git push`. If the rebase conflicts (the weekly pushed first): copy this run's lines of
   reports/changes.jsonl (routine "daily") to a temp file, `git rebase --abort`, `git reset --hard origin/<branch>`,
   append those lines back, run steps 2 to 4 again (step 3 will not step twice; step 4 will not add a negative
   twice and rebuilds the day's "added" list from the ledger), commit and push. If the push is still refused,
   mention it in step 6.
6. If any script printed NOTIFY lines (or failed): comment on the newest weekly report (how: read
   `trackers/<tracker.backend>.md`, verb "comment on the newest weekly report"), starting with "[argmax] Daily scout
   <data date> (run <today>):", then the NOTIFY lines as-is, then one sentence per ALERT on the likely cause and the
   fix (use AGENTS.md), written in `business.report_language`. If you can send a push notification, send one with the
   first line. If no script printed a NOTIFY line: post nothing.
7. Never change the account beyond steps 3 and 4, and never create reports or decisions: fixes happen in the weekly
   or after a human "yes". Never put CRM names or emails anywhere. Never use em-dashes. Commit messages carry no
   co-author line.
