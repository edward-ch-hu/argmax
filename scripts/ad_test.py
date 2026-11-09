"""Ad copy tests: one new RSA (the variant) next to a group's existing RSA (the control), built only from the ad
library (ad_tests.library, default docs/ad_library.json), whose every line cites a claim quoted from your website.
Thresholds come from adgrad.yaml (ad_tests); the defaults are shown below.

State: reports/ad_tests.json (a list, one entry per test). Applied pauses and new ads go to reports/changes.jsonl.

  plan                      eligible groups: enabled Search ad groups with 300+ impressions in the last 14 days,
                            exactly one enabled RSA (the control) and no running test; winning topics first
  create <json> [--apply]   start a test. JSON: {"ad_group": {"campaign": "US - Search", "name": "Analytics"},
                            "hypothesis": "one line", "headlines": [asset ids], "descriptions": [asset ids],
                            "final_url": "https://www.example.com/en/analytics/"}
                            Refuses (FAIL, nothing changed) when: an asset id is not in the library, has the wrong
                            type or locale, or cites no claim; an asset's claim or width failed the last claims_check,
                            or that check is not a live one, is SITE_UNREACHABLE, or is over 7 days old; the final
                            URL is not a library page for the locale with a claim on the group's topic; the group
                            is not eligible (see plan) or already has a running test; 3 tests are running; fewer
                            than 8 headlines or 2 descriptions (max 15 and 4), or a repeated text.
  evaluate [--apply]        per running test, since the variant's first impression: impressions, clicks, CTR, lead
                            signals (never a noise signal) and ref-matched leads per arm (by ad id; clicks saved before
                            ad ids were recorded count per ad group only). Decision: after 28+ days with 1,000+
                            impressions per arm, a two-proportion z-test on CTR decides at |z| >= 1.96 (pause the
                            loser); undecided by day 56, keep the arm with more lead signals per impression, then
                            the higher CTR. A disapproved variant fails the test (paused). A test ad (running, or a
                            winner) whose claim failed claims_check is paused at once; if it is the group's last
                            enabled ad, the paused control is enabled again in the same request. Never pauses the
                            last enabled ad of a group.
  reverse <test id> [--apply]
                            undo a concluded test (the owner replied "reverse" on its decision): enable the
                            paused loser and pause the winner, in one request; the test becomes "reversed".

Usage: uv run scripts/ad_test.py plan
       uv run scripts/ad_test.py create reports/ad-test-<date>.json [--apply]
       uv run scripts/ad_test.py evaluate [--apply]
       uv run scripts/ad_test.py reverse <test id> [--apply]
       --state <json> and --check <json> read another state / claims_check file (for tests); never --apply with them.
"""
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import ads_client
import claims_check
import config
import ledger
import match_ref
from ads_client import rows
from google.ads.googleads.errors import GoogleAdsException
from topics import ad_group_topic, winning

STATE = Path("reports/ad_tests.json")
MIN_HEADLINES, MAX_HEADLINES, MIN_DESCRIPTIONS, MAX_DESCRIPTIONS = 8, 15, 2, 4  # Google's RSA limits, kept tight


def t_cfg():
    return config.get().ad_tests


def locale_of(campaign, cfg=None):
    """The locale of a campaign: the longest ad_tests.campaign_locales prefix it starts with, else default_locale."""
    t = (cfg or config.get()).ad_tests
    prefixes = sorted((p for p in t.campaign_locales if campaign.startswith(p)), key=len, reverse=True)
    return t.campaign_locales[prefixes[0]] if prefixes else t.default_locale


def lead_signals_in():
    return ads_client.quoted(config.get().conversions.lead_signals)


