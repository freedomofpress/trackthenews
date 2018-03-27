#!/usr/bin/env python3
# Parses a collection of news outlet RSS feeds for recently published articles,
# then converts those articles to plaintext and searches them for mentions of
# FOIA or other public records law, then tweets matching excerpts.

import feedparser
import html2text
import json
import os
import requests
import sqlite3
import textwrap
import time
import yaml
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from readability import Document
from twython import Twython

# Comparison happens in lowercase, so no uppercase letters here!
FOIA_PHRASES = [
'f.o.i.a.',
'foia',
'freedom of information act',
'freedom of information law',
'records request',
'open records',
'public records act',
'public records law']

fullpath = os.path.dirname(os.path.realpath(__file__))
CONFIGFILE = os.path.join(fullpath, 'config.yaml')
RSSFEEDFILE = os.path.join(fullpath, 'rssfeeds.json')

with open(CONFIGFILE, 'r') as c:
    CONFIG = yaml.load(c)

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
        if self.outlet in ['ProPublica', 'Reuters']:
            res = requests.head(self.url, allow_redirects=True)
            self.url = res.headers['location'] if 'location' in res.headers \
                else res.url

        if self.outlet not in ['AP']:
            self.url = decruft_url(self.url)

    def clean(self):
        res = requests.get(self.url)
        doc = Document(res.text)

        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_emphasis = True
        h.body_width = 0

        self.plaintext = h.handle(doc.summary())

    def check_for_matches(self):
        self.clean()
        plaintext_grafs = self.plaintext.split('\n')

        for graf in plaintext_grafs:
            if any(phrase.lower() in graf.lower() for phrase in FOIA_PHRASES):
                self.matching_grafs.append(graf)

    def tweet(self):
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
            except:
                pass

        status = self.outlet + ": " + self.title + " " + self.url
        twitter.update_status(status=status, media_ids=media_ids)

        self.tweeted = True

def get_twitter_instance():
    app_key = CONFIG['twitter_app_key']
    app_secret = CONFIG['twitter_app_secret']
    oauth_token = CONFIG['twitter_oauth_token']
    oauth_token_secret = CONFIG['twitter_oauth_token_secret']

    return Twython(app_key, app_secret, oauth_token, oauth_token_secret)

def get_textsize(graf, width, fnt, spacing):
    wrapped_graf = textwrap.wrap(graf, width)

    line_spacing = fnt.getsize('A')[1] + spacing
    text_width = max(fnt.getsize(line)[0] for line in wrapped_graf)

    textsize = text_width, line_spacing * len(wrapped_graf)

    return textsize

def render_img(graf, width=60, square=False):
    # Take a paragraph of text and return an Image object that consists of that text rendered onto a plain background.

    font_name = 'LiberationSerif-Regular.ttf'
    fnt = ImageFont.truetype(font_name, size=36)
    spacing = 12 # Just a nice spacing number, visually

    if square == True:
        ts = {w: get_textsize(graf, w, fnt, spacing) \
                for w in range(20, width)}
        width = min(ts, key=lambda w: abs(ts.get(w)[1]-ts.get(w)[0]))

    textsize = get_textsize(graf, width, fnt, spacing)
    wrapped = '\n'.join(textwrap.wrap(graf, width))

    border = 60

    size = tuple(side + border * 2 for side in textsize)
    xy = (border, border)

    im = Image.new('RGB', size, color='#F5F5F5')
    d = ImageDraw.Draw(im)
    d.multiline_text(xy, wrapped, fill='#000000', font=fnt, spacing=12)

    return im

def decruft_url(url):
    url = url.split('?')[0].split('#')[0]
    return url

def parse_feed(outlet, url):
    # Take the URL of an RSS feed and return a list of Article objects
    feed = feedparser.parse(url)

    articles = []

    for entry in feed['entries']:
        title = entry['title']
        url = entry['link']

        article = Article(outlet, title, url)

        articles.append(article)

    return articles

def main():
    db = os.path.join(fullpath, CONFIG['db'])
    conn = sqlite3.connect(db)

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

            conn.execute("""
                insert into articles(title, outlet, url, tweeted, recorded_at)
                values (?, ?, ?, ?, ?)""",
                (article.title, article.outlet, article.url, article.tweeted, 
                datetime.utcnow()))

            conn.commit()

            time.sleep(1)

    conn.close()

if __name__ == '__main__':
    main()
