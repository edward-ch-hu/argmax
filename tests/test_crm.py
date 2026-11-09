import crm
import pytest
from conftest import ROOT

CSV = {"crm.source": "csv", "crm.csv_path": str(ROOT / "docs/crm.example.csv")}


def test_status_mapping(use):
    cfg = use(**CSV)
    assert crm.status_code("won", cfg) == "won"
    assert crm.status_code(" Lost after trial ", cfg) == "lost_after_trial"
    assert crm.status_code("Lost", cfg) == "lost_no_trial"
    assert crm.status_code("Trial", cfg) == "trial"
    assert crm.status_code("Something new", cfg) == "talking"  # default_status
    assert crm.stage("won") == "win" and crm.stage("lost_no_trial") == "lost" and crm.stage("trial") == "open"


def test_csv_rows_have_no_names_or_emails(use):
    use(**CSV)
    rows = crm.load()
    assert len(rows) == 5
    text = repr(rows)
    assert "Jane" not in text and "example.com" not in text
    won = rows[0]
    assert won["status"] == "won" and won["mrr"] == 400.0 and won["topics"] == ["analytics"]
    assert rows[1]["topics"] == ["analytics", "dashboards"] and rows[1]["mrr_missing"]
    assert rows[3]["topics"] == []
    assert len({r["fp"] for r in rows}) == 5


def test_funnel(use):
    use(**CSV)
    f = crm.funnel(crm.load())
    assert f["leads"] == 5 and f["won"] == 1 and f["trial"] == 1 and f["talking"] == 1
    assert f["open"] == 2
    assert f["lead_to_trial"] == 0.6  # trial + won + lost after trial
    assert f["trial_to_win"] == 0.5  # won / (won + lost after trial)
    assert f["lead_to_win"] == 0.2
    by = crm.funnel_by_topic(crm.load())
    assert by["analytics"]["leads"] == 2 and by["none"]["leads"] == 1


def test_parse_dates_and_skips(use):
    cfg = use(**CSV)
    values = [["Lead date", "Status", "Name"], ["2026/2/3 10:00", "Won", "A"], ["", "Won", "B"], ["soon", "Won", "C"], []]
    rows, skipped = crm.parse(values, cfg)
    assert [r["date"] for r in rows] == ["2026-02-03"] and skipped == 2
    assert crm.parse_date("03.02.2026", "%d.%m.%Y") == "2026-02-03"


def test_missing_header_exits(use):
    cfg = use(**CSV)
    with pytest.raises(SystemExit):
        crm.parse([["Date", "State"], ["2026-01-01", "Won"]], cfg)


def test_none_source_degrades():
    assert crm.load() == []
    assert crm.last_entry([]) is None
    assert crm.summary([], "2026-01-01")["last_entry"] is None


def test_ref_codes_and_fill(use):
    use(**CSV, **{"ref_codes.enabled": True, "ref_codes.live_from": "2026-01-06", "ref_codes.test_codes": []})
    rows = crm.load()
    assert rows[0]["refs"] == ["AM-1A2B3C4D"]
    fill = crm.ref_fill(rows)
    assert fill["since"] == "2026-01-06" and fill["leads"] == 4 and fill["with_ref"] == 0
    assert crm.ref_fill(rows, since="2026-01-01")["since"] == "2026-01-06"


def test_private_values(use):
    use(**CSV)
    values = crm.private_values()
    assert "jane example" in values and "kim@example.org" in values
