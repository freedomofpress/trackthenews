"""Exercise the CLI processing path without network requests or real publishers."""

import json
import sqlite3
import sys
from unittest.mock import Mock

import pytest
import requests

from trackthenews import core


@pytest.fixture
def feed_run(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "db: trackthenews.db\nuser-agent: test-agent\n", encoding="utf-8"
    )
    (tmp_path / "matchlist.txt").write_text("records\n", encoding="utf-8")
    (tmp_path / "matchlist_case_sensitive.txt").write_text("", encoding="utf-8")
    (tmp_path / "rssfeeds.json").write_text(
        json.dumps([{"outlet": "Example", "url": "https://example.org/feed"}]), encoding="utf-8"
    )
    article = core.Article("Example", "Records", "https://example.org/story")
    article.check_for_matches = Mock(
        side_effect=lambda session, blocklist: article.matching_grafs.append("records")
    )
    monkeypatch.setattr(core, "parse_feed", lambda *args: [article])
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    return tmp_path, article


def test_no_blocklist_still_checks_and_publishes(feed_run, monkeypatch):
    folder, article = feed_run
    monkeypatch.setattr(sys, "argv", ["trackthenews", str(folder)])
    publish = Mock()
    monkeypatch.setattr(core, "publish_article", publish)

    core.main()

    assert article.check_for_matches.call_args.kwargs["blocklist"] is None
    publish.assert_called_once_with(article)


def test_no_publish_records_without_contacting_publishers(feed_run, monkeypatch):
    folder, article = feed_run
    monkeypatch.setattr(sys, "argv", ["trackthenews", "--no-publish", str(folder)])
    publish = Mock()
    monkeypatch.setattr(core, "publish_article", publish)

    core.main()

    publish.assert_not_called()
    with sqlite3.connect(folder / "trackthenews.db") as connection:
        row = connection.execute("SELECT url, tweeted, tooted FROM articles").fetchone()
    assert row == (article.url, 0, 0)

    # Recorded URLs are skipped on later normal runs as well.
    monkeypatch.setattr(sys, "argv", ["trackthenews", str(folder)])
    core.main()
    publish.assert_not_called()


def test_feed_redirect_failure_does_not_block_later_feed(feed_run, monkeypatch):
    folder, article = feed_run
    (folder / "rssfeeds.json").write_text(
        json.dumps(
            [
                {"url": "https://example.org/bad-feed"},
                {"url": "https://example.org/good-feed"},
            ]
        ),
        encoding="utf-8",
    )

    def parse_feed(outlet, url, delicate, redirects, session):
        if url.endswith("bad-feed"):
            raise requests.TooManyRedirects("redirect loop")
        return [article]

    monkeypatch.setattr(core, "parse_feed", parse_feed)
    monkeypatch.setattr(core, "publish_article", Mock())
    monkeypatch.setattr(sys, "argv", ["trackthenews", str(folder)])

    core.main()

    article.check_for_matches.assert_called_once()
