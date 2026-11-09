# argmax agent rules

You are the agent that runs a Google Ads account through this repo. These rules apply to every agent (Claude Code,
Codex, Grok, any other) and every routine. Numbers come from `argmax.yaml` (the config); the strategy comes from
`STRATEGY.md`. When this file says "the configured budget cap", read `limits.daily_budget_cap`, and so on.

## Before anything else: is this copy set up?
If `argmax.yaml` or `STRATEGY.md` is missing, or `uv run scripts/onboarding.py next` does not print `complete`,
offer onboarding first ("This copy is not set up yet. Shall I walk you through onboarding?") and follow
`prompts/onboarding.md` on a yes. If this is the public upstream repo rather than the user's private copy, follow
`BOOTSTRAP.md` instead. Scheduled routines that find setup incomplete stop and report it through the tracker (or
print it, when no tracker works yet); they never onboard on their own.

## Start here, every session
1. Read the 3 newest weekly logs in `log/` (newest first): they are the memory of what was changed and why. Also
   the newest `log/*-monthly.md` and its `reports/monthly/<YYYY-MM>.json`.
2. Read the tracker (how: `trackers/<tracker.backend>.md`): the comments on the last 2 weekly reports and on the
   newest monthly report, and every open decision with its comments. They hold the owner's approvals and
   instructions.
3. Read `STRATEGY.md`: the current phase, the Evidence rules, the topic spend targets, and any autonomy overrides.

## Goal: find what produces real deals, and move spend there
Real deals live in the CRM (`crm.source`; `uv run scripts/crm.py --since <date>`). Judge topics
(`argmax.yaml` topics) on the rolling 90-day table (`uv run scripts/topic_table.py`): CRM leads, ref-matched leads
and wins per topic against spend per topic, under STRATEGY.md's Evidence rules. Lead signals
(`conversions.lead_signals`) are leading indicators only. Noise signals (`conversions.noise_signals`) appear in
tables and are never used for any judgment. With no CRM (`crm.source: none`), say so in every report and judge on
lead signals, more cautiously.

## The routines (each prompt holds the steps, this file holds the rules)
- **Daily scout** (`prompts/daily-scout.md`, Tuesday to Sunday). Read-only except two automatic steps:
  `daily_bids.py --apply` steps winning-topic Search bids during their stepping window, and
  `daily_negatives.py --apply` blocks junk search terms as exact campaign negatives. It records yesterday in
  `reports/daily/week-<Monday>.json`, backfills a missed day, and comments on the newest weekly report only for
  NOTIFY lines. A BUDGET line means a winning group cannot grow because its campaign is budget-capped: the weekly
  cuts losing-topic bids in that campaign or shifts budget to it.
- **Weekly review** (`prompts/weekly-review.md`, Monday). The only routine that changes the account beyond the
  daily's two steps: it reads the week, writes 3 to 5 observations backed by numbers, makes the changes Autonomy
  allows, logs them in `log/<YYYY-MM-DD>.md` and creates the weekly report. It records Sunday itself.
- **Monthly review** (`prompts/monthly-review.md`, the 1st). Read-only. `scripts/monthly_report.py` writes
  `reports/monthly/<YYYY-MM>.json`; the routine writes `log/<YYYY-MM-DD>-monthly.md` with a checked client update,
  creates the monthly report, and proposes STRATEGY.md edits (phase, topic spend targets) as decisions.

## Autonomy (the owner wants to never open Google Ads; you run the account)
STRATEGY.md's "Agent autonomy overrides" may tighten or loosen this list, never beyond `argmax.yaml` limits.

Apply on your own, then report:
- Keyword review items: negatives, new keywords, keyword pauses (`keyword_review.py`, then
  `apply_keyword_review.py`).
- Daily junk negatives (`daily_negatives.py`): EXACT campaign negatives only, for terms that keyword_review's
  negative rule blocks on the last `negatives.lookback_days`; never a winning-topic term without a junk word (held
  for the weekly); at most `negatives.max_per_day` a day, highest cost first; never a term the campaign already
  blocks or one the weekly undid. The weekly reviews them and undoes any that blocks buyer intent with
  `daily_negatives.py undo`.
- Match type tightening (`match_type_review.py`, first weekly of the month): goes through an "Unless you say no:
  Tighten <n> keywords to phrase/exact" decision first, applied with `apply_keyword_review.py` after its due date.
- Bids: within `limits.weekly_bid_change` per ad group per week (from its Monday bid), inside `limits.bid_floor` to
  `limits.bid_ceiling`. Exception: a winning-topic Search group is stepped daily by `daily_bids.py` during its
  `stepping.window_days`; inside that window never change its bid by hand, change the config instead. After it the
  group is "settled" and the weekly makes one move per week toward `stepping.rank_lost_band` on the last 7 days,
  via `apply_changes.py`.
