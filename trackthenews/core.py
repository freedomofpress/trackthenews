# Parses a collection of news outlet RSS feeds for recently published articles,
# then converts those articles to plaintext and searches them for mentions of
# given words or phrases, and posts the results to Twitter.

from __future__ import unicode_literals

from typing import IO, Iterable, List

import argparse
import json
import os
import sqlite3
import time
import textwrap
import sys

from datetime import datetime
from io import BytesIO, open
from builtins import input

import feedparser
import html2text
import requests
import yaml

from PIL import Image, ImageDraw, ImageFont
from readability import Document
from mastodon import Mastodon, MastodonNetworkError, MastodonError
import tweepy

# TODO: add/remove RSS feeds from within the script.
# Currently the matchwords list and RSS feeds list must be edited separately.
# TODO: add support for additional parsers beyond readability
# readability doesn't work very well on NYT, which requires something custom
# TODO: add other forms of output beyond a Twitter bot


class Article:
    def __init__(self, outlet, title, url, delicate=False, redirects=False):
        self.outlet = outlet
        self.title = title
        self.url = url
        self.delicate = delicate
        self.redirects = redirects
        self.canonicalize_url()

        self.matching_grafs = []
        self.tweeted = False
        self.tooted = False

    def canonicalize_url(self):
        """Process article URL to produce something roughly canonical."""
        # These outlets use redirect links in their RSS feeds.
        # Follow those links, then store only the final destination.
        if self.redirects:
            res = requests.head(self.url, allow_redirects=True, timeout=30)
            self.url = res.headers["location"] if "location" in res.headers else res.url

        # Some outlets' URLs don't play well with modifications, so those we
        # store crufty. Otherwise, decruft with extreme prejudice.
        if not self.delicate:
            self.url = decruft_url(self.url)

    def clean(self):
        """Download the article and strip it of HTML formatting."""
        self.res = requests.get(self.url, headers={"User-Agent": ua}, timeout=30)
        doc = Document(self.res.text)

        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_emphasis = True
        h.ignore_images = True
        h.body_width = 0

        self.plaintext = h.handle(doc.summary())

    def check_for_matches(self):
        """
        Clean up an article, check it against a block list, then for matches.
        """
        self.clean()
        plaintext_grafs = self.plaintext.split("\n")

        if blocklist_loaded and blocklist.check(self):
            pass
        else:
            for graf in plaintext_grafs:
                if any(word.lower() in graf.lower() for word in matchwords) or any(
                    word in graf for word in matchwords_case_sensitive
                ):
                    self.matching_grafs.append(graf)

    def prepare_images(self, square):
        """Prepares the images for upload."""
        img_files = []
        for graf in self.matching_grafs[:4]:
            img = render_img(graf, square=square)
            img_io = BytesIO()
            img.save(img_io, format="jpeg", quality=95)
            img_io.seek(0)
            img_files.append(img_io)

        return img_files

    def truncate_title(self, max_chars, source, link_characters=23):
        """Truncates the title to fit within the character limit."""

        # Ellipsis is a two-byte character; links have fixed length on Twitter and Mastodon
        remaining_chars = max_chars - len(source) - 3 - link_characters
        title = (
            (self.title[:remaining_chars] + "…")
            if len(self.title) > remaining_chars
            else self.title
        )
        return title

    def truncate_alt_text(self, text, max_chars=1500):
        """Truncates the alt text to fit within the character limit."""
        alt_text = "Excerpt: " + text
        remaining_chars = max_chars - 3  # 3 chars for the ellipsis
        alt_text = (
            (alt_text[:remaining_chars] + "…")
            if len(alt_text) > max_chars
            else alt_text
        )
        return alt_text

    def tweet(self):
        """Send images to be rendered and tweet them with a text status."""
        if "twitter" not in config:
            print("Twitter is not configured. Skipping tweet.")
            return

        square = False if len(self.matching_grafs) == 1 else True
        img_files = self.prepare_images(square)

        media = upload_twitter_images(img_files)
        media_ids = [m.media_id for m in media]

        source = self.outlet + ": " if self.outlet else ""

        # Tweets can be 280 characters
        title = self.truncate_title(280, source)

        content = "{}{} {}".format(source, title, self.url)

        twitter = get_twitter_client()

        twitter.create_tweet(text=content, media_ids=media_ids)

        self.tweeted = True

    def toot(self):
        """Send images to be rendered and toot them with a text status."""
        if "mastodon" not in config:
            print("Mastodon is not configured. Skipping toot.")
            return

        square = False if len(self.matching_grafs) == 1 else True
        img_files = self.prepare_images(square)

        mastodon = get_mastodon_instance()
        media_ids = []

        for idx, img_file in enumerate(img_files):
            try:
                alt_text = self.truncate_alt_text(self.matching_grafs[idx])
                res = mastodon.media_post(
                    img_file, mime_type="image/jpeg", description=alt_text
                )
                media_ids.append(res["id"])
            except MastodonError:
                pass

        source = self.outlet + ": " if self.outlet else ""

        # Toots can be 500 characters
        title = self.truncate_title(500, source)

        status = "{}{} {}".format(source, title, self.url)

        mastodon.status_post(status=status, media_ids=media_ids)

        self.tooted = True


