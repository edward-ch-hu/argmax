from datetime import datetime, timezone

import config
import crm
import doctor
import init
import onboarding
import pytest
import yaml
from conftest import EXAMPLE, ROOT, make

ANSWERS = {"account": {"customer_id": "222-333-4444", "currency": "EUR", "timezone": "Europe/Berlin", "name": "Test Co"},
           "limits": {"daily_budget_cap": 80}, "topics": ["boots", "Rain Jackets"], "winning_topics": ["boots"],
           "conversions": {"lead_signals": ["Purchase"]}}


def test_init_build_clears_the_fictional_example():
    c = init.build(ANSWERS, EXAMPLE)
    cfg = init.validate(c)
    assert cfg.account.customer_id == "2223334444" and cfg.account.login_customer_id is None
    assert set(cfg.topics) == {"boots", "rain_jackets"} and cfg.topics["rain_jackets"]["substrings"] == ["rain jackets"]
    assert cfg.ad_group_topics == {} and cfg.conversions.noise_signals == []
    assert cfg.ad_tests.enabled is False and cfg.website.base_url is None  # no site given: ad tests off
    assert cfg.crm.source == "none" and cfg.tracker.backend == "files"
    assert cfg.limits.bid_ceiling == EXAMPLE["limits"]["bid_ceiling"]  # untouched limits keep the example's values
    assert "Acme" not in yaml.safe_dump(c)


def test_init_build_with_crm_and_site():
    answers = dict(ANSWERS, website={"base_url": "https://shop.example.org"},
                   crm={"source": "csv", "csv_path": "orders.csv", "columns": {"lead_date": "Date", "status": "State"},
                        "statuses": {"won": ["Paid"]}}, tracker={"backend": "github-issues"})
    cfg = init.validate(init.build(answers, EXAMPLE))
    assert cfg.ad_tests.enabled is True and cfg.crm.statuses["won"] == ["Paid"] and cfg.crm.statuses["trial"] == []
    assert cfg.crm.columns["name"] is None


def test_init_build_invalid_answers_fail():
    with pytest.raises(config.ConfigError):
        init.validate(init.build(dict(ANSWERS, winning_topics=["nope"]), EXAMPLE))


def test_onboarding_state(tmp_path):
    path = tmp_path / "o.json"
    state = onboarding.load(path)
    assert onboarding.next_step(state) == "prerequisites" and not onboarding.complete(state)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state = onboarding.set_step(state, "prerequisites", "done", now=now)
    state = onboarding.set_step(state, "google_ads_api", "pending", "waiting on Basic access", now=now)
    onboarding.save(state, path)
    again = onboarding.load(path)
    assert onboarding.next_step(again) == "repo"
    for step in onboarding.STEPS:
        if again["steps"][step]["status"] == "todo":
            again = onboarding.set_step(again, step, "skipped")
    assert onboarding.next_step(again) == "google_ads_api"  # pending still needs doing
    again = onboarding.set_step(again, "google_ads_api", "done")
    assert onboarding.complete(again)
    with pytest.raises(ValueError):
        onboarding.set_step(again, "nope", "done")
    with pytest.raises(ValueError):
        onboarding.set_step(again, "repo", "finished")
    with pytest.raises(ValueError):
        onboarding.set_step(again, "repo", "done", "refresh_token 1//0gABCDEFGHIJKLMNOPQRSTUVWXYZ")


def test_doctor_credentials():
    full = {k: "x" for k in doctor.CREDENTIAL_KEYS}
    assert doctor.credentials_status(full, {})[0] == "OK"
    assert doctor.credentials_status(dict(full, refresh_token="INSERT_REFRESH_TOKEN"), {})[0] == "PENDING"
    assert doctor.credentials_status(dict(full, developer_token=""), {})[0] == "FAIL"
    assert doctor.credentials_status(None, {})[0] == "PENDING"
    env = {f"GOOGLE_ADS_{k.upper()}": "x" for k in doctor.CREDENTIAL_KEYS}
    status, message = doctor.credentials_status(None, env)
    assert status == "OK" and "x" not in message.replace("env vars", "")  # never echoes a value


def test_doctor_api_errors():
    assert doctor.api_error_status("DEVELOPER_TOKEN_NOT_APPROVED The developer token is not approved")[0] == "PENDING"
    assert doctor.api_error_status("USER_PERMISSION_DENIED")[0] == "FAIL"


def test_doctor_crm_and_tracker():
    cfg = make(**{"crm.source": "csv", "crm.csv_path": str(ROOT / "docs/crm.example.csv")})
    values = crm.raw_values(cfg)
    assert doctor.crm_status(values, cfg)[0] == "OK"
    values[2][3] = "On hold"
    status, message = doctor.crm_status(values, cfg)
    assert status == "PENDING" and "On hold" in message and "Jane" not in message
    bad = make(**{"crm.source": "csv", "crm.csv_path": "x.csv", "crm.columns.deal_value": "Revenue"})
    assert doctor.crm_status(values, bad)[0] == "FAIL"
    assert doctor.crm_status([], make())[0] == "OK"  # crm.source none
    assert doctor.tracker_status(make(), which=lambda _: None)[0] == "FAIL"  # github-issues without gh
    assert doctor.tracker_status(make(**{"tracker.backend": "files"}))[0] == "OK"


def test_crm_inspect_only_headers_and_statuses():
    values = [["Name", "Email", "Status"], ["Jane", "j@example.com", "Won"], ["Sam", "s@example.com", "Won"],
              ["Kim", "k@example.com", " Trial "], ["Lee", "l@example.com"]]
    out = crm.inspect(values, "status")
    assert out == {"headers": ["Name", "Email", "Status"], "rows": 4, "statuses": {"Won": 2, "Trial": 1}}
    assert "error" in crm.inspect(values, "Stage")
    assert crm.inspect([], "Status")["headers"] == []
