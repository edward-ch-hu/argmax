"""Check the ad library (ad_tests.library, default docs/ad_library.json) against your website, the source of truth
for every ad claim.

- every claim's quote must still appear on its page (website.base_url + page; tags stripped, whitespace,
  full-width spaces and full-width/half-width forms normalised, spaces ignored)
- every asset fits Google's width (headline 30, description 90; CJK full-width characters count 2), has a locale
  from website.locales, and cites known claims (library assets need at least one; imported live text may have none)
- every final URL of a live test ad in reports/ad_tests.json (running, or a concluded winner) returns 200

Prints OK, or one FAIL line per problem (with the assets and live test ads that use a failed claim), and
NOTIFY SITE_UNREACHABLE when the site cannot be fetched at all (the cloud environment may block it): then claims
are not judged and the run does not fail. A 404 or 410 is a FAIL (the page is gone), not unreachable.
Writes the result to reports/claims_check.json; ad_test.py create needs a live result under
ad_tests.claims_max_age_days old, and ad_test.py evaluate pauses test ads whose claims failed.

Usage: uv run scripts/claims_check.py                         (live site)
       uv run scripts/claims_check.py --local <build dir>     (a static build: <dir>/<page>/index.html or
                                                               <dir>/<page>.html; writes claims_check_local.json)
       uv run scripts/claims_check.py --library <json>        (another library file, e.g. a draft)
"""
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import ads_client
import config

TESTS = Path("reports/ad_tests.json")
OUT, OUT_LOCAL = Path("reports/claims_check.json"), Path("reports/claims_check_local.json")
LIMITS = {"headline": 30, "description": 90}
GONE = (404, 410)


def site():
    return config.get().website.base_url or ""


def library_path():
    return Path(config.get().ad_tests.library)


def width(text):
    """Google's ad text width: East Asian wide and full-width characters count 2, everything else 1."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def norm(text):
    """For matching: NFKC (full-width forms and spaces to half-width), then no whitespace at all."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def page_text(raw):
    t = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", raw)
    t = re.sub(r"(?s)<!--.*?-->|<[^>]+>", " ", t)
    return norm(html.unescape(t))