def get_mastodon_instance():
    """Return an authenticated Mastodon instance."""
    api_base_url = config["mastodon"]["api_base_url"]
    access_token = config["mastodon"]["access_token"]

    return Mastodon(access_token=access_token, api_base_url=api_base_url)


def get_twitter_client():
    """Return an authenticated Twitter client using the v2 API."""
    app_key = config["twitter"]["api_key"]
    app_secret = config["twitter"]["api_secret"]
    oauth_token = config["twitter"]["oauth_token"]
    oauth_token_secret = config["twitter"]["oauth_secret"]

    return tweepy.Client(
        consumer_key=app_key,
        consumer_secret=app_secret,
        access_token=oauth_token,
        access_token_secret=oauth_token_secret,
    )


def get_twitter_client_v1():
    """
    Return an authenticated Twitter client using the v1 API.

    As of 2023-07-06 uploading media still requires the v1 API.
    """
    app_key = config["twitter"]["api_key"]
    app_secret = config["twitter"]["api_secret"]
    oauth_token = config["twitter"]["oauth_token"]
    oauth_token_secret = config["twitter"]["oauth_secret"]

    tweepy_auth = tweepy.OAuth1UserHandler(
        app_key, app_secret, oauth_token, oauth_token_secret
    )

    return tweepy.API(tweepy_auth)


def upload_twitter_images(img_files: Iterable[IO]) -> List[tweepy.models.Media]:
    """Upload images to Twitter and return their IDs."""
    twitter = get_twitter_client_v1()

    media = []

    for img in img_files:
        try:
            res = twitter.media_upload(filename="image", file=img)
            media.append(res)
        except tweepy.errors.TweepyException as e:
            pass

    return media


def get_textsize(graf, width, fnt, spacing):
    """Take text and additional parameters and return the rendered size."""
    wrapped_graf = textwrap.wrap(graf, width)

    line_spacing = fnt.getsize("A")[1] + spacing
    text_width = max(fnt.getsize(line)[0] for line in wrapped_graf)

    textsize = text_width, line_spacing * len(wrapped_graf)

    return textsize


def render_img(graf, width=60, square=False):
    """Take a paragraph and render an Image of it on a plain background."""
    font_name = config["font"]
    font_dir = os.path.join(os.path.dirname(__file__), "fonts")
    font_path = os.path.join(font_dir, font_name)
    fnt = ImageFont.truetype(font_path, size=36)
    spacing = 12  # Just a nice spacing number, visually

    graf = graf.lstrip("#>—-• ")

    if square is True:
        ts = {w: get_textsize(graf, w, fnt, spacing) for w in range(20, width)}
        width = min(ts, key=lambda w: abs(ts.get(w)[1] - ts.get(w)[0]))

    textsize = get_textsize(graf, width, fnt, spacing)
    wrapped = "\n".join(textwrap.wrap(graf, width))

    border = 60

    size = tuple(side + border * 2 for side in textsize)
    xy = (border, border)

    im = Image.new("RGB", size, color=config["color"])
    draw_obj = ImageDraw.Draw(im)
    draw_obj.multiline_text(xy, wrapped, fill="#000000", font=fnt, spacing=12)

    return im


