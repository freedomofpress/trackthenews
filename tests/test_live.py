"""Smoke test against real feeds, to catch format drift. Never publishes.

Skipped by default; run with `poetry run pytest -m live`.
"""

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.live


def test_live_feeds_parse(ttn):
    shutil.copy(FIXTURES / "live-feeds.json", ttn.dir / "rssfeeds.json")

    rows, stderr = ttn("--no-publish")

    assert rows
    assert "Unable to fetch feed" not in stderr
