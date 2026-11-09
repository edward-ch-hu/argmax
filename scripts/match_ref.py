"""Match the ad click ref codes in the CRM to the Google Ads click that brought the lead (optional, config: ref_codes).

Your site puts "(ref <PREFIX>XXXXXXXX)" into the contact message or form of visitors who came from an ad, where
code = prefix + sha1(gclid).hex()[:8].upper() (docs/ref-codes.md has a snippet), and sales pastes the code into the
CRM. Google Ads keeps click ids (click_view) for 90 days and returns one day per query, so each day's clicks are saved
as code -> ad group, keyword, ad id in reports/daily/clicks/<date>.tsv. The gclid itself is not stored; look it up
again from Google Ads if you ever upload offline conversions.

A code found on two clicks is "ambiguous": report it, never guess. Read-only on the account. Run by the daily scout.

Usage: uv run scripts/match_ref.py   collects any missing days (up to 90 back, always re-collects the last 2),
                                     then prints every CRM lead with a ref code and its click as JSON
"""
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import ads_client
import config
import crm

CLICK_DIR = Path("reports/daily/clicks")
KEEP_DAYS = 120  # click_view only goes back 90 days; older files have no further use


def enabled(cfg=None):
    cfg = cfg or config.get()
    return cfg.ref_codes.enabled and crm.enabled(cfg)


def code_of(gclid, prefix=None):
    prefix = prefix if prefix is not None else config.get().ref_codes.prefix
    return prefix + hashlib.sha1(gclid.encode()).hexdigest()[:8].upper()


def collect(client, day):
    """Save one day's clicks as code / ad group id / keyword / ad id. Returns the number of clicks."""
    ga = client.get_service("GoogleAdsService")
    lines = []
    for r in ads_client.rows(ga, f"""SELECT click_view.gclid, ad_group.id, click_view.keyword_info.text,
            click_view.ad_group_ad FROM click_view WHERE segments.date = '{day}'"""):
        if r.click_view.gclid:
            keyword = r.click_view.keyword_info.text.replace("\t", " ").replace("\n", " ")
            ad_id = r.click_view.ad_group_ad.rpartition("~")[2]
            lines.append(f"{code_of(r.click_view.gclid)}\t{r.ad_group.id}\t{keyword}\t{ad_id}")
    CLICK_DIR.mkdir(parents=True, exist_ok=True)
    (CLICK_DIR / f"{day}.tsv").write_text("code\tad_group_id\tkeyword\tad_id\n" + "\n".join(sorted(lines)) + "\n")
    return len(lines)


def collect_missing(client, until):
    """Collect every day of the 90 up to `until` that has no file, plus the last 2 days again (late clicks).
    Days Google no longer serves (over 89 days before today) are skipped, so a back-dated run works."""
    end = date.fromisoformat(until)
    oldest = str(ads_client.today() - timedelta(days=89))
    done = []
    for back in range(89, -1, -1):
        day = str(end - timedelta(days=back))
        if day < oldest:
            continue
        if back < 2 or not (CLICK_DIR / f"{day}.tsv").exists():
            done.append((day, collect(client, day)))
    for path in CLICK_DIR.glob("*.tsv"):
        if path.stem < str(end - timedelta(days=KEEP_DAYS)):
            path.unlink()
    return done


def click_index(click_dir=None):
    index = {}
    for path in sorted((click_dir or CLICK_DIR).glob("*.tsv")):
        for line in path.read_text().splitlines()[1:]:
            code, ad_group_id, keyword, ad_id = (line.split("\t") + ["", "", ""])[:4]
            if code:
                index.setdefault(code, []).append({"click_date": path.stem, "ad_group_id": ad_group_id,
                                                   "keyword": keyword, "ad_id": ad_id})
    return index


def ad_group_names(client):
    ga = client.get_service("GoogleAdsService")
    return {str(r.ad_group.id): (r.campaign.name, r.ad_group.name)
            for r in ads_client.rows(ga, "SELECT campaign.name, ad_group.id, ad_group.name FROM ad_group")}


def match_rows(rows, index, names, test_codes=()):
    """One entry per (CRM lead, ref code): matched (one click), ambiguous (several) or not_found. No names."""
    out = []
    for r in rows:
        for code in r["refs"]:
            if code in test_codes:
                continue
            clicks = [dict(c) for c in index.get(code, [])]
            for c in clicks:
                c["campaign"], c["ad_group"] = names.get(c.pop("ad_group_id"), ("?", "?"))
            status = "matched" if len(clicks) == 1 else "ambiguous" if clicks else "not_found"
            out.append({"fp": r["fp"], "date": r["date"], "stage": r["stage"], "topics": r["topics"],
                        "mrr": r["mrr"], "code": code, "status": status, "clicks": clicks})
    return out


def match(client, rows=None):
    """match_rows() on the saved clicks; [] when ref codes are off."""
    if not enabled():
        return []
    rows = crm.load() if rows is None else rows
    index = click_index()
    names = ad_group_names(client) if any(c in index for r in rows for c in r["refs"]) else {}
    return match_rows(rows, index, names, set(config.get().ref_codes.test_codes))


def main():
    if not enabled():
        sys.exit("ref codes are off (ref_codes.enabled, and a CRM source, in argmax.yaml)")
    client = ads_client.load()
    done = collect_missing(client, str(ads_client.today() - timedelta(days=1)))
    print(f"Collected {len(done)} day(s), {sum(n for _, n in done)} clicks")
    print(json.dumps(match(client), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
