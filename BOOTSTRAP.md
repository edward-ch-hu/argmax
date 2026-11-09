# Bootstrap (for AI agents)

You are an AI coding agent. A user pointed you at this public argmax repo and asked you to set it up for them.
You may have read only this file, without cloning anything. Do the steps below in order, one at a time, and confirm
each with the user before moving on. Be brief; explain jargon in one line when it first comes up. No em-dashes.

The public upstream is https://github.com/edward-ch-hu/argmax (call it `<upstream-url>`). If the user gave you a
fork's URL instead, use that URL and its GitHub path wherever the commands below say `edward-ch-hu/argmax`.

## 1. Why a private copy (say this in one line)
"argmax keeps logs, reports and decisions about your ad account in the repo, so you run it from your own private
copy; this public repo is only the template."

## 2. Where should the copy live? Ask the user:
- (a) a private GitHub repo (recommended: issues become the approval inbox, Actions can schedule runs),
- (b) another git host (GitLab, Bitbucket, a server),
- (c) local only (no remote; scheduling is then by hand or a local cron).

Then ask for a name (default `argmax-<their business>`) and a parent folder (default the current directory).

## 3. Create and clone it
Check tools first: `git --version`; for (a) also `gh --version` and `gh auth status`. If `gh` is missing, give
the install link (https://cli.github.com) and stop until it is there; if not logged in, ask the user to run
`gh auth login` themselves (it is interactive and handles their credentials; never ask for a token in chat).

(a) private GitHub repo:
```bash
gh repo create <name> --private --template edward-ch-hu/argmax --clone
cd <name>
```
If template creation is unavailable (the upstream is not marked as a template, or the command fails):
```bash
git clone <upstream-url> <name> && cd <name>
gh repo create <name> --private --source . --remote origin-new --push
git remote remove origin && git remote rename origin-new origin
```
(b) another host: create an empty private repo there (the user does it in the web UI and gives you its URL), then
```bash
git clone <upstream-url> <name> && cd <name>
git remote set-url origin <their-private-url> && git push -u origin HEAD
```
(c) local only:
```bash
git clone <upstream-url> <name> && cd <name> && git remote remove origin
```

## 4. Keep upstream read-only
```bash
git remote add upstream <upstream-url> 2>/dev/null || git remote set-url upstream <upstream-url>
git remote set-url --push upstream DISABLED
```
`upstream` is only for pulling engine updates later (`docs/updating.md`). Never push the user's data there.
Verify with `git remote -v`: `origin` is the private copy (or absent for local only), `upstream` push is DISABLED.

## 5. Hand over to onboarding
From inside the new folder, read `AGENTS.md`, then follow `prompts/onboarding.md` from its first step. Its "repo"
step becomes a quick check that the above is done; record it with
`uv run scripts/onboarding.py set repo done` once uv is installed.

## If you cannot run commands or fetch URLs
Some agents (or sandboxes) cannot use a shell or the network. Then give the user these commands to run themselves,
one block at a time, and ask them to paste the output back (never secrets):
```bash
gh auth login
gh repo create <name> --private --template edward-ch-hu/argmax --clone
cd <name>
git remote add upstream https://github.com/edward-ch-hu/argmax
git remote set-url --push upstream DISABLED
```
Then ask them to open the new folder in an agent that can run commands (docs/agents/ lists Claude Code, Codex and
Grok setups) and say "onboard me".
