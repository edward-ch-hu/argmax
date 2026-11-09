# Bootstrap (for AI agents)

You are an AI coding agent. A user pointed you at this public argmax repo and asked you to set it up for them.
You may have read only this file, without cloning anything. Do the steps below in order, one at a time, and confirm
each with the user before moving on. Be brief; explain jargon in one line when it first comes up. No em-dashes.

The public upstream is https://github.com/edward-ch-hu/argmax (call it `<upstream-url>`). If the user gave you
another public argmax repo's URL instead, use that URL as `<upstream-url>`: it is only the source of the engine.

## 1. Why a private copy (say this in one line)
"argmax keeps logs, reports and decisions about your ad account in the repo, so you run it from your own private
copy; this public repo is only where engine updates come from."

## 2. Where should the copy live? Ask the user:
- (a) a private GitHub repo (recommended: issues become the approval inbox, Actions can schedule runs),
- (b) another git host (GitLab, Bitbucket, a server),
- (c) local only (no remote; scheduling is then by hand or a local cron).

Then ask for a name (default `argmax-<their business>`) and a parent folder (default the current directory).

Never use GitHub's "Fork" button: a fork of a public repo is always public (GitHub does not allow a private fork of
a public repo), and a public copy would expose the account's data and let anyone approve decisions. `doctor.py`
fails on a public repo and every routine stops there.

## 3. Create the copy: clone, then push to a new private remote
Check tools first: `git --version`; for (a) also `gh --version` and `gh auth status`. If `gh` is missing, give
the install link (https://cli.github.com) and stop until it is there; if not logged in, ask the user to run
`gh auth login` themselves (it is interactive and handles their credentials; never ask for a token in chat).

Every option starts with a clone, so the copy shares upstream's history and later updates are a plain
`git merge upstream/main` (`docs/updating.md`). The public repo becomes the read-only `upstream` remote:
```bash
git clone <upstream-url> <name> && cd <name>
git remote rename origin upstream
git remote set-url --push upstream DISABLED     # an accidental push to the public repo fails
```
Then the private `origin`:

(a) private GitHub repo (created and pushed in one step, from the folder you are in):
```bash
gh repo create <name> --private --source . --remote origin --push
```
(b) another host: create an empty private repo there (the user does it in the web UI and gives you its URL), then
```bash
git remote add origin <their-private-url> && git push -u origin HEAD
```
(c) local only: nothing more; there is no `origin`.

Alternative, not recommended: GitHub's "Use this template" button, where offered (or `gh repo create --template`). The copy then
has no shared history with upstream, so every engine update needs `git merge -X theirs --allow-unrelated-histories`
and a check of your files (`docs/updating.md`), and `gh repo create --template ... --clone` can clone before GitHub
has finished copying the files (an empty checkout). Use it only if the user insists.

## 4. Check the remotes
`git remote -v`: `origin` is the private copy (or absent for local only), `upstream` is the public repo with push
DISABLED. For (a), `gh repo view --json visibility,isFork -q '.visibility + " " + (.isFork|tostring)'` must say
`PRIVATE false`. `upstream` is only for pulling engine updates later (`docs/updating.md`). Never push the user's data
there.

## 5. Hand over to onboarding
From inside the new folder, read `AGENTS.md`, then follow `prompts/onboarding.md` from its first step. Its "repo"
step becomes a quick check that the above is done; record it with
`uv run scripts/onboarding.py set repo done` once uv is installed.

## If you cannot run commands or fetch URLs
Some agents (or sandboxes) cannot use a shell or the network. Then give the user these commands to run themselves,
one block at a time, and ask them to paste the output back (never secrets):
```bash
gh auth login
git clone https://github.com/edward-ch-hu/argmax <name> && cd <name>
git remote rename origin upstream
git remote set-url --push upstream DISABLED
gh repo create <name> --private --source . --remote origin --push
```
Then ask them to open the new folder in an agent that can run commands (docs/agents/ lists Claude Code, Codex and
Grok setups) and say "onboard me".
