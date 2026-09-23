"""Malformed redirects must not prevent other entries or feeds from running."""

from unittest.mock import Mock

import requests

from trackthenews import core


def test_bad_article_redirect_skips_only_affected_entry():
    feed_url = "https://example.org/feed"
    bad_url = "https://example.org/redirect-loop"
    good_url = "https://example.org/valid"
    session = Mock()
    session.get.return_value.text = (
        "<rss version='2.0'><channel><title>Example</title>"
        f"<item><title>Broken</title><link>{bad_url}</link></item>"
        f"<item><title>Working</title><link>{good_url}</link></item>"
        "</channel></rss>"
    )

    def head(url, **kwargs):
        if url == bad_url:
            raise requests.TooManyRedirects("redirect loop")
        return Mock(url=url, headers={})

    session.head.side_effect = head

    articles = core.parse_feed("Example", feed_url, False, True, session)

    assert [article.url for article in articles] == [good_url]
    assert session.head.call_count == 2
