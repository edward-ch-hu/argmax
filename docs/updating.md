# Updating your private copy from upstream

Your copy has two kinds of files:

| Yours (never in upstream) | Engine (from upstream) |
|---|---|
| `argmax.yaml`, `STRATEGY.md`, `docs/ad_library.json`, `log/`, `reports/`, `decisions/`, `.argmax/`, secrets | `scripts/`, `prompts/`, `trackers/`, `strategies/`, `docs/`, `tests/`, `AGENTS.md`, `README.md`, ... |

Upstream gitignores every "yours" path, so upstream commits never touch them and a merge cannot conflict with
them. Your copy tracks them with `git add -f`; leave `.gitignore` as it is.

## One-time: add upstream (read-only)
```bash
git remote add upstream https://github.com/edward-ch-hu/argmax   # the public repo (or the fork you set up from)
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
A copy made by cloning upstream (`BOOTSTRAP.md`, the default) shares its history, so this merge is ordinary.

### A copy made with "Use this template"
It has no shared history with upstream, so a plain `--allow-unrelated-histories` merge conflicts on every engine
file. The first time, take upstream's side of every conflict, then check that nothing of yours was touched:
```bash
git status --porcelain                                    # must be empty before you start
git fetch upstream
git merge -X theirs --allow-unrelated-histories upstream/main -m "Merge upstream argmax (first time)"
git diff --stat HEAD~1 HEAD -- argmax.yaml STRATEGY.md docs/ad_library.json log/ reports/ decisions/
```
The last command must print nothing: upstream never tracks those paths (they are gitignored there), so the merge
cannot change them. If it lists anything, stop and restore it with `git checkout HEAD~1 -- <path>`, then commit.
`-X theirs` also replaces any engine file you edited yourself with upstream's version: re-apply such edits by hand.
After this first merge the histories are joined and later merges are ordinary.

If a merge conflicts in an engine file you edited yourself, keep upstream's version unless you meant to fork the
engine (`git checkout --theirs <file>`), then re-apply your change. Read the new `argmax.example.yaml` for new
config fields: they have defaults, so an old `argmax.yaml` keeps working; `doctor.py` says if anything is missing.

## Ask your agent
> update argmax from upstream

The agent should: check the working tree is clean; add `upstream` if missing (push disabled); fetch; show the new
commits in a few lines; merge (`git merge-base HEAD upstream/main` fails on a "Use this template" copy that was
never merged: then use the first-time recipe above, including its check); run `uv sync`, `uv run pytest -q` and `uv run scripts/doctor.py --offline`; report
any new config fields worth setting; and push only to `origin` after you confirm. It never pushes to upstream and
never edits your config, strategy, logs or reports while updating.