def groups(ga, today):
    """Enabled Search ad groups with their 14-day impressions and enabled RSAs."""
    start, end = today - timedelta(days=14), today - timedelta(days=1)
    out = {}
    for r in rows(ga, """SELECT campaign.name, ad_group.id, ad_group.name, ad_group.resource_name FROM ad_group
            WHERE campaign.status = 'ENABLED' AND campaign.advertising_channel_type = 'SEARCH'
            AND ad_group.status = 'ENABLED'"""):
        out[str(r.ad_group.id)] = {"campaign": r.campaign.name, "ad_group": r.ad_group.name,
                                   "ad_group_id": str(r.ad_group.id), "resource": r.ad_group.resource_name,
                                   "topic": ad_group_topic(r.ad_group.name, "other"),
                                   "locale": locale_of(r.campaign.name), "impressions_14d": 0, "rsas": []}
    for r in rows(ga, f"""SELECT ad_group.id, metrics.impressions FROM ad_group WHERE segments.date BETWEEN
            '{start}' AND '{end}' AND campaign.advertising_channel_type = 'SEARCH'"""):
        if str(r.ad_group.id) in out:
            out[str(r.ad_group.id)]["impressions_14d"] += r.metrics.impressions
    for r in rows(ga, """SELECT ad_group.id, ad_group_ad.ad.id, ad_group_ad.policy_summary.approval_status
            FROM ad_group_ad WHERE ad_group_ad.status = 'ENABLED' AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
            AND campaign.advertising_channel_type = 'SEARCH'"""):
        if str(r.ad_group.id) in out:
            out[str(r.ad_group.id)]["rsas"].append(str(r.ad_group_ad.ad.id))
    return out


def eligibility(g, tests):
    if any(t["status"] == "running" and t["ad_group_id"] == g["ad_group_id"] for t in tests):
        return "a test is already running"
    need = t_cfg().min_impressions_14d
    if g["impressions_14d"] < need:
        return f"{g['impressions_14d']} impressions in 14 days (needs {need})"
    if len(g["rsas"]) != 1:
        return f"{len(g['rsas'])} enabled RSAs (needs exactly 1, the control)"
    return None


def plan(ga, tests, today):
    out = []
    for g in groups(ga, today).values():
        why = eligibility(g, tests)
        out.append({k: g[k] for k in ("campaign", "ad_group", "topic", "locale", "impressions_14d")}
                   | {"control_ad_id": g["rsas"][0] if len(g["rsas"]) == 1 else None,
                      "eligible": why is None, "why_not": why})
    wins = winning()
    out.sort(key=lambda g: (not g["eligible"], g["topic"] not in wins, -g["impressions_14d"]))
    return out


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None


def library_pages(library, locale, topic):
    """Final URLs allowed for a group: library claim pages of its locale with a claim on its topic."""
    return {claims_check.site() + c["page"] for c in library["claims"] if c["locale"] == locale and c["topic"] == topic}


