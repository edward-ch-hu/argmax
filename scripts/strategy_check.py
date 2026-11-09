"""Check that STRATEGY.md has the sections the routines rely on, and that topic spend targets add up.

Required sections (level-2 headings, in any order; extra sections are fine):
  Goal, Success signal, Evidence rules, Topic spend targets, Phases, Agent autonomy overrides, Change log
Topic spend targets: a markdown table whose first column is the topic and second the target share. Every share is
a percentage (like 45 or 45%) or TBD. When none is TBD they must sum to 100; mixing numbers and TBD fails. Topics in
the table should be config topics (or "other"); unknown names are warnings, not failures.
A "Fits goals: leads, calls" line (or "Fits goals: any") names the business.goal values the strategy is written
for; a config goal outside it, or no such line, is a warning (doctor.py shows it as "goal fit").
A "Bidding end state: ..." line says where bidding ends up: "smart bidding hand-off" or "agent-run manual CPC
(permanent)". It must name one of them and agree with business.bidding_end_state (smart_bidding or manual_cpc):
disagreeing is a failure, a missing line or a line still listing both is a warning (doctor.py: "bidding").

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


GOAL_WORDS = ("leads", "sales", "roas", "calls", "awareness", "any")  # config.GOALS plus "any"
GOALS_LINE = re.compile(r"^\W*fits goals\W*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def fits_goals(text):
    """The goals a strategy declares on its "Fits goals:" line, as a set ({"any"} for any), or None without one."""
    m = GOALS_LINE.search(text)
    if not m:
        return None
    return {w for w in re.findall(r"[a-z]+", m[1].lower()) if w in GOAL_WORDS} or None


def goal_fit(text, goal):
    """(status, message) for business.goal against the strategy's "Fits goals" line. Status OK, WARN or PENDING."""
    if goal is None:
        return "PENDING", "business.goal not set yet (onboarding step e, business)"
    fits = fits_goals(text)
    if fits is None:
        return "WARN", (f"STRATEGY.md has no \"Fits goals:\" line, so business.goal '{goal}' is not checked "
                        "against it (add one, e.g. \"Fits goals: leads\")")
    if "any" in fits or goal in fits:
        return "OK", f"business.goal '{goal}' fits the strategy ({', '.join(sorted(fits))})"
    return "WARN", (f"business.goal is '{goal}' but STRATEGY.md is written for {', '.join(sorted(fits))}: pick a "
                    "matching template in strategies/ or change the goal")


BIDDING_LINE = re.compile(r"^\W*bidding end state\W*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
END_STATE_NAMES = {"smart_bidding": "smart bidding hand-off", "manual_cpc": "agent-run manual CPC (permanent)"}


def bidding_end_state(text):
    """(state, raw) from the "Bidding end state:" line: state is smart_bidding, manual_cpc, "both" (the template's
    choice not made yet), "unknown", or None when there is no such line."""
    m = BIDDING_LINE.search(text)
    if not m:
        return None, None
    raw = m[1].strip()
    words = raw.lower()
    smart, manual = "smart" in words, "manual" in words
    state = "both" if smart and manual else "smart_bidding" if smart else "manual_cpc" if manual else "unknown"
    return state, raw


def bidding_fit(text, end_state):
    """(status, message) for STRATEGY.md's bidding end state against business.bidding_end_state. OK, WARN or FAIL."""
    state, raw = bidding_end_state(text)
    choices = " or ".join(f'"{v}"' for v in END_STATE_NAMES.values())
    if state is None:
        return "WARN", f"STRATEGY.md has no \"Bidding end state:\" line: add one with {choices}"
    if state == "unknown":
        return "FAIL", f"Bidding end state: '{raw}' is neither {choices}"
    if state == "both":
        return "WARN", (f"Bidding end state still lists both choices: keep {choices} (and the matching "
                        "business.bidding_end_state)")
    if end_state is None:
        return "WARN", (f"STRATEGY.md says {END_STATE_NAMES[state]} but business.bidding_end_state is not set: set it "
                        f"to {state}")
    if end_state != state:
        return "FAIL", (f"STRATEGY.md says {END_STATE_NAMES[state]} but business.bidding_end_state is {end_state}: "
                        "make them agree (changing either is a \"Needs yes\" decision)")
    return "OK", f"{END_STATE_NAMES[state]} in STRATEGY.md and business.bidding_end_state"


def pick_bidding(text, end_state):
    """The text with its "Bidding end state:" line set to `end_state` (smart_bidding or manual_cpc). Pure."""
    return BIDDING_LINE.sub(f"Bidding end state: {END_STATE_NAMES[end_state]}", text, count=1)


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
                warnings.append(f"Topic spend targets: '{name}' is not a topic in argmax.yaml")
    return fails, warnings


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "STRATEGY.md")
    if not path.exists():
        sys.exit(f"FAIL   no {path}: copy a template from strategies/ (see strategies/README.md)")
    import config

    try:
        cfg = config.load()
        topics, goal, end_state = set(cfg.topics), cfg.business.goal, cfg.business.bidding_end_state
    except config.ConfigError:  # the check works without a config; it only skips topic name and goal warnings
        topics = goal = end_state = None
    text = path.read_text(encoding="utf-8")
    fails, warnings = check(text, topics)
    if goal is not None:
        status, message = goal_fit(text, goal)
        if status == "WARN":
            warnings.append(message)
    status, message = bidding_fit(text, end_state)
    {"WARN": warnings, "FAIL": fails}.get(status, []).append(message)
    for w in warnings:
        print(f"WARN   {w}")
    for f in fails:
        print(f"FAIL   {f}")
    if fails:
        sys.exit(f"{len(fails)} problem(s) in {path}")
    print(f"OK     {path} has every required section")


if __name__ == "__main__":
    main()