def load_library(path=None):
    path = Path(path or library_path())
    if not path.exists():
        sys.exit(f"No ad library at {path}. Copy docs/ad_library.example.json there and replace it with exact quotes "
                 "from your own site (in a session with the owner). Ad tests stay off until then.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_tests(path=TESTS):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else []


def live_test_ads(tests):
    """Test ads that may be serving: variants of running tests and of concluded tests the variant won."""
    return [t for t in tests if t.get("status") == "running"
            or (t.get("status") == "concluded" and t.get("winner") == "variant")]


def fetch(page, local):
    """(status, text, error). status: 200, an HTTP error code, or None when the site cannot be reached after
    3 tries (error says why). 5xx and 403/429 (a proxy or rate limit) are retried too."""
    if local:
        base = Path(local) / page.strip("/")
        for path in (base / "index.html", base.with_suffix(".html")):
            if path.is_file():
                return 200, page_text(path.read_text(encoding="utf-8")), None
        return 404, "", None
    request = urllib.request.Request(site() + page, headers={"User-Agent": config.get().website.user_agent})
    status, error = None, None
    for attempt in range(3):
        if attempt:
            time.sleep(3 * attempt)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, page_text(response.read().decode("utf-8", "replace")), None
        except urllib.error.HTTPError as e:
            status, error = e.code, f"HTTP {e.code}"
            if e.code in GONE:
                return status, "", error
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            status, error = None, repr(getattr(e, "reason", e))
    return status, "", error


def check_assets(library, locales=None):
    locales = config.get().website.locales if locales is None else locales
    claims = {c["id"] for c in library["claims"]}
    fails = []
    for a in library["assets"]:
        w, limit = width(a["text"]), LIMITS.get(a["type"])
        if limit is None:
            fails.append((a["id"], f"FAIL asset {a['id']}: type must be headline or description"))
        elif w > limit:
            fails.append((a["id"], f"FAIL asset {a['id']}: width {w} > {limit} ({a['text']})"))
        if a["locale"] not in locales:
            fails.append((a["id"], f"FAIL asset {a['id']}: locale must be one of {', '.join(locales)}"))
        unknown = [c for c in a.get("claim_ids", []) if c not in claims]
        if unknown:
            fails.append((a["id"], f"FAIL asset {a['id']}: unknown claim(s) {', '.join(unknown)}"))
        if a.get("source") != "live" and not a.get("claim_ids"):
            fails.append((a["id"], f"FAIL asset {a['id']}: a library asset needs at least one claim_id"))
    return fails


def run(library, tests, local=None):
    base = site()
    pages, lines, unreachable = {}, [], []
    for page in sorted({c["page"] for c in library["claims"]} | {
            t["final_url"].removeprefix(base) for t in live_test_ads(tests)}):
        status, text, error = fetch(page, local)
        pages[page] = {"status": status, "text": text, "error": error}
        if status is None or (status != 200 and status not in GONE):
            unreachable.append(f"{page} ({error})")
    asset_fails = check_assets(library)
    result = {"checked_at": ads_client.now().isoformat(timespec="seconds"),
              "date": str(ads_client.today()), "mode": "local" if local else "live", "site": base,
              "claims": len(library["claims"]), "assets": len(library["assets"]), "pages": {},
              "failed_claims": [], "failed_assets": sorted({a for a, _ in asset_fails}), "failed_urls": []}
    if unreachable:
        result["status"] = "unreachable"
        lines.append(f"NOTIFY SITE_UNREACHABLE {base}: {', '.join(unreachable[:3])}"
                     f"{f' and {len(unreachable) - 3} more' if len(unreachable) > 3 else ''}; claims not checked")
        lines += [line for _, line in asset_fails]
        result["pages"] = {p: v["error"] or v["status"] for p, v in pages.items()}
        result["lines"] = lines
        return result

    used_by = {}
    for a in library["assets"]:
        for c in a.get("claim_ids", []):
            used_by.setdefault(c, []).append(a["id"])
    for c in library["claims"]:
        p = pages[c["page"]]
        if p["status"] != 200 or norm(c["quote"]) not in p["text"]:
            result["failed_claims"].append(c["id"])
            assets = used_by.get(c["id"], [])
            ads = [f"{t['id']} (ad {t['variant_ad_id']})" for t in live_test_ads(tests)
                   if set(assets) & set(t.get("headlines", []) + t.get("descriptions", []))]
            where = "page returned " + str(p["status"]) if p["status"] != 200 else "quote not found"
            lines.append(f"FAIL claim {c['id']}: {where} on {c['page']}"
                         f" (assets: {', '.join(assets) or 'none'}; live test ads: {', '.join(ads) or 'none'})")
    for t in live_test_ads(tests):
        status = pages[t["final_url"].removeprefix(base)]["status"]
        if status != 200:
            result["failed_urls"].append(t["final_url"])
            lines.append(f"FAIL url {t['final_url']}: returned {status} (test {t['id']})")
    lines += [line for _, line in asset_fails]
    result["pages"] = {p: v["status"] for p, v in pages.items()}
    result["status"] = "fail" if lines else "ok"
    if not lines:
        lines.append(f"OK claims_check ({result['mode']}): {len(library['claims'])} claims on {len(pages)} pages, "
                     f"{len(library['assets'])} assets, {len(live_test_ads(tests))} live test ad(s)")
    result["lines"] = lines
    return result


def last(path=OUT):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None


def main():
    if not site():
        sys.exit("website.base_url is not set in adgrad.yaml: nothing to check against")
    args = sys.argv[1:]
    opt = lambda name: args[args.index(name) + 1] if name in args else None  # noqa: E731
    local, custom = opt("--local"), opt("--library")
    result = run(load_library(custom), load_tests(), local)
    out = OUT_LOCAL if local else OUT
    if not custom:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "lines"}, ensure_ascii=False, indent=1))
    for line in result["lines"]:
        print(line)
    if result["status"] == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
