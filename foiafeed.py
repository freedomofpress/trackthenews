#!/usr/bin/env python3
# Parses a collection of news outlet RSS feeds for recently published articles,
# then converts those articles to plaintext and searches them for mentions of
# FOIA or other public records law, then tweets matching excerpts.

import json
import os
import sqlite3
import time
import textwrap

from datetime import datetime
from io import BytesIO

import feedparser
import html2text
import requests
import yaml

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from readability import Document
from twython import Twython, TwythonError

# Comparison happens in lowercase, so no uppercase letters here!
FOIA_PHRASES = [
    'f.o.i.a.',
    'foia',
    'freedom of information act',
    'freedom of information law',
    'records request',
    'open records',
    'public records act',
    'public records law',
    'public records obtained',
    'sunshine law',
    'sunshine act']

# These are outlets that syndicate redirect links in their RSS feeds. Boo!
RSS_REDIRECT_OUTLETS = ['ProPublica', 'Reuters', 'CNN']

# These are outlets that are sensitive to URL queries and fragments.
DELICATE_URL_OUTLETS = ['AP']

FULLPATH = os.path.dirname(os.path.realpath(__file__))
CONFIGFILE = os.path.join(FULLPATH, 'config.yaml')
RSSFEEDFILE = os.path.join(FULLPATH, 'rssfeeds.json')

with open(CONFIGFILE, 'r') as c:
    CONFIG = yaml.load(c)

# User-Agent for requests to pages. For forks, please fill this in!
USERAGENT = CONFIG['user-agent']

class Article:
    def __init__(self, outlet, title, url):
        self.outlet = outlet
        self.title = title
        self.url = url
        self.canonicalize_url()

        self.matching_grafs = []
        self.imgs = []
        self.tweeted = False

    def canonicalize_url(self):
        """Process article URL to produce something roughly canonical."""
        # These outlets use redirect links in their RSS feeds.
        # Follow those links, then store only the final destination.
        if self.outlet in RSS_REDIRECT_OUTLETS:
            res = requests.head(self.url, allow_redirects=True)
            self.url = res.headers['location'] if 'location' in res.headers \
                else res.url

        # Some outlets' URLs don't play well with modifications, so those we 
        # store crufty. Otherwise, decruft with extreme prejudice.
        if self.outlet not in DELICATE_URL_OUTLETS:
            self.url = decruft_url(self.url)

    def clean(self):
        """Download the article and strip it of HTML formatting."""
        self.res = requests.get(self.url, headers={'User-Agent':USERAGENT})
        doc = Document(self.res.text)

        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_emphasis = True
        h.ignore_images = True
        h.body_width = 0

        self.plaintext = h.handle(doc.summary())

    def check_blocklist(self):
        """
        This is likely to be a long set of rules for articles not to tweet.
        """
        blocked = False

        # Rules that require a BeautifulSoup parse:
        if self.outlet in ['Miami Herald']:
            soup = BeautifulSoup(self.res.text, 'lxml')
            # Attempt to exclude AP and McClatchy articles from other feeds
            if (soup.find(attrs={'class': 'byline'}) and
                    any(syndication in
                    soup.find(attrs={'class':'byline'}).get_text().lower()
                    for syndication in ['associated press', 'mcclatchydc'])):
                blocked = True

        # Rules that do not require a BeautifulSoup parse:
        # Exclude articles in LAT "Essential Politics" feed
        # (which shows multiple articles on a single page)
        if self.outlet == 'LA Times' and '/politics/essential/' in self.url:
            blocked = True

        return blocked

    def check_for_matches(self):
        """
        Clean up an article, check it against a block list, then for matches.
        """
        self.clean()
        plaintext_grafs = self.plaintext.split('\n')

        if self.check_blocklist():
            pass
        else:
            for graf in plaintext_grafs:
                if any(phrase.lower() in graf.lower() for phrase in FOIA_PHRASES):
                    self.matching_grafs.append(graf)

    def tweet(self):
        """Send images to be rendered and tweet them with a text status."""
        square = False if len(self.matching_grafs) == 1 else True
        for graf in self.matching_grafs[:4]:
            self.imgs.append(render_img(graf, square=square))

        twitter = get_twitter_instance()

        media_ids = []

        for img in self.imgs:
            try:
                img_io = BytesIO()
                img.save(img_io, format='jpeg', quality=95)
                img_io.seek(0)
                res = twitter.upload_media(media=img_io)

                media_ids.append(res['media_id'])
            except TwythonError:
                pass

        status = "{}: {} {}".format(self.outlet, self.title, self.url)
        twitter.update_status(status=status, media_ids=media_ids)

        self.tweeted = True

