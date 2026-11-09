# Strategy interview

Run this in any agent (Claude Code, Codex, Grok, a chat window with file access) from the root of your private
argmax copy. It writes `STRATEGY.md` in the structure the routines rely on, plus topic suggestions for
`argmax.yaml`. It writes nothing until you say yes.

---

You are helping the owner of a Google Ads account write `STRATEGY.md` for argmax. Read `AGENTS.md`,
`strategies/README.md`, the templates in `strategies/`, and `argmax.yaml` if it exists (the business profile,
topics, conversions, limits). Never ask for or repeat secrets, CRM names or emails. No em-dashes. Talk to the owner
in `business.report_language` when it is set.

1. Ask which way they want to go, in one message:
   (a) "Interview me": you ask the questions below;
   (b) "Use my notes": they paste notes or point you at a file (an old brief, a slide export, a doc);
   (c) "Just pick a template": they choose one from `strategies/README.md` and you fill in the blanks with them.
2. Gather, one or two questions at a time, skipping what the notes or config already answer:
   - The business: what they sell, to whom, and how a sale happens (on the site, a call, a sales conversation).
   - What counts as success: start from the business profile (`business.goal`, `goal_description`, `primary_kpi`,
     `kpi_conversions`, `markets`) and do not ask again what it already says. Only when there is no profile yet
     (strategy written before onboarding's business step), ask for it in plain words and propose the `business:`
     block alongside STRATEGY.md (`prompts/onboarding.md` step e has the questions).
   - Which Google Ads conversion actions are real leading signals, and which are noise (clicks on chat widgets,
     page-view goals). These become `conversions.lead_signals` and `noise_signals`.
   - Product lines or services they want to compare (these become topics), and which of them close deals today.
   - Constraints: monthly or daily budget ceiling, regions, hours, things the agent must never do, things it may do
     alone. Budget and bid numbers belong in `argmax.yaml` limits; rules belong under "Agent autonomy overrides".
   - Their sales cycle length (it sets the evidence windows: a 90-day table for a long B2B cycle, 30 days for a shop).
     Money floors in Evidence rules are in the account currency: write them relative to the account's CPC, or as
     the amount `uv run scripts/init.py --derive --dry-run` prints ("evidence floor"), never as a USD-sized number.
   - Where the account is now: new, messy, or running well (it sets the starting phase).
3. Pick the closest template that fits `business.goal` (its "Fits goals" line; `strategies/README.md` has the
   table) and adapt it. Keep the `Fits goals: ...` line, true to the goal, and every required section, exactly these
   level-2 headings: Goal, Success signal, Evidence rules, Topic spend targets, Phases, Agent autonomy overrides,
   Change log. Goal and Success signal point at the profile (`business.goal`, `business.primary_kpi`) and say how
   this strategy pursues it; they do not restate the goal, the KPI, the markets or the languages.
   Topic spend targets stay TBD (all rows) unless the owner gives shares that sum to 100 and says they are approved.
   Every rule from their notes must land in a section; list anything you could not place and ask.
4. Suggest `argmax.yaml` topics: name (lower_snake_case), substrings and whole words, which are winning, and an
   `ad_group_topics` map. If the config and Google Ads credentials work, read live names first:
   `uv run scripts/gaql.py "SELECT campaign.name, ad_group.name FROM ad_group WHERE ad_group.status = 'ENABLED'"`
   and the top keywords by spend
   (`SELECT ad_group.name, ad_group_criterion.keyword.text, metrics.cost_micros FROM keyword_view WHERE
   segments.date DURING LAST_30_DAYS AND ad_group_criterion.negative = FALSE ORDER BY metrics.cost_micros DESC
   LIMIT 50`), and build the topics from what the account actually contains.
5. Show before writing: a short summary (template used, goal, success signal, phase, overrides), the full proposed
   `STRATEGY.md` (or a diff against the existing one), and the proposed `argmax.yaml` topic block. Ask: "Write
   these?" Only on a yes: write `STRATEGY.md`, add a Change log line "<date>: written with prompts/strategy-
   interview.md", update `argmax.yaml` topics (and the business profile) only if they said yes to that part too,
   and run `uv run scripts/strategy_check.py`. Fix anything it reports, including a goal fit warning.
6. Tell them what happens next: the weekly and monthly routines read this file every run, and the monthly proposes
   topic spend targets from the 90-day table as a "Needs yes" decision.
