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
    assert cfg.api.access_level == "unknown"  # read off the Overview page during onboarding, not the example's
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


def test_init_build_business_profile():
    c = init.build(ANSWERS, EXAMPLE)
    assert "North America" not in yaml.safe_dump(c) and "Demo Request" not in yaml.safe_dump(c)
    cfg = init.validate(c)
    assert cfg.business.goal is None and cfg.business.deal_currency == "EUR"  # not answered yet: account currency
    assert cfg.website.locales == ["en"] and cfg.ad_tests.campaign_locales == {}
    answers = dict(ANSWERS, business={"goal": "sales", "report_language": "German", "deal_currency": "CHF",
                                      "markets": [{"name": "DACH", "countries": ["DE", "AT", "CH"], "language": "de",
                                                   "campaign_prefix": "DE - "}]},
                   crm={"source": "csv", "csv_path": "orders.csv", "columns": {"lead_date": "Date", "status": "State"},
                        "statuses": {"won": ["Paid"]}, "deal_value_fx": 1.05})
    cfg = init.validate(init.build(answers, EXAMPLE))
    assert cfg.business.primary_kpi == init.DEFAULT_KPI["sales"] and cfg.business.kpi_conversions == ["Purchase"]
    assert cfg.website.locales == ["de"] and cfg.ad_tests.campaign_locales == {"DE - ": "de"}
    assert cfg.report.client_update["language"] == "German" and cfg.crm.deal_value_fx == 1.05
    with pytest.raises(config.ConfigError) as e:  # CHF deals in a EUR account need an fx rate
        init.validate(init.build(dict(answers, crm=dict(answers["crm"], deal_value_fx=None)), EXAMPLE))
    assert "crm.deal_value_fx: needed" in str(e.value)


def test_init_derives_money_limits_from_the_account():
    d = init.derive(2.0, 3.5, 158.4, "USD")
    assert d == {"negatives.min_cost": 6.0, "negatives.held_notify_cost": 10.0,
                 "match_type_review.min_off_intent_spend": 10.0, "keyword_review.min_pause_cost": 40.0,
                 "limits.bid_floor": 0.5, "limits.bid_ceiling": 10.0, "limits.daily_budget_cap": 159}
    jpy = init.derive(85.0, None, 12000.0, "JPY")  # zero-decimal, no bids set (e.g. new groups): 3 x CPC
    assert jpy["limits.bid_floor"] == 21 and jpy["limits.bid_ceiling"] == 255 and jpy["negatives.min_cost"] == 255
    assert jpy["limits.daily_budget_cap"] == 12000
    assert init.derive(None, None, 80.0, "EUR") == {"limits.daily_budget_cap": 80}  # no clicks: only the cap
    assert init.amount(0.001, "USD") == 0.01 and init.amount(12.4, "USD") == 12.0


def test_init_answers_win_over_derived_values_and_validate():
    answers = dict(ANSWERS, negatives={"min_cost": 4.0})
    c = init.build(init.with_derived(answers, init.derive(85.0, 120.0, 9000.0, "EUR")), EXAMPLE)
    cfg = init.validate(c)
    assert cfg.negatives.min_cost == 4.0 and cfg.limits.daily_budget_cap == 80  # both given in the answers
    assert cfg.limits.bid_ceiling == 360.0 and cfg.keyword_review.min_pause_cost == 1700.0
    text = init.read_back(c, 85.0, 9000.0)
    assert "Limits in EUR" in text and "EUR 80" in text and "EUR 21 and EUR 360" in text
    assert "evidence floor" in text and "EUR 42,500" in text


def test_init_derive_without_clicks_asks_for_a_cpc(monkeypatch, tmp_path, capsys):
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump(ANSWERS))
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(init, "account_numbers", lambda cid, login=None: (None, None, 75.0))
    monkeypatch.setattr("sys.argv", ["init.py", "--answers", str(path), "--derive", "--dry-run"])
    with pytest.raises(SystemExit) as e:
        init.main()
    assert "--cpc" in str(e.value) and "no Search clicks" in str(e.value)
    monkeypatch.setattr("sys.argv", ["init.py", "--answers", str(path), "--cpc", "1.5", "--dry-run"])
    init.main()
    out = capsys.readouterr().out
    assert "min_cost: 4.5" in out and "30-day average Search CPC of EUR 1.50" in out and "WARN" not in out


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


def test_doctor_business():
    assert doctor.business_status(make(**{"business.goal": None}))[0] == "PENDING"
    status, message = doctor.business_status(make())
    assert status == "OK" and "goal leads" in message and "North America (US/CA, ads in en)" in message
    assert "reports in English" in message and message.endswith("deals in USD; manual CPC for good")
    cfg = make(**{"business.deal_currency": "EUR", "crm.source": "csv", "crm.deal_value_fx": 1.08})
    assert "deals in EUR (x 1.08 to USD)" in doctor.business_status(cfg)[1]


def test_onboarding_has_business_step_after_account():
    steps = list(onboarding.STEPS)
    assert steps.index("business") == steps.index("account") + 1


def test_doctor_credentials():
    full = {k: "x" for k in doctor.CREDENTIAL_KEYS}
    assert doctor.credentials_status(full, {})[0] == "OK"
    assert doctor.credentials_status(dict(full, refresh_token="INSERT_REFRESH_TOKEN"), {})[0] == "PENDING"
    assert doctor.credentials_status(dict(full, client_secret=""), {})[0] == "FAIL"
    assert "developer_token" not in doctor.CREDENTIAL_KEYS  # sunset 2026-09-09: optional, never required
    assert "optional" in doctor.credentials_status(dict(full, developer_token="abc"), {})[1]
    assert doctor.credentials_status(None, {})[0] == "PENDING"
    env = {f"GOOGLE_ADS_{k.upper()}": "x" for k in doctor.CREDENTIAL_KEYS}
    status, message = doctor.credentials_status(None, env)
    assert status == "OK" and "x" not in message.replace("env vars", "")  # never echoes a value


