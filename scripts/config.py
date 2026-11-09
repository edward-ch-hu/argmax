"""argmax config: one YAML file, validated once, read by every script through get().

Where it comes from (first match wins):
  1. ARGMAX_CONFIG_YAML  the whole YAML as text (handy for cloud routine environment variables)
  2. ARGMAX_CONFIG       a path to a YAML file
  3. argmax.yaml         in the working directory
Then ARGMAX_CUSTOMER_ID and ARGMAX_LOGIN_CUSTOMER_ID override the account ids when set.

Optional fields take the defaults in DEFAULTS. A missing file or an invalid field stops the script with one line per
problem. Secrets (OAuth client, refresh token, an old developer token) never live here: they stay in google-ads.yaml
or the GOOGLE_ADS_* environment variables.

api.access_level is the Google Ads API access level of the Cloud project that owns the OAuth client, as its Google
Ads API Overview page shows it (the API does not report it). Explorer restricts Keyword Planning, so
keyword_review.ideas "auto" skips Keyword Planner ideas on test or explorer access.

The business profile (business:) is the one source for markets and languages. When left out, website.locales,
ad_tests.campaign_locales and ad_tests.default_locale are derived from business.markets (when set, they must agree
with the markets). report.client_update.language defaults to business.report_language, business.deal_currency to
account.currency, and crm.deal_value_fx is needed only when those two currencies differ.
"""
import copy
import os
import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

DEFAULT_PATH = Path("argmax.yaml")
TRACKERS = ("github-issues", "files", "clickup", "notion", "linear")
CRM_SOURCES = ("none", "csv", "google_sheets")
STATUSES = ("talking", "trial", "won", "lost_after_trial", "lost_no_trial")
RESERVED_TOPICS = ("other", "none", "mixed")
GOALS = ("leads", "sales", "roas", "calls", "awareness")
# Where bidding ends up: a hand-off to Google's Smart Bidding, or Manual CPC run by the agent for good.
BIDDING_END_STATES = ("smart_bidding", "manual_cpc")
# Google Ads API access levels (per Cloud project since 2026-09-09) and their operations per day on production
# accounts: https://developers.google.com/google-ads/api/docs/api-policy/access-levels . None = not known yet.
ACCESS_LEVELS = {"unknown": None, "test": 0, "explorer": 2880, "basic": 15000, "standard": float("inf")}
IDEAS_MODES = ("auto", "off")