def decruft_url(url):
    """Attempt to remove extraneous characters from a given URL and return it."""
    url = url.split("?")[0].split("#")[0]
    return url


def parse_feed(outlet, url, delicate, redirects):
    """Take the URL of an RSS feed and return a list of Article objects."""
    feed = feedparser.parse(url)

    articles = []

    for entry in feed["entries"]:
        """If for some reason the entry is missing a title or URL, just leave them empty."""
        title = entry.get("title", "")
        url = entry.get("link", "")

        if not url:
            print("Entry is missing a URL. Skipping!")
            continue

        article = Article(outlet, title, url, delicate, redirects)

        articles.append(article)

    return articles


def config_twitter(config):

    twitter_setup = input("Would you like the bot to post to Twitter? (Y/n) ")
    if twitter_setup.lower().startswith("n"):
        return config

    if "twitter" in config.keys():
        replace = input("Twitter configuration already exists. Replace? (Y/n) ")
        if replace.lower() in ["n", "no"]:
            return config

    input(
        "Create a new Twitter app at https://developer.twitter.com/en/portal/projects-and-apps\n"
        "to post matching stories. For this step, you can be logged in as yourself or with the\n"
        "posting account, if they're different. Fill out Name, Description, and Website with\n"
        "values meaningful to you. These are not used in trackthenews config but may be\n"
        'publicly visible. Then click the "Keys and Access Tokens" tab.\n\n'
        "Press [Enter] to continue…"
    )

    api_key = input("Enter the provided API key: ").strip()
    api_secret = input("Enter the provided API secret: ").strip()

    input(
        "Now ensure you are logged in with the account that will do the posting.\n\n"
        "Press [Enter] to continue…"
    )

    tw = tweepy.OAuth1UserHandler(api_key, api_secret, callback="oob")

    auth_url = tw.get_authorization_url()

    pin = input("Enter the pin found at {} ".format(auth_url)).strip()

    oauth_token, oauth_secret = tw.get_access_token(pin)

    twitter = {
        "api_key": api_key,
        "api_secret": api_secret,
        "oauth_token": oauth_token,
        "oauth_secret": oauth_secret,
    }

    config["twitter"] = twitter

    return config


def config_mastodon(config):
    mastodon_setup = input("Would you like the bot to post to Mastodon? (Y/n) ")
    if mastodon_setup.lower().startswith("n"):
        return config

    if "mastodon" in config.keys():
        replace = input("Mastodon configuration already exists. Replace? (Y/n) ")
        if replace.lower() in ["n", "no"]:
            return config

    input(
        "To configure Mastodon, you will need your instance URL and an access token. To\n"
        "obtain an access token, visit the developer settings (under\n"
        "/settings/applications), and create an application with read and write\n"
        "permissions.\n\n"
        "Press [Enter] to continue…"
    )

    api_base_url = input(
        "Enter your Mastodon instance URL (e.g., 'https://mastodon.social'): "
    ).strip()
    access_token = input("Enter your access token: ").strip()

    # Verify the credentials by making a request to the API
    mastodon_client = Mastodon(access_token=access_token, api_base_url=api_base_url)
    try:
        mastodon_client.account_verify_credentials()
        print("Credentials verified successfully.")
    except MastodonNetworkError:
        print("Error: Could not verify credentials. Please check the entered values.")
        return config

    mastodon = {"api_base_url": api_base_url, "access_token": access_token}

    config["mastodon"] = mastodon

    return config


