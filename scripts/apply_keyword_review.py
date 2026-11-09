"""Apply the approved rows of a keyword review JSON (keyword_review.py or match_type_review.py).

  negatives -> campaign-level negative keyword (exact)
  positives -> ad group keyword (its match, phrase in keyword_review; optional "cpc" for a keyword-level bid)
  ideas     -> ad group keyword (phrase)
  pauses    -> pause the keyword; a row with "replaced_by" ({ad_group_id, text, match}, from match_type_review.py)
               is paused only when that new keyword was added in the same run
  (held_winning is ignored: move a row to negatives to block it; missing lists count as empty)
Refuses the whole file (FAIL lines, nothing changed) when:
- a row of negatives, positives, ideas or pauses has no "approve" (true or false), or misses a field it needs
- a new keyword's "cpc" is outside limits.bid_floor to limits.bid_ceiling
- a new keyword that replaces a paused one ("replaced_by") does not carry the paused keyword's own bid as "cpc"
  (none when the paused keyword had none): a match type change keeps the bid as it is
- a pause row's resource_name is not a live positive keyword of this account with the row's campaign, ad group,
  text and match type (only keywords the review or the match type review found can be paused)
With --apply every row goes to reports/changes.jsonl (ledger.py) for the monthly change audit: pending right before
its request, then applied or failed. daily_negatives.py applies its negatives through apply() too.

Usage: uv run scripts/apply_keyword_review.py reports/keyword-review-<date>.json          (validate only)
       uv run scripts/apply_keyword_review.py reports/keyword-review-<date>.json --apply  (makes the changes)
"""
import json
import sys
from pathlib import Path

import ads_client
import config
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


LISTS = ("negatives", "positives", "ideas", "pauses")
NEEDS = {"negatives": ("campaign_id", "campaign", "text", "match"),
         "positives": ("ad_group_id", "campaign", "ad_group", "text", "match"),
         "ideas": ("ad_group_id", "campaign", "ad_group", "text", "match"),
         "pauses": ("resource_name", "campaign", "ad_group", "text", "match")}
MATCH_TYPES = ("EXACT", "PHRASE", "BROAD")


def check_shape(review):
    """FAIL lines for rows that cannot be applied at all: no approve flag, a missing field, an unknown match. Pure."""
    fails = []
    if not isinstance(review, dict):
        return ["the file must be a JSON object with negatives / positives / ideas / pauses lists"]
    for key in LISTS:
        rows = review.get(key, [])
        if not isinstance(rows, list):
            fails.append(f"{key}: must be a list")
            continue
        for i, row in enumerate(rows):
            where = f"{key}[{i}]" + (f" \"{row.get('text')}\"" if isinstance(row, dict) and row.get("text") else "")
            if not isinstance(row, dict):
                fails.append(f"{where}: must be an object")
                continue
            if not isinstance(row.get("approve"), bool):
                fails.append(f"{where}: needs \"approve\": true or false")
            missing = [k for k in NEEDS[key] if row.get(k) in (None, "")]
            if missing:
                fails.append(f"{where}: missing {', '.join(missing)}")
            if row.get("match") not in (None, "") and row["match"] not in MATCH_TYPES:
                fails.append(f"{where}: match must be one of {', '.join(MATCH_TYPES)}")
    return fails


def check(review, live, cfg=None):
    """FAIL lines for the approved rows against the limits and the live account. Pure, for tests.
    live: {resource name: {campaign, ad_group, text, match, bid}} of the pause rows' keywords as the account has them
    (bid = the keyword's own cpc, None when it uses the ad group's bid); a missing resource is not a live keyword."""
    cfg = cfg or config.get()
    lim, cur = cfg.limits, cfg.account.currency
    fails = []
    adds = {added_key(r["ad_group_id"], r["text"], r["match"]): r
            for key in ("positives", "ideas") for r in review.get(key, []) if r["approve"]}
    for key in ("positives", "ideas"):
        for r in (r for r in review.get(key, []) if r["approve"] and r.get("cpc") is not None):
            cpc = r["cpc"]
            if isinstance(cpc, bool) or not isinstance(cpc, (int, float)) or cpc <= 0:
                fails.append(f"{key} \"{r['text']}\": cpc must be a positive number")
                continue
            bid = ads_client.micros(cpc, cur) / 1e6
            if not lim.bid_floor - 1e-9 <= bid <= lim.bid_ceiling + 1e-9:
                fails.append(f"{key} {r['campaign']} / {r['ad_group']} \"{r['text']}\": cpc {cur} {bid:.2f} is outside "
                             f"{lim.bid_floor:.2f} to {lim.bid_ceiling:.2f}")
    prefix = f"customers/{cfg.account.customer_id}/adGroupCriteria/"
    for r in (r for r in review.get("pauses", []) if r["approve"]):
        where = f"pause {r['campaign']} / {r['ad_group']} \"{r['text']}\" ({r['match']})"
        k = live.get(r["resource_name"])
        if not str(r["resource_name"]).startswith(prefix) or k is None:
            fails.append(f"{where}: {r['resource_name']} is not a live keyword of this account")
            continue
        found = (k["campaign"], k["ad_group"], k["text"].lower(), k["match"])
        if found != (r["campaign"], r["ad_group"], r["text"].lower(), r["match"]):
            fails.append(f"{where}: {r['resource_name']} is {k['campaign']} / {k['ad_group']} \"{k['text']}\" "
                         f"({k['match']}) in the account")
            continue
        new = r.get("replaced_by")
        if not new:
            continue
        if not isinstance(new, dict) or any(new.get(f) in (None, "") for f in ("ad_group_id", "text", "match")):
            fails.append(f"{where}: replaced_by needs ad_group_id, text and match")
            continue
        add = adds.get(added_key(new["ad_group_id"], new["text"], new["match"]))
        if add is None:
            continue  # the pause is skipped at run time when its replacement is not added
        own = ads_client.micros(k["bid"], cur) if k["bid"] else 0
        given = ads_client.micros(add["cpc"], cur) if isinstance(add.get("cpc"), (int, float)) and add["cpc"] else 0
        if own != given:
            fails.append(f"{where}: its replacement \"{add['text']}\" ({add['match']}) must keep the paused keyword's "
                         f"own bid ({f'cpc {cur} {own / 1e6:.2f}' if own else 'no cpc: it uses the ad group bid'}), "
                         f"got {f'{cur} {given / 1e6:.2f}' if given else 'none'}")
    return fails