DEFAULTS = {
    "business": {"goal": None, "goal_description": None, "primary_kpi": None, "kpi_conversions": [], "markets": [],
                 "report_language": "English", "deal_currency": None, "bidding_end_state": None},
    "account": {"customer_id": None, "login_customer_id": None, "name": "my account", "currency": None,
                "timezone": None},
    "limits": {"daily_budget_cap": None, "weekly_bid_change": 0.20, "bid_floor": 0.20, "bid_ceiling": 5.00,
               "allow_enable_performance_max": False},
    "guard": {"expected_bidding": "MANUAL_CPC", "search_networks_only": True, "overspend_multiple": 2.0},
    "stepping": {"enabled": True, "step": 0.10, "weekly_limit": 0.30, "window_days": 14,
                 "rank_lost_band": [0.20, 0.50], "budget_lost_max": 0.20, "min_impressions": 30, "new_groups": {}},
    "negatives": {"max_per_day": 10, "lookback_days": 7, "protect_days": 30, "held_notify_cost": 5.0, "min_cost": 3.0,
                  "min_cost_clicks": 3, "min_clicks": 10,
                  "junk_words": ["free", "download", "crack", "torrent", "jobs", "job", "salary", "career",
                                 "tutorial", "course", "github", "reddit"]},
    "api": {"access_level": "unknown"},
    "keyword_review": {"min_positive_conversions": 2, "min_pause_cost": 20.0, "ideas": "auto", "ideas_per_ad_group": 8,
                       "ideas_min_monthly_searches": 10},
    "match_type_review": {"broad_to_phrase_share": 0.30, "phrase_to_exact_share": 0.50, "min_off_intent_spend": 10.0},
    "topics": {},
    "winning_topics": [],
    "ad_group_topics": {},
    "conversions": {"lead_signals": [], "noise_signals": []},
    "website": {"base_url": None, "locales": None, "user_agent": "argmax claims check"},
    "ad_tests": {"enabled": True, "library": "docs/ad_library.json", "campaign_locales": None, "default_locale": None,
                 "min_impressions_14d": 300, "max_running": 3, "max_new_per_week": 1, "min_days": 28,
                 "max_days": 56, "min_arm_impressions": 1000, "z": 1.96, "claims_max_age_days": 7},
    "crm": {"source": "none", "csv_path": None, "sheet_id": None, "sheet_range": "Sheet1!A1:Z", "date_format": None,
            "columns": {"id": None, "lead_date": None, "status": None, "topics": None, "deal_value": None,
                        "name": None, "email": None, "ref": None},
            "statuses": {"talking": [], "trial": [], "won": [], "lost_after_trial": [], "lost_no_trial": []},
            "default_status": "talking", "deal_value_label": "MRR", "deal_value_fx": None, "stale_after_days": 14},
    "ref_codes": {"enabled": False, "prefix": "AM-", "live_from": None, "test_codes": []},
    "tracker": {"backend": "files", "github": {}, "clickup": {}, "notion": {}, "linear": {}, "files": {}},
    "report": {"history_start": None, "client_update": {"enabled": True, "language": None, "blocklist": []}},
}
# Sections that become attribute namespaces (cfg.limits.daily_budget_cap). Mappings keyed by user names (topics,
# ad group names, statuses, columns) stay plain dicts.
SECTIONS = ("business", "account", "api", "limits", "guard", "stepping", "negatives", "keyword_review", "match_type_review",
            "conversions", "website", "ad_tests", "crm", "ref_codes", "tracker", "report")


class ConfigError(Exception):
    """Raised by load() with every problem found, one per line."""


def merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict) and key not in ("topics", "ad_group_topics"):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def digits(value):
    """A Google Ads customer id as 10 digits (dashes and spaces removed), or None when it is not one."""
    if value is None:
        return None
    text = re.sub(r"[\s-]", "", str(value))
    return text if re.fullmatch(r"\d{10}", text) else None


