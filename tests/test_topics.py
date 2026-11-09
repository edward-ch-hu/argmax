from topics import main_topic, topics_of


def test_substrings_and_whole_words():
    assert topics_of("best web analytics tool") == ["analytics"]
    assert topics_of("BI dashboard software") == ["analytics", "dashboards"]
    assert topics_of("bike rental") == []  # "bi" is a whole word only
    assert topics_of("scheduled report by email, pdf report") == ["reporting"]


def test_main_topic_and_other():
    assert main_topic("kpi board for teams") == "dashboards"
    assert main_topic("cheap flights") == "other"
    assert main_topic("") == "other"


def test_custom_table():
    table = {"shoes": {"substrings": ["sneaker"], "words": ["kicks"]}}
    assert topics_of("new kicks, sneakers", table) == ["shoes"]
