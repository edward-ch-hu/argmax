"""Weekly keyword review for every enabled Search campaign. Read-only.

Writes reports/keyword-review-<date>.md (to read) and .json (to edit, then apply).

Conversions here are lead-signal conversions only (conversions.lead_signals, segmented by conversion action):
noise signals and every other action never save a term from being a negative, never make a positive and never keep
a keyword from a pause. Cost and clicks come from a second query, since a query segmented by conversion action
returns only conversion metrics and drops the rows without conversions.

Rules, on the last DAYS of Google Search traffic only (thresholds in argmax.yaml):
  NEGATIVE  search term with no lead-signal conversion after negatives.min_cost spend over at least
            negatives.min_cost_clicks clicks (so one expensive click in a quiet account is not enough), or after
            negatives.min_clicks clicks, or any click on a junk word (negatives.junk_words: free, jobs, download...)
  HELD      a would-be negative on a winning topic without a junk word: listed in held_winning for the weekly to
            judge (move a row to negatives to block it); apply_keyword_review.py ignores this list
  POSITIVE  search term with keyword_review.min_positive_conversions+ conversions that isn't a keyword yet -> phrase
  PAUSE     keyword with keyword_review.min_pause_cost+ spend and no conversion
  IDEA      Keyword Planner ideas per ad group, in the campaign's own language and locations. Skipped with a NOTE
            line (and "ideas_note" in the JSON) when keyword_review.ideas is off, when api.access_level is test or
            explorer (Explorer access restricts Keyword Planning services), or when Google refuses the call for
            access or quota; the rest of the review runs either way

Defaults: negatives approve=true; positives, pauses and ideas approve=false (they need a human or agent look:
converting search terms are often competitor brand names).

Usage: uv run scripts/keyword_review.py [DAYS]   (7, 14 or 30; default 30)
Then:  edit "approve" in the .json, run scripts/apply_keyword_review.py <json>
"""
import json
import sys
from collections import defaultdict
from functools import reduce
from pathlib import Path
from types import SimpleNamespace

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
    if conversions == 0 and (junk and clicks or (cost >= n.min_cost and clicks >= n.min_cost_clicks)
                             or clicks >= n.min_clicks):
        reason = f"junk word '{junk}'" if junk else f"{cfg.account.currency} {cost} / {clicks} clicks, 0 lead signals"
        topic = main_topic(term, cfg.topics)
        return reason, topic, topic in cfg.winning_topics and not junk
    return None


def field(row, dotted):
    """The value at a dotted GAQL field name of a result row, e.g. field(r, "campaign.id")."""
    return reduce(getattr, dotted.split("."), row)


def lead_conversions(ga, resource, fields, where, cfg=None):
    """{tuple of the `fields` values: lead-signal conversions} on `resource` (a GAQL FROM) for the rows matching
    `where`. Counts only conversions.lead_signals (metrics.all_conversions per conversion action, like ad_test.py),
    so noise signals never count. Rows without a lead-signal conversion are absent (read them as 0)."""
    signals = (cfg or config.get()).conversions.lead_signals
    out = defaultdict(float)
    for r in search(ga, f"""SELECT {", ".join(fields)}, segments.conversion_action_name, metrics.all_conversions
            FROM {resource} WHERE {where} AND segments.conversion_action_name IN {ads_client.quoted(signals)}
            AND metrics.all_conversions > 0"""):
        out[tuple(field(r, f) for f in fields)] += r.metrics.all_conversions
    return out


def with_conversions(rows, key_fields, conversions):
    """[(row, totals)]: each row's cost_micros and clicks with its lead-signal conversions from `conversions` (keyed by
    the values of `key_fields`; a key's conversions go to its first row only, so nothing counts twice)."""
    left = dict(conversions)
    return [(r, SimpleNamespace(cost_micros=r.metrics.cost_micros, clicks=r.metrics.clicks,
                                conversions=left.pop(tuple(field(r, f) for f in key_fields), 0.0))) for r in rows]


def period_of(days):
    return f"segments.date DURING LAST_{days}_DAYS" if days in (7, 14, 30) else "segments.date DURING LAST_30_DAYS"


def search_campaigns(ga):
    return {r.campaign.id: r.campaign.name for r in search(ga,
            "SELECT campaign.id, campaign.name FROM campaign WHERE campaign.status = 'ENABLED' "
            "AND campaign.advertising_channel_type = 'SEARCH'")}


TERM_KEY = ("campaign.id", "ad_group.id", "search_term_view.search_term")


def search_terms(ga, campaigns, period, cfg=None):
    """[(row, totals)] per ad group and search term on Google Search, for terms not yet added or excluded. totals has
    cost_micros, clicks and conversions (lead signals only)."""
    if not campaigns:
        return []
    where = (f"campaign.id IN ({','.join(map(str, campaigns))}) AND {period} "
             "AND segments.ad_network_type = 'SEARCH'")
    found = [r for r in search(ga, f"""SELECT campaign.id, ad_group.id, ad_group.name, search_term_view.search_term,
            search_term_view.status, segments.ad_network_type, metrics.cost_micros, metrics.clicks
            FROM search_term_view WHERE {where}""")]
    out = []
    for r, m in with_conversions(found, TERM_KEY, lead_conversions(ga, "search_term_view", TERM_KEY, where, cfg)):
        if r.search_term_view.status.name not in ("NONE", "UNKNOWN"):
            continue  # already added or excluded
        out.append(({"campaign_id": r.campaign.id, "campaign": campaigns[r.campaign.id], "ad_group_id": r.ad_group.id,
                     "ad_group": r.ad_group.name, "text": r.search_term_view.search_term, "cost": money(m.cost_micros),
                     "clicks": m.clicks, "conversions": round(m.conversions, 1)}, m))
    return out