def check_create(spec, library, check, g, tests, today, now=None):
    """Every rule a new test breaks, as lines (pure apart from the config, for tests)."""
    t_conf = t_cfg()
    now = now or ads_client.now()
    fails = []
    if g is None:
        return ["ad_group: no enabled Search ad group with that campaign and name"]
    if not (spec.get("hypothesis") or "").strip():
        fails.append("hypothesis: one line is required")
    why = eligibility(g, tests)
    if why:
        fails.append(f"ad group {g['campaign']} / {g['ad_group']} is not eligible: {why}")
    running = [t for t in tests if t["status"] == "running"]
    if len(running) >= t_conf.max_running:
        fails.append(f"{len(running)} tests are already running (max {t_conf.max_running})")

    if check is None:
        fails.append("no claims_check result: run scripts/claims_check.py first")
    else:
        age = now - datetime.fromisoformat(check["checked_at"])
        max_age = timedelta(days=t_conf.claims_max_age_days)
        if check.get("mode") != "live":
            fails.append("the last claims_check was not against the live site")
        if check.get("status") == "unreachable":
            fails.append("the last claims_check could not reach the site (SITE_UNREACHABLE): no new tests")
        if age > max_age:
            fails.append(f"the last claims_check is {age.days} days old (max {max_age.days}): run it again")

    assets = {a["id"]: a for a in library["assets"]}
    failed_claims = set((check or {}).get("failed_claims", []))
    failed_assets = set((check or {}).get("failed_assets", []))
    texts = []
    for kind, ids, low, high in (("headline", spec.get("headlines") or [], MIN_HEADLINES, MAX_HEADLINES),
                                 ("description", spec.get("descriptions") or [], MIN_DESCRIPTIONS, MAX_DESCRIPTIONS)):
        if not low <= len(ids) <= high:
            fails.append(f"{len(ids)} {kind}s (needs {low} to {high})")
        for i in ids:
            a = assets.get(i)
            if a is None:
                fails.append(f"asset {i}: not in the ad library")
                continue
            if a["type"] != kind:
                fails.append(f"asset {i}: is a {a['type']}, listed as a {kind}")
            if a["locale"] != g["locale"]:
                fails.append(f"asset {i}: locale {a['locale']}, campaign {g['campaign']} is {g['locale']}")
            if not a.get("claim_ids"):
                fails.append(f"asset {i}: cites no claim (unmapped text cannot be used in a test)")
            bad = [c for c in a.get("claim_ids", []) if c in failed_claims]
            if bad:
                fails.append(f"asset {i}: claim(s) {', '.join(bad)} failed the last claims_check")
            if i in failed_assets:
                fails.append(f"asset {i}: failed the last claims_check (width or claims)")
            limit = claims_check.LIMITS.get(kind)
            if claims_check.width(a["text"]) > limit:
                fails.append(f"asset {i}: width {claims_check.width(a['text'])} > {limit}")
            texts.append(a["text"])
    if len(set(texts)) != len(texts):
        fails.append("the same text is listed twice")
    url = spec.get("final_url") or ""
    allowed = library_pages(library, g["locale"], g["topic"])
    if url not in allowed:
        fails.append(f"final_url {url or '(none)'} is not a library page for {g['locale']} / {g['topic']}"
                     f" ({', '.join(sorted(allowed)) or 'none'})")
    return fails


def create(client, ga, spec, library, check, tests, today, apply):
    target = spec.get("ad_group") or {}
    g = next((g for g in groups(ga, today).values()
              if g["campaign"] == target.get("campaign") and g["ad_group"] == target.get("name")), None)
    fails = check_create(spec, library, check, g, tests, today)
    if fails:
        for line in fails:
            print(f"FAIL   {line}")
        sys.exit(f"Nothing changed: {len(fails)} rule(s) failed.")

    assets = {a["id"]: a for a in library["assets"]}
    op = client.get_type("AdGroupAdOperation")
    ad = op.create
    ad.ad_group = g["resource"]
    ad.status = client.enums.AdGroupAdStatusEnum.ENABLED
    ad.ad.final_urls.append(spec["final_url"])
    for kind, ids in (("headlines", spec["headlines"]), ("descriptions", spec["descriptions"])):
        for i in ids:
            text = client.get_type("AdTextAsset")
            text.text = assets[i]["text"]
            getattr(ad.ad.responsive_search_ad, kind).append(text)
    label = (f"new RSA   {g['campaign']} / {g['ad_group']}: {len(spec['headlines'])} headlines, "
             f"{len(spec['descriptions'])} descriptions -> {spec['final_url']} (control ad {g['rsas'][0]})")
    try:
        response = client.get_service("AdGroupAdService").mutate_ad_group_ads(
            request={"customer_id": ads_client.customer_id(), "operations": [op], "validate_only": not apply})
    except GoogleAdsException as ex:
        for e in ex.failure.errors:
            print(f"FAIL   {label}  <- {e.message}" + (f" ({e.trigger.string_value})" if e.trigger.string_value else ""))
        sys.exit("Nothing changed.")
    print(f"{'DONE ' if apply else 'VALID'}  {label}")
    print(f"       hypothesis: {spec['hypothesis']}")
    if not apply:
        return
    variant = response.results[0].resource_name.rpartition("~")[2]
    tests.append({"id": f"{today}-{g['locale']}-{g['ad_group'].lower().replace(' ', '-')}", "status": "running",
                  "campaign": g["campaign"], "ad_group": g["ad_group"], "ad_group_id": g["ad_group_id"],
                  "locale": g["locale"], "topic": g["topic"], "hypothesis": spec["hypothesis"], "started": str(today),
                  "control_ad_id": g["rsas"][0], "variant_ad_id": variant, "headlines": spec["headlines"],
                  "descriptions": spec["descriptions"], "final_url": spec["final_url"], "first_impression": None})
    ledger.append([ledger.entry("ad", f"{g['campaign']} / {g['ad_group']} / ad {variant}", "status", None, "ENABLED",
                                f"ad test: {spec['hypothesis']}", g["topic"],
                                f"variant CTR vs control ad {g['rsas'][0]}")])
    print(f"       test {tests[-1]['id']}: variant ad {variant}")
    return tests


