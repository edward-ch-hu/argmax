"""Map search terms, keywords, ad groups and CRM topic tags to the product topics you sell (config: topics).

Each topic has substrings (long enough to be safe inside other words) and whole words (short tokens like "bi" that
would match inside other words). winning_topics are the ones that close deals; ad_group_topics maps ad group names to
topics, so spend can be counted per topic.
"""
import re

import config

SPLIT = re.compile(r"[\s,，、/|;]+")


def topics():
    return config.get().topics


def winning():
    return tuple(config.get().winning_topics)


def ad_group_topic(name, default=None):
    return config.get().ad_group_topics.get(name, default)


def topics_of(text, table=None):
    """All topics a text mentions, in config order. Empty list when none."""
    table = topics() if table is None else table
    t = (text or "").lower()
    tokens = set(SPLIT.split(t))
    return [name for name, spec in table.items()
            if any(s.lower() in t for s in spec.get("substrings", []))
            or any(w.lower() in tokens for w in spec.get("words", []))]


def main_topic(text, table=None):
    found = topics_of(text, table)
    return found[0] if found else "other"
