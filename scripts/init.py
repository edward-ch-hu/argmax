"""Write argmax.yaml from answers. Non-interactive (what the onboarding agent calls) or interactive (by hand).

Answers are a partial config (YAML or JSON) laid over argmax.example.yaml after its fictional parts are cleared
(business profile, topics, ad group map, conversions, website, CRM, tracker, market_price, experiments): whatever you do not answer keeps the
example's limits and thresholds. Shortcuts: "topics" may be a list of names (each becomes a substring of itself), an
empty or missing website.base_url turns ad tests off, and business.goal without primary_kpi gets the usual KPI for
that goal (DEFAULT_KPI). The result is validated before anything is written.

Money limits are in the account currency, so the example's (USD-sized) values do not fit every account. --derive
reads the account once API access works (step c of onboarding) and sizes them from it; answers you give still win:
  cpc = the 30-day average Search CPC (cost / clicks of Search campaigns)
  negatives.min_cost                    3 x cpc    (a junk term's spend before it is blocked)
  negatives.held_notify_cost            5 x cpc
  match_type_review.min_off_intent_spend 5 x cpc
  keyword_review.min_pause_cost         20 x cpc   (about 20 clicks without a lead signal)
  limits.bid_floor                      0.25 x cpc
  limits.bid_ceiling                    3 x the highest current Search bid (ad group or keyword), or 3 x cpc
  limits.daily_budget_cap               today's total daily budget of enabled campaigns (shared budgets once),
                                        rounded up
  STRATEGY.md evidence floor (printed)  500 x cpc  (spend before a topic may be cut on outcome data)
With no Search clicks in 30 days there is no cpc: init stops and asks for --cpc <amount> (the CPC you expect, in the
account currency) or the limits in the answers. --cpc also works without API access. Every run prints the limits in
plain words in the account currency, to read back to the owner.

Usage: uv run scripts/init.py --answers answers.yaml [--derive | --cpc <amount>] [--dry-run] [--force]
                              [--strategy b2b-lead-gen]
       uv run scripts/init.py                      (asks a few questions instead)
  --derive    size the money limits from the account (needs google-ads.yaml or GOOGLE_ADS_* credentials)
  --cpc       size them from this cost per click instead (no API call; the cap must then be in the answers)
  --dry-run   print the YAML that would be written, write nothing (show it to the owner first)
  --force     overwrite an existing argmax.yaml
  --strategy  also copy strategies/<name>.md to STRATEGY.md when there is none
Changes nothing in Google Ads.
"""
import math
import copy
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
    c["api"] = copy.deepcopy(config.DEFAULTS["api"])  # unknown until the owner reads it off the Overview page
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
    # a market-price ceiling and experiments are set later, with the owner's "yes" (the example's are USD-sized)
    c["market_price"] = copy.deepcopy(config.DEFAULTS["market_price"])
    c["experiments"] = []
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


# Multiples of the 30-day average Search CPC for the money limits (see the docstring).
CPC_MULTIPLES = {"negatives.min_cost": 3, "negatives.held_notify_cost": 5, "match_type_review.min_off_intent_spend": 5,
                 "keyword_review.min_pause_cost": 20, "limits.bid_floor": 0.25}
CEILING_MULTIPLE = 3
EVIDENCE_MULTIPLE = 500
MONEY_KEYS = (*CPC_MULTIPLES, "limits.bid_ceiling", "limits.daily_budget_cap")


def amount(value, currency):
    """A money amount rounded for a config: whole units for zero-decimal currencies and amounts of 10 or more,
    else cents; never below the smallest unit. Pure."""
    import ads_client

    if currency in ads_client.ZERO_DECIMAL or value >= 10:
        return max(1, round(value)) if currency in ads_client.ZERO_DECIMAL else float(max(1, round(value)))
    return max(0.01, round(value, 2))


def derive(cpc, max_bid, budget_total, currency):
    """{dotted key: value} for the money limits from the account's numbers (any may be None). Pure."""
    out = {}
    if cpc:
        out.update({key: amount(cpc * x, currency) for key, x in CPC_MULTIPLES.items()})
        out["limits.bid_ceiling"] = amount(CEILING_MULTIPLE * (max_bid or cpc), currency)
        if out["limits.bid_ceiling"] <= out["limits.bid_floor"]:
            out["limits.bid_ceiling"] = amount(CEILING_MULTIPLE * cpc, currency)
    if budget_total:
        out["limits.daily_budget_cap"] = math.ceil(budget_total - 1e-9)
    return out


def nested(dotted):
    """{"a.b": 1} -> {"a": {"b": 1}}. Pure."""
    out = {}
    for key, value in dotted.items():
        node = out
        *path, last = key.split(".")
        for k in path:
            node = node.setdefault(k, {})
        node[last] = value
    return out


