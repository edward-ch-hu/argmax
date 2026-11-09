"""Bidding end state: a choice in STRATEGY.md and business.bidding_end_state, checked to agree. No network."""
from pathlib import Path

import config
import doctor
import pytest
import strategy_check
from conftest import ROOT, make

TEMPLATE = (ROOT / "strategies" / "b2b-lead-gen.md").read_text(encoding="utf-8")
MANUAL = strategy_check.pick_bidding(TEMPLATE, "manual_cpc")
SMART = strategy_check.pick_bidding(TEMPLATE, "smart_bidding")


def test_config_values():
    assert make().business.bidding_end_state == "manual_cpc"
    assert make(**{"business.bidding_end_state": None}).business.bidding_end_state is None
    with pytest.raises(config.ConfigError, match="bidding_end_state"):
        make(**{"business.bidding_end_state": "target_cpa"})


def test_manual_end_state_keeps_the_guard_on_manual_cpc():
    with pytest.raises(config.ConfigError, match="guard.expected_bidding: must be MANUAL_CPC"):
        make(**{"guard.expected_bidding": "TARGET_CPA"})
    with pytest.raises(config.ConfigError, match="guard.expected_bidding"):
        make(**{"guard.expected_bidding": None})  # the check cannot be switched off either
    cfg = make(**{"business.bidding_end_state": "smart_bidding", "guard.expected_bidding": "TARGET_CPA"})
    assert cfg.guard.expected_bidding == "TARGET_CPA"


def test_every_template_offers_both_choices_until_one_is_picked():
    for path in [ROOT / "STRATEGY.example.md", *sorted((ROOT / "strategies").glob("*.md"))]:
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        assert strategy_check.bidding_end_state(text)[0] == "both", path.name
        assert strategy_check.bidding_end_state(strategy_check.pick_bidding(text, "manual_cpc"))[0] == "manual_cpc"
        assert strategy_check.check(text) == ([], []), path.name


def test_bidding_fit():
    assert strategy_check.bidding_fit(MANUAL, "manual_cpc")[0] == "OK"
    assert strategy_check.bidding_fit(SMART, "smart_bidding")[0] == "OK"
    status, message = strategy_check.bidding_fit(MANUAL, "smart_bidding")
    assert status == "FAIL" and "agree" in message
    assert strategy_check.bidding_fit(TEMPLATE, "manual_cpc")[0] == "WARN"  # both choices still listed
    assert strategy_check.bidding_fit(MANUAL, None)[0] == "WARN"  # config not set yet
    assert strategy_check.bidding_fit("# Strategy\n", "manual_cpc")[0] == "WARN"  # no line (an older copy)
    assert strategy_check.bidding_fit("Bidding end state: whatever\n", "manual_cpc")[0] == "FAIL"
    assert strategy_check.bidding_end_state("Bidding end state: manual_cpc")[0] == "manual_cpc"


def test_doctor_shows_the_bidding_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "argmax.yaml").write_text((ROOT / "argmax.example.yaml").read_text(encoding="utf-8"))
    (tmp_path / "STRATEGY.md").write_text(SMART.replace("topic_a", "analytics").replace("topic_b", "dashboards"))
    results = {item: (status, message) for status, item, message in doctor.check(offline=True, env={})}
    assert results["bidding"][0] == "FAIL"  # the example config says manual_cpc
    Path("STRATEGY.md").write_text(MANUAL)
    results = {item: (status, message) for status, item, message in doctor.check(offline=True, env={})}
    assert results["bidding"][0] == "OK"


def test_init_copies_a_template_with_the_choice_made(tmp_path, monkeypatch):
    import init

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(init, "STRATEGIES", ROOT / "strategies")
    init.copy_strategy("b2b-lead-gen", "manual_cpc")
    assert strategy_check.bidding_end_state(Path("STRATEGY.md").read_text())[0] == "manual_cpc"
