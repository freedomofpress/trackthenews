"""Drive the CLI end to end against canned HTTP: no network, no credentials.

Feeds, articles, X, Mastodon, and webhooks are all served by `responses`.
Any request that isn't registered fails with ConnectionError.
"""

import json
import re
from pathlib import Path

import pytest
import responses

FIXTURES = Path(__file__).parent / "fixtures"

MATCH = "https://news.example/2026/inspection-reports"
NOMATCH = "https://news.example/2026/weekend-forecast"
LOOP = "https://news.example/redirect-loop"
BROKEN_FEED = "https://broken.example/feed"
WEBHOOK = "https://hooks.example/secret-token"
X_TWEET = "https://api.twitter.com/2/tweets"
MASTODON = "https://mastodon.example"
PUBLISHER_HOSTS = ("twitter.com", "mastodon.example")


@pytest.fixture
def http():
    """Serve the fixture feed and its articles."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.get("https://news.example/feed", body=(FIXTURES / "feed.xml").read_text())
        mock.get(BROKEN_FEED, status=302, headers={"Location": BROKEN_FEED})
        mock.head(MATCH)
        mock.head(NOMATCH)
        mock.head(LOOP, status=302, headers={"Location": LOOP})
        mock.get(MATCH, body=(FIXTURES / "article-match.html").read_text())
        mock.get(NOMATCH, body=(FIXTURES / "article-nomatch.html").read_text())
        yield mock


def stub_publishers(mock, x=200, mastodon=200):
    """Stand in for X and Mastodon, answering status posts with the given codes."""
    mock.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        json={"media_id": 1, "media_id_string": "1"},
    )
    mock.post(X_TWEET, status=x, json={"data": {"id": "1", "text": ""}, "title": "stub"})
    mock.get(re.compile(rf"{MASTODON}/api/v[12]/instance/?"), json={"version": "4.3.0"})
    mock.post(f"{MASTODON}/api/v2/media", json={"id": "1"})
    mock.post(f"{MASTODON}/api/v1/statuses", status=mastodon, json={"id": "1"})


def calls_to(mock, prefix):
    return [call for call in mock.calls if call.request.url.startswith(prefix)]


def test_publishes_match_and_skips_bad_links(ttn, http):
    stub_publishers(http)

    rows, stderr = ttn()

    assert rows == {MATCH: (True, True), NOMATCH: (False, False)}
    (tweet,) = calls_to(http, X_TWEET)
    assert json.loads(tweet.request.body)["text"].endswith(MATCH)  # query string decrufted
    assert f"Unable to resolve article URL {LOOP}" in stderr
    assert f"Unable to fetch feed {BROKEN_FEED}" in stderr


def test_x_outage_still_toots_and_fires_webhook(ttn, http):
    stub_publishers(http, x=401)
    http.post(WEBHOOK)

    rows, stderr = ttn(notifications={"webhook": {"url": WEBHOOK}})

    assert rows[MATCH] == (False, True)
    (hook,) = calls_to(http, WEBHOOK)
    payload = json.loads(hook.request.body)
    assert (payload["publisher"], payload["article_url"]) == ("X", MATCH)
    assert f"ERROR: X failed for {MATCH}" in stderr
    assert WEBHOOK not in stderr


def test_failed_webhook_never_logs_its_url(ttn, http):
    stub_publishers(http, mastodon=500)
    http.post(WEBHOOK, status=500)

    rows, stderr = ttn(notifications={"webhook": {"url": WEBHOOK, "type": "slack"}})

    assert rows[MATCH] == (True, False)
    assert "Unable to deliver slack webhook: HTTPError" in stderr
    assert WEBHOOK not in stderr


def test_no_publish_records_without_contacting_publishers(ttn, http):
    rows, _ = ttn("--no-publish")

    assert rows == {MATCH: (False, False), NOMATCH: (False, False)}
    assert not any(host in call.request.url for call in http.calls for host in PUBLISHER_HOSTS)

    # Recorded articles count as seen: a second run doesn't fetch them again.
    http.calls.reset()
    ttn("--no-publish")
    assert not [call for call in calls_to(http, MATCH) if call.request.method == "GET"]


@pytest.mark.parametrize("notifications", [None, {}, {"webhook": None}])
def test_empty_notifications_config(ttn, http, notifications):
    stub_publishers(http)

    rows, _ = ttn(notifications=notifications)

    assert rows[MATCH] == (True, True)