def setup_db(config):
    database = os.path.join(home, config["db"])
    if not os.path.isfile(database):
        conn = sqlite3.connect(database)
        schema_script = """create table articles (
            id          integer primary key not null,
            title       text,
            outlet      text,
            url         text,
            tweeted     boolean,
            tooted      boolean,
            recorded_at datetime
        );"""
        conn.executescript(schema_script)
        conn.commit()
        conn.close()


def setup_matchlist():
    path = os.path.join(home, "matchlist.txt")
    path_case_sensitive = os.path.join(home, "matchlist_case_sensitive.txt")

    if os.path.isfile(path):
        print("A matchlist already exists at {path}.".format(**locals()))
    else:
        with open(path, "w") as f:
            f.write("")
        print(
            "A new matchlist has been generated at {path}. You can add case insensitive entries to match, one per line.".format(
                **locals()
            )
        )

    if os.path.isfile(path_case_sensitive):
        print(
            "A case-sensitive matchlist already exists at {path_case_sensitive}.".format(
                **locals()
            )
        )
    else:
        with open(path_case_sensitive, "w") as f:
            f.write("")
        print(
            "A new case-sensitive matchlist has been generated at {path_case_sensitive}. You can add case-sensitive entries to match, one per line.".format(
                **locals()
            )
        )

    return


def setup_rssfeedsfile():
    path = os.path.join(home, "rssfeeds.json")

    if os.path.isfile(path):
        print("An RSS feeds file already exists at {path}.".format(**locals()))
        return
    else:
        with open(path, "w") as f:
            f.write("")
            print(
                "A new RSS feeds file has been generated at {path}.".format(**locals())
            )

    return