def z_score(clicks_a, imp_a, clicks_b, imp_b):
    """Two-proportion z on CTR (b minus a), pooled; 0 when undefined."""
    if not imp_a or not imp_b:
        return 0.0
    p = (clicks_a + clicks_b) / (imp_a + imp_b)
    se = math.sqrt(p * (1 - p) * (1 / imp_a + 1 / imp_b))
    return (clicks_b / imp_b - clicks_a / imp_a) / se if se else 0.0


def decide(arms, days, cfg=None):
    """(winner or None, how). arms = {"control": {...}, "variant": {...}} with impressions, clicks, lead_signals."""
    t = (cfg or config.get()).ad_tests
    MIN_ARM_IMPRESSIONS, MIN_DAYS, MAX_DAYS, Z = t.min_arm_impressions, t.min_days, t.max_days, t.z
    c, v = arms["control"], arms["variant"]
    z = z_score(c["clicks"], c["impressions"], v["clicks"], v["impressions"])
    enough = min(c["impressions"], v["impressions"]) >= MIN_ARM_IMPRESSIONS and days >= MIN_DAYS
    if enough and abs(z) >= Z:
        return ("variant" if z > 0 else "control"), f"CTR z = {z:+.2f} (|z| >= {Z})"
    if days >= MAX_DAYS:
        rate = lambda a, k: a[k] / a["impressions"] if a["impressions"] else 0.0  # noqa: E731
        for key, what in (("lead_signals", "lead signals per impression"), ("clicks", "CTR")):
            if rate(v, key) != rate(c, key):
                return ("variant" if rate(v, key) > rate(c, key) else "control"), \
                    f"day {days}, CTR z = {z:+.2f} undecided; higher {what}"
        return "control", f"day {days}, no difference; the control stays"
    need = [f"day {days} of {MIN_DAYS}" if days < MIN_DAYS else "",
            f"{min(c['impressions'], v['impressions'])} of {MIN_ARM_IMPRESSIONS} impressions in the smaller arm"
            if min(c["impressions"], v["impressions"]) < MIN_ARM_IMPRESSIONS else ""]
    return None, f"CTR z = {z:+.2f}; " + (", ".join(n for n in need if n) or f"|z| < {Z}, runs to day {MAX_DAYS}")


def arm_stats(ga, t, since, until):
    out = {k: {"impressions": 0, "clicks": 0, "lead_signals": 0.0, "ref_leads": 0} for k in ("control", "variant")}
    arm = {t["control_ad_id"]: "control", t["variant_ad_id"]: "variant"}
    where = f"ad_group.id = {t['ad_group_id']} AND segments.date BETWEEN '{since}' AND '{until}'"
    for r in rows(ga, f"SELECT ad_group_ad.ad.id, metrics.impressions, metrics.clicks FROM ad_group_ad WHERE {where}"):
        a = arm.get(str(r.ad_group_ad.ad.id))
        if a:
            out[a]["impressions"] += r.metrics.impressions
            out[a]["clicks"] += r.metrics.clicks
    for r in rows(ga, f"""SELECT ad_group_ad.ad.id, segments.conversion_action_name, metrics.all_conversions
            FROM ad_group_ad WHERE {where} AND segments.conversion_action_name IN {lead_signals_in()}"""):
        a = arm.get(str(r.ad_group_ad.ad.id))
        if a:
            out[a]["lead_signals"] += r.metrics.all_conversions
    for a in out.values():
        a["ctr"] = round(a["clicks"] / a["impressions"], 4) if a["impressions"] else None
        a["lead_signals"] = round(a["lead_signals"], 1)
    return out


