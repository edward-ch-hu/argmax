"""Match type review: which Search keywords match too broadly. Read-only.

For each enabled Search keyword (positive), from search_term_view with the keyword segment over DAYS of Google
Search traffic: spend, clicks, lead-signal conversions (conversions.lead_signals only, as in keyword_review.py), and
the spend on off-intent search terms. A term is off-intent when
  - it would be a negative under keyword_review.py's rule (on its totals in the campaign over DAYS, not held, and
    not protected by a lead signal in its campaign over negatives.protect_days), or
  - it has a junk word (negatives.junk_words), or
  - its main topic differs from the ad group's topic (ad_group_topics) and is not a winning topic.
Proposals (all approve=false; the weekly raises one "Unless you say no" decision, then applies the file with
apply_keyword_review.py):
  BROAD  with off-intent share >= match_type_review.broad_to_phrase_share and off-intent spend >= min_off_intent_spend:
         add the same text as PHRASE (same bid), pause the broad one (only once the phrase one is added: "replaced_by")
  PHRASE with off-intent share >= phrase_to_exact_share and the same spend floor: the same, to EXACT
Writes reports/match-type-review-<date>.json: "keywords" (every keyword with spend, by off-intent spend) and the
proposals in keyword review shape ("positives" = the new keywords, "pauses" = the old ones).

Usage: uv run scripts/match_type_review.py [DAYS]   (7, 14 or 30; default 30)
"""
import json
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import ads_client
import config
from ads_client import rows
from keyword_review import (junk_word, lead_conversions, money, negative_rule, norm, period_of, protect_terms,
                            search_campaigns, with_conversions)
from topics import ad_group_topic, main_topic

TOP_TERMS = 5


def rules(cfg=None):
    m = (cfg or config.get()).match_type_review
    return {"BROAD": ("PHRASE", m.broad_to_phrase_share), "PHRASE": ("EXACT", m.phrase_to_exact_share)}


def off_intent(term, totals, group_topic, cfg=None, recent=0):
    """True when a search term is off-intent for a keyword in a group of `group_topic`. totals = (cost, clicks, conv)
    of the term in its campaign over the window; recent = its lead signals over negatives.protect_days."""
    cfg = cfg or config.get()
    cost, clicks, conv = totals
    negative = negative_rule(term, cost, clicks, conv, cfg, recent)
    topic = main_topic(term, cfg.topics)
    return bool((negative and not negative[2]) or junk_word(term, cfg.negatives.junk_words)
                or (group_topic and topic != group_topic and topic not in cfg.winning_topics))


