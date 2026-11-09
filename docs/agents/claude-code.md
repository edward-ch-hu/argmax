# Running argmax with Claude Code

Facts checked against Anthropic's docs on 2026-11-09 (links inline). Claude Code moves fast: if a flag below is
rejected, `claude --help` and https://code.claude.com/docs are the reference.

## Install and log in
```bash
curl -fsSL https://claude.ai/install.sh | bash        # macOS, Linux, WSL
# Windows PowerShell: irm https://claude.ai/install.ps1 | iex
# or: brew install --cask claude-code   /   npm install -g @anthropic-ai/claude-code (Node 22+)
claude            # first run opens a browser to log in (subscription), or set ANTHROPIC_API_KEY
```
Source: https://code.claude.com/docs/en/setup, https://code.claude.com/docs/en/authentication.
For CI with a subscription: `claude setup-token` prints a long-lived token to store as `CLAUDE_CODE_OAUTH_TOKEN`.

## How it picks up the rules
The repo's `CLAUDE.md` imports `AGENTS.md` (`@AGENTS.md`), so Claude Code loads the shared rules on every session,
headless runs included. Recent versions can also read `AGENTS.md` directly, but only when no `CLAUDE.md` exists
(https://code.claude.com/docs/en/memory#agents-md); the import works on every version. Do not use `--bare` for
routines: it skips `CLAUDE.md`.

## Onboard and run by hand
```bash
cd your-private-argmax
claude
> onboard me
> run the weekly review          # the agent follows prompts/weekly-review.md
```

## MCP connectors (ClickUp, Notion, Linear trackers)
Local sessions:
```bash
claude mcp add --transport http clickup https://mcp.clickup.com/mcp
claude mcp add --transport http notion  https://mcp.notion.com/mcp
claude mcp add --transport http linear  https://mcp.linear.app/mcp
claude mcp login <name>          # or /mcp inside a session, to complete OAuth
```
Source: https://code.claude.com/docs/en/mcp. Add `--scope project` to write `.mcp.json` (committed, shared).
Cloud routines do not see servers added with `claude mcp add`: connect the app at
claude.ai/customize/connectors instead (or commit a `.mcp.json` for single-repo routines).
`github-issues` needs no MCP: it uses `gh`. `files` needs nothing.

## Headless
```bash
claude -p "$(cat prompts/weekly-review.md)" \
  --permission-mode dontAsk \
  --allowedTools "Read,Edit,Write,Glob,Grep,Bash(uv *),Bash(pip install *),Bash(git *),Bash(gh *)" \
  --max-turns 200 --output-format text
```
`-p` runs non-interactively; `--allowedTools` pre-approves exactly what the routine needs and `dontAsk` denies
anything else instead of waiting for a prompt (https://code.claude.com/docs/en/headless,
https://code.claude.com/docs/en/cli-reference). Avoid `--dangerously-skip-permissions`: argmax's own guardrails
are scripts, and the allowlist keeps the agent on them.

## Scheduling
**Cloud scheduled tasks (recommended).** In a session, `/schedule` (or claude.ai/code/routines) creates a task: a
prompt, your private repo, connectors, and a schedule (https://code.claude.com/docs/en/routines; research preview,
needs a claude.ai subscription login). Create three:

| Task | Schedule (account time zone) | Prompt |
|---|---|---|
| argmax daily scout | 08:00 Tuesday to Sunday | `Follow prompts/daily-scout.md.` |
| argmax weekly review | 09:00 Monday | `Follow prompts/weekly-review.md.` |
| argmax monthly review | 10:00 on the 1st | `Follow prompts/monthly-review.md.` |

Custom cron is read as UTC unless prefixed with `CRON_TZ=<Area/City>`. Then, in the task's cloud environment:
- Environment variables: `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`,
  `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_LOGIN_CUSTOMER_ID`, `GOOGLE_ADS_USE_PROTO_PLUS=True`, and `GH_TOKEN` for
  the github-issues tracker. `argmax.yaml` is committed in your private copy (or set `ARGMAX_CONFIG_YAML`).
- Network: allow `googleads.googleapis.com`, `oauth2.googleapis.com`, `sheets.googleapis.com` (Sheets CRM), your
  website (claims check), `pypi.org` and `files.pythonhosted.org` (uv sync), and `api.github.com`.
- Pushes: tasks push to `claude/`-prefixed branches unless allowed otherwise. The prompts push to the default
  branch; allow it in the task settings, or merge the `claude/` branches (the next run reads the default branch, so
  logs must land there).

**GitHub Actions.** `.github/workflows/argmax-weekly-claude-code.yml.example` uses
`anthropics/claude-code-action@v1` (inputs `prompt`, `claude_args`, `anthropic_api_key` or
`claude_code_oauth_token`; https://code.claude.com/docs/en/github-actions). Copy it to `.yml`, add the secrets, and
duplicate it for the daily and monthly routines with their crons.

**cron on your machine.** `crontab -e`, e.g. Monday 09:00 local time:
`0 9 * * 1 cd /path/to/your-private-argmax && claude -p "$(cat prompts/weekly-review.md)" --permission-mode dontAsk --allowedTools "..." >> log/cron.txt 2>&1`

## Where secrets go
`google-ads.yaml` and `client_secret.json` locally (gitignored); environment variables in cloud tasks; GitHub
Actions secrets in CI. Never in `argmax.yaml`, prompts, logs or the tracker.

## Limitations
- Cloud tasks are a research preview with hourly and daily run limits; they draw on your subscription usage.
- OAuth-only connectors (ClickUp) work in cloud tasks through claude.ai connectors but not in GitHub Actions.
- A scheduled run that hits a permission it was not given stops; check its transcript and widen the allowlist.
