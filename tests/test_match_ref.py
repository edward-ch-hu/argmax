import hashlib

import match_ref


def test_code_hash_scheme():
    expected = "AM-" + hashlib.sha1(b"Cj0KCQ-test").hexdigest()[:8].upper()
    assert match_ref.code_of("Cj0KCQ-test") == expected
    assert match_ref.code_of("Cj0KCQ-test", "XY-").startswith("XY-")
    assert len(match_ref.code_of("abc")) == 11


def test_match_rows(tmp_path):
    a, b = match_ref.code_of("gclid-a"), match_ref.code_of("gclid-b")
    (tmp_path / "2026-01-05.tsv").write_text(f"code\tad_group_id\tkeyword\tad_id\n{a}\t7\tweb analytics\t99\n{b}\t7\t\t\n")
    (tmp_path / "2026-01-06.tsv").write_text(f"code\tad_group_id\tkeyword\tad_id\n{b}\t8\tkpi board\t98\n")
    index = match_ref.click_index(tmp_path)
    rows = [{"fp": "f1", "date": "2026-01-06", "stage": "win", "topics": ["analytics"], "mrr": 100.0,
             "refs": [a, b, "AM-00000000", "AM-TEST0000"]}]
    out = match_ref.match_rows(rows, index, {"7": ("US - Search", "Analytics")}, {"AM-TEST0000"})
    status = {e["code"]: e["status"] for e in out}
    assert status == {a: "matched", b: "ambiguous", "AM-00000000": "not_found"}
    assert out[0]["clicks"][0]["ad_group"] == "Analytics"
    assert index[a][0]["ad_group_id"] == "7"  # the index is not mutated by matching


def test_off_by_default():
    assert not match_ref.enabled()
