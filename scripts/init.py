"""Write argmax.yaml from answers. Non-interactive (what the onboarding agent calls) or interactive (by hand).

Answers are a partial config (YAML or JSON) laid over argmax.example.yaml after its fictional parts are cleared
(business profile, topics, ad group map, conversions, website, CRM, tracker): whatever you do not answer keeps the
example's limits and thresholds. Shortcuts: "topics" may be a list of names (each becomes a substring of itself), an
empty or missing website.base_url turns ad tests off, and business.goal without primary_kpi gets the usual KPI for
that goal (DEFAULT_KPI). The result is validated before anything is written.

Usage: uv run scripts/init.py --answers answers.yaml [--dry-run] [--force] [--strategy b2b-lead-gen]
       uv run scripts/init.py                      (asks a few questions instead)
  --dry-run   print the YAML that would be written, write nothing (show it to the owner first)
  --force     overwrite an existing argmax.yaml
  --strategy  also copy strategies/<name>.md to STRATEGY.md when there is none
Changes nothing in Google Ads.
"""
import copy
import shutil
import sys
from pathlib import Path

import config
import yaml

EXAMPLE, TARGET = Path("argmax.example.yaml"), Path("argmax.yaml")
STRATEGIES = Path("strategies")
DEFAULT_KPI = {"leads": "CRM wins", "sales": "orders", "roas": "purchase value per spend", "calls": "qualified calls",
               "awareness": "impression share"}
HEADER = ("# argmax config written by scripts/init.py. Comments for every field: argmax.example.yaml.\n"
          "# Secrets never go here: google-ads.yaml or GOOGLE_ADS_* env vars (SETUP.md).\n")


def cleared(base):
    """The example with its fictional business removed (limits and thresholds stay)."""
    c = copy.deepcopy(base)
    c["account"].update({"customer_id": None, "login_customer_id": None, "name": "my account"})
    c["business"] = copy.deepcopy(config.DEFAULTS["business"])
    c["topics"], c["winning_topics"], c["ad_group_topics"] = {}, [], {}
    c["conversions"] = {"lead_signals": [], "noise_signals": []}
    c["website"]["base_url"] = None
    c["website"].pop("locales", None)            # derived from business.markets
    c["ad_tests"].pop("campaign_locales", None)  # derived from business.markets
    c["ad_tests"].pop("default_locale", None)
    c["crm"] = copy.deepcopy(config.DEFAULTS["crm"])
    c["ref_codes"] = copy.deepcopy(config.DEFAULTS["ref_codes"])
    c["tracker"] = merge_plain(copy.deepcopy(config.DEFAULTS["tracker"]), {"backend": "files"})
    c["report"]["client_update"]["blocklist"] = []
    return c


def merge_plain(base, extra):
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict) and key not in ("topics", "ad_group_topics"):
            merge_plain(base[key], value)
        else:
            base[key] = value
    return base


def build(answers, base):
    """The new config dict from answers over the cleared example (pure, for tests)."""
    answers = copy.deepcopy(answers or {})
    topics = answers.get("topics")
    if isinstance(topics, list):
        answers["topics"] = {t.strip().lower().replace(" ", "_"): {"substrings": [t.strip().lower().replace("_", " ")],
                                                                    "words": []} for t in topics if t.strip()}
    c = merge_plain(cleared(base), answers)
    b = c["business"]
    if b.get("goal") in DEFAULT_KPI and not b.get("primary_kpi"):
        b["primary_kpi"] = DEFAULT_KPI[b["goal"]]
    if not (c.get("website") or {}).get("base_url"):
        c["website"]["base_url"] = None
        c["ad_tests"]["enabled"] = False
    return c


def validate(c):
    """Raises config.ConfigError when the built config is invalid."""
    return config.load_dict(yaml.safe_load(yaml.safe_dump(c)))


