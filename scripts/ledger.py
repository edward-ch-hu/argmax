"""Change ledger: one JSON line per change applied to the account, in reports/changes.jsonl.

Written by apply_changes.py, apply_keyword_review.py, daily_negatives.py and ad_test.py on --apply; read by
monthly_report.py (change_audit) to check whether past changes worked. Each line: date, routine, level (campaign /
ad_group / keyword / ad), entity, field, before, after, reason, topic (a topic name, or "mixed" for a campaign-wide
change), expected_effect, judge_leads_after (date + 6 weeks) and judge_wins_after (date + 10 weeks).
daily_negatives.py also adds campaign, text, cost and clicks to its lines.
"""
import json
from datetime import timedelta
from pathlib import Path

import ads_client

PATH = Path("reports/changes.jsonl")
LEADS_AFTER, WINS_AFTER = timedelta(weeks=6), timedelta(weeks=10)


def entry(level, entity, field, before, after, reason, topic, expected_effect, routine="weekly", day=None):
    day = day or ads_client.today()
    return {"date": str(day), "routine": routine, "level": level, "entity": entity, "field": field,
            "before": before, "after": after, "reason": reason, "topic": topic or "mixed",
            "expected_effect": expected_effect, "judge_leads_after": str(day + LEADS_AFTER),
            "judge_wins_after": str(day + WINS_AFTER)}


def append(entries, path=None):
    path = path or PATH
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"Logged {len(entries)} change(s) to {path}")


def read(path=None):
    path = path or PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
