"""Read-only view of your CRM: real leads and won deals (config: crm).

Sources: none (default; scripts that need the CRM say so and carry on), csv (a file with a header row) or
google_sheets (a range read with the same Google login as the Ads API). The first row holds the headers; crm.columns
maps them: lead_date and status are required; topics (one header or a list, the first non-empty wins), deal_value,
name, email, id and ref are optional.

Privacy: names and emails are never printed or stored. Each row gets a short fingerprint (hash of id, or name +
email + lead date) so daily files can spot new or changed rows without saying who it is.

Status mapping (crm.statuses, case-insensitive exact match): talking and trial are open, won is a win,
lost_after_trial and lost_no_trial are losses. An unknown status counts as crm.default_status (open).
funnel(): lead_to_trial = leads that reached a trial, trial_to_win = won / decided trials (won + lost_after_trial),
lead_to_win = won / leads.

Usage: uv run scripts/crm.py [--since YYYY-MM-DD]   (default: last 7 days) prints a JSON summary
       uv run scripts/crm.py inspect (--csv PATH | --sheet ID [--range "Sheet1!A1:Z"]) [--status-column NAME]
           for onboarding, without argmax.yaml: prints the header row and the distinct values (with counts) of the
           status column only. Never prints any other cell, so no names or emails.
"""
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import ads_client
import config
from topics import topics_of

STATUSES = config.STATUSES
STAGE = {"won": "win", "lost_after_trial": "lost", "lost_no_trial": "lost"}


def enabled(cfg=None):
    return (cfg or config.get()).crm.source != "none"


def ref_pattern(cfg=None):
    prefix = (cfg or config.get()).ref_codes.prefix
    return re.compile(re.escape(prefix) + r"[0-9A-F]{8}")


def status_code(status, cfg=None):
    """One of STATUSES for a raw status value, from crm.statuses (case-insensitive), else crm.default_status."""
    c = (cfg or config.get()).crm
    value = (status or "").strip().lower()
    for code in STATUSES:
        if value in (v.strip().lower() for v in c.statuses.get(code, [])):
            return code
    return c.default_status


def stage(code):
    return STAGE.get(code, "open")