def live_keywords(ga, resource_names):
    """{resource name: {campaign, ad_group, text, match, bid}} for the positive keywords among `resource_names`."""
    if not resource_names:
        return {}
    out = {}
    for r in ads_client.rows(ga, f"""SELECT campaign.name, ad_group.name, ad_group_criterion.resource_name,
            ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.cpc_bid_micros
            FROM ad_group_criterion WHERE ad_group_criterion.resource_name IN {ads_client.quoted(sorted(resource_names))}
            AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE
            AND ad_group_criterion.status != 'REMOVED'"""):
        k = r.ad_group_criterion
        out[k.resource_name] = {"campaign": r.campaign.name, "ad_group": r.ad_group.name, "text": k.keyword.text,
                                "match": k.keyword.match_type.name, "bid": k.cpc_bid_micros / 1e6 or None}
    return out


def refuse(fails):
    for line in fails:
        print(f"FAIL   {line}")
    raise SystemExit(f"Nothing changed: {len(fails)} rule(s) failed.")


def send(client, service, method, ops, labels, validate_only, entries=None):
    """One partial-failure request. Prints a line per operation; returns {index: error} of the failed ones. With
    entries (one ledger entry per operation, when applying) logs them pending before and applied or failed after."""
    if not ops:
        return {}
    planned = ledger.begin(entries) if entries and not validate_only else None
    try:
        response = getattr(service, method)(request={"customer_id": ads_client.customer_id(), "operations": ops,
                                                     "partial_failure": True, "validate_only": validate_only})
    except GoogleAdsException as ex:
        message = "; ".join(e.message for e in ex.failure.errors)
        for label in labels:
            print(f"FAIL   {label}  <- {message}")
        if planned:
            ledger.finish(planned, "failed")
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
    if planned:
        ledger.finish([e for i, e in enumerate(planned) if i in failed], "failed")
        ledger.finish([e for i, e in enumerate(planned) if i not in failed], "applied")
    return failed


def apply(client, review, validate_only, routine="weekly", annotate=None):
    """Checks the file, then sends the approved rows (validate-only unless told otherwise). With validate_only False
    every row is logged to the ledger (pending, then applied or failed). Returns [(row, ledger entry)] that went
    through. annotate(row) adds fields to a row's ledger entry. Exits with FAIL lines when a check fails."""
    fails = check_shape(review)
    if fails:
        refuse(fails)
    cid = ads_client.customer_id()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    pauses = {r["resource_name"] for r in review.get("pauses", []) if r["approve"]}
    fails = check(review, live_keywords(ga, pauses))
    if fails:
        refuse(fails)
    match = client.enums.KeywordMatchTypeEnum
    campaign_service = client.get_service("CampaignService")
    ad_group_service = client.get_service("AdGroupService")
    criteria = client.get_service("AdGroupCriterionService")
    print("VALIDATE ONLY (no changes)" if validate_only else "APPLYING CHANGES")
    done = []

    def entries(kind, rows):
        return [{**ledger_entry(kind, r, routine), **(annotate(r) if annotate else {})} for r in rows]

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
    logged = entries("negative", rows)
    failed = send(client, client.get_service("CampaignCriterionService"), "mutate_campaign_criteria", ops, labels,
                  validate_only, logged)
    done += [(r, logged[i]) for i, r in enumerate(rows) if i not in failed]

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
    logged = entries("add", rows)
    failed = send(client, criteria, "mutate_ad_group_criteria", ops, labels, validate_only, logged)
    added = {added_key(r["ad_group_id"], r["text"], r["match"]) for i, r in enumerate(rows) if i not in failed}
    done += [(r, logged[i]) for i, r in enumerate(rows) if i not in failed]

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
    logged = entries("pause", rows)
    failed = send(client, criteria, "mutate_ad_group_criteria", ops, labels, validate_only, logged)
    done += [(r, logged[i]) for i, r in enumerate(rows) if i not in failed]
    return done


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    try:
        review = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"FAIL   cannot read {sys.argv[1]}: {e}\nNothing changed.")
    fails = check_shape(review)
    if fails:
        refuse(fails)
    apply(ads_client.load(), review, "--apply" not in sys.argv)


if __name__ == "__main__":
    main()
