"""Google Ads client and shared helpers.

Credentials: google-ads.yaml if present (local), else the GOOGLE_ADS_* environment variables (cloud). Only the OAuth
client (client_id, client_secret) and the refresh token are needed: Google sunset developer tokens on 2026-09-09
(the header is optional and ignored; google-ads-python 32.0.0 and later no longer require one), and API access now
belongs to the Google Cloud project that owns the OAuth client. Empty values and INSERT_ placeholders are dropped,
so developer_token and login_customer_id may be left out or left empty. The account (customer id, manager id,
currency, time zone) comes from argmax.yaml through config.py.
"""
import os
import re
from datetime import datetime
from pathlib import Path

import config

CREDENTIALS = Path("google-ads.yaml")
# The google-ads library settings argmax passes on (GOOGLE_ADS_<KEY> in the environment). Only the OAuth trio is
# required; use_proto_plus defaults to True.
SETTING_KEYS = ("client_id", "client_secret", "refresh_token", "developer_token", "login_customer_id",
                "use_proto_plus", "json_key_file_path", "impersonated_email", "use_application_default_credentials",
                "endpoint", "linked_customer_id", "http_proxy")
REQUIRED_KEYS = ("client_id", "client_secret", "refresh_token")
# Currencies Google Ads bills in whole units: bids and budgets round to 1, not 0.01.
ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK", "PYG", "UGX"}


def cfg():
    return config.get()


def customer_id():
    return config.get().account.customer_id


def currency():
    return config.get().account.currency


def now():
    """The current time in the account's time zone (the routines' clock), whatever the machine's zone."""
    return datetime.now(config.get().tz)


def today():
    return now().date()


def micros(amount, currency_code=None):
    """An amount in the account currency as micros, rounded to the currency's smallest billable unit."""
    unit = 1_000_000 if (currency_code or currency()) in ZERO_DECIMAL else 10_000
    return round(amount * 1_000_000 / unit) * unit


def budget_total(budgets):
    """The total daily budget from (budget resource name, amount) pairs of the enabled campaigns: a shared budget
    counts once, however many campaigns use it. Pure."""
    return round(sum(dict(budgets).values()), 2)


def quoted(names):
    """A GAQL IN list of string literals: ('A', 'B')."""
    return "(" + ", ".join("'" + n.replace("\\", "\\\\").replace("'", "\\'") + "'" for n in names) + ")"


def rows(ga, query):
    """All result rows of a GAQL query. Keep a reference to `ga` while using them, or the stream closes early."""
    return [r for batch in ga.search_stream(customer_id=customer_id(), query=query) for r in batch.results]


def placeholder(value):
    """True for a value that is not really set: None, empty, or an INSERT_... placeholder from the example."""
    return value is None or str(value).strip() == "" or str(value).strip().startswith("INSERT_")


def client_settings(env=None, path=None):
    """The google-ads library settings from google-ads.yaml (local) or the GOOGLE_ADS_* env vars (cloud), with
    placeholders dropped and use_proto_plus defaulting to True. Never printed: it holds secrets."""
    import yaml

    env = os.environ if env is None else env
    path = CREDENTIALS if path is None else Path(path)
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
    else:
        data = {k: env.get(f"GOOGLE_ADS_{k.upper()}") for k in SETTING_KEYS}
    data = {k: v for k, v in data.items() if not placeholder(v)}
    if "login_customer_id" in data:  # the library wants 10 digits; dashes are a common slip
        data["login_customer_id"] = re.sub(r"[\s-]", "", str(data["login_customer_id"]))
    data.setdefault("use_proto_plus", True)
    return data


def missing_credentials(settings):
    """The required OAuth values that are not set (developer_token is not one of them)."""
    if settings.get("json_key_file_path") or settings.get("use_application_default_credentials"):
        return []  # service account or Application Default Credentials instead of a refresh token
    return [k for k in REQUIRED_KEYS if placeholder(settings.get(k))]


