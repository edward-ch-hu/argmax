"""Google Ads client and shared helpers.

Credentials: google-ads.yaml if present (local), else the GOOGLE_ADS_* environment variables (cloud). The account
(customer id, manager id, currency, time zone) comes from adgrad.yaml through config.py.
"""
import os
from datetime import datetime
from pathlib import Path

import config

CREDENTIALS = Path("google-ads.yaml")
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


def quoted(names):
    """A GAQL IN list of string literals: ('A', 'B')."""
    return "(" + ", ".join("'" + n.replace("\\", "\\\\").replace("'", "\\'") + "'" for n in names) + ")"


def rows(ga, query):
    """All result rows of a GAQL query. Keep a reference to `ga` while using them, or the stream closes early."""
    return [r for batch in ga.search_stream(customer_id=customer_id(), query=query) for r in batch.results]


def load():
    from google.ads.googleads.client import GoogleAdsClient

    if CREDENTIALS.exists():
        client = GoogleAdsClient.load_from_storage(str(CREDENTIALS))
    else:
        client = GoogleAdsClient.load_from_env()
    login = config.get().account.login_customer_id
    if login:
        client.login_customer_id = login
    return client


def oauth_credentials():
    """client_id, client_secret and refresh_token from google-ads.yaml or the GOOGLE_ADS_* environment variables."""
    import yaml

    if CREDENTIALS.exists():
        c = yaml.safe_load(CREDENTIALS.read_text())
        return {k: c[k] for k in ("client_id", "client_secret", "refresh_token")}
    return {k: os.environ[f"GOOGLE_ADS_{k.upper()}"] for k in ("client_id", "client_secret", "refresh_token")}


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