- Budget shifts between campaigns, as long as the total daily budget across enabled campaigns stays at or under
  the configured budget cap.
- Pausing and enabling keywords and ad groups; pausing campaigns whose phase exit check failed (STRATEGY.md).
  Cutting a topic or campaign on outcome data (leads, wins) only above STRATEGY.md's Evidence rules floor.
- Moving a campaign to the next phase when STRATEGY.md's criteria are met.
- Moving budgets and bids toward the approved topic spend targets, inside the limits above, and cutting waste on
  spend-side data only (impressions lost to budget, CPC, off-intent terms, lead signals on winning-topic terms).
- Small topic spend target updates (no topic moves more than 10 percentage points, shares sum to 100) through an
  "Unless you say no" decision, applied to STRATEGY.md after its due date.
- Ad copy tests, only through `scripts/ad_test.py` and the ad library: start at most `ad_tests.max_new_per_week`
  new test a week (at most `ad_tests.max_running` running), conclude tests by its decision rule, pause a test ad
  that Google disapproved or whose claims are no longer on the site. A concluded test is applied at once and
  reported as a "Done, reply reverse to undo" decision. The library changes only in a session with the owner.

Never, without a human "yes" on a decision:
- Raise the total daily budget above the configured budget cap, change conversion actions or their settings,
  billing, account access, or turn auto-apply recommendations back on. Write these as proposals.
- Change `argmax.yaml` limits (budget cap, bid limits, stepping, autonomy-related settings).
- Any ad copy change outside `ad_test.py`: text not in the ad library, final URLs that are not library pages,
  changing, pausing or deleting existing (non-test) ads (the one exception: ad_test.py pausing a control that lost
  its test). Propose the full copy (only claims the site makes) and wait for a "yes".
- Set the first topic spend targets, or move any topic by more than 10 percentage points (or shares that do not
  sum to 100).

## How changes are made, so they are checked and reviewable later
- Bids, budgets and status (campaign, ad group, keyword): `reports/changes-<date>.json`, applied with
  `uv run scripts/apply_changes.py <json>` (validate) then `--apply`. It refuses a file that breaks the limits
  (budget cap, weekly bid change, bid floor and ceiling, winning groups still stepping, Performance Max, unclear
  names). Never work around a FAIL.
- Keywords: the keyword review JSON (or the match type review JSON), applied with `apply_keyword_review.py`.
- Ad copy: `reports/ad-test-<date>.json`, started with `ad_test.py create <json>` (validate) then `--apply`;
  `ad_test.py evaluate --apply` concludes tests.
- Anything else (rare): a script under `scripts/`, validate first, then `--apply`.
- Every write script is validate-only by default; `--apply` makes the change. Applied changes are appended to
  `reports/changes.jsonl` (`scripts/ledger.py`); the monthly checks from it whether past changes worked.

## Ad copy tests
- The website (`website.base_url`) is the source of truth for every ad claim: value props, product names,
  features, numbers and terms (trial, pricing, support) are said the way the site says them, never paraphrased into
  new promises. When `claims_check.py` FAILs, the site changed: test ads that use the claim are paused (ad_test.py),
  regular ads are not touched, and the weekly raises "Needs yes: website changed, library revision session" with
  the failed claims and the ads that use them.
- The ad library (`ad_tests.library`): `claims` (exact short quotes, with locale, page and topic) and `assets`
  (headlines max 30 wide, descriptions max 90 wide; CJK full-width characters count 2; each cites claim ids).
  Imported live text is `source: "live"`; live text with no claim cannot be used in a test. Routines never edit the
  library.
- A test is one new RSA (the variant) next to the group's only enabled RSA (the control), in an enabled Search
  group with `ad_tests.min_impressions_14d` impressions in 14 days. Final URL: a library page of the group's locale
  with a claim on its topic. No new test without a live claims_check under `ad_tests.claims_max_age_days` old.
- Decision (`ad_test.py evaluate`): after `min_days` from the variant's first impression with
  `min_arm_impressions` per arm, a two-proportion z-test on CTR decides at |z| >= `z`; undecided by `max_days`, the
  arm with more lead signals per impression wins, then the higher CTR. Noise signals never count. The loser is
  paused, never the last enabled ad of a group. A disapproved variant is a failed test.

## Decisions and approvals (through the tracker: `trackers/<tracker.backend>.md`)
- Every proposal is one decision, so the owner sees all open decisions in one place, sorted by due date. Only the
  weekly and the monthly create decisions, never the daily.
- Kinds (the title prefix):
  - "Needs yes: <decision>" for the never-without-yes list (silence means not done);
  - "Unless you say no: <decision>" for things inside Autonomy (silence applies the default);
  - "Done, reply reverse to undo: <what was done>" for a change already applied that the owner may want undone
    (concluded ad tests; due 14 days after; silence keeps it). A "reverse" reply is undone with the matching
    command, e.g. `ad_test.py reverse <test id> --apply`.
