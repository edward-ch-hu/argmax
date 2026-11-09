# Running adgrad with OpenAI Codex CLI

Facts checked against OpenAI's docs and the openai/codex source on 2026-11-09 (links inline; the docs moved to
learn.chatgpt.com). If a flag is rejected, `codex exec --help` is the reference.

## Install and log in
```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh    # or: npm install -g @openai/codex / brew install --cask codex
codex login                                             # ChatGPT login in a browser
printenv OPENAI_API_KEY | codex login --with-api-key    # or an API key (recommended for automation)
codex login --device-auth                               # headless machines
```
Source: https://github.com/openai/codex, https://learn.chatgpt.com/docs/auth.md.

## How it picks up the rules
Codex reads `AGENTS.md` natively, from the git root down to the working directory
(https://learn.chatgpt.com/docs/agent-configuration/agents-md). Nothing to configure. It ignores `CLAUDE.md`,
which only points to `AGENTS.md` anyway. adgrad's `AGENTS.md` is well under Codex's default 32 KiB limit.

## Onboard and run by hand
```bash
cd your-private-adgrad
codex
> onboard me
> run the weekly review
```

## MCP connectors (ClickUp, Notion, Linear trackers)
```bash
codex mcp add notion --url https://mcp.notion.com/mcp
codex mcp add linear --url https://mcp.linear.app/mcp
codex mcp add clickup --url https://mcp.clickup.com/mcp
codex mcp login <name>        # OAuth
codex mcp list
```
Or in `~/.codex/config.toml` (or a trusted project's `.codex/config.toml`):
```toml
[mcp_servers.linear]
url = "https://mcp.linear.app/mcp"
bearer_token_env_var = "LINEAR_API_KEY"   # a Linear API key works headless
```
Source: https://learn.chatgpt.com/docs/extend/mcp. ClickUp's server is OAuth only, so in CI prefer
`github-issues` (via `gh`) or `files`.

## Headless
```bash
codex exec --sandbox workspace-write \
  -c 'sandbox_workspace_write.network_access=true' \
  "$(cat prompts/weekly-review.md)"
```
`codex exec` runs non-interactively and starts read-only; `--sandbox workspace-write` lets it edit the repo, and
the network setting lets the scripts reach the Google Ads API (network is off by default in that sandbox).
`--full-auto` is no longer supported. `--dangerously-bypass-approvals-and-sandbox` removes all protection: only
inside a throwaway VM. Useful extras: `--json`, `-o last-message.txt`, `-m <model>`.
Source: https://learn.chatgpt.com/docs/non-interactive-mode, https://learn.chatgpt.com/docs/agent-approvals-security.md.
Whether the sandbox lets `git push` reach your remote depends on your setup; the GitHub Actions example lets the
workflow commit instead (`ADGRAD_COMMIT=workflow`).

## Scheduling
**GitHub Actions (recommended).** `.github/workflows/adgrad-weekly-codex.yml.example` uses `openai/codex-action@v1`
(inputs `prompt-file`, `openai-api-key`, `sandbox`, `codex-args`; https://learn.chatgpt.com/docs/github-action.md).
Copy it to `.yml`, add the secrets, duplicate for the daily and monthly routines.

**cron on your machine.**
`0 9 * * 1 cd /path/to/your-private-adgrad && codex exec --sandbox workspace-write -c 'sandbox_workspace_write.network_access=true' "$(cat prompts/weekly-review.md)" >> log/cron.txt 2>&1`

**Codex app scheduled tasks.** The ChatGPT/Codex desktop and web apps have scheduled tasks
(https://learn.chatgpt.com/docs/automations.md); desktop tasks run locally while the app is open. The CLI has no
scheduler of its own. A cron-style schedule for Codex Cloud tasks against a GitHub repo could not be verified.

## Where secrets go
Locally: `google-ads.yaml`, `client_secret.json` (gitignored). CI: GitHub Actions secrets, passed only to the
step that needs them (OpenAI's docs warn against job-wide API key env vars in workflows that run repo code).

## Limitations
- The sandbox needs network on for the Google Ads API; review what else the run may reach.
- No built-in scheduler in the CLI; use Actions or cron.
- OAuth-only connectors are awkward headless.
