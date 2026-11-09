"""Shared fixtures: the fictional example config (adgrad.example.yaml) is active for every test. No network."""
import copy
from pathlib import Path

import config
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = yaml.safe_load((ROOT / "adgrad.example.yaml").read_text(encoding="utf-8"))


def make(**overrides):
    """A config from the example with dotted overrides, e.g. make(**{"crm.source": "csv"})."""
    data = copy.deepcopy(EXAMPLE)
    for dotted, value in overrides.items():
        node = data
        *path, last = dotted.split(".")
        for key in path:
            node = node.setdefault(key, {})
        node[last] = value
    return config.load_dict(data)


@pytest.fixture(autouse=True)
def example_config():
    cfg = config.activate(make())
    yield cfg
    config.activate(None)


@pytest.fixture
def use():
    """use(**overrides) activates a modified example config for one test."""
    def activate(**overrides):
        return config.activate(make(**overrides))
    return activate