def get_twitter_instance():
    """Return an authenticated twitter instance."""
    app_key = CONFIG['twitter_app_key']
    app_secret = CONFIG['twitter_app_secret']
    oauth_token = CONFIG['twitter_oauth_token']
    oauth_token_secret = CONFIG['twitter_oauth_token_secret']

    return Twython(app_key, app_secret, oauth_token, oauth_token_secret)

def get_textsize(graf, width, fnt, spacing):
    """Take text and additional parameters and return the rendered size."""
    wrapped_graf = textwrap.wrap(graf, width)

    line_spacing = fnt.getsize('A')[1] + spacing
    text_width = max(fnt.getsize(line)[0] for line in wrapped_graf)

    textsize = text_width, line_spacing * len(wrapped_graf)

    return textsize

def render_img(graf, width=60, square=False):
    """Take a paragraph and render an Image of it on a plain background."""
    font_name = 'LiberationSerif-Regular.ttf'
    fnt = ImageFont.truetype(font_name, size=36)
    spacing = 12 # Just a nice spacing number, visually

    if square is True:
        ts = {w: get_textsize(graf, w, fnt, spacing) \
                for w in range(20, width)}
        width = min(ts, key=lambda w: abs(ts.get(w)[1]-ts.get(w)[0]))

    textsize = get_textsize(graf, width, fnt, spacing)
    wrapped = '\n'.join(textwrap.wrap(graf, width))

    border = 60

    size = tuple(side + border * 2 for side in textsize)
    xy = (border, border)

    # The following color is a nice light gray. Maybe if you're forking this,
    # pick a different one for a distinct visual identity!
    im = Image.new('RGB', size, color='#F5F5F5')
    draw_obj = ImageDraw.Draw(im)
    draw_obj.multiline_text(xy, wrapped, fill='#000000', font=fnt, spacing=12)

    return im

def decruft_url(url):
    """Attempt to remove extraneous characters from a given URL and return it."""
    url = url.split('?')[0].split('#')[0]
    return url

def parse_feed(outlet, url):
    """Take the URL of an RSS feed and return a list of Article objects."""
    feed = feedparser.parse(url)

    articles = []

    for entry in feed['entries']:
        title = entry['title']
        url = entry['link']

        article = Article(outlet, title, url)

        articles.append(article)

    return articles

def main():
    database = os.path.join(FULLPATH, CONFIG['db'])
    conn = sqlite3.connect(database)

    with open(RSSFEEDFILE, 'r') as f:
        rss_feeds = json.load(f)

    for feed in rss_feeds:
        outlet = feed['outlet']
        url = feed['url']
        articles = parse_feed(outlet, url)

        recent_urls = [entry[0] for entry in list(conn.execute(
            'select url from articles where outlet=? \
             order by id desc limit 1000', (outlet,)))]

        articles = [a for a in articles if a.url and a.url not in recent_urls]

        for counter, article in enumerate(articles, 1):

            print('Checking {} article {}/{}'.format(
                article.outlet, counter, len(articles)))

            article.check_for_matches()

            if article.matching_grafs:
                print("Got one!")
                article.tweet()

            conn.execute("""insert into articles(
                         title, outlet, url, tweeted,recorded_at)
                         values (?, ?, ?, ?, ?)""",
                         (article.title, article.outlet, article.url,
                          article.tweeted, datetime.utcnow()))

            conn.commit()

            time.sleep(1)

    conn.close()

if __name__ == '__main__':
    main()
