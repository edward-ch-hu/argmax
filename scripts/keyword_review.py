"""Weekly keyword review for every enabled Search campaign. Read-only.

Writes reports/keyword-review-<date>.md (to read) and .json (to edit, then apply).

Rules, on the last DAYS of Google Search traffic only (thresholds in argmax.yaml):
  NEGATIVE  search term with clicks but no conversion after negatives.min_cost spend or negatives.min_clicks clicks,
            or any click on a junk word (negatives.junk_words: free, jobs, download...)
  HELD      a would-be negative on a winning topic without a junk word: listed in held_winning for the weekly to
            judge (move a row to negatives to block it); apply_keyword_review.py ignores this list
  POSITIVE  search term with keyword_review.min_positive_conversions+ conversions that isn't a keyword yet -> phrase
  PAUSE     keyword with keyword_review.min_pause_cost+ spend and no conversion
  IDEA      Keyword Planner ideas per ad group, in the campaign's own language and locations

Defaults: negatives approve=true; positives, pauses and ideas approve=false (they need a human or agent look:
converting search terms are often competitor brand names).

Usage: uv run scripts/keyword_review.py [DAYS]   (7, 14 or 30; default 30)
Then:  edit "approve" in the .json, run scripts/apply_keyword_review.py <json>
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import ads_client
import config
from ads_client import rows as search
from google.ads.googleads.errors import GoogleAdsException
from topics import main_topic


def money(micros):
    return round(micros / 1e6, 2)


def junk_word(term, words=None):
    words = config.get().negatives.junk_words if words is None else words
    t = term.lower()
    return next((w for w in words if w.lower() in t), None)


def negative_rule(term, cost, clicks, conversions, cfg=None):
    """The NEGATIVE rule: None, or (reason, topic, held); held = a winning topic without a junk word (held_winning)."""
    cfg = cfg or config.get()
    n = cfg.negatives
    junk = junk_word(term, n.junk_words)
    if conversions == 0 and (junk and clicks or cost >= n.min_cost or clicks >= n.min_clicks):
        reason = f"junk word '{junk}'" if junk else f"{cfg.account.currency} {cost} / {clicks} clicks, 0 conv"
        topic = main_topic(term, cfg.topics)
        return reason, topic, topic in cfg.winning_topics and not junk
    return None


def period_of(days):
    return f"segments.date DURING LAST_{days}_DAYS" if days in (7, 14, 30) else "segments.date DURING LAST_30_DAYS"


def search_campaigns(ga):
    return {r.campaign.id: r.campaign.name for r in search(ga,
            "SELECT campaign.id, campaign.name FROM campaign WHERE campaign.status = 'ENABLED' "
            "AND campaign.advertising_channel_type = 'SEARCH'")}


def search_terms(ga, campaigns, period):
    """[(row, metrics)] per ad group and search term on Google Search, for terms not yet added or excluded."""
    if not campaigns:
        return []
    out = []
    for r in search(ga, f"""SELECT campaign.id, ad_group.id, ad_group.name, search_term_view.search_term,
            search_term_view.status, segments.ad_network_type, metrics.cost_micros, metrics.clicks, metrics.conversions
            FROM search_term_view WHERE campaign.id IN ({",".join(map(str, campaigns))}) AND {period}
            AND segments.ad_network_type = 'SEARCH'"""):
        if r.search_term_view.status.name not in ("NONE", "UNKNOWN"):
            continue  # already added or excluded
        m = r.metrics
        out.append(({"campaign_id": r.campaign.id, "campaign": campaigns[r.campaign.id], "ad_group_id": r.ad_group.id,
                     "ad_group": r.ad_group.name, "text": r.search_term_view.search_term, "cost": money(m.cost_micros),
                     "clicks": m.clicks, "conversions": round(m.conversions, 1)}, m))
    return out


def main():
    cfg = config.get()
    k = cfg.keyword_review
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")
    period = period_of(days)

    campaigns = search_campaigns(ga)
    if not campaigns:
        sys.exit("No enabled Search campaign.")
    ids = ",".join(map(str, campaigns))

    existing = defaultdict(set)
    for r in search(ga, f"""SELECT campaign.id, ad_group_criterion.keyword.text FROM ad_group_criterion
            WHERE campaign.id IN ({ids}) AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE
            AND ad_group_criterion.status != 'REMOVED'"""):
        existing[r.campaign.id].add(r.ad_group_criterion.keyword.text.lower().strip('"[]+'))

    out = {"date": str(ads_client.today()), "days": days, "currency": cfg.account.currency, "negatives": [],
           "held_winning": [], "positives": [], "pauses": [], "ideas": []}

    for row, m in search_terms(ga, campaigns, period):
        negative = negative_rule(row["text"], row["cost"], m.clicks, m.conversions, cfg)
        if negative:
            reason, topic, held = negative
            if held:
                out["held_winning"].append({**row, "topic": topic, "match": "EXACT", "reason": reason, "approve": False})
            else:
                out["negatives"].append({**row, "match": "EXACT", "reason": reason, "approve": True})
        elif m.conversions >= k.min_positive_conversions and row["text"].lower() not in existing[row["campaign_id"]]:
            out["positives"].append({**row, "match": "PHRASE", "reason": f"{row['conversions']} conv", "approve": False})

    for r in search(ga, f"""SELECT campaign.id, ad_group.name, ad_group_criterion.resource_name,
            ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
            ad_group_criterion.quality_info.quality_score, metrics.cost_micros, metrics.clicks, metrics.conversions
            FROM keyword_view WHERE campaign.id IN ({ids}) AND {period} AND ad_group_criterion.status = 'ENABLED'"""):
        m, kw = r.metrics, r.ad_group_criterion
        if money(m.cost_micros) >= k.min_pause_cost and m.conversions == 0:
            out["pauses"].append({"campaign": campaigns[r.campaign.id], "ad_group": r.ad_group.name,
                                  "resource_name": kw.resource_name, "text": kw.keyword.text,
                                  "match": kw.keyword.match_type.name,
                                  "quality_score": kw.quality_info.quality_score or None, "cost": money(m.cost_micros),
                                  "clicks": m.clicks, "reason": f"{cfg.account.currency} {money(m.cost_micros)}, 0 conv",
                                  "approve": False})

    out["ideas"] = keyword_ideas(client, ga, campaigns, existing)
    for key in ("negatives", "held_winning", "positives", "pauses"):
        out[key].sort(key=lambda x: -x["cost"])

    Path("reports").mkdir(exist_ok=True)
    stem = Path(f"reports/keyword-review-{out['date']}")
    stem.with_suffix(".json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    stem.with_suffix(".md").write_text(render(out))
    print(f"{len(out['negatives'])} negatives, {len(out['held_winning'])} held (winning topic), "
          f"{len(out['positives'])} positives, {len(out['pauses'])} pauses, {len(out['ideas'])} ideas -> {stem}.md / .json")


def keyword_ideas(client, ga, campaigns, existing):
    """Planner ideas per ad group, seeded with its own live keywords and landing page."""
    cfg = config.get()
    k = cfg.keyword_review
    planner = client.get_service("KeywordPlanIdeaService")
    ids = ",".join(map(str, campaigns))
    negatives = defaultdict(set)
    for r in search(ga, f"""SELECT campaign.id, ad_group_criterion.keyword.text FROM ad_group_criterion
            WHERE campaign.id IN ({ids}) AND ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = TRUE"""):
        negatives[r.campaign.id].add(r.ad_group_criterion.keyword.text.lower().strip('"[]+'))
    groups = defaultdict(lambda: {"seeds": [], "url": None})
    for r in search(ga, f"""SELECT campaign.id, ad_group.id, ad_group.name, ad_group_criterion.keyword.text,
            metrics.clicks FROM keyword_view WHERE campaign.id IN ({ids}) AND ad_group.status = 'ENABLED'
            AND ad_group_criterion.status = 'ENABLED' AND ad_group_criterion.negative = FALSE
            AND segments.date DURING LAST_30_DAYS AND metrics.impressions > 0 ORDER BY metrics.clicks DESC"""):
        g = groups[(r.campaign.id, r.ad_group.id, r.ad_group.name)]
        if len(g["seeds"]) < 10:
            g["seeds"].append(r.ad_group_criterion.keyword.text.strip('"[]+'))
    for r in search(ga, f"""SELECT campaign.id, ad_group.id, ad_group_ad.ad.final_urls FROM ad_group_ad
            WHERE campaign.id IN ({ids}) AND ad_group_ad.status = 'ENABLED'"""):
        for key, g in groups.items():
            if key[1] == r.ad_group.id and r.ad_group_ad.ad.final_urls:
                g["url"] = r.ad_group_ad.ad.final_urls[0]
    targeting = {}
    for cid in campaigns:
        crit = search(ga, f"""SELECT campaign_criterion.type, campaign_criterion.location.geo_target_constant,
                campaign_criterion.language.language_constant FROM campaign_criterion
                WHERE campaign.id = {cid} AND campaign_criterion.negative = FALSE
                AND campaign_criterion.type IN ('LOCATION', 'LANGUAGE')""")
        targeting[cid] = ([c.campaign_criterion.location.geo_target_constant for c in crit
                           if c.campaign_criterion.type_.name == "LOCATION"],
                          [c.campaign_criterion.language.language_constant for c in crit
                           if c.campaign_criterion.type_.name == "LANGUAGE"])

    ideas = []
    for (cid, gid, gname), g in groups.items():
        geos, langs = targeting[cid]
        req = client.get_type("GenerateKeywordIdeasRequest")
        req.customer_id = ads_client.customer_id()
        req.language = langs[0] if langs else "languageConstants/1000"
        req.geo_target_constants.extend(geos)
        req.keyword_and_url_seed.keywords.extend(g["seeds"])
        if g["url"]:
            req.keyword_and_url_seed.url = g["url"]
        req.page_size = 200
        try:
            found = list(planner.generate_keyword_ideas(request=req))
        except GoogleAdsException as ex:
            print(f"ideas for {campaigns[cid]} / {gname} failed: {ex.failure.errors[0].message}")
            continue
        blocked = negatives[cid] | {w.lower() for w in cfg.negatives.junk_words}
        fresh = [i for i in found if i.text.lower() not in existing[cid]
                 and i.keyword_idea_metrics.avg_monthly_searches >= k.ideas_min_monthly_searches
                 and not any(b in i.text.lower() for b in blocked)]
        fresh.sort(key=lambda i: -i.keyword_idea_metrics.avg_monthly_searches)
        for i in fresh[:k.ideas_per_ad_group]:
            km = i.keyword_idea_metrics
            ideas.append({"campaign_id": cid, "campaign": campaigns[cid], "ad_group_id": gid, "ad_group": gname,
                          "text": i.text, "monthly_searches": km.avg_monthly_searches, "competition": km.competition.name,
                          "top_bid": money(km.high_top_of_page_bid_micros), "match": "PHRASE", "approve": False})
    return ideas


def render(out):
    lines = [f"# Keyword review {out['date']} (last {out['days']} days, Google Search only, {out['currency']})", ""]
    sections = [("negatives", "Block these search terms (negative, exact)", ["campaign", "text", "cost", "clicks", "reason"]),
                ("held_winning", "Not blocked: winning-topic terms with no conversion (judge by hand)",
                 ["campaign", "ad_group", "text", "topic", "cost", "clicks"]),
                ("positives", "Add these search terms as keywords (phrase)", ["campaign", "ad_group", "text", "cost", "conversions"]),
                ("pauses", "Pause these keywords", ["campaign", "ad_group", "text", "match", "quality_score", "cost", "clicks"]),
                ("ideas", "New keyword ideas (Keyword Planner)", ["campaign", "ad_group", "text", "monthly_searches", "competition", "top_bid"])]
    for key, title, cols in sections:
        rows = out[key]
        lines += [f"## {title} ({len(rows)})", ""]
        if not rows:
            lines += ["None.", ""]
            continue
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
