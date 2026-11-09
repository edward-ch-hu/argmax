"""Smoke test: checks argmax.yaml, lists every Google Ads account the credentials can reach, and says whether the
configured customer_id is one of them.

Usage: uv run scripts/check_connection.py
"""
import ads_client
import config
from google.ads.googleads.errors import GoogleAdsException


def main():
    cfg = config.get()
    print(f"Config OK: account {cfg.account.customer_id} ({cfg.account.currency}, {cfg.account.timezone}), "
          f"budget cap {cfg.limits.daily_budget_cap:g}, CRM {cfg.crm.source}, tracker {cfg.tracker.backend}")
    client = ads_client.load()
    service = client.get_service("CustomerService")
    try:
        response = service.list_accessible_customers()
    except GoogleAdsException as ex:
        for error in ex.failure.errors:
            print(f"Error: {error.message}")
        raise SystemExit(1) from None
    ids = [name.removeprefix("customers/") for name in response.resource_names]
    print(f"Connected. {len(ids)} directly accessible account(s):")
    for i in ids:
        print(f"  {i}")
    try:
        account = ads_client.rows(client.get_service("GoogleAdsService"),
                                  "SELECT customer.descriptive_name, customer.currency_code, customer.time_zone FROM customer")
    except GoogleAdsException as ex:
        print(f"FAIL   cannot read account {cfg.account.customer_id}: {ex.failure.errors[0].message}")
        print("       Check account.customer_id and account.login_customer_id (your manager account) in argmax.yaml.")
        raise SystemExit(1) from None
    c = account[0].customer
    print(f"OK     account {cfg.account.customer_id}: {c.descriptive_name} ({c.currency_code}, {c.time_zone})")
    for what, live, mine in (("currency", c.currency_code, cfg.account.currency),
                             ("timezone", c.time_zone, cfg.account.timezone)):
        if live != mine:
            print(f"WARN   account.{what} in argmax.yaml is {mine}, the account says {live}: use {live}")


if __name__ == "__main__":
    main()
