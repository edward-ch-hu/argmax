"""What is set up and what is missing: one OK / FAIL / PENDING line per item. Changes nothing anywhere.

Items: config (argmax.yaml), guardrails (when argmax.yaml and scripts/ last changed and by whom, and whether
ARGMAX_CONFIG_YAML locks the config; the weekly report copies this line), repo (with gh, also under --offline: the
GitHub origin and the github-issues repo must be PRIVATE, or every routine stops: logs hold account data and anyone
could approve a decision on a public repo; WARN when gh cannot tell), business profile, strategy (STRATEGY.md), whether business.goal fits it and whether its bidding end state agrees
with business.bidding_end_state, credentials (google-ads.yaml or GOOGLE_ADS_* env vars, never
printed; no developer token needed), API access (skipped with --offline), API quota (api.access_level against the
estimated operations per day), tracker, CRM (header row and status values only), ad library, experiments (when the
config has any: each one's phase), onboarding progress.
PENDING means waiting on something (Explorer access approval, an onboarding step); WARN
means it works but looks wrong (e.g. goal roas with a lead-gen strategy); FAIL means something is wrong. Exit 1 when
anything FAILs.

Usage: uv run scripts/doctor.py [--offline]
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import ads_client
import config
import yaml

CREDENTIAL_KEYS = ads_client.REQUIRED_KEYS  # client_id, client_secret, refresh_token; a developer token is optional

# Estimated Google Ads API operations per run (Search/SearchStream request = 1, each mutate operation = 1, failed
# requests count too). How they are counted: SETUP.md, "API access levels and quota". The weekly figure is the busy
# case (validate and apply both counted, keyword ideas on); Monday runs the weekly only, Tuesday to Sunday the daily.
OPS_ESTIMATE = {"daily scout": 60, "weekly review": 400}


def credentials_status(file_data, env):
    """(status, message) for Google Ads credentials from google-ads.yaml data (or None) and the environment. Pure."""
    if file_data is not None:
        source = "google-ads.yaml"
        values = {k: str(file_data.get(k) or "") for k in (*CREDENTIAL_KEYS, "developer_token")}
    else:
        source = "GOOGLE_ADS_* env vars"
        values = {k: env.get(f"GOOGLE_ADS_{k.upper()}", "") for k in (*CREDENTIAL_KEYS, "developer_token")}
        if not any(values.values()):
            return "PENDING", "no google-ads.yaml and no GOOGLE_ADS_* env vars (SETUP.md, onboarding step c)"
    missing = [k for k in CREDENTIAL_KEYS if ads_client.placeholder(values[k])]
    if missing == ["refresh_token"]:
        return "PENDING", f"{source}: no refresh token yet (uv run scripts/get_refresh_token.py client_secret.json)"
    if missing:
        return "FAIL", f"{source}: missing {', '.join(missing)}"
    token = "" if ads_client.placeholder(values["developer_token"]) else \
        " (a developer_token is set too: optional, Google ignores it since 2026-09-09)"
    return "OK", f"{source}: OAuth client and refresh token set{token}"


def api_error_status(message):
    """(status, message with what to do) for an API error: PENDING while the Cloud project has Test access only,
    else FAIL. Pure."""
    return ads_client.explain_api_error(message)


def quota_status(cfg, estimate=None):
    """(status, message): the access level in argmax.yaml against the estimated operations per day. Pure."""
    estimate = estimate or OPS_ESTIMATE
    level = cfg.api.access_level
    limit = config.ACCESS_LEVELS[level]
    peak = max(estimate.values())
    runs = ", ".join(f"{k} up to {v:,}" for k, v in estimate.items())
    if level == "unknown":
        return "PENDING", (f"api.access_level is unknown: read it on the Google Ads API Overview page "
                           f"(console.cloud.google.com/google/ads-apis/overview) and set it ({runs} operations a day)")
    if level == "test":
        return "PENDING", ("api.access_level is test: test accounts only. Apply for Explorer on the Google Ads API "
                           "Overview page (usually approved automatically)")
    if peak > limit:
        return "WARN", f"{level} allows {limit:,} operations a day; argmax may need {runs}: apply for Basic"
    allowed = "unlimited" if limit == float("inf") else f"{limit:,}"
    note = "; no Keyword Planner ideas on explorer (Basic, after brand verification, adds them)" \
        if level == "explorer" and cfg.keyword_review.ideas != "off" else ""
    return "OK", f"{level}: {allowed} operations a day on live accounts, argmax needs {runs}{note}"


def crm_status(values, cfg):
    """(status, message) for the CRM's header row and status values. Pure; never returns a cell other than statuses."""
    import crm

    if cfg.crm.source == "none":
        return "OK", "crm.source is none: lead and win data off (scripts say so and carry on)"
    if not values:
        return "FAIL", "the CRM is empty or unreadable"
    header = values[0]
    missing = [f"{k}: {cfg.crm.columns.get(k)}" for k in ("lead_date", "status", "deal_value", "name", "email", "id")
               if cfg.crm.columns.get(k) and crm.header_index(header, cfg.crm.columns[k]) is None]
    topics = cfg.crm.columns.get("topics") or []
    missing += [f"topics: {t}" for t in ([topics] if isinstance(topics, str) else topics)
                if crm.header_index(header, t) is None]
    if missing:
        return "FAIL", f"header(s) not found in the first row: {', '.join(missing)}"
    seen = crm.inspect(values, cfg.crm.columns["status"])["statuses"]
    known = {v.strip().lower() for vals in cfg.crm.statuses.values() for v in vals}
    unmapped = sorted(v for v in seen if v.strip().lower() not in known)
    if unmapped:
        return "PENDING", (f"status values not in crm.statuses (count as {cfg.crm.default_status}): "
                           + ", ".join(unmapped))
    return "OK", f"{len(values) - 1} rows, every status value mapped"