def initial_setup():
    configfile = os.path.join(home, "config.yaml")

    if os.path.isfile(configfile):
        with open(configfile, "r", encoding="utf-8") as f:
            config = yaml.full_load(f)
    else:
        to_configure = input(
            "It looks like this is the first time you've run trackthenews, or you've moved or deleted its configuration files.\nWould you like to create a new configuration in {}? (Y/n) ".format(
                home
            )
        )

        config = {}

        if to_configure.lower() in ["n", "no", "q", "exit", "quit"]:
            sys.exit("Ok, quitting the program without configuring.")

    if sys.version_info.major > 2:
        os.makedirs(home, exist_ok=True)
    else:
        try:
            os.makedirs(home)
        except:
            pass

    if "db" not in config:
        config["db"] = "trackthenews.db"

    if "user-agent" not in config:
        ua = input(
            "What would you like your script's user-agent to be?\nThis should be something that is meaningful to you and may show up in the logs of the sites you are tracking: "
        )

        ua = ua + " / powered by trackthenews (a project of freedom.press)"

        config["user-agent"] = ua

    if "color" not in config:
        config["color"] = "#F5F5F5"

    if "font" not in config:
        config["font"] = "NotoSerif-Regular.ttf"

    setup_matchlist()
    setup_rssfeedsfile()
    setup_db(config)
    config = config_twitter(config)
    config = config_mastodon(config)

    # check if either Twitter or Mastodon has been configured
    if "twitter" not in config and "mastodon" not in config:
        print(
            "Error: The bot must have at least one of Twitter or Mastodon configured."
        )
        sys.exit(1)

    with open(configfile, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    return config


def apply_migrations(conn):
    # Check if the "tooted" column exists
    cursor = conn.execute("PRAGMA table_info(articles)")
    columns = [column[1] for column in cursor.fetchall()]
    if "tooted" not in columns:
        # If the "tooted" column does not exist, add it
        print("Adding missing 'tooted' column")
        conn.execute("ALTER TABLE articles ADD COLUMN tooted boolean")
        conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description="Track articles from RSS feeds for a custom list of keywords and act on the matches."
    )

    parser.add_argument(
        "-c", "--config", help="Run configuration process", action="store_true"
    )
    parser.add_argument(
        "dir",
        nargs="?",
        help="The directory to store or find the configuration files.",
        default=os.path.join(os.getcwd(), "ttnconfig"),
    )

    args = parser.parse_args()

    global home
    home = os.path.abspath(args.dir)

    print("Running with configuration files in {}".format(home))

    if args.config:
        initial_setup()
        sys.exit(
            "Created new configuration files. Now go populate the RSS Feed file and the list of matchwords!"
        )

    configfile = os.path.join(home, "config.yaml")
    if not os.path.isfile(configfile):
        initial_setup()

    global config
    with open(configfile, encoding="utf-8") as f:
        config = yaml.full_load(f)

    global ua
    ua = config["user-agent"]

    database = os.path.join(home, config["db"])
    if not os.path.isfile(database):
        setup_db(config)

    conn = sqlite3.connect(database)

    apply_migrations(conn)

    matchlist = os.path.join(home, "matchlist.txt")
    matchlist_case_sensitive = os.path.join(home, "matchlist_case_sensitive.txt")
    if not (os.path.isfile(matchlist) and os.path.isfile(matchlist_case_sensitive)):
        setup_matchlist()

    global matchwords
    global matchwords_case_sensitive
    with open(matchlist, "r", encoding="utf-8") as f:
        matchwords = [w for w in f.read().split("\n") if w]
    with open(matchlist_case_sensitive, "r", encoding="utf-8") as f:
        matchwords_case_sensitive = [w for w in f.read().split("\n") if w]

    if not (matchwords or matchwords_case_sensitive):
        sys.exit(
            "You must add words to at least one of the matchwords lists, located at {} and {}.".format(
                matchlist, matchlist_case_sensitive
            )
        )

    sys.path.append(home)
    global blocklist_loaded
    global blocklist
    try:
        import blocklist as blocklist

        blocklist_loaded = True
        print("Loaded blocklist.")
    except ImportError:
        blocklist_loaded = False
        print("No blocklist to load.")

    if matchwords:
        print("Matching against the following words: {}".format(matchwords))
    if matchwords_case_sensitive:
        print(
            "Matching against the following case-sensitive words: {}".format(
                matchwords_case_sensitive
            )
        )

    rssfeedsfile = os.path.join(home, "rssfeeds.json")
    if not os.path.isfile(rssfeedsfile):
        setup_rssfeedsfile()

    with open(rssfeedsfile, "r", encoding="utf-8") as f:
        try:
            rss_feeds = json.load(f)
        except json.JSONDecodeError:
            sys.exit(
                "You must add RSS feeds to the RSS feeds list, located at {}.".format(
                    rssfeedsfile
                )
            )

    for feed in rss_feeds:
        outlet = feed["outlet"] if "outlet" in feed else ""
        url = feed["url"]
        delicate = True if "delicateURLs" in feed and feed["delicateURLs"] else False
        redirects = True if "redirectLinks" in feed and feed["redirectLinks"] else False

        articles = parse_feed(outlet, url, delicate, redirects)
        deduped = []

        for article in articles:
            article_exists = conn.execute(
                "select * from articles where url = ?", (article.url,)
            ).fetchall()
            if not article_exists:
                deduped.append(article)

        for counter, article in enumerate(deduped, 1):
            print(
                "Checking {} article {}/{}".format(
                    article.outlet, counter, len(deduped)
                )
            )

            try:
                article.check_for_matches()
            except:
                print("Having trouble with that article. Skipping for now.")
                pass

            if article.matching_grafs:
                print("Got one!")
                article.tweet()
                article.toot()

            conn.execute(
                """insert into articles(
                         title, outlet, url, tweeted, tooted, recorded_at)
                         values (?, ?, ?, ?, ?, ?)""",
                (
                    article.title,
                    article.outlet,
                    article.url,
                    article.tweeted,
                    article.tooted,
                    datetime.utcnow(),
                ),
            )

            conn.commit()

            time.sleep(1)

    conn.close()


if __name__ == "__main__":
    main()