def account_numbers(customer_id, login_customer_id=None):
    """(30-day average Search CPC or None, highest current Search bid or None, today's enabled budget total) read
    from the account. Read-only."""
    import ads_client

    client = ads_client.client_from_credentials()
    if login_customer_id:
        client.login_customer_id = config.digits(login_customer_id)
    ga = client.get_service("GoogleAdsService")
    cid = config.digits(customer_id)

    def rows(query):
        return [r for batch in ga.search_stream(customer_id=cid, query=query) for r in batch.results]

    cost = clicks = 0
    for r in rows("""SELECT metrics.cost_micros, metrics.clicks FROM campaign
            WHERE campaign.advertising_channel_type = 'SEARCH' AND segments.date DURING LAST_30_DAYS"""):
        cost, clicks = cost + r.metrics.cost_micros, clicks + r.metrics.clicks
    bids = [r.ad_group.cpc_bid_micros for r in rows("""SELECT ad_group.cpc_bid_micros FROM ad_group
            WHERE campaign.status = 'ENABLED' AND ad_group.status = 'ENABLED'
            AND campaign.advertising_channel_type = 'SEARCH'""")]
    bids += [r.ad_group_criterion.cpc_bid_micros for r in rows("""SELECT ad_group_criterion.cpc_bid_micros
            FROM ad_group_criterion WHERE campaign.status = 'ENABLED' AND ad_group.status = 'ENABLED'
            AND ad_group_criterion.status = 'ENABLED' AND ad_group_criterion.type = 'KEYWORD'
            AND ad_group_criterion.negative = FALSE AND campaign.advertising_channel_type = 'SEARCH'""")]
    budgets = [(r.campaign_budget.resource_name, r.campaign_budget.amount_micros / 1e6) for r in
               rows("SELECT campaign_budget.resource_name, campaign_budget.amount_micros FROM campaign "
                    "WHERE campaign.status = 'ENABLED'")]
    return ((cost / clicks / 1e6) if clicks else None, (max(bids) / 1e6) if any(bids) else None,
            ads_client.budget_total(budgets))


def has(answers, dotted):
    node = answers or {}
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return node not in (None, "")


def with_derived(answers, derived):
    """The answers with derived limits filled in where the answers do not set them. Pure."""
    return merge_plain(nested(derived), copy.deepcopy(answers or {}))


def read_back(c, cpc=None, budget_total=None):
    """The money limits in plain words in the account currency, for the owner to confirm. Pure."""
    cur, lim, n = c["account"]["currency"], c["limits"], c["negatives"]
    m = lambda v: f"{cur} {v:,.2f}".replace(".00", "")  # noqa: E731
    lines = [f"Limits in {cur}" + (f", sized from a 30-day average Search CPC of {m(cpc)}:" if cpc else ":")]
    lines.append(f"- The total daily budget across enabled campaigns never goes above {m(lim['daily_budget_cap'])}"
                 + (f" (today's enabled budgets add up to {m(budget_total)})." if budget_total else "."))
    lines.append(f"- Ad group and keyword bids stay between {m(lim['bid_floor'])} and {m(lim['bid_ceiling'])}, and an "
                 f"ad group bid moves at most {lim['weekly_bid_change']:.0%} a week.")
    lines.append(f"- A search term with no lead signal is blocked after {m(n['min_cost'])} spent over at least "
                 f"{n.get('min_cost_clicks', 3)} clicks, or after {n['min_clicks']} clicks; a junk word after one click.")
    lines.append(f"- A winning-topic term held for the weekly is flagged once it costs {m(n['held_notify_cost'])}.")
    lines.append(f"- A keyword with no lead signal is proposed for a pause after {m(c['keyword_review']['min_pause_cost'])}.")
    lines.append(f"- A keyword is proposed for a tighter match type once {m(c['match_type_review']['min_off_intent_spend'])} "
                 "of its spend went to off-intent searches.")
    safety = (c.get("market_price") or {}).get("safety_limit")
    if safety:
        lines.append(f"- No market-price ceiling (experiments, market_price.groups) ever goes above {m(safety)}.")
    if cpc:
        lines.append(f"- STRATEGY.md evidence floor: no topic is cut on outcome data before about "
                     f"{m(amount(EVIDENCE_MULTIPLE * cpc, cur))} spent on it ({EVIDENCE_MULTIPLE} x CPC).")
    return "\n".join(lines)


def validate(c):
    """Raises config.ConfigError when the built config is invalid."""
    return config.load_dict(yaml.safe_load(yaml.safe_dump(c)))