def business_status(cfg):
    """(status, message) for the business profile. Pure."""
    b = cfg.business
    if b.goal is None:
        return "PENDING", "no business profile yet: goal, KPI, markets, report language (onboarding step e, business)"
    markets = ", ".join(f"{m['name']} ({'/'.join(m['countries'])}, ads in {m['language']})" for m in b.markets)
    deals = b.deal_currency if b.deal_currency == cfg.account.currency else \
        f"{b.deal_currency} (x {cfg.crm.deal_value_fx:g} to {cfg.account.currency})"
    end = {"smart_bidding": "smart bidding hand-off", "manual_cpc": "manual CPC for good"}.get(
        b.bidding_end_state, "bidding end state not set")
    return "OK", (f"goal {b.goal}, KPI {b.primary_kpi} ({', '.join(b.kpi_conversions) or 'no conversion action'}); "
                  f"markets {markets}; reports in {b.report_language}; deals in {deals}; {end}")


GUARDED = ("argmax.yaml", "scripts/")
UPSTREAM = "edward-ch-hu/argmax"


def git(*args):
    """stdout of a git command, or None when git or the repo is not there."""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def guardrails_status(last_change, dirty, source, differs):
    """(status, message): when argmax.yaml and scripts/ last changed and by whom, and whether the run environment
    locks the config. last_change: "<date> <short commit> <author>" or None; dirty: uncommitted paths. Pure.
    The weekly report copies the message into its header, so drift in the guardrails is visible."""
    if last_change:
        date_, commit, author = (last_change.split(" ", 2) + ["", ""])[:3]
        when = f"argmax.yaml and scripts/ last changed {date_} {commit} by {author}".strip()
    else:
        when = "argmax.yaml and scripts/ last changed: unknown (not a git checkout, or never committed)"
    if source is None:
        lock = "no config yet"
    elif source == "ARGMAX_CONFIG_YAML":
        lock = "config locked by ARGMAX_CONFIG_YAML (argmax.yaml is advisory" + (
            ", and differs from it)" if differs else ")")
    else:
        lock = (f"config from {source}, not locked: set ARGMAX_CONFIG_YAML in the run environment so the agent cannot "
                "change limits (SETUP.md, Guardrails lock)")
    if dirty:
        return "WARN", f"uncommitted changes in {', '.join(dirty)}: guardrails edited outside git; {when}; {lock}"
    return "OK", f"{when}; {lock}"


