"""Check the "## Client update (external)" section of a monthly log before it goes to a client or stakeholder.

Fails (exit 1) on: an "@"; any CRM name or email (from the raw CRM, case-insensitive, names under 3 characters
skipped); an em-dash; a blocked word (case-insensitive; English words match whole words, plurals included). Blocked
words: the internal vocabulary below, the configured budget cap, every conversion action name (lead and noise
signals), and report.client_update.blocklist (add competitor brands there). Prints the rule and the line number
only, never the matched CRM value. Prints OK when the section is clean.

Usage: uv run scripts/check_external.py log/<YYYY-MM-DD>-monthly.md
"""
import re
import sys
from pathlib import Path

import config
import crm

INTERNAL = ["agent", "automation", "script", "routine", "AI", "Claude", "Codex", "Grok", "LLM", "argmax", "proposal",
            "z-test", "z test", "ad_test", "claims_check", "ad_library", "ad library", "guardrail", "autonomy"]
# Allowed on purpose: "ad copy test", "A/B" and "trial" (a client may hear that ad copy was tested).
HEADING = "## Client update (external)"
EM_DASH = "\u2014"


def blocklist(cfg=None):
    cfg = cfg or config.get()
    cap = cfg.limits.daily_budget_cap
    return (INTERNAL + [f"{cap:g}"] + cfg.conversions.lead_signals + cfg.conversions.noise_signals
            + cfg.report.client_update["blocklist"])


def section(text):
    """(first line number, lines) of the section, or None when the heading is missing."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == HEADING:
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
            return i + 2, lines[i + 1:end]
    return None


def pattern(word):
    if re.fullmatch(r"[0-9.]+", word):  # a number on its own, not part of a bigger one such as 4,160 or 1600
        return re.compile(rf"(?<![0-9])(?<![0-9][,.]){re.escape(word)}(?![0-9]|[,.][0-9])")
    if re.fullmatch(r"[A-Za-z0-9 _-]+", word):
        return re.compile(rf"(?<![a-z0-9]){re.escape(word)}(?:s|es)?(?![a-z0-9])", re.IGNORECASE)
    return re.compile(re.escape(word), re.IGNORECASE)


def problems(first, lines, private, words):
    blocked = [(w, pattern(w)) for w in words]
    out = []
    for n, line in enumerate(lines, start=first):
        if "@" in line:
            out.append(f"line {n}: contains '@'")
        if EM_DASH in line:
            out.append(f"line {n}: contains an em-dash")
        if any(value in line.lower() for value in private):
            out.append(f"line {n}: contains a CRM name or email")
        out += [f"line {n}: blocked word '{w}'" for w, p in blocked if p.search(line)]
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    found = section(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if found is None:
        sys.exit(f"FAIL   no '{HEADING}' section in {sys.argv[1]}")
    bad = problems(*found, crm.private_values(), blocklist())
    for line in bad:
        print(f"FAIL   {line}")
    if bad:
        sys.exit(f"{len(bad)} problem(s): rewrite the client update and run this again.")
    print(f"OK     client update ({len(found[1])} lines) is clean")


if __name__ == "__main__":
    main()
