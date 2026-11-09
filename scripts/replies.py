"""Which comments on a decision count as the owner's reply (github-issues tracker; PR reviews for the files tracker).

A comment counts only when it does not start with "[argmax]" (the agent's own notes) and its author is the owner,
tracker.github.assignee, or has write access to the repo (admin, maintain or write: gh api
repos/<repo>/collaborators/<login>/permission). Any other comment is listed under "ignored" with its author, so the
run can mention it in the report, and is never acted on: on GitHub anyone who can see an issue may comment, and a
"yes" from them is not an approval. Read-only; needs the gh CLI, logged in.

Usage: uv run scripts/replies.py <issue number>     (a decision issue)
       uv run scripts/replies.py --pr <number>      (a pull request touching decisions/: comments and reviews)
Prints JSON: {"repo", "replies": [{author, createdAt, body}], "ignored": [{author, createdAt, why}], "own": <n>}
"""
import json
import subprocess
import sys

import config
from doctor import git, github_repo

WRITE = ("admin", "maintain", "write")


def classify(comments, assignee, permission):
    """(replies, ignored, own count) from [{author, createdAt, body}]. permission(login) -> GitHub permission name.
    Pure apart from permission()."""
    replies, ignored, own, cache = [], [], 0, {}
    for c in comments:
        body, author = (c.get("body") or "").strip(), c.get("author") or ""
        if body.startswith("[argmax]"):
            own += 1
            continue
        if assignee and author.lower() == assignee.lower():
            replies.append(c)
            continue
        if author not in cache:
            cache[author] = permission(author) if author else "none"
        if cache[author] in WRITE:
            replies.append(c)
        else:
            ignored.append({"author": author, "createdAt": c.get("createdAt"),
                            "why": f"not the owner ({assignee or 'no tracker.github.assignee set'}) and no write access "
                                   f"(permission: {cache[author]})"})
    return replies, ignored, own


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAIL   gh {' '.join(args[:3])}: {r.stderr.strip()}")
    return r.stdout


def permission_of(repo):
    def look(login):
        r = subprocess.run(["gh", "api", f"repos/{repo}/collaborators/{login}/permission", "--jq", ".permission"],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "none"
    return look


def comments_of(repo, number, pr=False):
    fields = "comments,reviews" if pr else "comments"
    data = json.loads(gh("pr" if pr else "issue", "view", str(number), "--repo", repo, "--json", fields))
    items = data.get("comments", []) + data.get("reviews", [])
    out = [{"author": (c.get("author") or {}).get("login", ""), "createdAt": c.get("createdAt") or c.get("submittedAt"),
            "body": c.get("body", "")} for c in items]
    return sorted((c for c in out if c["body"].strip()), key=lambda c: c["createdAt"] or "")


def main():
    args = [a for a in sys.argv[1:] if a != "--pr"]
    if len(args) != 1 or not args[0].isdigit():
        sys.exit(__doc__)
    cfg = config.get()
    gh_cfg = cfg.tracker.github or {}
    repo = gh_cfg.get("repo") or github_repo(git("remote", "get-url", "origin"))
    if not repo:
        sys.exit("FAIL   no GitHub repo: set tracker.github.repo, or use a GitHub origin")
    replies, ignored, own = classify(comments_of(repo, args[0], "--pr" in sys.argv), gh_cfg.get("assignee") or "",
                                     permission_of(repo))
    print(json.dumps({"repo": repo, "replies": replies, "ignored": ignored, "own": own}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
