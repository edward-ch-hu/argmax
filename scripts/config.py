"""adgrad config: one YAML file, validated once, read by every script through get().

Where it comes from (first match wins):
  1. ADGRAD_CONFIG_YAML  the whole YAML as text (handy for cloud routine environment variables)
  2. ADGRAD_CONFIG       a path to a YAML file
  3. adgrad.yaml         in the working directory
Then ADGRAD_CUSTOMER_ID and ADGRAD_LOGIN_CUSTOMER_ID override the account ids when set.

Optional fields take the defaults in DEFAULTS. A missing file or an invalid field stops the script with one line per
problem. Secrets (developer token, OAuth client, refresh token) never live here: they stay in google-ads.yaml or the
GOOGLE_ADS_* environment variables.
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

DEFAULT_PATH = Path("adgrad.yaml")
TRACKERS = ("github-issues", "files", "clickup", "notion", "linear")
CRM_SOURCES = ("none", "csv", "google_sheets")
STATUSES = ("talking", "trial", "won", "lost_after_trial", "lost_no_trial")
RESERVED_TOPICS = ("other", "none", "mixed")

DEFAULTS = {
    "account": {"customer_id": None, "login_customer_id": None, "name": "my account", "currency": None,
                "timezone": None},
    "limits": {"daily_budget_cap": None, "weekly_bid_change": 0.20, "bid_floor": 0.20, "bid_ceiling": 5.00,
               "allow_enable_performance_max": False},
    "guard": {"expected_bidding": "MANUAL_CPC", "search_networks_only": True, "overspend_multiple": 2.0},
    "stepping": {"enabled": True, "step": 0.10, "weekly_limit": 0.30, "window_days": 14,
                 "rank_lost_band": [0.20, 0.50], "budget_lost_max": 0.20, "min_impressions": 30, "new_groups": {}},
    "negatives": {"max_per_day": 10, "lookback_days": 7, "held_notify_cost": 5.0, "min_cost": 3.0, "min_clicks": 10,
                  "junk_words": ["free", "download", "crack", "torrent", "jobs", "job", "salary", "career",
                                 "tutorial", "course", "github", "reddit"]},
    "keyword_review": {"min_positive_conversions": 2, "min_pause_cost": 20.0, "ideas_per_ad_group": 8,
                       "ideas_min_monthly_searches": 10},
    "match_type_review": {"broad_to_phrase_share": 0.30, "phrase_to_exact_share": 0.50, "min_off_intent_spend": 10.0},
    "topics": {},
    "winning_topics": [],
    "ad_group_topics": {},
    "conversions": {"lead_signals": [], "noise_signals": []},
    "website": {"base_url": None, "locales": ["en"], "user_agent": "adgrad claims check"},
    "ad_tests": {"enabled": True, "library": "docs/ad_library.json", "campaign_locales": {}, "default_locale": None,
                 "min_impressions_14d": 300, "max_running": 3, "max_new_per_week": 1, "min_days": 28,
                 "max_days": 56, "min_arm_impressions": 1000, "z": 1.96, "claims_max_age_days": 7},
    "crm": {"source": "none", "csv_path": None, "sheet_id": None, "sheet_range": "Sheet1!A1:Z", "date_format": None,
            "columns": {"id": None, "lead_date": None, "status": None, "topics": None, "deal_value": None,
                        "name": None, "email": None, "ref": None},
            "statuses": {"talking": [], "trial": [], "won": [], "lost_after_trial": [], "lost_no_trial": []},
            "default_status": "talking", "deal_value_label": "MRR", "deal_value_fx": 1.0, "stale_after_days": 14},
    "ref_codes": {"enabled": False, "prefix": "AG-", "live_from": None, "test_codes": []},
    "tracker": {"backend": "files", "github": {}, "clickup": {}, "notion": {}, "linear": {}, "files": {}},
    "report": {"history_start": None, "client_update": {"enabled": True, "language": "English", "blocklist": []}},
}
# Sections that become attribute namespaces (cfg.limits.daily_budget_cap). Mappings keyed by user names (topics,
# ad group names, statuses, columns) stay plain dicts.
SECTIONS = ("account", "limits", "guard", "stepping", "negatives", "keyword_review", "match_type_review",
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


def validate(c):
    """Every problem in the merged config dict, as lines. Normalises ids in place."""
    p = []
    a = c["account"]
    cid = digits(a["customer_id"])
    if cid is None:
        p.append(f"account.customer_id: must be a 10-digit Google Ads id like 123-456-7890 (got {a['customer_id']!r})")
    a["customer_id"] = cid
    if a["login_customer_id"] not in (None, ""):
        login = digits(a["login_customer_id"])
        if login is None:
            p.append(f"account.login_customer_id: must be a 10-digit manager id or empty (got {a['login_customer_id']!r})")
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
    number(p, "negatives.min_cost", n["min_cost"], 0)
    number(p, "negatives.min_clicks", n["min_clicks"], 1)
    number(p, "negatives.held_notify_cost", n["held_notify_cost"], 0)
    str_list(p, "negatives.junk_words", n["junk_words"])
    for key, value in c["keyword_review"].items():
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

    w = c["website"]
    if w["base_url"] is not None:
        if not (isinstance(w["base_url"], str) and re.fullmatch(r"https?://[^/\s]+", w["base_url"].rstrip("/"))):
            p.append(f"website.base_url: must be like https://www.example.com, no path (got {w['base_url']!r})")
        else:
            w["base_url"] = w["base_url"].rstrip("/")
    str_list(p, "website.locales", w["locales"], allow_empty=False)

    t = c["ad_tests"]
    if t["enabled"] and w["base_url"] is None:
        p.append("ad_tests.enabled: needs website.base_url (the site is the source of truth for ad claims)")
    if not isinstance(t["campaign_locales"], dict):
        p.append("ad_tests.campaign_locales: must map campaign name prefixes to locales")
    elif isinstance(w["locales"], list):
        for prefix, loc in t["campaign_locales"].items():
            if loc not in w["locales"]:
                p.append(f"ad_tests.campaign_locales.{prefix}: '{loc}' is not in website.locales")
    if t["default_locale"] is None and isinstance(w["locales"], list) and w["locales"]:
        t["default_locale"] = w["locales"][0]
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
    number(p, "crm.deal_value_fx", crm["deal_value_fx"], 0, low_open=True)
    number(p, "crm.stale_after_days", crm["stale_after_days"], 1)

    r = c["ref_codes"]
    if not (isinstance(r["prefix"], str) and re.fullmatch(r"[A-Z0-9]{1,6}-", r["prefix"])):
        p.append(f"ref_codes.prefix: 1 to 6 capital letters or digits and a dash, like AG- (got {r['prefix']!r})")
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
    str_list(p, "report.client_update.blocklist", c["report"]["client_update"]["blocklist"])
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
    if env.get("ADGRAD_CONFIG_YAML"):
        return env["ADGRAD_CONFIG_YAML"], "ADGRAD_CONFIG_YAML"
    path = Path(env["ADGRAD_CONFIG"]) if env.get("ADGRAD_CONFIG") else DEFAULT_PATH
    if not path.exists():
        raise ConfigError(f"no config at {path}: run `uv run scripts/init.py`, or copy adgrad.example.yaml to "
                          "adgrad.yaml and fill it in (cloud: set ADGRAD_CONFIG or ADGRAD_CONFIG_YAML)")
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
            if env.get(f"ADGRAD_{key.upper()}"):
                account[key] = env[f"ADGRAD_{key.upper()}"]
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
            sys.exit(f"adgrad config problem: {e}")
    return _active


def activate(cfg):
    """Use this config for the rest of the run (tests, init.py). None forgets it."""
    global _active
    _active = cfg
    return cfg
