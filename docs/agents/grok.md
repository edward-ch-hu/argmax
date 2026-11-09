# Running argmax with Grok Build (xAI)

Grok Build is xAI's official coding agent CLI (binary `grok`), announced 2026-05-25 as an early beta for SuperGrok
and X Premium Plus subscribers (https://x.ai/news/grok-build-cli, https://docs.x.ai/build/overview.md). Facts
checked on 2026-11-09. A community project, `superagent-ai/grok-cli`, also installs a `grok` binary: it is not
xAI's. Check with `which grok` and `grok --help`.

## Install and log in
```bash
curl -fsSL https://x.ai/cli/install.sh | bash      # Windows PowerShell: irm https://x.ai/cli/install.ps1 | iex
grok login                                         # browser; `grok login --device-auth` on headless hosts
# or set XAI_API_KEY
```

## How it picks up the rules
Grok Build reads `AGENTS.md` and `CLAUDE.md` natively in every directory from the repo root down
(https://docs.x.ai/build/features/project-rules.md), so it needs no extra file: `AGENTS.md` carries the rules, and
`CLAUDE.md` only points to it. `grok inspect` lists the files it loaded.

## Onboard and run by hand
```bash
cd your-private-argmax
grok
> onboard me
> run the weekly review
```

## MCP connectors (ClickUp, Notion, Linear trackers)
```bash
grok mcp add --transport http notion  https://mcp.notion.com/mcp
grok mcp add --transport http linear  https://mcp.linear.app/mcp
grok mcp add --transport http clickup https://mcp.clickup.com/mcp
grok mcp list
grok mcp doctor
```
OAuth runs automatically on first use. `--scope project` writes `.grok/config.toml`. Grok Build also loads a
project `.mcp.json` (https://docs.x.ai/build/features/mcp-servers.md).

## Headless
```bash
grok --no-auto-update -p "$(cat prompts/weekly-review.md)" \
  --permission-mode dontAsk \
  --allow 'Read' --allow 'Edit' --allow 'Write' \
  --allow 'Bash(pip install uv)' --allow 'Bash(uv sync)' --allow 'Bash(uv run scripts/*)' \
  --allow 'Bash(git add -f *)' --allow 'Bash(git commit -m *)' --allow 'Bash(git pull --rebase*)' \
  --allow 'Bash(git push*)' --allow 'Bash(git rebase --abort)' --allow 'Bash(git reset --hard origin/*)' \
  --allow 'Bash(gh issue *)' --allow 'Bash(gh label *)' --allow 'Bash(gh pr view *)' --allow 'Bash(gh repo view *)' \
  --max-turns 200 --output-format plain
```
`-p` runs one prompt non-interactively; `dontAsk` silently denies anything without an allow rule
(https://docs.x.ai/build/cli/headless-scripting.md, https://docs.x.ai/build/features/permissions). Bash rules are
prefixes with no word boundary, so keep the trailing ` *`; compound commands are split and every part must be
allowed. Not `Bash(uv *)`: it would allow `uv run python -c "..."`, a direct API call that skips every guardrail.
Path-scoped `Edit(...)` / `Write(...)` rules are not in xAI's CLI docs, so edits stay unscoped here: set
`ARGMAX_CONFIG_YAML` in the environment (the lock, SETUP.md "Guardrails lock"), keep the workflow's "Guardrail
files untouched" step, and read each weekly report's Guardrails line. Avoid `--always-approve` / `--yolo` outside a
throwaway VM.

## Scheduling
- **GitHub Actions**: there is no official Grok GitHub Action. `.github/workflows/argmax-weekly-grok.yml.example`
  installs the CLI and runs it headless with an `XAI_API_KEY` secret. Whether an API key works without a
  subscription could not be verified: test one run by hand first.
- **cron on your machine**: the headless command above in `crontab -e`, e.g. `0 9 * * 1 cd /path/to/copy && grok
  --no-auto-update -p "$(cat prompts/weekly-review.md)" ... >> log/cron.txt 2>&1`.
- xAI's separate "Grok Bot" has scheduled routines, but it is a general assistant, not a repo-bound coding agent;
  it is not a supported way to run argmax.

## Where secrets go
Locally: `google-ads.yaml`, `client_secret.json` (gitignored), `XAI_API_KEY` in your shell profile or a secret
manager. CI: GitHub Actions secrets. Never in `argmax.yaml`, prompts, logs or the tracker.

## Limitations (say them plainly)
- Early beta, gated to subscribers; flags may change. Verify with `grok --help`.
- No official CI action; the workflow example installs the CLI itself, and the install path may need adding to
  `PATH` (the example tries the usual locations).
- OAuth connectors (ClickUp, Notion) are interactive; for unattended runs use the `github-issues` tracker (`gh`
  with a token) or `files`, which need no MCP at all.