def ref_leads(matches, t, since):
    """Ref-matched leads on this group's clicks since `since`: per arm by ad id, plus clicks with no ad id."""
    out = {"control": 0, "variant": 0, "group_only": 0}
    for e in matches:
        if e["status"] != "matched":
            continue
        c = e["clicks"][0]
        if c["click_date"] < since or (c["campaign"], c["ad_group"]) != (t["campaign"], t["ad_group"]):
            continue
        key = {t["control_ad_id"]: "control", t["variant_ad_id"]: "variant"}.get(c.get("ad_id"), "group_only")
        out[key] += 1
    return out


def evaluate(client, ga, tests, check, apply):
    today = ads_client.today()
    until = today - timedelta(days=1)
    failed_claims = set((check or {}).get("failed_claims", [])) if (check or {}).get("mode") == "live" else set()
    library = claims_check.load_library()
    claims_of = {a["id"]: set(a.get("claim_ids", [])) for a in library["assets"]}
    active = [t for t in tests if t in claims_check.live_test_ads(tests)]
    ads = {}
    if active:
        ids = ", ".join(sorted({t["control_ad_id"] for t in active} | {t["variant_ad_id"] for t in active}))
        for r in rows(ga, f"""SELECT ad_group.id, ad_group_ad.ad.id, ad_group_ad.resource_name, ad_group_ad.status,
                ad_group_ad.policy_summary.approval_status, ad_group_ad.policy_summary.policy_topic_entries
                FROM ad_group_ad WHERE ad_group_ad.ad.id IN ({ids})"""):
            ads[str(r.ad_group_ad.ad.id)] = r.ad_group_ad
    enabled = {}
    for r in rows(ga, "SELECT ad_group.id, ad_group_ad.ad.id FROM ad_group_ad WHERE ad_group_ad.status = 'ENABLED'"):
        enabled.setdefault(str(r.ad_group.id), set()).add(str(r.ad_group_ad.ad.id))
    matches = None

    report, ops, changes = [], [], []

    def status_op(ad_id, status, t, reason):
        op = client.get_type("AdGroupAdOperation")
        op.update.resource_name = ads[ad_id].resource_name
        op.update.status = getattr(client.enums.AdGroupAdStatusEnum, status)
        op.update_mask.paths.append("status")
        ops.append(op)
        changes.append(ledger.entry("ad", f"{t['campaign']} / {t['ad_group']} / ad {ad_id}", "status",
                                    "PAUSED" if status == "ENABLED" else "ENABLED", status, f"ad test {t['id']}: {reason}",
                                    t["topic"], "the better ad copy keeps serving"))
        enabled.setdefault(t["ad_group_id"], set())
        (enabled[t["ad_group_id"]].add if status == "ENABLED" else enabled[t["ad_group_id"]].discard)(ad_id)
        print(f"{'DONE ' if apply else 'VALID'}  {status:<7} {t['campaign']} / {t['ad_group']} / ad {ad_id} ({reason})")

    def pause(ad_id, t, reason):
        """Pause unless it is the group's last enabled ad; then enable the paused control first, if there is one."""
        group = enabled.get(t["ad_group_id"], set())
        if group - {ad_id}:
            status_op(ad_id, "PAUSED", t, reason)
            return True
        control = t["control_ad_id"]
        if ad_id != control and control in ads and ads[control].status.name == "PAUSED":
            status_op(control, "ENABLED", t, "restored: the test ad had to stop")
            status_op(ad_id, "PAUSED", t, reason)
            return True
        print(f"HOLD   {t['campaign']} / {t['ad_group']} / ad {ad_id}: last enabled ad of the group, not paused ({reason})")
        return False

    for t in active:
        variant = ads.get(t["variant_ad_id"])
        entry = {"id": t["id"], "campaign": t["campaign"], "ad_group": t["ad_group"], "hypothesis": t["hypothesis"],
                 "status": t["status"]}
        report.append(entry)
        if variant is None or variant.status.name == "REMOVED":
            entry["action"] = "stopped: the variant ad no longer exists"
            t.update(status="stopped", ended=str(today), reason=entry["action"])
            continue
        bad = sorted(set().union(*(claims_of.get(a, set()) for a in t["headlines"] + t["descriptions"])) & failed_claims)
        if bad:
            reason = f"site changed: claim(s) {', '.join(bad)} not on the site any more"
            entry["action"] = f"pause variant: {reason}"
            if pause(t["variant_ad_id"], t, reason):
                t.update(status="failed" if t["status"] == "running" else "retired", ended=str(today), reason=reason)
            continue
        if t["status"] != "running":
            entry["action"] = "winner still serving; claims OK"
            continue
        approval = variant.policy_summary.approval_status.name
        entry["variant_approval"] = approval
        if approval == "DISAPPROVED":
            topics = [p.topic for p in variant.policy_summary.policy_topic_entries]
            reason = f"disapproved by Google ({', '.join(topics) or 'no topic given'})"
            entry["action"] = f"failed: {reason}"
            if pause(t["variant_ad_id"], t, reason):
                t.update(status="failed", ended=str(today), reason=reason)
            continue
        if variant.status.name != "ENABLED" or t["control_ad_id"] not in enabled.get(t["ad_group_id"], set()):
            entry["action"] = "stopped: an arm was paused outside ad_test.py"
            t.update(status="stopped", ended=str(today), reason=entry["action"])
            continue

        first = t.get("first_impression") or next((str(r.segments.date) for r in rows(ga, f"""SELECT segments.date,
            metrics.impressions FROM ad_group_ad WHERE ad_group_ad.ad.id = {t['variant_ad_id']}
            AND ad_group.id = {t['ad_group_id']} AND segments.date BETWEEN '{t['started']}' AND '{until}'
            AND metrics.impressions > 0 ORDER BY segments.date""")), None)
        if first is None:
            entry["action"] = f"waiting: no variant impression yet (review status {approval})"
            continue
        t["first_impression"] = first
        days = (until - date.fromisoformat(first)).days + 1
        arms = arm_stats(ga, t, first, until)
        if matches is None:
            matches = match_ref.match(client)
        refs = ref_leads(matches, t, first)
        for k in ("control", "variant"):
            arms[k]["ref_leads"] = refs[k]
        entry.update(days=days, since=first, arms=arms, ref_leads_group_only=refs["group_only"],
                     ref_note="ref leads per arm by ad id; group_only = clicks saved without an ad id")
        winner, how = decide(arms, days)
        entry["decision"] = how
        if winner is None:
            entry["action"] = "running"
            continue
        loser = "control" if winner == "variant" else "variant"
        entry["action"] = f"conclude: {winner} wins, pause the {loser}"
        if pause(t[f"{loser}_ad_id"], t, f"lost the test ({how})"):
            t.update(status="concluded", ended=str(today), winner=winner, decided_by=how,
                     result={"days": days, "since": first, "arms": arms, "ref_leads_group_only": refs["group_only"]})

    if ops:
        try:
            client.get_service("AdGroupAdService").mutate_ad_group_ads(
                request={"customer_id": ads_client.customer_id(), "operations": ops, "validate_only": not apply})
        except GoogleAdsException as ex:
            sys.exit("FAIL   " + "; ".join(e.message for e in ex.failure.errors) + "\nNothing changed.")
        if apply:
            ledger.append(changes)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    for e in report:
        print(f"TEST   {e['id']} {e['campaign']} / {e['ad_group']}: {e['action']}"
              + (f" ({e['decision']})" if e.get("decision") else ""))
    if not report:
        print("TEST   no running test")
    return tests