def keyword_stats(ga, ids, period, cfg=None):
    """[(row, totals)] per enabled keyword over the period; totals as in search_terms (lead-signal conversions)."""
    where = f"campaign.id IN ({ids}) AND {period} AND ad_group_criterion.status = 'ENABLED'"
    key = ("ad_group_criterion.resource_name",)
    found = [r for r in search(ga, f"""SELECT campaign.id, ad_group.name, ad_group_criterion.resource_name,
            ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
            ad_group_criterion.quality_info.quality_score, metrics.cost_micros, metrics.clicks
            FROM keyword_view WHERE {where}""")]
    return with_conversions(found, key, lead_conversions(ga, "keyword_view", key, where, cfg))


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

    for row, m in search_terms(ga, campaigns, period, cfg):
        negative = negative_rule(row["text"], row["cost"], m.clicks, m.conversions, cfg)
        if negative:
            reason, topic, held = negative
            if held:
                out["held_winning"].append({**row, "topic": topic, "match": "EXACT", "reason": reason, "approve": False})
            else:
                out["negatives"].append({**row, "match": "EXACT", "reason": reason, "approve": True})
        elif m.conversions >= k.min_positive_conversions and row["text"].lower() not in existing[row["campaign_id"]]:
            out["positives"].append({**row, "match": "PHRASE", "reason": f"{row['conversions']} lead signals",
                                     "approve": False})

    for r, m in keyword_stats(ga, ids, period, cfg):
        kw = r.ad_group_criterion
        if money(m.cost_micros) >= k.min_pause_cost and m.conversions == 0:
            out["pauses"].append({"campaign": campaigns[r.campaign.id], "ad_group": r.ad_group.name,
                                  "resource_name": kw.resource_name, "text": kw.keyword.text,
                                  "match": kw.keyword.match_type.name,
                                  "quality_score": kw.quality_info.quality_score or None, "cost": money(m.cost_micros),
                                  "clicks": m.clicks,
                                  "reason": f"{cfg.account.currency} {money(m.cost_micros)}, 0 lead signals",
                                  "approve": False})

    out["ideas"], note = keyword_ideas(client, ga, campaigns, existing)
    if note:
        out["ideas_note"] = note
        print(f"NOTE  {note}")
    for key in ("negatives", "held_winning", "positives", "pauses"):
        out[key].sort(key=lambda x: -x["cost"])

    Path("reports").mkdir(exist_ok=True)
    stem = Path(f"reports/keyword-review-{out['date']}")
    stem.with_suffix(".json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    stem.with_suffix(".md").write_text(render(out))
    print(f"{len(out['negatives'])} negatives, {len(out['held_winning'])} held (winning topic), "
          f"{len(out['positives'])} positives, {len(out['pauses'])} pauses, {len(out['ideas'])} ideas -> {stem}.md / .json")


# Error codes that mean the project may not use Keyword Planning at all (access level) or not now (quota): stop
# asking for the remaining ad groups instead of failing each one.
ACCESS_ERRORS = ("AUTHORIZATION_ERROR", "QUOTA_ERROR", "ACTION_NOT_PERMITTED", "SERVICE_ACCESS_DENIED",
                 "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION", "DEVELOPER_TOKEN_NOT_APPROVED", "RESOURCE_EXHAUSTED",
                 "PERMISSION_DENIED", "ACCESS LEVEL", "EXPLORER")


def ideas_skip_reason(cfg=None):
    """Why Keyword Planner ideas are not asked for at all, or None. Pure."""
    cfg = cfg or config.get()
    if cfg.keyword_review.ideas == "off":
        return "keyword ideas skipped: keyword_review.ideas is off"
    level = cfg.api.access_level
    if level in ("test", "explorer"):
        return (f"keyword ideas skipped: api.access_level is {level}, which does not include Keyword Planning "
                "(apply for Basic access, after brand verification, to get them; SETUP.md step 1)")
    return None


def access_refused(ex):
    """True when a GoogleAdsException says the project may not use this service (access level) or is out of quota."""
    text = " ".join(f"{e.error_code} {e.message}" for e in ex.failure.errors).upper()
    return any(code in text for code in ACCESS_ERRORS)


def keyword_ideas(client, ga, campaigns, existing):
    """(ideas, note): Planner ideas per ad group, seeded with its own live keywords and landing page. note says why
    there are none when they were skipped (switched off, access level, or refused by Google), else None."""
    cfg = config.get()
    k = cfg.keyword_review
    skip = ideas_skip_reason(cfg)
    if skip:
        return [], skip
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
            if access_refused(ex):
                return ideas, (f"keyword ideas skipped: Google refused Keyword Planner ({ex.failure.errors[0].message}). "
                               "Explorer access does not include it and the daily quota counts too; set "
                               "api.access_level or keyword_review.ideas: off to stop asking (SETUP.md step 1)")
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
    return ideas, None


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
        if key == "ideas" and out.get("ideas_note"):
            lines += [f"NOTE: {out['ideas_note']}.", ""]
        if not rows:
            lines += ["None.", ""]
            continue
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