def guardrails_check(env):
    last = (git("log", "-1", "--format=%cs %h %an", "--", *GUARDED) or "").strip() or None
    status = git("status", "--porcelain", "--", *GUARDED)
    dirty = sorted({line[3:] for line in (status or "").splitlines() if line.strip()})
    try:
        _, source = config.source(env)
    except config.ConfigError:
        source = None
    differs = False
    if source == "ARGMAX_CONFIG_YAML" and config.DEFAULT_PATH.exists():
        try:
            differs = yaml.safe_load(env["ARGMAX_CONFIG_YAML"]) != yaml.safe_load(config.DEFAULT_PATH.read_text())
        except yaml.YAMLError:
            differs = True
    return guardrails_status(last, dirty, source, differs)


def github_repo(url):
    """owner/name for a github.com remote URL (https or ssh), else None. Pure."""
    m = re.match(r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$",
                 (url or "").strip())
    return f"{m[1]}/{m[2]}" if m else None


def visibility_status(repo, view):
    """(status, message) for a GitHub repo that holds argmax's logs or decisions. view: the parsed output of
    `gh repo view <repo> --json visibility,isFork`, or None when gh could not answer. Pure."""
    why = ("its logs and reports hold your account's data, and on a public repo anyone could comment \"yes\" on a "
           "decision")
    if view is None:
        return "WARN", f"{repo}: could not read its visibility with gh (gh missing or not logged in); it must be private: {why}"
    visibility = str(view.get("visibility", "")).upper()
    if visibility != "PRIVATE":
        if repo.lower() == UPSTREAM:
            return "FAIL", (f"{repo} is the public upstream: run argmax from your own private copy (BOOTSTRAP.md), "
                            f"because {why}")
        fork = " It is a fork: GitHub forks of a public repo are always public, so make a new private repo instead " \
               "(BOOTSTRAP.md)." if view.get("isFork") else " Make it private (Settings, General, Danger Zone)."
        return "FAIL", f"{repo} is {visibility.lower() or 'not private'}: routines stop until it is private: {why}.{fork}"
    return "OK", f"{repo} is private"


def repo_visibility(cfg, which=shutil.which):
    """[(status, message)] for the GitHub repos argmax writes to: the origin remote and tracker.github.repo."""
    repos = []
    origin = github_repo(git("remote", "get-url", "origin"))
    if origin:
        repos.append(origin)
    tracked = ((cfg.tracker.github or {}).get("repo") or "") if cfg and cfg.tracker.backend == "github-issues" else ""
    if tracked and tracked not in repos:
        repos.append(tracked)
    out = []
    for repo in repos:
        view = None
        if which("gh"):
            r = subprocess.run(["gh", "repo", "view", repo, "--json", "visibility,isFork"], capture_output=True, text=True)
            if r.returncode == 0:
                try:
                    view = json.loads(r.stdout)
                except ValueError:
                    view = None
        out.append(visibility_status(repo, view))
    return out


def tracker_status(cfg, which=shutil.which):
    """(status, message) for the tracker setting. The MCP backends are tested by the agent, not here."""
    backend = cfg.tracker.backend
    doc = Path("trackers") / f"{backend}.md"
    if not doc.exists():
        return "FAIL", f"{doc} does not exist"
    if backend == "github-issues":
        if not which("gh"):
            return "FAIL", "github-issues needs the gh CLI (https://cli.github.com) and `gh auth login`"
        return "OK", "github-issues via gh (auth checked below when online)"
    if backend == "files":
        return "OK", "files: decisions/ and reports/weekly/ in this repo, no setup"
    return "OK", f"{backend}: ids set; the agent tests its connector (onboarding step f)"