def client_from_credentials():
    """A GoogleAdsClient from google-ads.yaml or the environment alone (no argmax.yaml needed)."""
    from google.ads.googleads.client import GoogleAdsClient

    settings = client_settings()
    missing = missing_credentials(settings)
    if missing:
        source = str(CREDENTIALS) if CREDENTIALS.exists() else "the GOOGLE_ADS_* environment variables"
        raise SystemExit(f"FAIL   {source}: missing {', '.join(missing)} (SETUP.md step 2; no developer token needed)")
    return GoogleAdsClient.load_from_dict(settings)


def load():
    client = client_from_credentials()
    login = config.get().account.login_customer_id
    if login:
        client.login_customer_id = login
    return client


def oauth_credentials():
    """client_id, client_secret and refresh_token from google-ads.yaml or the GOOGLE_ADS_* environment variables."""
    settings = client_settings()
    return {k: settings.get(k) for k in REQUIRED_KEYS}


def error_text(ex):
    """One line for a GoogleAdsException: each error's code and message."""
    return "; ".join(f"{str(e.error_code).strip()} {e.message}".strip() for e in ex.failure.errors)


def expired_token(text):
    """True when an error text says the refresh token no longer works (Google's invalid_grant). Pure."""
    m = str(text).upper()
    return "INVALID_GRANT" in m or "TOKEN HAS BEEN EXPIRED OR REVOKED" in m


def explain_api_error(text):
    """(status, message) for an API error text, with what to do. PENDING means waiting on Google (Test access only),
    FAIL means something to fix. Pure; the codes are AuthorizationError values of the Google Ads API."""
    m = text.upper()
    if expired_token(text):
        return "FAIL", (f"{text}. The refresh token expired or was revoked. Usual cause: the OAuth consent screen is "
                        "still in Testing, where Google expires refresh tokens after 7 days. Set it to In production "
                        "(Google Auth Platform, Audience, Publish app), then run get_refresh_token.py again and update "
                        "the token wherever the routines read it (SETUP.md, Troubleshooting)")
    if any(code in m for code in ("CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION", "DEVELOPER_TOKEN_NOT_APPROVED",
                                  "ONLY_APPROVED_FOR_USE_WITH_TEST_ACCOUNTS", "TEST ACCOUNTS", "TEST_ACCOUNTS")):
        return "PENDING", ("the Cloud project has Test access (test accounts only): apply for Explorer on the Google "
                           "Ads API Overview page, https://console.cloud.google.com/google/ads-apis/overview "
                           "(SETUP.md step 1)")
    if "AUTHORIZATION_ERROR" in m.replace("AUTHORIZATION_ERROR:", ""):
        return "FAIL", (f"{text}. Known Google issue: projects upgraded after 2026-09-09 can get AUTHORIZATION_ERROR on "
                        "production accounts; workaround: a new Cloud project that applies for Explorer "
                        "(SETUP.md, Troubleshooting)")
    if "USER_PERMISSION_DENIED" in m:
        return "FAIL", (f"{text}. The signed-in Google login cannot reach this account: check account.customer_id, "
                        "and set account.login_customer_id only when you reach the account through a manager account")
    if "INVALID_LOGIN_CUSTOMER_ID" in m:
        return "FAIL", (f"{text}. account.login_customer_id must be the manager account the ad account sits under, or "
                        "empty when your login has direct access to the ad account")
    return "FAIL", text


def run(main):
    """Runs a script's main(); an expired or revoked refresh token stops it with one FAIL line and what to do, instead
    of a traceback (the error comes from google-auth, not as a GoogleAdsException)."""
    try:
        main()
    except Exception as e:  # e.g. google.auth RefreshError, or a gRPC error carrying it
        if not expired_token(f"{e}"):
            raise
        raise SystemExit(f"FAIL   {explain_api_error(f'{type(e).__name__}: {e}')[1]}") from None


def sheet_values(spreadsheet_id, cell_range):
    """Rows of a Google Sheet range, read with the same OAuth login (needs the spreadsheets.readonly scope)."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials

    c = oauth_credentials()
    creds = Credentials(None, refresh_token=c["refresh_token"], client_id=c["client_id"],
                        client_secret=c["client_secret"], token_uri="https://oauth2.googleapis.com/token")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{cell_range}"
    response = AuthorizedSession(creds).get(url)
    response.raise_for_status()
    return response.json().get("values", [])
