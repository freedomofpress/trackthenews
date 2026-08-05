"""
Tests for the image rendering and upload path.

Regression coverage for issue #117: tweepy resolves an upload's MIME type from
the filename we hand it, so an extensionless filename produced a ``None`` MIME
type and crashed every post to Twitter.
"""

import mimetypes

import pytest
import tweepy
from PIL import Image

from trackthenews import core

CONFIG = {
    "color": "#F5F5F5",
    "font": "NotoSerif-Regular.ttf",
    "twitter": {
        "api_key": "api-key",
        "api_secret": "api-secret",
        "oauth_token": "oauth-token",
        "oauth_secret": "oauth-secret",
    },
}


@pytest.fixture(autouse=True)
def config(monkeypatch):
    """Stand in for the module-level config that main() populates at runtime."""
    monkeypatch.setattr(core, "config", CONFIG, raising=False)
    return CONFIG


@pytest.fixture
def article():
    article = core.Article(
        outlet="Example Outlet",
        title="An article about a records request",
        url="https://example.com/article",
    )
    article.matching_grafs = ["A paragraph mentioning a public records request."]
    return article


def test_rendered_images_use_the_declared_image_format(article):
    """The bytes we upload have to actually be the format IMAGE_FORMAT claims."""
    (img_file,) = article.prepare_images(square=False)

    assert Image.open(img_file).format == core.IMAGE_FORMAT.upper()


def test_upload_filename_resolves_to_the_declared_mime_type():
    """
    The filename is the only signal tweepy has to work from.

    Python 3.13 removed imghdr, so tweepy no longer sniffs the file's magic
    bytes and falls back to mimetypes.guess_type(), which reads the extension
    and nothing else.
    """
    assert mimetypes.guess_type(core.IMAGE_FILENAME)[0] == core.IMAGE_MIME_TYPE


def test_upload_twitter_images_posts_each_image(monkeypatch, article):
    """
    Run tweepy's real media_upload() with only the outbound HTTP call stubbed.

    Going through tweepy rather than around it is the point: this is what
    exercises its MIME type detection, so a future change to how tweepy derives
    file types fails here instead of in production.
    """
    requests_made = []

    def fake_request(self, method, endpoint, **kwargs):
        requests_made.append((method, endpoint, kwargs))
        return tweepy.models.Media.parse(self, {"media_id": 1234, "media_id_string": "1234"})

    monkeypatch.setattr(tweepy.API, "request", fake_request)

    article.matching_grafs = ["First excerpt.", "Second excerpt."]
    media = core.upload_twitter_images(article.prepare_images(square=True))

    assert [m.media_id for m in media] == [1234, 1234]
    assert len(requests_made) == 2

    for method, endpoint, kwargs in requests_made:
        # Images are small enough to go up in one piece; the chunked endpoints
        # are only reached when tweepy reads the file type as a video.
        assert (method, endpoint) == ("POST", "media/upload")
        filename, _ = kwargs["files"]["media"]
        assert mimetypes.guess_type(filename)[0] == core.IMAGE_MIME_TYPE


def test_tweet_uploads_images_and_posts_a_status(monkeypatch, article):
    """
    The end-to-end path from the bug report: main() -> tweet() -> media upload.

    Media upload still runs through tweepy for real here; only the two outbound
    API calls are stubbed.
    """
    tweets = []

    def fake_upload(self, method, endpoint, **kwargs):
        return tweepy.models.Media.parse(self, {"media_id": 1234, "media_id_string": "1234"})

    monkeypatch.setattr(tweepy.API, "request", fake_upload)
    monkeypatch.setattr(tweepy.Client, "create_tweet", lambda self, **kwargs: tweets.append(kwargs))

    article.tweet()

    assert article.tweeted is True
    assert tweets == [
        {
            "text": (
                "Example Outlet: An article about a records request https://example.com/article"
            ),
            "media_ids": [1234],
        }
    ]


def test_tweet_is_skipped_when_twitter_is_not_configured(monkeypatch, article, config):
    monkeypatch.delitem(config, "twitter")

    article.tweet()

    assert article.tweeted is False


def test_upload_twitter_images_skips_images_the_api_rejects(monkeypatch, article):
    """One rejected image shouldn't cost us the rest of the post."""
    attempts = []

    def fake_request(self, method, endpoint, **kwargs):
        attempts.append(endpoint)
        if len(attempts) == 1:
            raise tweepy.errors.TweepyException("nope")
        return tweepy.models.Media.parse(self, {"media_id": 5678, "media_id_string": "5678"})

    monkeypatch.setattr(tweepy.API, "request", fake_request)

    article.matching_grafs = ["First excerpt.", "Second excerpt."]
    media = core.upload_twitter_images(article.prepare_images(square=True))

    assert [m.media_id for m in media] == [5678]