def check(offline=False, env=None):
    env = os.environ if env is None else env
    out = []
    cfg = None
    try:
        cfg = config.load(env)
        out.append(("OK", "config", f"account {cfg.account.customer_id}, {cfg.account.currency}, "
                    f"{cfg.account.timezone}, cap {cfg.limits.daily_budget_cap:g}"))
    except config.ConfigError as e:
        first = str(e).splitlines()
        status = "PENDING" if "no config at" in str(e) else "FAIL"
        out.append((status, "config", " / ".join(first[:4]) + (" ..." if len(first) > 4 else "")))
        if status == "FAIL":
            cfg = None

    if cfg:
        b = business_status(cfg)
        out.append((b[0], "business", b[1]))

    import strategy_check
    path = Path("STRATEGY.md")
    if not path.exists():
        out.append(("PENDING", "strategy", "no STRATEGY.md (prompts/strategy-interview.md or strategies/)"))
    else:
        text = path.read_text(encoding="utf-8")
        fails, _ = strategy_check.check(text, set(cfg.topics) if cfg else None)
        out.append(("FAIL", "strategy", "; ".join(fails)) if fails else ("OK", "strategy", "required sections present"))
        if cfg and cfg.business.goal is not None:
            g = strategy_check.goal_fit(text, cfg.business.goal)
            out.append((g[0], "goal fit", g[1]))
        if cfg:
            b = strategy_check.bidding_fit(text, cfg.business.bidding_end_state)
            out.append((b[0], "bidding", b[1]))

    cred_file = Path("google-ads.yaml")
    file_data = (yaml.safe_load(cred_file.read_text()) or {}) if cred_file.exists() else None
    cred = credentials_status(file_data, env)
    out.append((cred[0], "credentials", cred[1]))

    if cfg:
        q = quota_status(cfg)
        out.append((q[0], "api quota", q[1]))

    g = guardrails_check(env)
    out.append((g[0], "guardrails", g[1]))
    for status, message in repo_visibility(cfg):  # also with --offline: the daily runs that way and must stop too
        out.append((status, "repo", message))

    if offline:
        out.append(("PENDING", "api", "skipped (--offline)"))
    elif cred[0] != "OK" or cfg is None:
        out.append(("PENDING", "api", "needs config and credentials first"))
    else:
        out.append(api_check(cfg))

    if cfg:
        t = tracker_status(cfg)
        if t[0] == "OK" and cfg.tracker.backend == "github-issues" and not offline:
            ok = subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0
            t = t if ok else ("FAIL", "gh is not logged in: run `gh auth login`")
        out.append((t[0], "tracker", t[1]))
        if cfg.crm.source == "none" or not offline or cfg.crm.source == "csv":
            try:
                import crm
                values = crm.raw_values(cfg) if cfg.crm.source != "none" else []
                c = crm_status(values, cfg)
            except (SystemExit, Exception) as e:  # any read problem is a FAIL line, not a crash
                c = ("FAIL", f"cannot read the CRM: {e}")
            out.append((c[0], "crm", c[1]))
        else:
            out.append(("PENDING", "crm", "google_sheets not read (--offline)"))
        if cfg.ad_tests.enabled:
            lib = Path(cfg.ad_tests.library)
            out.append(("OK", "ad library", f"{lib} present") if lib.exists() else
                       ("PENDING", "ad library", f"no {lib}: ad tests wait until it is filled from your site "
                        "(docs/ad_library.example.json)"))

    if cfg and cfg.experiments:
        import experiments
        exp_state, today = experiments.load_state(), ads_client.today()
        out.append(("OK", "experiments", "; ".join(f"{e['id']} {experiments.phase(e, today, exp_state)} "
                                                   f"({e['start']} to {e['end']})" for e in cfg.experiments)))

    import onboarding
    state = onboarding.load()
    out.append(("OK", "onboarding", "complete") if onboarding.complete(state) else
               ("PENDING", "onboarding", f"next step: {onboarding.next_step(state)} (say \"continue onboarding\")"))
    return out


def api_check(cfg):
    import ads_client
    from google.ads.googleads.errors import GoogleAdsException

    try:
        client = ads_client.load()
        rows = ads_client.rows(client.get_service("GoogleAdsService"),
                               "SELECT customer.descriptive_name, customer.currency_code, customer.time_zone FROM customer")
    except GoogleAdsException as ex:
        status, message = api_error_status(ads_client.error_text(ex))
        return status, "api", message
    except SystemExit as e:  # missing credentials
        return "FAIL", "api", str(e)
    except Exception as e:  # e.g. an expired refresh token (RefreshError: invalid_grant)
        status, message = api_error_status(f"{type(e).__name__}: {e}")
        return status, "api", message
    c = rows[0].customer
    notes = [f"{what} in argmax.yaml is {mine}, the account says {live}"
             for what, live, mine in (("currency", c.currency_code, cfg.account.currency),
                                      ("timezone", c.time_zone, cfg.account.timezone)) if live != mine]
    return ("FAIL" if notes else "OK"), "api", "; ".join(notes) or f"reads {c.descriptive_name or 'the account'}"


def main():
    results = check("--offline" in sys.argv)
    for status, item, message in results:
        print(f"{status:8}{item:12} {message}")
    if any(s == "FAIL" for s, _, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
