"""Read-only Google Ads query (GAQL). Prints one JSON object per row.

Usage: uv run scripts/gaql.py "SELECT campaign.name, metrics.clicks FROM campaign WHERE segments.date DURING LAST_7_DAYS"
"""
import json
import sys

import ads_client
from google.ads.googleads.errors import GoogleAdsException
from google.protobuf.json_format import MessageToDict


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    client = ads_client.load()
    try:
        service = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
        for row in ads_client.rows(service, sys.argv[1]):
            print(json.dumps(MessageToDict(type(row).pb(row), preserving_proto_field_name=True), ensure_ascii=False))
    except GoogleAdsException as ex:
        sys.exit("; ".join(e.message for e in ex.failure.errors))


if __name__ == "__main__":
    main()
