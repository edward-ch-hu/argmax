# adgrad

> **Set up in one message.** Paste this into Claude Code, Codex or Grok:
>
> ```
> Set up adgrad for me from REPO_URL. Follow its BOOTSTRAP.md.
> ```
>
> Your agent makes your own private copy, clones it, and walks you through onboarding.
> (`REPO_URL` is this repo's URL; it is the only place it appears.)

**An AI agent that runs your Google Ads account inside hard guardrails.**

AdaGrad takes adaptive gradient steps on parameters. adgrad takes adaptive gradient steps on *spend*: every day
and every week it nudges bids, budgets and keywords toward whatever actually produces deals, with step sizes and
limits you set, a ledger of every move, and an approval inbox for anything bigger. You stop opening Google Ads;
you read one weekly report and answer a few "yes / no" decisions.

```
spend[t+1] = clip(spend[t] + lr * grad(deals | spend), guardrails)
```

This public repo is a **GitHub template**: you run adgrad from your own private copy, because its logs and reports
hold your account's data.

## What it does

- **Daily scout** checks the account for drift (auto-apply sneaking back on, Display leaking into Search, budget
  over cap), records the day, steps winning-topic bids toward a visibility sweet spot, and blocks junk search terms.
- **Weekly review** reads the week, writes 3 to 5 numbered observations, reviews keywords and match types, moves
  bids and budgets toward the topics that close deals, runs ad copy A/B tests, and files a report.
- **Monthly review** recomputes the whole history from scratch (spend, new customers, first-month ROI, funnel per
  topic), audits whether last month's changes worked, writes a client-ready update, and proposes strategy changes.
- **Real deals, not vanity conversions.** It reads your CRM (CSV or Google Sheet) and judges topics on a rolling
  90-day table of spend vs leads vs wins. Noisy conversions are shown and never trusted. Optional ref codes tie a
  CRM lead back to the exact ad click.

## Guardrails (the actual product)

The agent is clever; the guardrails are dumb, deterministic Python, and they win every argument.

| Guardrail | Where | What happens on a breach |
|---|---|---|
| Validate by default | every write script | nothing changes without `--apply` |
| Total daily budget cap | `apply_changes.py`, `daily_guard.py` | the whole change file is refused (FAIL, exit 1) |
| Weekly bid change limit (from Monday's bid) | `apply_changes.py` | refused |
| Bid floor and ceiling | `apply_changes.py`, `daily_bids.py` | refused / clamped |
| Daily stepping window (winning groups only) | `daily_bids.py` | hand edits refused while stepping |
| Max junk negatives per day, never winning-topic terms | `daily_negatives.py` | held for the weekly |
| Ad copy only from a claims library quoted from your site | `claims_check.py`, `ad_test.py` | test refused or paused |
| A/B decisions by two-proportion z-test, never the last ad | `ad_test.py` | waits for evidence |
| Evidence floors before defunding a topic | `STRATEGY.md` | spend-side fixes only |
| Change ledger with judge-by dates | `reports/changes.jsonl` | the monthly audits every change |
| Approval inbox: "Needs yes", "Unless you say no", "Done, reply reverse to undo" | your tracker | silence has a defined meaning |
| Privacy: no CRM names or emails anywhere, only fingerprints | `crm.py`, `check_external.py` | client update refused |

Everything numeric lives in `adgrad.yaml`. The agent may not change it without your "yes".

## Architecture

```mermaid
flowchart LR
  subgraph You
    O[Owner] -- "yes / no / reverse" --> T
  end
  subgraph Agent["AI agent (Claude Code, Codex, Grok)"]
    P[prompts/*.md] --> R[AGENTS.md rules]
  end
  R -- runs --> S[scripts/*.py]
  S -- validate / --apply --> G[(Google Ads API)]
  S -- reads --> C[(CRM: CSV or Sheet)]
  S -- reads --> W[(Your website: ad claims)]
  S -- writes --> L[log/, reports/, ledger]
  R -- reports and decisions --> T[Tracker: GitHub Issues, files, ClickUp, Notion, Linear]
  CFG[adgrad.yaml + STRATEGY.md] --> S
  CFG --> R
```

## The three routines

| Routine | When | Changes the account? | Prompt |
|---|---|---|---|
| Daily scout | Tue to Sun, morning | bid steps on winning groups, junk negatives | `prompts/daily-scout.md` |
| Weekly review | Monday, morning | yes, inside Autonomy and the limits | `prompts/weekly-review.md` |
| Monthly review | the 1st | never | `prompts/monthly-review.md` |

## Quickstart (about 10 minutes of your time, plus Google's token approval)

1. **Make your private copy.** Paste the one-message prompt at the top into your agent, or by hand:
   `gh repo create my-adgrad --private --template <owner>/<repo> --clone` (details in `BOOTSTRAP.md`).
2. **Open it in your agent and say "onboard me".** `prompts/onboarding.md` walks you through prerequisites, the
   Google Ads API, picking the account, your tracker, your CRM, your strategy, the guardrails, a first read-only
   run, and scheduling. It saves progress, so "continue onboarding" resumes (handy while Google approves your
   developer token).
3. **Read your first weekly report**, answer decisions with "yes", "no" or "reverse".

Prefer doing it by hand? `SETUP.md` is the full manual reference. `uv run scripts/doctor.py` tells you what is
still missing at any point.

## Pick your agent

| | Claude Code | Codex CLI | Grok Build |
|---|---|---|---|
| Rules file | `CLAUDE.md` (imports `AGENTS.md`) | `AGENTS.md` | `AGENTS.md` (also reads `CLAUDE.md`) |
| Headless | `claude -p` | `codex exec` | `grok -p` |
| Scheduling | cloud scheduled tasks (`/schedule`), Actions, cron | Actions (`openai/codex-action`), cron | Actions (no official action), cron |
| MCP trackers | yes (claude.ai connectors in the cloud) | yes | yes |
| Guide | [docs/agents/claude-code.md](docs/agents/claude-code.md) | [docs/agents/codex.md](docs/agents/codex.md) | [docs/agents/grok.md](docs/agents/grok.md) |

`github-issues` (via `gh`) and `files` trackers work with every agent, headless, no MCP needed.

## Pick your strategy

`STRATEGY.md` is the agent's standing brief: goal, what counts as success, evidence rules, topic spend targets,
phases. Start from a template in [strategies/](strategies/README.md): B2B lead gen, e-commerce ROAS, local
services, new-account discovery, brand defense. Or let `prompts/strategy-interview.md` interview you, or port your
existing notes.

## Safety notes

- **Validate by default, `--apply` to change.** Every write script prints what it would do and changes nothing
  until `--apply`. A FAIL line means nothing changed, and the agent is told never to work around one.
- **Secrets never touch the repo**: `google-ads.yaml`, `client_secret*.json` and env vars only (all gitignored).
- **Your data stays in your private copy.** The public template gitignores every runtime path; your copy tracks
  them with `git add -f`, and `upstream` is set read-only.
- **Auto-apply recommendations stay off**, and the daily guard alerts if Google turns any back on.
- You are responsible for your ad account. Start with conservative limits; onboarding defaults to them.

## FAQ

**Does it need a CRM?** No. With `crm.source: none` it judges on lead-signal conversions and says so in every
report. With a CRM it judges on real deals, which is the point.

**Will it blow my budget?** It cannot raise the total daily budget above your cap: `apply_changes.py` refuses the
whole file. Raising the cap is a "Needs yes" decision for you.

**Can it write ads?** Only from a library of claims quoted verbatim from your own website, checked against the
live site before each test. New copy outside the library is a proposal you approve.

**Which agent is best?** Whichever you already pay for. The engine is plain Python; the agent reads markdown.

**How do I get updates?** "update adgrad from upstream" in your agent, or `docs/updating.md`.

**Is this affiliated with Google, Anthropic, OpenAI or xAI?** No.

## Layout

```
AGENTS.md            rules for every agent (CLAUDE.md points here)
BOOTSTRAP.md         for an agent setting up a new private copy
adgrad.example.yaml  every setting, commented (your adgrad.yaml is gitignored)
STRATEGY.example.md  the strategy structure; strategies/ has ready-made ones
prompts/             daily, weekly, monthly routines; onboarding; strategy interview
scripts/             the engine (validate-only by default)
trackers/            how to report and ask for approval in each tool
docs/                agents, ref codes, updating, examples
tests/               pytest, no network
```

## License

MIT, see [LICENSE](LICENSE). Contributions welcome: `uv run pytest -q && uv run ruff check .` before a PR.
