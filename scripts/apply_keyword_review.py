"""Apply the approved rows of a keyword review JSON (keyword_review.py or match_type_review.py).

  negatives -> campaign-level negative keyword (exact)
  positives -> ad group keyword (its match, phrase in keyword_review; optional "cpc" for a keyword-level bid)
  ideas     -> ad group keyword (phrase)
  pauses    -> pause the keyword; a row with "replaced_by" ({ad_group_id, text, match}, from match_type_review.py)
               is paused only when that new keyword was added in the same run
  (held_winning is ignored: move a row to negatives to block it; missing lists count as empty)
With --apply every applied row is appended to reports/changes.jsonl (ledger.py) for the monthly change audit.
daily_negatives.py applies its negatives through apply() too.

Usage: uv run scripts/apply_keyword_review.py reports/keyword-review-<date>.json          (validate only)
       uv run scripts/apply_keyword_review.py reports/keyword-review-<date>.json --apply  (makes the changes)
"""
import json
import sys
from pathlib import Path

import ads_client
import ledger
from google.ads.googleads.errors import GoogleAdsException
from topics import ad_group_topic, main_topic


def ledger_entry(kind, row, routine="weekly"):
    topic = ad_group_topic(row.get("ad_group")) or main_topic(row["text"])
    where = f"{row['campaign']} / {row['ad_group']}"
    if kind == "negative":
        return ledger.entry("keyword", f"{row['campaign']} (campaign negative) / {row['text']}", "negative", None,
                            row["match"], row.get("reason", ""), topic, "less spend on off-intent searches", routine)
    if kind == "add":
        return ledger.entry("keyword", f"{where} / {row['text']}", "keyword", None, row["match"],
                            row.get("reason", "keyword idea"), topic, f"more relevant {topic} traffic", routine)
    return ledger.entry("keyword", f"{where} / {row['text']} ({row['match']})", "status", "ENABLED", "PAUSED",
                        row.get("reason", ""), topic, "less spend on a keyword with no conversions", routine)


def added_key(ad_group_id, text, match):
    return int(ad_group_id), text.lower(), match


def send(client, service, method, ops, labels, validate_only):
    """One partial-failure request. Prints a line per operation; returns {index: error} of the failed ones."""
    if not ops:
        return {}
    try:
        response = getattr(service, method)(request={"customer_id": ads_client.customer_id(), "operations": ops,
                                                     "partial_failure": True, "validate_only": validate_only})
    except GoogleAdsException as ex:
        message = "; ".join(e.message for e in ex.failure.errors)
        for label in labels:
            print(f"FAIL   {label}  <- {message}")
        return {i: message for i in range(len(ops))}
    failed = {}
    if response.partial_failure_error.details:
        for detail in response.partial_failure_error.details:
            failure = client.get_type("GoogleAdsFailure").__class__.deserialize(detail.value)
            for error in failure.errors:
                failed[error.location.field_path_elements[0].index] = error.message
    for i, label in enumerate(labels):
        print(f"{'FAIL ' if i in failed else ('VALID' if validate_only else 'DONE ')}  {label}"
              + (f"  <- {failed[i]}" if i in failed else ""))
    return failed


def apply(client, review, validate_only, routine="weekly"):
    """Sends the approved rows (validate-only unless told otherwise). Returns [(row, ledger entry)] that went through."""
    cid = ads_client.customer_id()
    match = client.enums.KeywordMatchTypeEnum
    campaign_service = client.get_service("CampaignService")
    ad_group_service = client.get_service("AdGroupService")
    criteria = client.get_service("AdGroupCriterionService")
    print("VALIDATE ONLY (no changes)" if validate_only else "APPLYING CHANGES")
    done = []

    ops, labels, rows = [], [], []
    for row in (r for r in review.get("negatives", []) if r["approve"]):
        op = client.get_type("CampaignCriterionOperation")
        op.create.campaign = campaign_service.campaign_path(cid, row["campaign_id"])
        op.create.negative = True
        op.create.keyword.text = row["text"]
        op.create.keyword.match_type = match[row["match"]]
        ops.append(op)
        labels.append(f"negative  {row['campaign']}: [{row['text']}]")
        rows.append(row)
    failed = send(client, client.get_service("CampaignCriterionService"), "mutate_campaign_criteria", ops, labels,
                  validate_only)
    done += [(r, ledger_entry("negative", r, routine)) for i, r in enumerate(rows) if i not in failed]

    ops, labels, rows = [], [], []
    for row in (r for key in ("positives", "ideas") for r in review.get(key, []) if r["approve"]):
        op = client.get_type("AdGroupCriterionOperation")
        op.create.ad_group = ad_group_service.ad_group_path(cid, row["ad_group_id"])
        op.create.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        op.create.keyword.text = row["text"]
        op.create.keyword.match_type = match[row["match"]]
        if row.get("cpc"):
            op.create.cpc_bid_micros = ads_client.micros(row["cpc"])
        ops.append(op)
        labels.append(f"add       {row['campaign']} / {row['ad_group']}: \"{row['text']}\" ({row['match']})")
        rows.append(row)
    failed = send(client, criteria, "mutate_ad_group_criteria", ops, labels, validate_only)
    added = {added_key(r["ad_group_id"], r["text"], r["match"]) for i, r in enumerate(rows) if i not in failed}
    done += [(r, ledger_entry("add", r, routine)) for i, r in enumerate(rows) if i not in failed]

    ops, labels, rows = [], [], []
    for row in (r for r in review.get("pauses", []) if r["approve"]):
        label = f"pause     {row['campaign']} / {row['ad_group']}: {row['text']} ({row['match']})"
        new = row.get("replaced_by")
        if new and added_key(new["ad_group_id"], new["text"], new["match"]) not in added:
            print(f"SKIP   {label}  <- its replacement \"{new['text']}\" ({new['match']}) was not added")
            continue
        op = client.get_type("AdGroupCriterionOperation")
        op.update.resource_name = row["resource_name"]
        op.update.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
        op.update_mask.paths.append("status")
        ops.append(op)
        labels.append(label)
        rows.append(row)
    failed = send(client, criteria, "mutate_ad_group_criteria", ops, labels, validate_only)
    done += [(r, ledger_entry("pause", r, routine)) for i, r in enumerate(rows) if i not in failed]
    return done


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    review = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    validate_only = "--apply" not in sys.argv
    done = apply(ads_client.load(), review, validate_only)
    if not validate_only:
        ledger.append([e for _, e in done])


if __name__ == "__main__":
    main()
