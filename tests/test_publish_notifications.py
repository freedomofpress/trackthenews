from unittest.mock import Mock

import pytest

from trackthenews import core


@pytest.fixture
def article(monkeypatch):
    monkeypatch.setattr(core, "config", {"twitter": {}, "mastodon": {}}, raising=False)
    item = core.Article("Outlet", "Title", "https://example.org/story")
    item.matching_grafs = ["Example excerpt"]
    monkeypatch.setattr(item, "prepare_images", lambda square: [])
    return item


@pytest.mark.parametrize("failed", ["X", "Mastodon"])
def test_publish_attempts_other_platform_after_failure(monkeypatch, article, failed):
    x = Mock()
    mastodon = Mock()
    monkeypatch.setattr(core, "get_twitter_client", lambda: x)
    monkeypatch.setattr(core, "get_mastodon_instance", lambda: mastodon)
    monkeypatch.setattr(core, "upload_twitter_images", lambda files: [])
    if failed == "X":
        x.create_tweet.side_effect = RuntimeError("X unavailable")
    else:
        mastodon.status_post.side_effect = RuntimeError("Mastodon unavailable")

    core.publish_article(article)

    x.create_tweet.assert_called_once()
    mastodon.status_post.assert_called_once()
    assert article.tweeted is (failed != "X")
    assert article.tooted is (failed != "Mastodon")


@pytest.mark.parametrize(
    ("kind", "key"), [("slack", "text"), ("discord", "content"), ("custom", "event")]
)
def test_webhook_payload(monkeypatch, article, kind, key):
    core.config["notifications"] = {"webhook": {"url": "https://example.org/hook", "type": kind}}
    post = Mock(return_value=Mock())
    monkeypatch.setattr(core.requests, "post", post)

    core.notify_error("X", article, RuntimeError("failed"))

    payload = post.call_args.kwargs["json"]
    assert key in payload
    assert post.call_args.kwargs["timeout"] == core.HTTP_TIMEOUT_SECONDS


def test_failed_webhook_does_not_block_mastodon(monkeypatch, article):
    core.config["notifications"] = {"webhook": {"url": "https://example.org/hook"}}
    monkeypatch.setattr(core.requests, "post", Mock(side_effect=core.requests.ConnectionError()))
    monkeypatch.setattr(article, "tweet", Mock(side_effect=RuntimeError("X failed")))
    toot = Mock()
    monkeypatch.setattr(article, "toot", toot)

    core.publish_article(article)

    toot.assert_called_once()


def test_syslog_handler_configuration(monkeypatch):
    handler = Mock()
    monkeypatch.setattr(core.logging.handlers, "SysLogHandler", Mock(return_value=handler))
    core.configure_notifications({"syslog": True, "syslog_socket": "/tmp/test-log"})
    assert handler in core.logger.handlers
    core.configure_notifications({})
