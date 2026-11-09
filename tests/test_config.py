import copy

import config
import pytest
from conftest import EXAMPLE, ROOT, make


def test_example_loads_and_normalises():
    cfg = make()
    assert cfg.account.customer_id == "1234567890"
    assert cfg.account.login_customer_id == "1112223333"
    assert str(cfg.tz) == "America/New_York"
    assert cfg.limits.daily_budget_cap == 150
    assert cfg.winning_topics == ["analytics"]
    assert cfg.ad_tests.default_locale == "en"
    assert cfg.crm.columns["lead_date"] == "Lead date"


def test_defaults_fill_missing_sections():
    data = {k: copy.deepcopy(EXAMPLE[k]) for k in ("account", "limits", "topics", "conversions")}
    data["ad_tests"] = {"enabled": False}
    cfg = config.load_dict(data)
    assert cfg.stepping.step == 0.10
    assert cfg.negatives.max_per_day == 10
    assert cfg.crm.source == "none"
    assert cfg.tracker.backend == "files"


@pytest.mark.parametrize("overrides, message", [
    ({"account.customer_id": "12345"}, "account.customer_id"),
    ({"account.timezone": "Mars/Olympus"}, "account.timezone"),
    ({"account.timezone": "+08:00"}, "account.timezone"),
    ({"account.currency": "dollars"}, "account.currency"),
    ({"limits.daily_budget_cap": 0}, "limits.daily_budget_cap"),
    ({"limits.weekly_bid_change": 1.5}, "limits.weekly_bid_change"),
    ({"limits.bid_floor": 9.0}, "limits.bid_floor: must be under"),
    ({"winning_topics": ["nope"]}, "winning_topics: 'nope' is not a topic"),
    ({"ad_group_topics": {"X": "nope"}}, "ad_group_topics.X"),
    ({"topics": {"Bad Name": {"substrings": ["x"]}}}, "lower_snake_case"),
    ({"topics": {"other": {"substrings": ["x"]}}}, "lower_snake_case"),
    ({"conversions.noise_signals": ["Signup"]}, "both a lead signal and a noise signal"),
    ({"conversions.lead_signals": []}, "conversions.lead_signals"),
    ({"crm.source": "excel"}, "crm.source"),
    ({"crm.source": "csv", "crm.csv_path": None}, "crm.csv_path"),
    ({"crm.source": "google_sheets"}, "crm.sheet_id"),
    ({"crm.source": "csv", "crm.statuses.won": []}, "crm.statuses.won"),
    ({"crm.source": "csv", "crm.statuses.trial": ["Won"]}, "listed under both"),
    ({"ref_codes.enabled": True}, "ref_codes.enabled: needs a CRM"),
    ({"ref_codes.prefix": "ag"}, "ref_codes.prefix"),
    ({"tracker.backend": "jira"}, "tracker.backend"),
    ({"tracker.backend": "clickup"}, "tracker.clickup.weekly_list_id"),
    ({"stepping.rank_lost_band": [0.6, 0.2]}, "stepping.rank_lost_band"),
    ({"website.base_url": "https://example.com/en/"}, "website.base_url"),
    ({"website.base_url": None}, "ad_tests.enabled: needs website.base_url"),
])
def test_invalid_fields_fail_clearly(overrides, message):
    with pytest.raises(config.ConfigError) as e:
        make(**overrides)
    assert message in str(e.value)


def test_all_problems_reported_at_once():
    with pytest.raises(config.ConfigError) as e:
        make(**{"account.customer_id": "x", "account.currency": "x"})
    assert "customer_id" in str(e.value) and "currency" in str(e.value)


def test_missing_file_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(config.ConfigError) as e:
        config.load(env={})
    assert "init.py" in str(e.value)


def test_get_exits_with_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ARGMAX_CONFIG", raising=False)
    monkeypatch.delenv("ARGMAX_CONFIG_YAML", raising=False)
    config.activate(None)
    with pytest.raises(SystemExit) as e:
        config.get()
    assert "argmax config problem" in str(e.value)


def test_env_sources_and_overrides(tmp_path):
    text = (ROOT / "argmax.example.yaml").read_text()
    cfg = config.load(env={"ARGMAX_CONFIG_YAML": text, "ARGMAX_CUSTOMER_ID": "999-888-7777"})
    assert cfg.account.customer_id == "9998887777"
    path = tmp_path / "c.yaml"
    path.write_text(text)
    assert config.load(env={"ARGMAX_CONFIG": str(path)}).account.name == "Acme Analytics"


def test_invalid_yaml(tmp_path):
    with pytest.raises(config.ConfigError) as e:
        config.load(env={"ARGMAX_CONFIG_YAML": "a: [unclosed"})
    assert "not valid YAML" in str(e.value)