def reverse(client, ga, tests, test_id, apply):
    t = next((t for t in tests if t["id"] == test_id), None)
    if not t or t["status"] != "concluded":
        sys.exit(f"FAIL   no concluded test {test_id}\nNothing changed.")
    winner = t[f"{t['winner']}_ad_id"]
    loser = t["control_ad_id"] if t["winner"] == "variant" else t["variant_ad_id"]
    ads = {str(r.ad_group_ad.ad.id): r.ad_group_ad for r in rows(ga, f"""SELECT ad_group_ad.ad.id,
        ad_group_ad.resource_name, ad_group_ad.status FROM ad_group_ad WHERE ad_group_ad.ad.id IN ({winner}, {loser})""")}
    if loser not in ads or ads[loser].status.name == "REMOVED":
        sys.exit(f"FAIL   the losing ad {loser} no longer exists\nNothing changed.")
    ops, changes = [], []
    for ad_id, status in ((loser, "ENABLED"), (winner, "PAUSED")):
        op = client.get_type("AdGroupAdOperation")
        op.update.resource_name = ads[ad_id].resource_name
        op.update.status = getattr(client.enums.AdGroupAdStatusEnum, status)
        op.update_mask.paths.append("status")
        ops.append(op)
        changes.append(ledger.entry("ad", f"{t['campaign']} / {t['ad_group']} / ad {ad_id}", "status",
                                    ads[ad_id].status.name, status, f"owner reversed ad test {t['id']}", t["topic"],
                                    "the ad copy before the test serves again"))
        print(f"{'DONE ' if apply else 'VALID'}  {status:<7} {t['campaign']} / {t['ad_group']} / ad {ad_id}")
    try:
        client.get_service("AdGroupAdService").mutate_ad_group_ads(
            request={"customer_id": ads_client.customer_id(), "operations": ops, "validate_only": not apply})
    except GoogleAdsException as ex:
        sys.exit("FAIL   " + "; ".join(e.message for e in ex.failure.errors) + "\nNothing changed.")
    if not apply:
        return None
    ledger.append(changes)
    t.update(status="reversed", reversed=str(ads_client.today()))
    return tests


