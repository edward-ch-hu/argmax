"""Check that STRATEGY.md has the sections the routines rely on, and that topic spend targets add up.

Required sections (level-2 headings, in any order; extra sections are fine):
  Goal, Success signal, Evidence rules, Topic spend targets, Phases, Agent autonomy overrides, Change log
Topic spend targets: a markdown table whose first column is the topic and second the target share. Every share is
a percentage (like 45 or 45%) or TBD. When none is TBD they must sum to 100; mixing numbers and TBD fails. Topics in
the table should be config topics (or "other"); unknown names are warnings, not failures.

Usage: uv run scripts/strategy_check.py [STRATEGY.md]
"""
import re
import sys
from pathlib import Path

REQUIRED = ("Goal", "Success signal", "Evidence rules", "Topic spend targets", "Phases", "Agent autonomy overrides",
            "Change log")


def sections(text):
    """{heading: body} for every '## ' heading (a trailing parenthetical like '(approved ...)' is ignored)."""
    out, current = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            current = re.sub(r"\s*\(.*\)\s*$", "", m[1]).strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def targets(body):
    """[(topic, share or None for TBD, raw)] from the first table in the section; the header row is skipped."""
    out = []
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            if out:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("-: ") or cells[0].lower() in ("topic", "topics"):
            continue
        raw = cells[1]
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%?", raw)
        out.append((cells[0].strip("` "), float(m[1]) if m else None, raw))
    return out


def check(text, topics=None):
    """(fails, warnings) for a STRATEGY.md text. topics: config topic names, for warnings."""
    fails, warnings = [], []
    found = sections(text)
    lowered = {k.lower(): k for k in found}
    for name in REQUIRED:
        if name.lower() not in lowered:
            fails.append(f"missing section '## {name}'")
    body = found.get(lowered.get("topic spend targets", ""), "")
    rows = targets(body)
    if "topic spend targets" in lowered and not rows:
        fails.append("Topic spend targets: no table (| Topic | Target share |)")
    bad = [raw for _, share, raw in rows if share is None and raw.upper() != "TBD"]
    if bad:
        fails.append(f"Topic spend targets: shares must be a number or TBD (got {', '.join(bad)})")
    numbers = [s for _, s, _ in rows if s is not None]
    if numbers and len(numbers) != len(rows):
        fails.append("Topic spend targets: some shares are numbers and some TBD; set all or none")
    elif numbers and abs(sum(numbers) - 100) > 0.01:
        fails.append(f"Topic spend targets: shares sum to {sum(numbers):g}, not 100")
    if topics is not None:
        for name, _, _ in rows:
            base = name.split(" ")[0]
            if base not in topics and base != "other":
                warnings.append(f"Topic spend targets: '{name}' is not a topic in adgrad.yaml")
    return fails, warnings


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "STRATEGY.md")
    if not path.exists():
        sys.exit(f"FAIL   no {path}: copy a template from strategies/ (see strategies/README.md)")
    import config

    try:
        topics = set(config.load().topics)
    except config.ConfigError:  # the check works without a config; it only skips topic name warnings
        topics = None
    fails, warnings = check(path.read_text(encoding="utf-8"), topics)
    for w in warnings:
        print(f"WARN   {w}")
    for f in fails:
        print(f"FAIL   {f}")
    if fails:
        sys.exit(f"{len(fails)} problem(s) in {path}")
    print(f"OK     {path} has every required section")


if __name__ == "__main__":
    main()