def write(c, force=False):
    if TARGET.exists() and not force:
        sys.exit(f"{TARGET} exists. Edit it, or pass --force to replace it.")
    TARGET.write_text(HEADER + yaml.safe_dump(c, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {TARGET}.")


def copy_strategy(name, end_state=None):
    """Copies strategies/<name>.md to STRATEGY.md (never over an existing one), with its "Bidding end state" line set
    to business.bidding_end_state when that is known."""
    if Path("STRATEGY.md").exists():
        print("STRATEGY.md exists: left as it is.")
        return
    src = STRATEGIES / f"{name}.md"
    if not src.exists():
        sys.exit(f"No strategy template {src}. Choose one of: "
                 + ", ".join(sorted(p.stem for p in STRATEGIES.glob("*.md") if p.stem != "README")))
    text = src.read_text(encoding="utf-8")
    if end_state:
        import strategy_check
        text = strategy_check.pick_bidding(text, end_state)
    Path("STRATEGY.md").write_text(text, encoding="utf-8")
    print(f"Copied {src} to STRATEGY.md" + (f" (bidding end state: {end_state})." if end_state else "."))


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
        "login_customer_id": ask("Manager account id, only if you reach the ad account through one (empty for a "
                                 "single account)", "",
                                 check=lambda v: None if not v or config.digits(v) else "10 digits or empty") or None,
        "name": ask("Account or business name", "my account"),
        "currency": ask("Account currency (ISO code)", "USD").upper(),
        "timezone": ask("Account time zone (IANA name)", "America/New_York")}}
    levels = [k for k in config.ACCESS_LEVELS]
    a["api"] = {"access_level": ask(f"Google Ads API access level on your Cloud project's Overview page "
                                    f"({' | '.join(levels)})", "unknown",
                                    check=lambda v: None if v in levels else ", ".join(levels))}
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
        "deal_currency": ask("Currency of deal values in your CRM", a["account"]["currency"]).upper(),
        "bidding_end_state": ask("Where bidding ends up: smart_bidding (hand bids to Google once conversions are many "
                                 "and clean) or manual_cpc (the agent keeps Manual CPC for good; low volume or noisy "
                                 "conversions)", "manual_cpc",
                                 check=lambda v: None if v in config.BIDDING_END_STATES else "smart_bidding or manual_cpc")}
    if a["business"]["deal_currency"] != a["account"]["currency"]:
        cur, deal = a["account"]["currency"], a["business"]["deal_currency"]
        a["crm"] = {"deal_value_fx": float(ask(f"How many {cur} is 1 {deal} (for ROI)", "1"))}
    cur = a["account"]["currency"]
    cpc = float(ask(f"Your usual cost per click in {cur} (sizes the money limits; the account's 30-day average is "
                    "best)", "1"))
    a["limits"] = {"daily_budget_cap": float(ask(f"Total daily budget cap across enabled campaigns, in {cur}", "100"))}
    a = with_derived(a, derive(cpc, None, None, cur))
    a["topics"] = ask_list("Topics you sell (comma-separated)", list(base["topics"]))
    names = [t.lower().replace(" ", "_") for t in a["topics"]]
    a["winning_topics"] = [t for t in ask_list("Which of them close deals today", names[:1]) if t in names]
    a["conversions"] = {"lead_signals": ask_list("Conversion actions that signal a lead", ["Form Submit"]),
                        "noise_signals": ask_list("Noisy conversion actions to show but never judge on", [])}
    a["website"] = {"base_url": ask("Website base URL for ad claims (empty turns ad tests off)", "") or None}
    a["tracker"] = {"backend": ask(f"Tracker ({', '.join(config.TRACKERS)})", "files",
                                   check=lambda v: None if v in config.TRACKERS else ", ".join(config.TRACKERS))}
    return a, cpc


def main():
    args = sys.argv[1:]
    opt = lambda name: args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None  # noqa: E731
    base = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    path = opt("--answers")
    cpc = budget_total = None
    if path:
        answers = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    else:
        answers, cpc = interactive(base)
    if "--derive" in args or opt("--cpc"):
        account = (answers or {}).get("account") or {}
        cur = account.get("currency")
        max_bid = None
        if opt("--cpc"):
            cpc = float(opt("--cpc"))
        else:
            if not config.digits(account.get("customer_id")):
                sys.exit("--derive needs account.customer_id in the answers")
            cpc, max_bid, budget_total = account_numbers(account["customer_id"], account.get("login_customer_id"))
        if cpc is None:
            missing = [k for k in MONEY_KEYS if k != "limits.daily_budget_cap" and not has(answers, k)]
            if missing:
                sys.exit(f"Not written: the account has no Search clicks in the last 30 days, so the money limits "
                         f"cannot be sized from it. Run again with --cpc <the cost per click you expect, in {cur}> "
                         f"(Keyword Planner's top-of-page bid, or another account's average), or put these in the "
                         f"answers in {cur}: {', '.join(missing)}.")
        answers = with_derived(answers, derive(cpc, max_bid, budget_total, cur))
    c = build(answers, base)
    try:
        validate(c)
    except config.ConfigError as e:
        print(f"Not written, the answers fail validation:\n{e}")
        sys.exit(1)
    unsized = [k for k in MONEY_KEYS if not has(answers, k)]
    if unsized:
        print(f"WARN   {', '.join(unsized)} keep the example's values, sized for a USD account: run with --derive "
              f"(or --cpc) to size them for this {c['account']['currency']} account.")
    if "--dry-run" in args:
        print(HEADER + yaml.safe_dump(c, sort_keys=False, allow_unicode=True))
        print(read_back(c, cpc, budget_total))
        return
    write(c, "--force" in args)
    print(read_back(c, cpc, budget_total))
    if opt("--strategy"):
        copy_strategy(opt("--strategy"), c["business"].get("bidding_end_state"))
    print("Next: `uv run scripts/doctor.py` shows what is still missing.")


if __name__ == "__main__":
    main()
