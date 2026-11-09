"""lead_conversions selects every non-date segment its WHERE clause filters on (GAQL requires it)."""
from types import SimpleNamespace

import keyword_review


def test_network_segment_in_where_is_selected(monkeypatch):
    seen = []
    monkeypatch.setattr(keyword_review, "search", lambda ga, q: seen.append(q) or [])
    cfg = SimpleNamespace(conversions=SimpleNamespace(lead_signals=["Demo Request"]))
    keyword_review.lead_conversions(None, "search_term_view", ("campaign.id",),
                                    "campaign.id IN (1) AND segments.ad_network_type = 'SEARCH'", cfg)
    select = seen[0].split("FROM")[0]
    assert "segments.ad_network_type" in select


def test_no_extra_segment_when_not_filtered(monkeypatch):
    seen = []
    monkeypatch.setattr(keyword_review, "search", lambda ga, q: seen.append(q) or [])
    cfg = SimpleNamespace(conversions=SimpleNamespace(lead_signals=["Demo Request"]))
    keyword_review.lead_conversions(None, "keyword_view", ("ad_group_criterion.resource_name",),
                                    "campaign.id IN (1)", cfg)
    assert "segments.ad_network_type" not in seen[0].split("FROM")[0]
