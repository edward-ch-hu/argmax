"""List the Google Ads accounts your credentials can reach, with name, currency, time zone and whether each is a
manager. Needs only google-ads.yaml (or GOOGLE_ADS_* env vars), not argmax.yaml, so onboarding can pick the
account and read its currency and time zone from the API instead of asking. No developer token or manager account
needed: a regular ad account your login can open is listed directly (use it with an empty login_customer_id); the
accounts under a manager are listed "via manager" (that manager's id is then the login_customer_id). An account
that answers with a Test access error means the Cloud project still needs Explorer access. Read-only.

Usage: uv run scripts/accounts.py [--json]
"""
import json
import sys

import ads_client
from google.ads.googleads.errors import GoogleAdsException

CHILDREN = ("SELECT customer_client.id, customer_client.descriptive_name, customer_client.currency_code, "
            "customer_client.time_zone, customer_client.manager, customer_client.test_account FROM customer_client "
            "WHERE customer_client.level = 1")
QUERY = ("SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone, "
         "customer.manager, customer.test_account FROM customer")


def client():
    return ads_client.client_from_credentials()


def fmt(cid):
    cid = str(cid)
    return f"{cid[:3]}-{cid[3:6]}-{cid[6:]}"


def entry(r, via=None):
    return {"customer_id": fmt(r.id), "name": r.descriptive_name, "currency": r.currency_code,
            "timezone": r.time_zone, "manager": r.manager, "test_account": r.test_account,
            **({"login_customer_id": fmt(via)} if via else {})}


def main():
    c = client()
    try:
        ids = [n.removeprefix("customers/") for n in c.get_service("CustomerService").list_accessible_customers().resource_names]
    except GoogleAdsException as ex:
        status, message = ads_client.explain_api_error(ads_client.error_text(ex))
        sys.exit(f"{status:7}{message}")
    out = []
    for cid in ids:
        try:
            c.login_customer_id = cid
            ga = c.get_service("GoogleAdsService")  # the login id is read when the service is created
            rows = [r for batch in ga.search_stream(customer_id=cid, query=QUERY) for r in batch.results]
            me = rows[0].customer
            out.append(entry(me))
            if me.manager:  # the ad accounts under a manager are reached through it (login_customer_id)
                out += [entry(r.customer_client, cid) for batch in ga.search_stream(customer_id=cid, query=CHILDREN)
                        for r in batch.results if str(r.customer_client.id) != cid]
        except GoogleAdsException as ex:
            out.append({"customer_id": fmt(cid), "error": ads_client.explain_api_error(ads_client.error_text(ex))[1]})
    if "--json" in sys.argv:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return
    for a in out:
        if "error" in a:
            print(f"{a['customer_id']}  (cannot read: {a['error']})")
        else:
            kind = "manager" if a["manager"] else "test account" if a["test_account"] else "ad account"
            via = f"  (via manager {a['login_customer_id']})" if a.get("login_customer_id") else ""
            print(f"{a['customer_id']}  {a['name'] or '(no name)'}  {a['currency']}  {a['timezone']}  [{kind}]{via}")


if __name__ == "__main__":
    main()