def write(c, force=False):
    if TARGET.exists() and not force:
        sys.exit(f"{TARGET} exists. Edit it, or pass --force to replace it.")
    TARGET.write_text(HEADER + yaml.safe_dump(c, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {TARGET}.")


def copy_strategy(name):
    if Path("STRATEGY.md").exists():
        print("STRATEGY.md exists: left as it is.")
        return
    src = STRATEGIES / f"{name}.md"
    if not src.exists():
        sys.exit(f"No strategy template {src}. Choose one of: "
                 + ", ".join(sorted(p.stem for p in STRATEGIES.glob("*.md") if p.stem != "README")))
    shutil.copy(src, "STRATEGY.md")
    print(f"Copied {src} to STRATEGY.md.")


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


def interactive(base):
    print("argmax init: a few questions, Enter keeps the [default]. The onboarding prompt (prompts/onboarding.md)\n"
          "does this and more with your agent; everything else stays as in argmax.example.yaml.\n")
    digits = lambda v: None if config.digits(v) else "10 digits, like 123-456-7890"  # noqa: E731
    a = {"account": {
        "customer_id": ask("Google Ads customer id (the ad account)", check=digits),
        "login_customer_id": ask("Manager (MCC) account id, empty if none", "",
                                 check=lambda v: None if not v or config.digits(v) else "10 digits or empty") or None,
        "name": ask("Account or business name", "my account"),
        "currency": ask("Account currency (ISO code)", "USD").upper(),
        "timezone": ask("Account time zone (IANA name)", "America/New_York")}}
    goal = ask(f"Business goal ({' | '.join(config.GOALS)})", "leads",
               check=lambda v: None if v in config.GOALS else ", ".join(config.GOALS))
    language = ask("Ad language of your main market, as a site locale code (en, de, zh-tw)", "en")
    a["business"] = {
        "goal": goal,
        "goal_description": ask("The goal in one line, in your words", "") or None,
        "primary_kpi": ask("What success is counted in", DEFAULT_KPI[goal]),
        "markets": [{"name": ask("Main market name", "Main"),
                     "countries": ask_list("Its countries or regions (comma-separated)", ["US"]),
                     "language": language}],
        "report_language": ask("Language for reports and decisions", "English"),
        "deal_currency": ask("Currency of deal values in your CRM", a["account"]["currency"]).upper()}
    if a["business"]["deal_currency"] != a["account"]["currency"]:
        cur, deal = a["account"]["currency"], a["business"]["deal_currency"]
        a["crm"] = {"deal_value_fx": float(ask(f"How many {cur} is 1 {deal} (for ROI)", "1"))}
    a["limits"] = {"daily_budget_cap": float(ask("Total daily budget cap across enabled campaigns", "100"))}
    a["topics"] = ask_list("Topics you sell (comma-separated)", list(base["topics"]))
    names = [t.lower().replace(" ", "_") for t in a["topics"]]
    a["winning_topics"] = [t for t in ask_list("Which of them close deals today", names[:1]) if t in names]
    a["conversions"] = {"lead_signals": ask_list("Conversion actions that signal a lead", ["Form Submit"]),
                        "noise_signals": ask_list("Noisy conversion actions to show but never judge on", [])}
    a["website"] = {"base_url": ask("Website base URL for ad claims (empty turns ad tests off)", "") or None}
    a["tracker"] = {"backend": ask(f"Tracker ({', '.join(config.TRACKERS)})", "files",
                                   check=lambda v: None if v in config.TRACKERS else ", ".join(config.TRACKERS))}
    return a


def main():
    args = sys.argv[1:]
    opt = lambda name: args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None  # noqa: E731
    base = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    path = opt("--answers")
    answers = yaml.safe_load(Path(path).read_text(encoding="utf-8")) if path else interactive(base)
    c = build(answers, base)
    try:
        validate(c)
    except config.ConfigError as e:
        print(f"Not written, the answers fail validation:\n{e}")
        sys.exit(1)
    if "--dry-run" in args:
        print(HEADER + yaml.safe_dump(c, sort_keys=False, allow_unicode=True))
        return
    write(c, "--force" in args)
    if opt("--strategy"):
        copy_strategy(opt("--strategy"))
    print("Next: `uv run scripts/doctor.py` shows what is still missing.")


if __name__ == "__main__":
    main()
