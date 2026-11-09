"""Onboarding progress in .argmax/onboarding.json (gitignored, never holds secrets), so "continue onboarding"
resumes where it stopped. prompts/onboarding.md drives the steps; this file only records them.

Usage: uv run scripts/onboarding.py                         show every step and its status
       uv run scripts/onboarding.py next                    print the first step that is not done or skipped
       uv run scripts/onboarding.py set <step> <status> ["note"]
Statuses: todo, done, pending (waiting on something outside, e.g. developer token approval), skipped.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(".argmax/onboarding.json")
STEPS = ("prerequisites", "repo", "google_ads_api", "account", "tracker", "crm", "strategy", "guardrails",
         "first_run", "scheduling")
STATUSES = ("todo", "done", "pending", "skipped")
SECRET_HINTS = ("token", "secret", "password", "refresh", "api_key", "apikey")


def load(path=None):
    path = path or PATH
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    steps = state.get("steps", {})
    return {"steps": {s: steps.get(s, {"status": "todo"}) for s in STEPS}, "updated": state.get("updated")}


def set_step(state, step, status, note=None, now=None):
    """A new state with one step changed (pure, for tests). Refuses unknown steps, statuses and secret-looking notes."""
    if step not in STEPS:
        raise ValueError(f"unknown step '{step}' (steps: {', '.join(STEPS)})")
    if status not in STATUSES:
        raise ValueError(f"unknown status '{status}' (statuses: {', '.join(STATUSES)})")
    if note and any(h in note.lower() for h in SECRET_HINTS) and any(len(w) >= 20 for w in note.split()):
        raise ValueError("the note looks like it holds a secret: keep secrets out of onboarding.json")
    out = {"steps": {k: dict(v) for k, v in state["steps"].items()}}
    out["steps"][step] = {"status": status, **({"note": note} if note else {})}
    out["updated"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return out


def next_step(state):
    return next((s for s in STEPS if state["steps"][s]["status"] in ("todo", "pending")), None)


def complete(state):
    """True when every step is done or skipped."""
    return all(v["status"] in ("done", "skipped") for v in state["steps"].values())


def save(state, path=None):
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")


def main():
    args = sys.argv[1:]
    state = load()
    if args[:1] == ["set"]:
        if len(args) < 3:
            sys.exit(__doc__)
        try:
            state = set_step(state, args[1], args[2], args[3] if len(args) > 3 else None)
        except ValueError as e:
            sys.exit(f"FAIL   {e}")
        save(state)
    if args[:1] == ["next"]:
        print(next_step(state) or "complete")
        return
    for step, v in state["steps"].items():
        print(f"{v['status'].upper():8} {step}" + (f": {v['note']}" if v.get("note") else ""))
    print("Onboarding complete." if complete(state) else f"Next: {next_step(state)}")


if __name__ == "__main__":
    main()
