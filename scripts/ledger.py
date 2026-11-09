"""Change ledger: one JSON line per change applied to the account, in reports/changes.jsonl.

Written by apply_changes.py, apply_keyword_review.py, daily_negatives.py, daily_bids.py, experiments.py and
ad_test.py on --apply; read by monthly_report.py (change_audit) to check whether past changes worked. Each line:
date, routine, level (campaign / ad_group / keyword / ad), entity, field, before, after, reason, topic (a topic name,
or "mixed" for a campaign-wide change), expected_effect, judge_leads_after (date + 6 weeks) and judge_wins_after
(date + 10 weeks). daily_negatives.py also adds campaign, text, cost and clicks to its lines. A change made by or for
an experiment (daily_bids.py steps, experiments.py ends and reverses) carries its id in "experiment".

Written in two steps, so a run that dies mid-mutate leaves a trace: before the mutate the planned entries are printed
and written with "status": "pending" and an "id"; after it, the same ids are written again with "status": "applied"
(or "failed"). read() returns applied changes only (and the lines of older runs, which have no status); unconfirmed()
returns pending lines with no outcome line, which the monthly lists apart: check the account's change history for
them before trusting either way.
"""
import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import ads_client

PATH = Path("reports/changes.jsonl")
LEADS_AFTER, WINS_AFTER = timedelta(weeks=6), timedelta(weeks=10)
OUTCOMES = ("applied", "failed")


def entry(level, entity, field, before, after, reason, topic, expected_effect, routine="weekly", day=None,
          experiment=None):
    day = day or ads_client.today()
    out = {"date": str(day), "routine": routine, "level": level, "entity": entity, "field": field,
           "before": before, "after": after, "reason": reason, "topic": topic or "mixed",
           "expected_effect": expected_effect, "judge_leads_after": str(day + LEADS_AFTER),
           "judge_wins_after": str(day + WINS_AFTER)}
    if experiment:
        out["experiment"] = experiment
    return out


def write(lines, path=None):
    path = path or PATH
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for e in lines:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def describe(e):
    return f"{e['level']} {e['entity']}: {e['field']} {e['before']} -> {e['after']}"


def begin(entries, path=None):
    """Prints the planned entries and writes them as pending lines. Returns them with their ids (pass those to
    finish()). Call it right before the mutate that applies them."""
    run = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    planned = [{**e, "id": f"{run}-{i}"} for i, e in enumerate(entries)]
    for e in planned:
        print(f"LEDGER pending  {describe(e)}")
    write([{**e, "status": "pending"} for e in planned], path)
    return planned


def finish(entries, status="applied", path=None):
    """Writes the outcome of planned entries (from begin(), fields may be updated, the id must stay)."""
    write([{**e, "status": status} for e in entries], path)
    if entries and status == "applied":
        print(f"Logged {len(entries)} change(s) to {path or PATH}")


@contextmanager
def pending(entries, apply=True, path=None):
    """Around one atomic mutate: pending lines before it, applied after it, failed when it raises (re-raised). Does
    nothing when not applying or when there is nothing to log."""
    if not apply or not entries:
        yield entries
        return
    planned = begin(entries, path)
    try:
        yield planned
    except BaseException:
        finish(planned, "failed", path)
        raise
    finish(planned, "applied", path)


def append(entries, path=None):
    """Logs changes already applied in one step (no pending line)."""
    write([{**e, "status": "applied"} for e in entries], path)
    if entries:
        print(f"Logged {len(entries)} change(s) to {path or PATH}")


def lines(path=None):
    path = path or PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read(path=None, entries=None):
    """The applied changes (lines with status applied, or no status: written before pending lines existed)."""
    entries = lines(path) if entries is None else entries
    return [e for e in entries if e.get("status", "applied") == "applied"]


def unconfirmed(path=None, entries=None):
    """Pending lines whose id never got an applied or failed line: the run stopped between the two."""
    entries = lines(path) if entries is None else entries
    done = {e.get("id") for e in entries if e.get("status") in OUTCOMES}
    return [e for e in entries if e.get("status") == "pending" and e.get("id") not in done]