def number(problems, where, value, low=None, high=None, low_open=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{where}: must be a number (got {value!r})")
        return
    if low is not None and (value <= low if low_open else value < low):
        problems.append(f"{where}: must be {'over' if low_open else 'at least'} {low} (got {value})")
    if high is not None and value > high:
        problems.append(f"{where}: must be at most {high} (got {value})")


def str_list(problems, where, value, allow_empty=True):
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        problems.append(f"{where}: must be a list of non-empty strings")
        return False
    if not allow_empty and not value:
        problems.append(f"{where}: needs at least one entry")
        return False
    return True


def one_line(problems, where, value, required=False):
    """A one-line string (or None when not required)."""
    if value is None and not required:
        return
    if not (isinstance(value, str) and value.strip() and "\n" not in value.strip()):
        problems.append(f"{where}: must be one line of text (got {value!r})")


def validate_business(p, c):
    """The business profile. Fills deal_currency and kpi_conversions defaults in place."""
    b, a = c["business"], c["account"]
    if b["goal"] is not None and b["goal"] not in GOALS:
        p.append(f"business.goal: must be one of {', '.join(GOALS)} (got {b['goal']!r})")
    one_line(p, "business.goal_description", b["goal_description"])
    one_line(p, "business.primary_kpi", b["primary_kpi"])
    if b["goal"] is not None and not b["primary_kpi"]:
        p.append("business.primary_kpi: needed once business.goal is set (what success is counted in, e.g. CRM wins)")
    one_line(p, "business.report_language", b["report_language"], required=True)
    end = b["bidding_end_state"]
    if end is not None and end not in BIDDING_END_STATES:
        p.append(f"business.bidding_end_state: must be one of {', '.join(BIDDING_END_STATES)} (got {end!r})")
    elif end == "manual_cpc" and c["guard"]["expected_bidding"] != "MANUAL_CPC":
        p.append("guard.expected_bidding: must be MANUAL_CPC while business.bidding_end_state is manual_cpc (bids stay "
                 f"Manual CPC for good, so the daily guard alerts on any other strategy; got {c['guard']['expected_bidding']!r})")
    if b["deal_currency"] is None:
        b["deal_currency"] = a["currency"]
    elif not (isinstance(b["deal_currency"], str) and re.fullmatch(r"[A-Z]{3}", b["deal_currency"])):
        p.append(f"business.deal_currency: must be a 3-letter ISO code like USD (got {b['deal_currency']!r})")
    signals = c["conversions"]["lead_signals"]
    if str_list(p, "business.kpi_conversions", b["kpi_conversions"]):
        if not b["kpi_conversions"] and isinstance(signals, list):
            b["kpi_conversions"] = list(signals)
        for name in b["kpi_conversions"]:
            if isinstance(signals, list) and name not in signals:
                p.append(f"business.kpi_conversions: '{name}' is not in conversions.lead_signals (add it there first)")

    markets = b["markets"]
    if not isinstance(markets, list):
        p.append("business.markets: must be a list of {name, countries, language, campaign_prefix}")
        b["markets"] = markets = []
    if b["goal"] is not None and not markets:
        p.append("business.markets: needed once business.goal is set (at least one market: countries and ad language)")
    names, prefixes = set(), set()
    for i, m in enumerate(markets):
        where = f"business.markets[{i}]"
        if not isinstance(m, dict):
            p.append(f"{where}: must be a mapping with name, countries, language")
            continue
        unknown = set(m) - {"name", "countries", "language", "campaign_prefix"}
        if unknown:
            p.append(f"{where}: unknown key(s) {', '.join(sorted(unknown))} (use name, countries, language, campaign_prefix)")
        name = m.get("name")
        if not (isinstance(name, str) and name.strip()):
            p.append(f"{where}.name: needed (e.g. US or DACH)")
        else:
            where = f"business.markets.{name}"
            if name in names:
                p.append(f"{where}: two markets have this name")
            names.add(name)
        str_list(p, f"{where}.countries", m.get("countries"), allow_empty=False)
        lang = m.get("language")
        if not (isinstance(lang, str) and re.fullmatch(r"[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*", lang)):
            p.append(f"{where}.language: the ad language as a site locale code like en, de or zh-tw (got {lang!r})")
        prefix = m.get("campaign_prefix")
        if prefix is not None:
            if not (isinstance(prefix, str) and prefix):
                p.append(f"{where}.campaign_prefix: a campaign name prefix like \"US - \", or leave it out")
            elif prefix in prefixes:
                p.append(f"{where}.campaign_prefix: '{prefix}' is used by two markets")
            else:
                prefixes.add(prefix)


def market_locales(c):
    """(languages in market order, {campaign prefix: language}) from business.markets (valid entries only)."""
    langs, prefixes = [], {}
    for m in c["business"]["markets"]:
        if not isinstance(m, dict) or not isinstance(m.get("language"), str):
            continue
        if m["language"] not in langs:
            langs.append(m["language"])
        if isinstance(m.get("campaign_prefix"), str) and m["campaign_prefix"]:
            prefixes[m["campaign_prefix"]] = m["language"]
    return langs, prefixes


def validate(c):
    """Every problem in the merged config dict, as lines. Normalises ids and fills derived values in place."""
    p = []
    a = c["account"]
    cid = digits(a["customer_id"])
    if cid is None:
        p.append(f"account.customer_id: must be a 10-digit Google Ads id like 123-456-7890 (got {a['customer_id']!r})")
    a["customer_id"] = cid
    if a["login_customer_id"] not in (None, ""):
        login = digits(a["login_customer_id"])
        if login is None:
            p.append("account.login_customer_id: the 10-digit id of the manager account you reach the ad account "
                     f"through, or empty when your login has direct access (got {a['login_customer_id']!r})")
        a["login_customer_id"] = login
    else:
        a["login_customer_id"] = None
    if not (isinstance(a["currency"], str) and re.fullmatch(r"[A-Z]{3}", a["currency"])):
        p.append(f"account.currency: must be a 3-letter ISO code like USD (got {a['currency']!r})")
    try:
        if not isinstance(a["timezone"], str):
            raise ZoneInfoNotFoundError
        ZoneInfo(a["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        p.append(f"account.timezone: must be an IANA name like America/New_York (got {a['timezone']!r})")

    lim = c["limits"]
    number(p, "limits.daily_budget_cap", lim["daily_budget_cap"], 0, low_open=True)
    number(p, "limits.weekly_bid_change", lim["weekly_bid_change"], 0, 1, low_open=True)
    number(p, "limits.bid_floor", lim["bid_floor"], 0, low_open=True)
    number(p, "limits.bid_ceiling", lim["bid_ceiling"], 0, low_open=True)
    if all(isinstance(lim[k], (int, float)) for k in ("bid_floor", "bid_ceiling")) and lim["bid_floor"] >= lim["bid_ceiling"]:
        p.append("limits.bid_floor: must be under limits.bid_ceiling")

    g = c["guard"]
    if g["expected_bidding"] is not None and not isinstance(g["expected_bidding"], str):
        p.append("guard.expected_bidding: a bidding strategy type like MANUAL_CPC, or null to skip the check")
    number(p, "guard.overspend_multiple", g["overspend_multiple"], 1)

    s = c["stepping"]
    number(p, "stepping.step", s["step"], 0, 0.5, low_open=True)
    number(p, "stepping.weekly_limit", s["weekly_limit"], 0, 1, low_open=True)
    number(p, "stepping.window_days", s["window_days"], 1)
    number(p, "stepping.budget_lost_max", s["budget_lost_max"], 0, 1)
    number(p, "stepping.min_impressions", s["min_impressions"], 0)
    band = s["rank_lost_band"]
    if not (isinstance(band, list) and len(band) == 2 and all(isinstance(x, (int, float)) for x in band)
            and 0 <= band[0] < band[1] <= 1):
        p.append(f"stepping.rank_lost_band: must be [low, high] with 0 <= low < high <= 1 (got {band!r})")
    if not isinstance(s["new_groups"], dict):
        p.append("stepping.new_groups: must map ad group names to YYYY-MM-DD dates")

    n = c["negatives"]
    number(p, "negatives.max_per_day", n["max_per_day"], 0)
    number(p, "negatives.lookback_days", n["lookback_days"], 1, 90)
    number(p, "negatives.protect_days", n["protect_days"], 0, 365)
    if isinstance(n["protect_days"], (int, float)) and isinstance(n["lookback_days"], (int, float)) and \
            0 < n["protect_days"] < n["lookback_days"]:
        p.append("negatives.protect_days: must be 0 (off) or at least negatives.lookback_days")
    number(p, "negatives.min_cost", n["min_cost"], 0)
    number(p, "negatives.min_clicks", n["min_clicks"], 1)
    number(p, "negatives.min_cost_clicks", n["min_cost_clicks"], 1)
    number(p, "negatives.held_notify_cost", n["held_notify_cost"], 0)
    str_list(p, "negatives.junk_words", n["junk_words"])
    level = c["api"]["access_level"]
    if level not in ACCESS_LEVELS:
        p.append(f"api.access_level: must be one of {', '.join(ACCESS_LEVELS)} (got {level!r}); read it on the Google "
                 "Ads API Overview page of your Cloud project")
    for key, value in c["keyword_review"].items():
        if key == "ideas":
            if isinstance(value, bool):  # YAML reads a bare off as false (and on as true)
                value = c["keyword_review"]["ideas"] = "auto" if value else "off"
            if value not in IDEAS_MODES:
                p.append(f"keyword_review.ideas: must be one of {', '.join(IDEAS_MODES)} (got {value!r})")
            continue
        number(p, f"keyword_review.{key}", value, 0)
    m = c["match_type_review"]
    number(p, "match_type_review.broad_to_phrase_share", m["broad_to_phrase_share"], 0, 1, low_open=True)
    number(p, "match_type_review.phrase_to_exact_share", m["phrase_to_exact_share"], 0, 1, low_open=True)
    number(p, "match_type_review.min_off_intent_spend", m["min_off_intent_spend"], 0)

    topics = c["topics"]
    if not isinstance(topics, dict) or not topics:
        p.append("topics: define at least one topic (name: {substrings: [...], words: [...]})")
        topics = {}
    for name, t in topics.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(name)) or name in RESERVED_TOPICS:
            p.append(f"topics.{name}: names are lower_snake_case and not one of {', '.join(RESERVED_TOPICS)}")
        if not isinstance(t, dict):
            p.append(f"topics.{name}: must have substrings and/or words lists")
            continue
        t.setdefault("substrings", [])
        t.setdefault("words", [])
        ok = str_list(p, f"topics.{name}.substrings", t["substrings"]) & str_list(p, f"topics.{name}.words", t["words"])
        if ok and not t["substrings"] and not t["words"]:
            p.append(f"topics.{name}: needs at least one substring or word")
    if str_list(p, "winning_topics", c["winning_topics"]):
        for w in c["winning_topics"]:
            if w not in topics:
                p.append(f"winning_topics: '{w}' is not a topic")
    if not isinstance(c["ad_group_topics"], dict):
        p.append("ad_group_topics: must map ad group names to topics")
    else:
        for group, topic in c["ad_group_topics"].items():
            if topic not in topics:
                p.append(f"ad_group_topics.{group}: '{topic}' is not a topic")

    conv = c["conversions"]
    if str_list(p, "conversions.lead_signals", conv["lead_signals"], allow_empty=False) and \
            str_list(p, "conversions.noise_signals", conv["noise_signals"]):
        both = set(conv["lead_signals"]) & set(conv["noise_signals"])
        if both:
            p.append(f"conversions: {', '.join(sorted(both))} is both a lead signal and a noise signal")

    validate_business(p, c)
    langs, market_prefixes = market_locales(c)

    w = c["website"]
    if w["base_url"] is not None:
        if not (isinstance(w["base_url"], str) and re.fullmatch(r"https?://[^/\s]+", w["base_url"].rstrip("/"))):
            p.append(f"website.base_url: must be like https://www.example.com, no path (got {w['base_url']!r})")
        else:
            w["base_url"] = w["base_url"].rstrip("/")
    # Locales come from business.markets (one source of truth); an explicit website.locales or
    # ad_tests.campaign_locales is allowed but must agree with the markets.
    if w["locales"] is None:
        w["locales"] = langs or ["en"]
    elif str_list(p, "website.locales", w["locales"], allow_empty=False):
        for lang in langs:
            if lang not in w["locales"]:
                p.append(f"website.locales: misses '{lang}', the ad language of a market in business.markets "
                         "(leave website.locales out to derive it from the markets)")

    t = c["ad_tests"]
    if t["enabled"] and w["base_url"] is None:
        p.append("ad_tests.enabled: needs website.base_url (the site is the source of truth for ad claims)")
    if t["campaign_locales"] is None:
        t["campaign_locales"] = dict(market_prefixes)
    elif isinstance(t["campaign_locales"], dict):
        for prefix, loc in market_prefixes.items():
            if prefix in t["campaign_locales"] and t["campaign_locales"][prefix] != loc:
                p.append(f"ad_tests.campaign_locales.{prefix}: '{t['campaign_locales'][prefix]}' disagrees with "
                         f"business.markets, which gives '{loc}' (set it in business.markets only)")
        t["campaign_locales"] = {**market_prefixes, **t["campaign_locales"]}
    if not isinstance(t["campaign_locales"], dict):
        p.append("ad_tests.campaign_locales: must map campaign name prefixes to locales")
    elif isinstance(w["locales"], list):
        for prefix, loc in t["campaign_locales"].items():
            if loc not in w["locales"]:
                p.append(f"ad_tests.campaign_locales.{prefix}: '{loc}' is not in website.locales")
    if t["default_locale"] is None and isinstance(w["locales"], list) and w["locales"]:
        t["default_locale"] = (langs or w["locales"])[0]
    for key in ("min_impressions_14d", "max_running", "max_new_per_week", "min_days", "max_days",
                "min_arm_impressions", "claims_max_age_days"):
        number(p, f"ad_tests.{key}", t[key], 0)
    number(p, "ad_tests.z", t["z"], 0, low_open=True)
    if isinstance(t["min_days"], int) and isinstance(t["max_days"], int) and t["min_days"] > t["max_days"]:
        p.append("ad_tests.min_days: must not be over ad_tests.max_days")

    crm = c["crm"]
    if crm["source"] not in CRM_SOURCES:
        p.append(f"crm.source: must be one of {', '.join(CRM_SOURCES)} (got {crm['source']!r})")
    elif crm["source"] != "none":
        if crm["source"] == "csv" and not crm["csv_path"]:
            p.append("crm.csv_path: needed when crm.source is csv")
        if crm["source"] == "google_sheets" and not crm["sheet_id"]:
            p.append("crm.sheet_id: needed when crm.source is google_sheets")
        for col in ("lead_date", "status"):
            if not crm["columns"].get(col):
                p.append(f"crm.columns.{col}: needed (the header of that column in your CRM)")
        statuses = crm["statuses"]
        unknown = set(statuses) - set(STATUSES)
        if unknown:
            p.append(f"crm.statuses: unknown key(s) {', '.join(sorted(unknown))} (use {', '.join(STATUSES)})")
        for key in STATUSES:
            str_list(p, f"crm.statuses.{key}", statuses.get(key, []))
        if not statuses.get("won"):
            p.append("crm.statuses.won: list the status values that mean a won deal")
        seen = {}
        for key in STATUSES:
            for v in statuses.get(key, []) if isinstance(statuses.get(key), list) else []:
                if v.strip().lower() in seen:
                    p.append(f"crm.statuses: '{v}' is listed under both {seen[v.strip().lower()]} and {key}")
                seen[v.strip().lower()] = key
    if crm["default_status"] not in ("talking", "trial"):
        p.append("crm.default_status: must be talking or trial (an unknown status is an open lead)")
    deal_cur, account_cur = c["business"]["deal_currency"], c["account"]["currency"]
    if crm["deal_value_fx"] is None:
        if deal_cur != account_cur and crm["source"] != "none":
            p.append(f"crm.deal_value_fx: needed because business.deal_currency ({deal_cur}) differs from "
                     f"account.currency ({account_cur}): how much 1 {deal_cur} is in {account_cur}")
        crm["deal_value_fx"] = 1.0
    else:
        number(p, "crm.deal_value_fx", crm["deal_value_fx"], 0, low_open=True)
        if deal_cur == account_cur and crm["deal_value_fx"] != 1:
            p.append(f"crm.deal_value_fx: must be 1 when business.deal_currency equals account.currency ({account_cur}); "
                     "set business.deal_currency to the currency the CRM's deal values are in")
    number(p, "crm.stale_after_days", crm["stale_after_days"], 1)

    r = c["ref_codes"]
    if not (isinstance(r["prefix"], str) and re.fullmatch(r"[A-Z0-9]{1,6}-", r["prefix"])):
        p.append(f"ref_codes.prefix: 1 to 6 capital letters or digits and a dash, like AM- (got {r['prefix']!r})")
    if r["live_from"] is not None:
        try:
            r["live_from"] = str(date.fromisoformat(str(r["live_from"])))
        except ValueError:
            p.append(f"ref_codes.live_from: must be YYYY-MM-DD (got {r['live_from']!r})")
    str_list(p, "ref_codes.test_codes", r["test_codes"])
    if r["enabled"] and crm["source"] == "none":
        p.append("ref_codes.enabled: needs a CRM (crm.source csv or google_sheets) to read the codes from")

    tr = c["tracker"]
    if tr["backend"] not in TRACKERS:
        p.append(f"tracker.backend: must be one of {', '.join(TRACKERS)} (got {tr['backend']!r})")
    need = {"clickup": ("weekly_list_id", "monthly_list_id", "decisions_list_id"),
            "notion": ("weekly_database_id", "monthly_database_id", "decisions_database_id"),
            "linear": ("team_id",)}
    for key in need.get(tr["backend"], ()):
        section = tr.get(tr["backend"].split("-")[0]) or {}
        if not section.get(key):
            p.append(f"tracker.{tr['backend']}.{key}: needed for the {tr['backend']} backend")

    hs = c["report"]["history_start"]
    if hs is not None and not re.fullmatch(r"\d{4}-\d{2}", str(hs)):
        p.append(f"report.history_start: must be YYYY-MM (got {hs!r})")
    cu = c["report"]["client_update"]
    if cu["language"] is None:
        cu["language"] = c["business"]["report_language"]
    else:
        one_line(p, "report.client_update.language", cu["language"])
    str_list(p, "report.client_update.blocklist", cu["blocklist"])
    return p


def build(c):
    cfg = SimpleNamespace(**{k: v for k, v in c.items() if k not in SECTIONS})
    for k in SECTIONS:
        setattr(cfg, k, SimpleNamespace(**c[k]))
    cfg.tz = ZoneInfo(c["account"]["timezone"])
    cfg.raw = c
    return cfg


def load_dict(data):
    """Validate a config dict (the parsed YAML) and return the config. Raises ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError("the config must be a YAML mapping")
    c = merge(DEFAULTS, data)
    problems = validate(c)
    if problems:
        raise ConfigError("\n".join(problems))
    return build(c)


def source(env=None):
    """(YAML text, where it came from), or raises ConfigError when no config is found."""
    env = os.environ if env is None else env
    if env.get("ARGMAX_CONFIG_YAML"):
        return env["ARGMAX_CONFIG_YAML"], "ARGMAX_CONFIG_YAML"
    path = Path(env["ARGMAX_CONFIG"]) if env.get("ARGMAX_CONFIG") else DEFAULT_PATH
    if not path.exists():
        raise ConfigError(f"no config at {path}: run `uv run scripts/init.py`, or copy argmax.example.yaml to "
                          "argmax.yaml and fill it in (cloud: set ARGMAX_CONFIG or ARGMAX_CONFIG_YAML)")
    return path.read_text(encoding="utf-8"), str(path)


def load(env=None):
    env = os.environ if env is None else env
    text, where = source(env)
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{where} is not valid YAML: {e}") from None
    if isinstance(data, dict):
        account = data.setdefault("account", {}) or {}
        data["account"] = account
        for key in ("customer_id", "login_customer_id"):
            if env.get(f"ARGMAX_{key.upper()}"):
                account[key] = env[f"ARGMAX_{key.upper()}"]
    try:
        return load_dict(data)
    except ConfigError as e:
        raise ConfigError(f"{where}:\n{e}") from None


_active = None


def get():
    """The config for this run, loaded on first use. Exits with a clear message when it is missing or invalid."""
    global _active
    if _active is None:
        try:
            _active = load()
        except ConfigError as e:
            sys.exit(f"argmax config problem: {e}")
    return _active


def activate(cfg):
    """Use this config for the rest of the run (tests, init.py). None forgets it."""
    global _active
    _active = cfg
    return cfg
