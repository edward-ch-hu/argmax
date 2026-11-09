import json

import check_external
import claims_check
import daily_scout
import monthly_report
import strategy_check
import topic_table
from conftest import ROOT


def test_claims_width_and_example_library():
    assert claims_check.width("abc") == 3
    assert claims_check.width("日本語") == 6
    library = claims_check.load_library(ROOT / "docs/ad_library.example.json")
    assert claims_check.check_assets(library) == []
    assert claims_check.norm(" Real-time　 visitor ") == "Real-timevisitor"


def test_claims_local_build(tmp_path):
    library = claims_check.load_library(ROOT / "docs/ad_library.example.json")
    for page, text in (("en/analytics", "Real-time visitor analytics. 14-day free trial, no card required. "
                                         "Cookieless tracking"), ("en/dashboards", "Drag-and-drop dashboards")):
        (tmp_path / page).mkdir(parents=True)
        (tmp_path / page / "index.html").write_text(f"<html><body><p>{text}</p></body></html>")
    result = claims_check.run(library, [], local=tmp_path)
    assert result["failed_claims"] == ["en-reporting-scheduled"]  # that page is missing
    assert result["status"] == "fail"


def test_check_external_blocklist():
    words = check_external.blocklist()
    assert "Signup" in words and "Chat Widget Open" in words and "150" in words
    text = "# m\n## Client update (external)\nWe tested ad copy.\nThe agent spent 150 a day.\nMail me@x.io\n## Next\nagent"
    first, lines = check_external.section(text)
    bad = check_external.problems(first, lines, {"jane example"}, words)
    assert bad == ["line 4: blocked word 'agent'", "line 4: blocked word '150'", "line 5: contains '@'"]
    assert check_external.problems(first, ["Spent 4,150 and 1500 in total"], set(), words) == []
    assert check_external.problems(first, ["Jane Example signed"], {"jane example"}, words)


def test_strategy_templates_pass_and_targets_sum():
    for path in [ROOT / "STRATEGY.example.md", *sorted((ROOT / "strategies").glob("*.md"))]:
        if path.name == "README.md":
            continue
        fails, _ = strategy_check.check(path.read_text())
        assert fails == [], (path.name, fails)
    base = (ROOT / "STRATEGY.example.md").read_text()
    good = base.replace("| analytics | TBD |", "| analytics | 50 |").replace("| dashboards | TBD |", "| dashboards | 20 |") \
        .replace("| reporting | TBD |", "| reporting | 20 |").replace("| other | TBD |", "| other | 10% |")
    assert strategy_check.check(good)[0] == []
    bad = good.replace("| other | 10% |", "| other | 15 |")
    assert any("sum to 105" in f for f in strategy_check.check(bad)[0])
    mixed = base.replace("| analytics | TBD |", "| analytics | 50 |")
    assert any("some shares are numbers" in f for f in strategy_check.check(mixed)[0])
    missing = base.replace("## Change log", "## Notes")
    assert "missing section '## Change log'" in strategy_check.check(missing)[0]
    _, warnings = strategy_check.check(base, topics={"analytics"})
    assert any("dashboards" in w for w in warnings)


def test_monthly_lines_and_history(use):
    use(**{"crm.source": "csv", "crm.csv_path": str(ROOT / "docs/crm.example.csv")})
    import crm
    rows = crm.load()
    hist = monthly_report.month_history({"2026-01": 1000.0}, rows, ["2025-12", "2026-01"], 1.0)
    jan = hist[1]
    assert jan["wins"] == 1 and jan["new_value"] == 400.0 and jan["roi"] == 0.4 and jan["open_leads"] == 2
    assert monthly_report.line(jan) == ("January 2026: spent USD 1,000, 1 new customer, at least new MRR 400, "
                                        "first-month ROI 0.4x")
    assert monthly_report.line(hist[0]) == "December 2025: spent USD 0, 0 new customers"
    summary = monthly_report.client_summary(hist, "2026-01")
    assert summary["year_to_date"].startswith("2026 to date (from January)")
    assert monthly_report.history_start("2026-01") == "2025-02"
    prev = {"history": [dict(jan, wins=0, new_value=0.0)]}
    assert monthly_report.revisions(hist, prev)[0]["changes"]["wins"] == [0, 1]


def test_topic_table_and_spend_line(use):
    use(**{"crm.source": "csv", "crm.csv_path": str(ROOT / "docs/crm.example.csv")})
    import crm
    spend = {"analytics": {"cost": 75.0}, "reporting": {"cost": 25.0}}
    matches = [{"status": "matched", "date": "2026-01-05", "fp": "x", "clicks": [{"ad_group": "Analytics"}]}]
    out = topic_table.table(spend, crm.load(), matches, "2026-01-01", "2026-01-31")
    assert out["analytics"] == {"spend": 75.0, "spend_share": 0.75, "leads": 2, "ref_matched_leads": 1, "wins": 1,
                                "trial_to_win": 1.0}
    assert out["none"]["leads"] == 1 and out["reporting"]["trial_to_win"] == 0.0


def test_daily_scout_helpers(tmp_path):
    assert daily_scout.week_path("2026-01-07", tmp_path).name == "week-2026-01-05.json"
    seen = {"a": "open", "b": "open"}
    current = [{"fp": "a", "stage": "win", "date": "2026-01-01", "topics": [], "mrr": 1.0},
               {"fp": "c", "stage": "open", "date": "2026-01-06", "topics": [], "mrr": 0.0}]
    new, changed = daily_scout.crm_diff(current, seen)
    assert [r["date"] for r in new] == ["2026-01-06"] and changed[0]["from"] == "open"
    assert daily_scout.crm_diff(current, None) == ([], [])
    out = {"date": "2026-01-21", "crm": {"last_entry": "2026-01-07"}}
    assert daily_scout.crm_quiet_alert(out, None)  # 14 days
    assert not daily_scout.crm_quiet_alert({"date": "2026-01-22", "crm": {"last_entry": "2026-01-07"}},
                                           {"date": "2026-01-21", "crm": {"last_entry": "2026-01-07"}})
    fill = {"date": "2026-01-21", "crm": {"ref_fill_14d": {"leads": 2, "with_ref": 0, "since": "2026-01-08"}}}
    assert daily_scout.ref_gap_alert(fill, None)
    assert not daily_scout.ref_gap_alert({"date": "2026-01-21", "crm": {"ref_fill_14d": {"leads": 2, "with_ref": 0}}},
                                         {"crm": {"ref_gap_alerted": "2026-01-18"}})
    assert json.dumps(fill)
