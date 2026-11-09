"""Write adgrad.yaml from adgrad.example.yaml by asking a few questions. Copies a strategy template to STRATEGY.md
when there is none. Changes nothing in Google Ads.

Everything not asked keeps the example's value: read adgrad.example.yaml for the comments, then edit adgrad.yaml.

Usage: uv run scripts/init.py [--force]   (--force overwrites an existing adgrad.yaml)
"""
import shutil
import sys
from pathlib import Path

import config
import yaml

EXAMPLE, TARGET = Path("adgrad.example.yaml"), Path("adgrad.yaml")
STRATEGIES = Path("strategies")


def ask(question, default=None, check=None):
    while True:
        answer = input(f"{question}{f' [{default}]' if default not in (None, '') else ''}: ").strip()
        value = answer or (default if default is not None else "")
        problem = check(value) if check else None
        if not problem:
            return value
        print(f"  {problem}")


def ask_list(question, default):
    return [x.strip() for x in ask(question, ", ".join(default)).split(",") if x.strip()]


def build(answers, base):
    """The new config dict: the example with the answers filled in (pure, for tests)."""
    c = yaml.safe_load(yaml.safe_dump(base))
    a = c["account"]
    a.update({k: answers[k] for k in ("customer_id", "login_customer_id", "name", "currency", "timezone")})
    c["limits"]["daily_budget_cap"] = float(answers["daily_budget_cap"])
    c["topics"] = {t: {"substrings": [t.replace("_", " ")], "words": []} for t in answers["topics"]}
    c["winning_topics"] = [t for t in answers["winning_topics"] if t in c["topics"]]
    c["ad_group_topics"] = {}
    c["conversions"]["lead_signals"] = answers["lead_signals"]
    c["conversions"]["noise_signals"] = answers["noise_signals"]
    c["website"]["base_url"] = answers["base_url"] or None
    c["ad_tests"]["enabled"] = bool(answers["base_url"])
    c["ad_tests"]["campaign_locales"] = {}
    c["crm"]["source"] = answers["crm"]
    if answers["crm"] == "csv":
        c["crm"]["csv_path"] = answers["crm_location"]
    elif answers["crm"] == "google_sheets":
        c["crm"]["sheet_id"] = answers["crm_location"]
    c["tracker"]["backend"] = answers["tracker"]
    return c


def main():
    if TARGET.exists() and "--force" not in sys.argv:
        sys.exit(f"{TARGET} exists. Edit it, or run with --force to start over.")
    base = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    print("adgrad init: a few questions, Enter keeps the [default]. Everything else stays as in adgrad.example.yaml.\n")
    digits = lambda v: None if config.digits(v) else "10 digits, like 123-456-7890"  # noqa: E731
    answers = {
        "customer_id": ask("Google Ads customer id (the ad account)", check=digits),
        "login_customer_id": ask("Manager (MCC) account id, empty if none", "",
                                 check=lambda v: None if not v or config.digits(v) else "10 digits or empty"),
        "name": ask("Account or business name", "my account"),
        "currency": ask("Account currency (ISO code)", "USD").upper(),
        "timezone": ask("Account time zone (IANA name)", "America/New_York"),
        "daily_budget_cap": ask("Total daily budget cap across enabled campaigns", "100"),
        "topics": [t.lower().replace(" ", "_") for t in ask_list("Topics you sell (comma-separated)",
                                                                 list(base["topics"]))],
    }
    answers["winning_topics"] = [t.lower() for t in ask_list("Which of them close deals today (comma-separated)",
                                                            answers["topics"][:1])]
    answers["lead_signals"] = ask_list("Conversion actions that signal a lead (comma-separated)",
                                       base["conversions"]["lead_signals"])
    answers["noise_signals"] = ask_list("Noisy conversion actions to show but never judge on (empty for none)", [])
    answers["base_url"] = ask("Website base URL for ad claims (empty turns ad tests off)", "")
    answers["crm"] = ask("CRM source: none, csv or google_sheets", "none",
                         check=lambda v: None if v in config.CRM_SOURCES else "none, csv or google_sheets")
    answers["crm_location"] = (ask("CSV path" if answers["crm"] == "csv" else "Google Sheet id")
                               if answers["crm"] != "none" else "")
    answers["tracker"] = ask(f"Tracker ({', '.join(config.TRACKERS)})", "github-issues",
                             check=lambda v: None if v in config.TRACKERS else f"one of {', '.join(config.TRACKERS)}")
    c = build(answers, base)
    try:
        config.load_dict(yaml.safe_load(yaml.safe_dump(c)))
    except config.ConfigError as e:
        print(f"\nNot written, the answers fail validation:\n{e}\nFix them and run init again.")
        sys.exit(1)
    header = ("# adgrad config written by scripts/init.py. Comments for every field: adgrad.example.yaml.\n"
              "# Next: map your ad group names to topics (ad_group_topics) and, with a CRM, its columns and statuses.\n")
    TARGET.write_text(header + yaml.safe_dump(c, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"\nWrote {TARGET}.")
    if not Path("STRATEGY.md").exists():
        choices = sorted(p.stem for p in STRATEGIES.glob("*.md") if p.stem != "README")
        pick = ask(f"Strategy template ({', '.join(choices)})", "b2b-lead-gen",
                   check=lambda v: None if v in choices else f"one of {', '.join(choices)}")
        shutil.copy(STRATEGIES / f"{pick}.md", "STRATEGY.md")
        print(f"Copied strategies/{pick}.md to STRATEGY.md. Edit it, or run prompts/strategy-interview.md in your agent.")
    print("Then: map ad_group_topics, set up google-ads.yaml (SETUP.md) and run `uv run scripts/check_connection.py`.")


if __name__ == "__main__":
    main()