def main():
    if not t_cfg().enabled:
        sys.exit("ad_tests.enabled is false in adgrad.yaml: no ad copy tests")
    args = sys.argv[1:]
    opt = lambda name: args[args.index(name) + 1] if name in args else None  # noqa: E731
    state, check_path = Path(opt("--state") or STATE), opt("--check") or claims_check.OUT
    apply = "--apply" in args
    if apply and (opt("--state") or opt("--check")):
        sys.exit("--state and --check are for tests: never with --apply")
    words = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--state", "--check"))]
    if not words or words[0] not in ("plan", "create", "evaluate", "reverse") or \
            (words[0] in ("create", "reverse") and len(words) < 2):
        sys.exit(__doc__)
    tests = read_json(state) or []
    client = ads_client.load()
    ga = client.get_service("GoogleAdsService")  # keep a reference so the stream isn't closed early
    today = ads_client.today()

    if words[0] == "plan":
        out = plan(ga, tests, today)
        running = sum(t["status"] == "running" for t in tests)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        for g in out:
            print(f"{'ELIGIBLE' if g['eligible'] else 'SKIP    '} {g['campaign']} / {g['ad_group']} ({g['topic']}, "
                  f"{g['impressions_14d']} impressions in 14 days)" + (f": {g['why_not']}" if g["why_not"] else
                                                                       f", control ad {g['control_ad_id']}"))
        cap = t_cfg().max_running
        print(f"CAPACITY {cap - running} of {cap} test slots free ({running} running)")
        return
    check = read_json(check_path)
    if words[0] == "create":
        spec = json.loads(Path(words[1]).read_text(encoding="utf-8"))
        result = create(client, ga, spec, claims_check.load_library(), check, tests, today, apply)
    elif words[0] == "reverse":
        result = reverse(client, ga, tests, words[1], apply)
    else:
        result = evaluate(client, ga, tests, check, apply)
    if apply and result is not None:
        state.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"Saved {state}")


if __name__ == "__main__":
    main()