def main():
    cfg = config.get()
    cur = cfg.account.currency
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    period = period_of(days)
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    campaigns = search_campaigns(ga)
    if not campaigns:
        sys.exit("No enabled Search campaign.")
    ids = ",".join(map(str, campaigns))

    keywords, existing = {}, {}
    for r in rows(ga, f"""SELECT campaign.id, ad_group.id, ad_group.name, ad_group_criterion.resource_name,
            ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.status,
            ad_group_criterion.cpc_bid_micros, ad_group.status FROM ad_group_criterion
            WHERE campaign.id IN ({ids}) AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE
            AND ad_group_criterion.status != 'REMOVED' AND ad_group.status != 'REMOVED'"""):
        k = r.ad_group_criterion
        existing[(r.ad_group.id, k.keyword.text.lower(), k.keyword.match_type.name)] = k.status.name
        if k.status.name == "ENABLED" and r.ad_group.status.name == "ENABLED":
            keywords[k.resource_name] = {
                "campaign_id": r.campaign.id, "campaign": campaigns[r.campaign.id], "ad_group_id": r.ad_group.id,
                "ad_group": r.ad_group.name, "resource_name": k.resource_name, "text": k.keyword.text,
                "match": k.keyword.match_type.name, "own_bid": money(k.cpc_bid_micros) or None,
                "micros": 0, "off_micros": 0, "clicks": 0, "conversions": 0.0, "off_terms": defaultdict(int)}

    found, totals = [], defaultdict(lambda: [0, 0, 0.0])
    where = f"campaign.id IN ({ids}) AND {period} AND segments.ad_network_type = 'SEARCH'"
    key = ("campaign.id", "segments.keyword.ad_group_criterion", "search_term_view.search_term")
    terms = rows(ga, f"""SELECT campaign.id, ad_group.name, search_term_view.search_term,
            segments.keyword.ad_group_criterion, segments.ad_network_type, metrics.cost_micros, metrics.clicks
            FROM search_term_view WHERE {where}""")
    for r, m in with_conversions(terms, key, lead_conversions(ga, "search_term_view", key, where, cfg)):
        if r.segments.keyword.ad_group_criterion in keywords:
            found.append((r, m))
        t = totals[(r.campaign.id, r.search_term_view.search_term.lower())]
        t[0] += m.cost_micros
        t[1] += m.clicks
        t[2] += m.conversions

    recent = protect_terms(ga, campaigns, ads_client.today() - timedelta(days=1), cfg)
    for r, m in found:
        k, term = keywords[r.segments.keyword.ad_group_criterion], r.search_term_view.search_term
        cost, clicks, conv = totals[(r.campaign.id, term.lower())]
        off = off_intent(term, (money(cost), clicks, conv), ad_group_topic(k["ad_group"]), cfg,
                         recent.get((r.campaign.id, norm(term)), 0))
        k["micros"] += m.cost_micros
        k["clicks"] += m.clicks
        k["conversions"] += m.conversions
        if off:
            k["off_micros"] += m.cost_micros
            k["off_terms"][term] += m.cost_micros

    out = {"date": str(ads_client.today()), "days": days, "currency": cur, "source": "match_type_review",
           "keywords": [], "negatives": [], "held_winning": [], "positives": [], "pauses": [], "ideas": []}
    for k in keywords.values():
        if not k["micros"]:
            continue
        spend, off_spend = money(k["micros"]), money(k["off_micros"])
        share = round(off_spend / spend, 3) if spend else 0.0
        top = sorted(k["off_terms"].items(), key=lambda x: -x[1])[:TOP_TERMS]
        row = {key: k[key] for key in ("campaign", "ad_group", "text", "match")}
        row.update({"spend": spend, "clicks": k["clicks"], "conversions": round(k["conversions"], 1),
                    "off_intent_spend": off_spend, "off_intent_share": share,
                    "top_off_intent_terms": [{"term": t, "cost": money(c)} for t, c in top], "proposal": None})
        out["keywords"].append(row)
        target, min_share = rules(cfg).get(k["match"], (None, 1.1))
        if not target or share < min_share or off_spend < cfg.match_type_review.min_off_intent_spend:
            continue
        text = k["text"].replace("+", "").strip()
        reason = f"{k['match']}: {share:.0%} of {cur} {spend} on off-intent terms in {days} days ({cur} {off_spend})"
        status = existing.get((k["ad_group_id"], text.lower(), target))
        if status == "PAUSED":
            row["proposal"] = f"none: the {target} version exists but is paused"
            continue
        pause = {"campaign": k["campaign"], "ad_group": k["ad_group"], "resource_name": k["resource_name"],
                 "text": k["text"], "match": k["match"], "cost": spend, "clicks": k["clicks"],
                 "reason": reason, "approve": False}
        if status is None:
            new = {"campaign_id": k["campaign_id"], "campaign": k["campaign"], "ad_group_id": k["ad_group_id"],
                   "ad_group": k["ad_group"], "text": text, "match": target, "cost": spend,
                   "reason": f"replaces {k['match']} '{k['text']}': {reason}", "approve": False}
            if k["own_bid"]:
                new["cpc"] = k["own_bid"]
            out["positives"].append(new)
            pause["replaced_by"] = {"ad_group_id": k["ad_group_id"], "text": text, "match": target}
        out["pauses"].append(pause)
        row["proposal"] = f"{target}" + ("" if status is None else f" (the {target} version is already enabled: pause only)")
    out["keywords"].sort(key=lambda r: (-r["off_intent_spend"], -r["spend"]))
    for key in ("positives", "pauses"):
        out[key].sort(key=lambda x: -x["cost"])

    for r in out["keywords"]:
        if r["off_intent_spend"]:
            terms = ", ".join(f"{t['term']} ({t['cost']:.2f})" for t in r["top_off_intent_terms"])
            print(f"{r['off_intent_spend']:9.2f} of {r['spend']:9.2f} ({r['off_intent_share']:4.0%})  {r['match']:6} "
                  f"{r['campaign']} / {r['ad_group']} / {r['text']}" + (f"  -> {r['proposal']}" if r["proposal"] else "")
                  + f"  [{terms}]")
    proposed = [r for r in out["keywords"] if r["proposal"] and not r["proposal"].startswith("none")]
    path = Path(f"reports/match-type-review-{out['date']}.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{len(proposed)} keywords proposed ({sum(r['match'] == 'BROAD' for r in proposed)} to PHRASE, "
          f"{sum(r['match'] == 'PHRASE' for r in proposed)} to EXACT), carrying {cur} "
          f"{sum(r['off_intent_spend'] for r in proposed):.2f} off-intent spend in {days} days -> {path}")


if __name__ == "__main__":
    main()