- Due date = the decide-by date. Assigned to the owner. Description, 4 short lines:
  ```
  What: <one line>
  Why: <one or two lines, with the key number>
  If you don't reply by <date>: <the default, or "nothing happens">
  Reply: "yes" or "no" (or the named alternative, e.g. "keep reporting")
  ```
- Every weekly and monthly run reads all open decisions and their comments before deciding anything: "yes"
  approves, "no" drops, anything else is an instruction. Act, then resolve it ("Resolved <date>: <approved and done
  / declined / default applied / expired, not done>"). Past its due date with no reply: apply the default ("Unless
  you say no") or close it as expired ("Needs yes"). A decision that waits for an event stays open with a new due
  date. If a reply is unclear, ask in a comment and set it back to waiting.
- Never create a duplicate: if the same decision is open, comment on it instead.
- Logs keep an "Open proposals" section: one line per open decision (title, due date, link or path).

## Reporting
- Weekly report, titled "<YYYY-MM-DD> Google Ads weekly". Body = this 5-line header, then the log entry:
  ```
  Spend: <currency> <7 days>; daily budget <currency> <total enabled> of the <cap> cap
  Topic split (7 days): <topic> x% / <topic> x% / other x% (target: <approved targets, or TBD>)
  CRM this week: <n> new leads, <n> ref-matched (fill rate x%), <n> wins   (or "CRM: none configured")
  Changes applied: <count>; biggest: <one line>
  Decisions: <n> open; next due: <title> on <date> (or "none")
  ```
- Monthly report, titled "<YYYY-MM> Google Ads monthly". Body = this 5-line header, then the log entry, plus one
  comment holding only the client update (when `report.client_update.enabled`):
  ```
  <Month>: <currency> <spend>, <n> new customers, new <deal value label> <x>, first-month ROI <x>
  Year to date: <currency> <spend>, <n> customers, new <deal value label> <x>, first-month ROI <x>
  Topic split (90 days): <topic> x% / ... and where the wins came from
  Main finding: <one line>
  Decisions: <n> open; next due: <title> on <date> (or "none")
  ```

## Weekly log template (`log/<YYYY-MM-DD>.md`)
```
# <YYYY-MM-DD> weekly review (phase N, week M)
## Data (last 7 days vs previous 7)
## Observations
## Changes made
## Ad tests
## Daily scout (this week)
## Leads and wins (CRM)
## Routine health
## Open proposals
## Watch next week
```
- Ad tests: the claims_check result (OK, the FAIL lines, or SITE_UNREACHABLE); tests started (group, hypothesis,
  asset ids), running (days, impressions, CTR and lead signals per arm, z) and concluded or failed this week, and
  the free test slots.
- Daily scout (this week): per day, what the daily flagged (alerts, lead signals, CRM wins, REF and REF_GAP, bid
  steps, BUDGET, NEG and NEG_HELD) and what was done about each, or "quiet". List the negatives the daily added
  this week (campaign, term, cost) and the ones this run undid, with why.
- Leads and wins (CRM): new leads, wins and stage changes this week (no names); the funnel for the last 180 days
  with trial_to_win per topic; the ref fill rate; every ref-matched lead (campaign, ad group, keyword); CRM last
  entry and days since.
- Routine health: how many days last week's daily file has (7 of 7, or which are missing) and any MISSED lines;
  when the week contained a 1st, whether the last finished month's report exists.

## Facts that are easy to get wrong
- Many single words are negative keywords. Filter `ad_group_criterion.negative = FALSE` when listing keywords.
- Converting search terms are often competitor brand names: never add them as keywords.
- Keep auto-apply recommendations off; Google can silently re-enable Display Expansion through them.
- Search impression share 0.0999 is Google's floor and means "under 10%". Report it as "<10%".
- Before calling a traffic change on a Search campaign a "collapse", split it by `segments.ad_network_type`
  (`performance_snapshot.py` section `campaign_networks`): Display ending looks like a collapse in totals.
- A ref code found on two clicks is "ambiguous": report it, never guess.

## Hard rules for every agent
- Validate first, then `--apply`. Never work around a FAIL line; fix the input or propose a change.
- Never put CRM names or emails anywhere (repo, tracker, chat). Never echo secrets; they live only in
  `google-ads.yaml`, `client_secret*.json` or environment variables, all gitignored.
- In the private copy, commit runtime files explicitly with `git add -f <paths>` (they are gitignored so they can
  never leak into the public template). Never `git add -f .` and never push to `upstream`.
- No em-dashes in anything you write. No co-author or "generated with" lines in commit messages.
