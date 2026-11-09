"""What is set up and what is missing: one OK / FAIL / PENDING line per item. Changes nothing anywhere.

Items: config (adgrad.yaml), strategy (STRATEGY.md), credentials (google-ads.yaml or GOOGLE_ADS_* env vars, never
printed), API access (skipped with --offline), tracker, CRM (header row and status values only), ad library,
onboarding progress. PENDING means waiting on something (a developer token approval, an onboarding step); FAIL
means something is wrong. Exit 1 when anything FAILs.

Usage: uv run scripts/doctor.py [--offline]
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import config
import yaml

CREDENTIAL_KEYS = ("developer_token", "client_id", "client_secret", "refresh_token")


def credentials_status(file_data, env):
    """(status, message) for Google Ads credentials from google-ads.yaml data (or None) and the environment. Pure."""
    if file_data is not None:
        source = "google-ads.yaml"
        values = {k: str(file_data.get(k) or "") for k in CREDENTIAL_KEYS}
    else:
        source = "GOOGLE_ADS_* env vars"
        values = {k: env.get(f"GOOGLE_ADS_{k.upper()}", "") for k in CREDENTIAL_KEYS}
        if not any(values.values()):
            return "PENDING", "no google-ads.yaml and no GOOGLE_ADS_* env vars (SETUP.md, onboarding step c)"
    missing = [k for k, v in values.items() if not v or v.startswith("INSERT_")]
    if missing == ["refresh_token"]:
        return "PENDING", f"{source}: no refresh token yet (uv run scripts/get_refresh_token.py client_secret.json)"
    if missing:
        return "FAIL", f"{source}: missing {', '.join(missing)}"
    return "OK", f"{source}: all four values set"


def api_error_status(message):
    """PENDING for a developer token still waiting on approval (test accounts only), else FAIL. Pure."""
    m = message.upper().replace(" ", "_")
    if "DEVELOPER_TOKEN_NOT_APPROVED" in m or "ONLY_APPROVED_FOR_USE_WITH_TEST_ACCOUNTS" in m or "TEST_ACCOUNTS" in m:
        return "PENDING", "the developer token works on test accounts only until Google approves Basic access"
    return "FAIL", message


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
    return "OK", f"{backend}: ids set; the agent tests its connector (onboarding step e)"


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

    import strategy_check
    path = Path("STRATEGY.md")
    if not path.exists():
        out.append(("PENDING", "strategy", "no STRATEGY.md (prompts/strategy-interview.md or strategies/)"))
    else:
        fails, _ = strategy_check.check(path.read_text(encoding="utf-8"), set(cfg.topics) if cfg else None)
        out.append(("FAIL", "strategy", "; ".join(fails)) if fails else ("OK", "strategy", "required sections present"))

    cred_file = Path("google-ads.yaml")
    file_data = (yaml.safe_load(cred_file.read_text()) or {}) if cred_file.exists() else None
    cred = credentials_status(file_data, env)
    out.append((cred[0], "credentials", cred[1]))

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
        status, message = api_error_status("; ".join(f"{e.error_code} {e.message}" for e in ex.failure.errors))
        return status, "api", message
    except Exception as e:  # e.g. a bad refresh token
        return "FAIL", "api", f"{type(e).__name__}: {e}"
    c = rows[0].customer
    notes = [f"{what} in adgrad.yaml is {mine}, the account says {live}"
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