def parse_date(text, fmt=None):
    """YYYY-MM-DD from a cell: crm.date_format when set, else YYYY-MM-DD or YYYY/MM/DD (a time after it is ignored)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        if fmt:
            return str(datetime.strptime(text, fmt).date())
        m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
        return str(date(int(m[1]), int(m[2]), int(m[3]))) if m else None
    except (ValueError, TypeError):
        return None


def money(text):
    cleaned = re.sub(r"[^0-9.\-]", "", text or "")
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def raw_values(cfg=None):
    """The CRM as a list of rows (the first is the header). [] when crm.source is none."""
    c = (cfg or config.get()).crm
    if c.source == "csv":
        path = Path(c.csv_path)
        if not path.exists():
            sys.exit(f"crm.csv_path: {path} does not exist")
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))
    if c.source == "google_sheets":
        return ads_client.sheet_values(c.sheet_id, c.sheet_range)
    return []


def header_index(header, name):
    """Index of a header (case-insensitive, trimmed), or None."""
    if not name:
        return None
    want = name.strip().lower()
    return next((i for i, h in enumerate(header) if str(h).strip().lower() == want), None)


def parse(values, cfg=None):
    """Rows of the CRM as dicts with no names or emails. Returns (rows, skipped) where skipped counts rows with no
    readable lead date."""
    cfg = cfg or config.get()
    c = cfg.crm
    if not values:
        return [], 0
    header, cols = values[0], c.columns
    missing = [cols[k] for k in ("lead_date", "status") if header_index(header, cols[k]) is None]
    if missing:
        sys.exit(f"crm.columns: header(s) {', '.join(missing)} not found in the CRM's first row")
    idx = {k: header_index(header, cols.get(k)) for k in ("id", "lead_date", "status", "deal_value", "name", "email",
                                                           "ref")}
    topic_cols = cols.get("topics") or []
    topic_idx = [header_index(header, t) for t in ([topic_cols] if isinstance(topic_cols, str) else topic_cols)]
    pattern = ref_pattern(cfg)
    out, skipped = [], 0
    for n, v in enumerate(values[1:], start=2):
        v = [str(x) for x in v] + [""] * (len(header) - len(v))

        def cell(key, v=v):
            return v[idx[key]] if idx[key] is not None else ""

        day = parse_date(cell("lead_date"), c.date_format)
        if not day:
            skipped += bool(any(x.strip() for x in v))
            continue
        tags = next((v[i] for i in topic_idx if i is not None and v[i].strip()), "")
        who = cell("id") or (cell("name") + "|" + cell("email") if cell("name") or cell("email") else f"row{n}")
        code = status_code(cell("status"), cfg)
        value_text = cell("deal_value")
        ref_text = cell("ref") if idx["ref"] is not None else " ".join(v)
        out.append({
            "fp": hashlib.sha1(f"{who}|{day}".encode()).hexdigest()[:10],
            "date": day, "status": code, "stage": stage(code),
            "tested": code in ("trial", "won", "lost_after_trial"),
            "topics": topics_of(tags), "tags": tags,
            "mrr": money(value_text), "mrr_missing": not value_text.strip(),
            "refs": sorted(set(pattern.findall(ref_text.upper()))),
        })
    return out, skipped


def load(cfg=None):
    """CRM rows ([] when crm.source is none)."""
    cfg = cfg or config.get()
    if not enabled(cfg):
        return []
    return parse(raw_values(cfg), cfg)[0]


def private_values(cfg=None, min_name_len=3):
    """Names and emails from the raw CRM, lower-cased, for leak checks (check_external.py). Never print these."""
    cfg = cfg or config.get()
    values = raw_values(cfg)
    if not values:
        return set()
    out = set()
    for key, min_len in (("name", min_name_len), ("email", 1)):
        i = header_index(values[0], cfg.crm.columns.get(key))
        if i is None:
            continue
        for v in values[1:]:
            value = (v[i] if i < len(v) else "").strip()
            if len(value) >= min_len:
                out.add(value.lower())
    return out


def by_topic(rows):
    out = defaultdict(lambda: {"leads": 0, "wins": 0, "mrr": 0.0})
    for r in rows:
        for t in r["topics"] or ["none"]:
            out[t]["leads"] += 1
            out[t]["wins"] += r["stage"] == "win"
            out[t]["mrr"] += r["mrr"] if r["stage"] == "win" else 0.0
    return dict(out)


def rate(part, whole):
    return round(part / whole, 3) if whole else None


def funnel(rows):
    n = {k: sum(r["status"] == k for r in rows) for k in STATUSES}
    leads = len(rows)
    return {"leads": leads, **n, "open": n["talking"] + n["trial"],
            "lead_to_trial": rate(n["trial"] + n["won"] + n["lost_after_trial"], leads),
            "trial_to_win": rate(n["won"], n["won"] + n["lost_after_trial"]),
            "lead_to_win": rate(n["won"], leads)}


def funnel_by_topic(rows):
    topics = sorted({t for r in rows for t in r["topics"] or ["none"]})
    return {t: funnel([r for r in rows if t in (r["topics"] or ["none"])]) for t in topics}


def ref_fill(rows, since=None, until="9999", cfg=None):
    """Share of leads (lead date from `since`, never before ref_codes.live_from) that carry a real ref code."""
    r = (cfg or config.get()).ref_codes
    start = max(since or "0000", r.live_from or "0000")
    leads = [x for x in rows if start <= x["date"] <= until]
    with_ref = sum(bool(set(x["refs"]) - set(r.test_codes)) for x in leads)
    return {"since": start if start != "0000" else None, "leads": len(leads), "with_ref": with_ref,
            "rate": rate(with_ref, len(leads))}


def last_entry(rows):
    return max((r["date"] for r in rows), default=None)


def summary(rows, since, now=None):
    now = now or ads_client.today()
    recent = [r for r in rows if r["date"] >= since]
    last_180 = [r for r in rows if r["date"] >= str(now - timedelta(days=180))]
    last = last_entry(rows)
    out = {
        "rows": len(rows),
        "last_entry": last,
        "days_since_last_entry": (now - date.fromisoformat(last)).days if last else None,
        "since": since,
        "new_leads": len(recent),
        "new_wins": [{k: r[k] for k in ("date", "topics", "mrr")} for r in recent if r["stage"] == "win"],
        "new_by_topic": by_topic(recent),
        "last_180_days_by_topic": by_topic(last_180),
        "funnel": {"since": {"all": funnel(recent), "by_topic": funnel_by_topic(recent)},
                   "last_180_days": {"all": funnel(last_180), "by_topic": funnel_by_topic(last_180)}},
    }
    if config.get().ref_codes.enabled:
        out["ref_fill"] = ref_fill(rows)
    return out


def inspect(values, status_column=None):
    """{"headers": [...], "statuses": {value: count}} from raw rows: the header row and one column only (pure)."""
    if not values:
        return {"headers": [], "rows": 0, "statuses": {}}
    header = [str(h) for h in values[0]]
    out = {"headers": header, "rows": max(len(values) - 1, 0), "statuses": {}}
    i = header_index(header, status_column)
    if status_column and i is None:
        out["error"] = f"no column '{status_column}' in the header row"
    elif i is not None:
        for v in values[1:]:
            value = str(v[i]).strip() if i < len(v) else ""
            if value:
                out["statuses"][value] = out["statuses"].get(value, 0) + 1
    return out


def inspect_main(args):
    opt = lambda name: args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None  # noqa: E731
    if opt("--csv"):
        with Path(opt("--csv")).open(encoding="utf-8-sig", newline="") as f:
            values = list(csv.reader(f))
    elif opt("--sheet"):
        values = ads_client.sheet_values(opt("--sheet"), opt("--range") or "Sheet1!A1:Z")
    else:
        sys.exit(__doc__)
    print(json.dumps(inspect(values, opt("--status-column")), ensure_ascii=False, indent=1))


def main():
    if sys.argv[1:2] == ["inspect"]:
        inspect_main(sys.argv[2:])
        return
    if not enabled():
        print(json.dumps({"crm": "none", "note": "crm.source is none in argmax.yaml: no lead or win data"}))
        return
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else str(ads_client.today() - timedelta(days=7))
    print(json.dumps(summary(load(), since), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
