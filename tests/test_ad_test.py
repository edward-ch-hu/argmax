from datetime import date, datetime, timedelta

import ad_test
import claims_check
import pytest
from conftest import ROOT

ARM = {"impressions": 2000, "clicks": 100, "lead_signals": 2.0}


def arms(control=None, variant=None):
    return {"control": {**ARM, **(control or {})}, "variant": {**ARM, **(variant or {})}}


def test_z_score():
    assert ad_test.z_score(100, 2000, 100, 2000) == 0
    assert ad_test.z_score(100, 2000, 150, 2000) == pytest.approx(3.27, abs=0.01)
    assert ad_test.z_score(0, 0, 1, 10) == 0


def test_decides_on_ctr_after_min_days():
    assert ad_test.decide(arms(variant={"clicks": 150}), 30)[0] == "variant"
    assert ad_test.decide(arms(control={"clicks": 150}), 30)[0] == "control"
    assert ad_test.decide(arms(variant={"clicks": 150}), 20)[0] is None  # too early
    assert ad_test.decide(arms(variant={"clicks": 150, "impressions": 900}), 30)[0] is None  # too few impressions


def test_undecided_falls_back_to_lead_signals_then_ctr():
    winner, how = ad_test.decide(arms(variant={"clicks": 105, "lead_signals": 5.0}), 56)
    assert winner == "variant" and "lead signals" in how
    winner, how = ad_test.decide(arms(variant={"clicks": 104}), 56)
    assert winner == "variant" and "CTR" in how
    assert ad_test.decide(arms(), 56)[0] == "control"


def test_thresholds_come_from_config(use):
    use(**{"ad_tests.min_days": 7})
    assert ad_test.decide(arms(variant={"clicks": 150}), 8)[0] == "variant"


def test_locale_of(use):
    assert ad_test.locale_of("US - Search") == "en"
    assert ad_test.locale_of("Brand") == "en"  # default_locale
    use(**{"website.locales": ["en", "de"], "ad_tests.campaign_locales": {"DE": "de", "DE - Brand": "en"}})
    assert ad_test.locale_of("DE - Search") == "de"
    assert ad_test.locale_of("DE - Brand") == "en"  # the longest prefix wins


def test_check_create_rules():
    library = claims_check.load_library(ROOT / "docs/ad_library.example.json")
    now = datetime(2026, 1, 7, 9, 0).astimezone()
    check = {"mode": "live", "status": "ok", "checked_at": (now - timedelta(days=1)).isoformat(),
             "failed_claims": [], "failed_assets": []}
    group = {"campaign": "US - Search", "ad_group": "Analytics", "ad_group_id": "1", "topic": "analytics",
             "locale": "en", "impressions_14d": 500, "rsas": ["11"]}
    spec = {"hypothesis": "trial angle beats realtime angle",
            "headlines": ["en-an-h01", "en-an-h02", "en-an-h03", "en-an-h04"], "descriptions": ["en-an-d01"],
            "final_url": "https://www.example.com/en/analytics/"}
    fails = ad_test.check_create(spec, library, check, group, [], date(2026, 1, 7), now)
    assert any("4 headlines" in f for f in fails)
    assert any("1 descriptions" in f for f in fails)
    assert any("en-an-h04: cites no claim" in f for f in fails)
    assert not any("final_url" in f for f in fails)

    stale = dict(check, checked_at=(now - timedelta(days=9)).isoformat(), status="unreachable")
    bad_url = dict(spec, final_url="https://www.example.com/en/dashboards/")
    fails = ad_test.check_create(bad_url, library, stale, group, [], date(2026, 1, 7), now)
    assert any("days old" in f for f in fails)
    assert any("SITE_UNREACHABLE" in f for f in fails)
    assert any("final_url" in f for f in fails)

    running = [{"status": "running", "ad_group_id": str(i)} for i in range(3)]
    fails = ad_test.check_create(spec, library, check, dict(group, impressions_14d=10), running, date(2026, 1, 7), now)
    assert any("3 tests are already running" in f for f in fails)
    assert any("not eligible" in f for f in fails)