def test_doctor_api_errors():
    assert doctor.api_error_status("DEVELOPER_TOKEN_NOT_APPROVED The developer token is not approved")[0] == "PENDING"
    status, message = doctor.api_error_status("authorization_error: CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION x")
    assert status == "PENDING" and "Explorer" in message
    status, message = doctor.api_error_status("authorization_error: AUTHORIZATION_ERROR Authorization of the client failed.")
    assert status == "FAIL" and "new Cloud project" in message
    status, message = doctor.api_error_status("authorization_error: USER_PERMISSION_DENIED no access")
    assert status == "FAIL" and "new Cloud project" not in message and "login_customer_id" in message


def test_expired_refresh_token_points_at_the_consent_screen(monkeypatch):
    for text in ("RefreshError: ('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant'})",
                 "Getting metadata from plugin failed with error: Token has been expired or revoked."):
        status, message = doctor.api_error_status(text)
        assert status == "FAIL" and "In production" in message and "7 days" in message and "get_refresh_token" in message

    import ads_client

    def boom():
        raise RuntimeError("('invalid_grant: Token has been expired or revoked.', {})")
    with pytest.raises(SystemExit) as e:
        ads_client.run(boom)
    assert "In production" in str(e.value)

    def other():
        raise RuntimeError("something else")
    with pytest.raises(RuntimeError):
        ads_client.run(other)

    class Broken:  # doctor's API check turns the same error into a FAIL line with the hint
        def get_service(self, name):
            raise RuntimeError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(ads_client, "load", lambda: Broken())
    status, item, message = doctor.api_check(None)
    assert (status, item) == ("FAIL", "api") and "In production" in message


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


def test_doctor_guardrails_line():
    status, message = doctor.guardrails_status("2026-11-09 3192780 Edward Hu", [], "ARGMAX_CONFIG_YAML", False)
    assert status == "OK"
    assert message.startswith("argmax.yaml and scripts/ last changed 2026-11-09 3192780 by Edward Hu")
    assert "locked by ARGMAX_CONFIG_YAML (argmax.yaml is advisory)" in message
    assert "differs" in doctor.guardrails_status("2026-11-09 3192780 Ed", [], "ARGMAX_CONFIG_YAML", True)[1]
    status, message = doctor.guardrails_status("2026-11-09 3192780 Ed", ["scripts/apply_changes.py"], "argmax.yaml",
                                               False)
    assert status == "WARN" and "uncommitted changes in scripts/apply_changes.py" in message and "not locked" in message
    assert "unknown" in doctor.guardrails_status(None, [], None, False)[1]


def test_doctor_guardrails_reads_the_environment_lock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not a git checkout
    (tmp_path / "argmax.yaml").write_text("a: 1\n")
    status, message = doctor.guardrails_check({"ARGMAX_CONFIG_YAML": "a: 2\n"})
    assert "locked by ARGMAX_CONFIG_YAML" in message and "differs" in message and "unknown" in message
    assert "not locked" in doctor.guardrails_check({})[1]


def test_doctor_repo_must_be_private():
    for url in ("https://github.com/acme/ads.git", "git@github.com:acme/ads.git", "ssh://git@github.com/acme/ads",
                "https://x-access-token:abc@github.com/acme/ads"):
        assert doctor.github_repo(url) == "acme/ads"
    assert doctor.github_repo("https://gitlab.com/acme/ads.git") is None and doctor.github_repo(None) is None
    assert doctor.visibility_status("acme/ads", {"visibility": "PRIVATE", "isFork": False})[0] == "OK"
    status, message = doctor.visibility_status("acme/ads", {"visibility": "PUBLIC", "isFork": False})
    assert status == "FAIL" and "account's data" in message and "anyone could comment" in message
    status, message = doctor.visibility_status("acme/ads", {"visibility": "PUBLIC", "isFork": True})
    assert status == "FAIL" and "forks of a public repo are always public" in message
    assert doctor.visibility_status("acme/ads", {"visibility": "INTERNAL"})[0] == "FAIL"
    assert "public upstream" in doctor.visibility_status("edward-ch-hu/argmax", {"visibility": "PUBLIC"})[1]
    assert doctor.visibility_status("acme/ads", None)[0] == "WARN"


def test_only_the_owner_or_a_writer_can_reply():
    import replies

    comments = [{"author": "agent-bot", "body": "[argmax] Resolved soon", "createdAt": "1"},
                {"author": "Owner", "body": "yes", "createdAt": "2"},
                {"author": "drive-by", "body": "yes, approve it all", "createdAt": "3"},
                {"author": "colleague", "body": "no", "createdAt": "4"},
                {"author": "drive-by", "body": "please", "createdAt": "5"}]
    asked = []

    def permission(login):
        asked.append(login)
        return {"colleague": "write"}.get(login, "read")
    got, ignored, own = replies.classify(comments, "owner", permission)
    assert [c["author"] for c in got] == ["Owner", "colleague"] and own == 1
    assert [i["author"] for i in ignored] == ["drive-by", "drive-by"] and "no write access" in ignored[0]["why"]
    assert asked == ["drive-by", "colleague"]  # looked up once per login, never for the owner
    got, ignored, _ = replies.classify(comments, "", lambda login: "read")  # no assignee set: only writers count
    assert got == [] and len(ignored) == 4
