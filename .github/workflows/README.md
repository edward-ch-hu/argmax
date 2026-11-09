# Workflow examples (disabled)

GitHub only runs `.yml` / `.yaml` files, so these `.example` files do nothing until you copy one in your PRIVATE copy:

```bash
cp .github/workflows/argmax-weekly-claude-code.yml.example .github/workflows/argmax-weekly.yml
```

Each runs the weekly review headless on a schedule (and by hand from the Actions tab). For the daily scout and the
monthly review, copy it again, change `name`, the `cron`, and the prompt file (`prompts/daily-scout.md`,
`prompts/monthly-review.md`). Cron is UTC: convert from your account time zone.

Secrets (Settings, Secrets and variables, Actions):
- `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN` (no developer token needed)
- optional `GOOGLE_ADS_LOGIN_CUSTOMER_ID`, only when the ad account is reached through a manager account (an unset
  secret is passed as an empty value, which argmax ignores)
- one agent key: `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (Claude Code), `OPENAI_API_KEY` (Codex),
  `XAI_API_KEY` (Grok)
- `ARGMAX_CONFIG_YAML`: the whole config. Recommended: it is the guardrails lock. The agent can edit files in the
  checkout, but not a secret, so with it set `argmax.yaml` in the repo is only advisory (SETUP.md, "Guardrails lock")

The secrets reach only the step that runs the agent, not the whole job. The agent does the work, allowed only
argmax's scripts and the tracker's `gh` commands (see each example). Then "Guardrail files untouched" fails the run,
and nothing is committed, if the agent changed `scripts/`, `prompts/`, `trackers/`, `AGENTS.md` or `argmax.yaml`, or
left code in `log/`, `reports/` or `decisions/`. The last step commits the runtime files (`ARGMAX_COMMIT=workflow`). The built-in
`GITHUB_TOKEN` handles issues (github-issues tracker) and the push. Scheduled workflows run from the default branch
only.
