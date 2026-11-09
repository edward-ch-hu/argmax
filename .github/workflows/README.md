# Workflow examples (disabled)

GitHub only runs `.yml` / `.yaml` files, so these `.example` files do nothing until you copy one in your PRIVATE copy:

```bash
cp .github/workflows/argmax-weekly-claude-code.yml.example .github/workflows/argmax-weekly.yml
```

Each runs the weekly review headless on a schedule (and by hand from the Actions tab). For the daily scout and the
monthly review, copy it again, change `name`, the `cron`, and the prompt file (`prompts/daily-scout.md`,
`prompts/monthly-review.md`). Cron is UTC: convert from your account time zone.

Secrets (Settings, Secrets and variables, Actions):
- `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`,
  `GOOGLE_ADS_LOGIN_CUSTOMER_ID`
- one agent key: `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (Claude Code), `OPENAI_API_KEY` (Codex),
  `XAI_API_KEY` (Grok)
- optional `ARGMAX_CONFIG_YAML` if you do not commit `argmax.yaml`

The agent does the work; the last step commits the runtime files (`ARGMAX_COMMIT=workflow`). The built-in
`GITHUB_TOKEN` handles issues (github-issues tracker) and the push. Scheduled workflows run from the default branch
only.
