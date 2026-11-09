"""The two-step ledger (pending, then applied or failed) and apply_keyword_review's checks. No network."""
import json
from datetime import date

import apply_keyword_review as akr
import daily_negatives
import ledger
import monthly_report
import pytest

KW = "customers/1234567890/adGroupCriteria/11~22"
LIVE = {KW: {"campaign": "US - Search", "ad_group": "Analytics", "text": "web analytics", "match": "BROAD", "bid": 1.5}}


def entry(**kw):
    return {**ledger.entry("keyword", "US - Search / Analytics / x", "status", "ENABLED", "PAUSED", "r", "analytics",
                           "e", day=date(2026, 1, 7)), **kw}


def test_pending_then_applied_or_failed(tmp_path, capsys):
    path = tmp_path / "changes.jsonl"
    with ledger.pending([entry()], path=path):
        assert "LEDGER pending" in capsys.readouterr().out  # printed before the mutate runs
        assert ledger.read(path) == [] and len(ledger.unconfirmed(path)) == 1
    assert [e["status"] for e in ledger.lines(path)] == ["pending", "applied"]
    assert len(ledger.read(path)) == 1 and ledger.unconfirmed(path) == []

    with pytest.raises(RuntimeError):
        with ledger.pending([entry(entity="y")], path=path):
            raise RuntimeError("mutate failed")
    assert [e["status"] for e in ledger.lines(path)][-1] == "failed"
    assert len(ledger.read(path)) == 1 and ledger.unconfirmed(path) == []

    ledger.begin([entry(entity="z")], path=path)  # the run died before the outcome line
    assert [e["entity"] for e in ledger.unconfirmed(path)] == ["z"] and len(ledger.read(path)) == 1

    with ledger.pending([entry(entity="v")], apply=False, path=path):  # validate only: nothing written
        pass
    assert len(ledger.lines(path)) == 5


def test_old_lines_without_status_still_count():
    old = [entry()]  # written before pending lines existed
    assert ledger.read(entries=old) == old and ledger.unconfirmed(entries=old) == []
    assert daily_negatives.daily_lines(entries=[{**entry(), "routine": "daily", "field": "negative", "after": "EXACT",
                                                 "status": "pending", "id": "a"}]) == []


def test_monthly_lists_unconfirmed_lines_and_does_not_judge_them():
    lines = [{**entry(), "status": "pending", "id": "x"},
             {**entry(date="2026-02-03"), "status": "pending", "id": "y"},
             {**entry(date="2026-02-03"), "status": "applied", "id": "y"}]
    out = monthly_report.change_audit(None, None, [], "2026-01", date(2026, 2, 1), lines)
    assert out["this_month"] == [] and [e["date"] for e in out["unconfirmed"]] == ["2026-01-07"]


def review(**lists):
    base = {"negatives": [], "positives": [], "ideas": [], "pauses": []}
    base.update(lists)
    return base


def add(text="web analytics", match="PHRASE", cpc=None, approve=True):
    row = {"campaign_id": 1, "campaign": "US - Search", "ad_group_id": 11, "ad_group": "Analytics", "text": text,
           "match": match, "approve": approve}
    if cpc is not None:
        row["cpc"] = cpc
    return row


def pause(replaced=True, **kw):
    row = {"campaign": "US - Search", "ad_group": "Analytics", "resource_name": KW, "text": "web analytics",
           "match": "BROAD", "approve": True}
    if replaced:
        row["replaced_by"] = {"ad_group_id": 11, "text": "web analytics", "match": "PHRASE"}
    return {**row, **kw}


def test_shape_needs_approve_and_fields():
    fails = akr.check_shape(review(negatives=[{"campaign_id": 1, "campaign": "C", "text": "a", "match": "EXACT"}],
                                   pauses=[{"approve": True, "text": "b"}], ideas=[add(match="FUZZY")]))
    assert any("negatives[0]" in f and "approve" in f for f in fails)
    assert any("pauses[0]" in f and "missing resource_name" in f for f in fails)
    assert any("match must be one of" in f for f in fails)
    assert akr.check_shape(review(positives=[add()])) == []
    assert akr.check_shape([]) != []


def test_main_refuses_a_row_without_approve_without_a_traceback(tmp_path, monkeypatch, capsys):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review(negatives=[{"campaign_id": 1, "campaign": "C", "text": "a", "match": "EXACT"}])))
    monkeypatch.setattr("sys.argv", ["apply_keyword_review.py", str(path), "--apply"])
    monkeypatch.setattr(akr.ads_client, "load", lambda: pytest.fail("must not reach the API"))
    with pytest.raises(SystemExit, match="Nothing changed"):
        akr.main()
    assert "FAIL" in capsys.readouterr().out


def test_keyword_bids_stay_inside_floor_and_ceiling():
    assert akr.check(review(positives=[add(cpc=1.0)]), {}) == []
    assert any("outside 0.30 to 6.00" in f for f in akr.check(review(positives=[add(cpc=9.0)]), {}))
    assert any("outside" in f for f in akr.check(review(ideas=[add(cpc=0.1)]), {}))
    assert any("positive number" in f for f in akr.check(review(ideas=[add(cpc="2")]), {}))
    assert akr.check(review(positives=[add(cpc=9.0, approve=False)]), {}) == []  # not approved: not checked


def test_replacement_keeps_the_paused_keywords_own_bid():
    assert akr.check(review(positives=[add(cpc=1.5)], pauses=[pause()]), LIVE) == []
    fails = akr.check(review(positives=[add(cpc=2.0)], pauses=[pause()]), LIVE)
    assert any("own bid (cpc USD 1.50)" in f for f in fails)
    fails = akr.check(review(positives=[add()], pauses=[pause()]), LIVE)
    assert any("got none" in f for f in fails)
    no_bid = {KW: dict(LIVE[KW], bid=None)}
    assert akr.check(review(positives=[add()], pauses=[pause()]), no_bid) == []
    assert any("uses the ad group bid" in f for f in akr.check(review(positives=[add(cpc=1.0)], pauses=[pause()]), no_bid))


def test_pauses_only_for_live_keywords_that_match_the_row():
    assert akr.check(review(pauses=[pause(replaced=False)]), LIVE) == []
    other = "customers/1234567890/adGroups/11"
    assert any("not a live keyword" in f for f in akr.check(review(pauses=[pause(False, resource_name=other)]), LIVE))
    foreign = "customers/9999999999/adGroupCriteria/11~22"
    assert any("not a live keyword" in f for f in
               akr.check(review(pauses=[pause(False, resource_name=foreign)]), {foreign: LIVE[KW]}))
    assert any("in the account" in f for f in akr.check(review(pauses=[pause(False, text="other words")]), LIVE))
