# Strategy templates

`STRATEGY.md` is the agent's standing brief: what counts as success, how much evidence a decision needs, where
spend should go, and which phase the account is in. Every routine reads it before deciding anything.
`adgrad.yaml` sets how fast the agent may move (caps and limits); `STRATEGY.md` sets where it is going.

## Pick one

| Template | For | Judged on |
|---|---|---|
| [b2b-lead-gen.md](b2b-lead-gen.md) | sales-led businesses with a CRM | CRM leads and wins per topic |
| [ecommerce-roas.md](ecommerce-roas.md) | online stores | conversion value per spend per category |
| [local-services.md](local-services.md) | local businesses, calls and forms | booked jobs, cost per job |
| [new-account-discovery.md](new-account-discovery.md) | new or messy accounts | junk cut first, then first deals |
| [brand-defense.md](brand-defense.md) | brands bid on by others | brand coverage, non-brand reported apart |

```bash
cp strategies/b2b-lead-gen.md STRATEGY.md   # or let `uv run scripts/init.py` copy one
uv run scripts/strategy_check.py            # required sections present, shares sum to 100
```

Then replace the placeholder topics (`topic_a`, `category_a`...) with the topic names from `adgrad.yaml`.
Combining is fine: e.g. brand-defense rules added to b2b-lead-gen under "Agent autonomy overrides".

## Required sections

The routines and `strategy_check.py` rely on these level-2 headings (any order, extra sections allowed):
Goal, Success signal, Evidence rules, Topic spend targets, Phases, Agent autonomy overrides, Change log.
Topic spend targets is a table `| Topic | Target share |` with every share a number (summing to 100) or all TBD.

## Port an existing strategy

Have notes, a slide, or a doc that describes how you run the account? Run
[prompts/strategy-interview.md](../prompts/strategy-interview.md) in your agent (Claude Code, Codex, Grok, any).
It either interviews you or reads your notes, maps them onto the required sections, suggests matching
`adgrad.yaml` topics, shows you a summary and diff, and writes `STRATEGY.md` only after you say yes.
By hand: start from the closest template, move each rule you have into the matching section, and put anything
that limits the agent under "Agent autonomy overrides". Limits that are numbers (budget cap, bid ceiling) go in
`adgrad.yaml` instead.
