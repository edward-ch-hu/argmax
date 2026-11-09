# Updating your private copy from upstream

Your copy has two kinds of files:

| Yours (never in upstream) | Engine (from upstream) |
|---|---|
| `adgrad.yaml`, `STRATEGY.md`, `docs/ad_library.json`, `log/`, `reports/`, `decisions/`, `.adgrad/`, secrets | `scripts/`, `prompts/`, `trackers/`, `strategies/`, `docs/`, `tests/`, `AGENTS.md`, `README.md`, ... |

Upstream gitignores every "yours" path, so upstream commits never touch them and a merge cannot conflict with
them. Your copy tracks them with `git add -f`; leave `.gitignore` as it is.

## One-time: add upstream (read-only)
```bash
git remote add upstream <upstream-url>    # the public adgrad repo you set up from
git remote set-url --push upstream DISABLED   # makes an accidental push to upstream fail
```

## Update
```bash
git fetch upstream
git log --oneline HEAD..upstream/main     # what is new
git merge upstream/main                   # or: git rebase upstream/main, if you prefer
uv sync
uv run pytest -q && uv run scripts/doctor.py --offline
git push                                  # to YOUR origin only
```
A copy made with "Use this template" has no shared history with upstream: the first time, use
`git merge upstream/main --allow-unrelated-histories` and keep your side of any conflict in a "yours" file
(there should be none). Later merges are ordinary.

If a merge conflicts in an engine file you edited yourself, keep upstream's version unless you meant to fork the
engine (`git checkout --theirs <file>`), then re-apply your change. Read the new `adgrad.example.yaml` for new
config fields: they have defaults, so an old `adgrad.yaml` keeps working; `doctor.py` says if anything is missing.

## Ask your agent
> update adgrad from upstream

The agent should: check the working tree is clean; add `upstream` if missing (push disabled); fetch; show the new
commits in a few lines; merge; run `uv sync`, `uv run pytest -q` and `uv run scripts/doctor.py --offline`; report
any new config fields worth setting; and push only to `origin` after you confirm. It never pushes to upstream and
never edits your config, strategy, logs or reports while updating.
