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
'public records']

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
        self.matching_grafs = []
        self.imgs = []
        self.tweeted = False

def get_twitter_creds():
    twitter_app_key = CONFIG['twitter_app_key']
    twitter_app_secret = CONFIG['twitter_app_secret']
    twitter_oauth_token = CONFIG['twitter_oauth_token']
    twitter_oauth_token_secret = CONFIG['twitter_oauth_token_secret']

    return twitter_app_key, twitter_app_secret, twitter_oauth_token, twitter_oauth_token_secret

def get_twitter_instance():
    app_key, app_secret, oauth_token, oauth_token_secret = get_twitter_creds()

    return Twython(app_key, app_secret, oauth_token, oauth_token_secret)

def twitter_upload(imgs, twitter):
    # Take a list of Image objects and return a list of Twitter media_ids
    media_ids = []

    for img in imgs:
        try:
            img_io = BytesIO()
            img.save(img_io, format='jpeg', quality=95)
            img_io.seek(0)
            res = twitter.upload_media(media=img_io)

            media_ids.append(res['media_id'])
        except:
            pass

    return media_ids

def tweet_article(article, twitter):
    # Take an Article object, upload its images, and post it to Twitter
    media_ids = twitter_upload(article.imgs, twitter)
    status = article.outlet + ": " + article.title + " " + article.url

    twitter.update_status(status=status, media_ids=media_ids)

def render_img(graf, width=70):
    # Take a paragraph of text and return an Image object that consists of that text rendered onto a plain background.

    wrapped_list = textwrap.wrap(graf, width)
    wrapped = '\n'.join(wrapped_list)

    blank_im = Image.new('RGB', (0,0))
    blank_d = ImageDraw.Draw(blank_im)

    font_name = 'LiberationSerif-Regular.ttf'
    fnt = ImageFont.truetype(font_name, size=36)

    textsize = blank_d.multiline_textsize(wrapped, font=fnt, spacing=12)
    border = 60 

    size = tuple(side + border * 2 for side in textsize)
    xy = (border, border)

    im = Image.new('RGB', size, color='#F5F5F5')
    d = ImageDraw.Draw(im)
    d.multiline_text(xy, wrapped, fill='#000000', font=fnt, spacing=12)

    return im

def clean_article(doc):
    # Take a Readability doc and return a long string corresponding to the plain text of that article.

    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_emphasis = True
    h.body_width = 0

    plaintext_article = h.handle(doc.summary())
    return plaintext_article

def parse_feed(outlet, url):
    # Take the URL of an RSS feed and return a list of Article objects

    feed = feedparser.parse(url)

    articles = []

    for entry in feed['entries']:
        url = entry['link']
        if outlet in ['ProPublica', 'Reuters']:
            res = requests.get(url)
            url = res.url
        elif outlet == 'New York Times' and '/video/' in url:
            continue

        title = entry['title']

        articles.append(Article(outlet, title, url))

    return articles

def main():
    db = os.path.join(fullpath, CONFIG['db'])
    conn = sqlite3.connect(db)

    recent_urls = [entry[0] for entry in list(conn.execute(
        'select url from articles order by id desc limit 1000'))]

    twitter = get_twitter_instance()
    
    with open(RSSFEEDFILE, 'r') as f:
        rss_feeds = json.load(f)

    for feed in rss_feeds:
        outlet = feed['outlet']
        url = feed['url']
        articles = parse_feed(outlet, url)

        articles = [article for article in articles if article.url not in recent_urls]
        
        for counter, article in enumerate(articles, 1):
            res = requests.get(article.url)
            doc = Document(res.text)

            plaintext_article = clean_article(doc)
            matching_grafs = []

            print("Checking {} article {}/{}".format(article.outlet, counter, len(articles)))

            plaintext_grafs = plaintext_article.split('\n')
            
            for graf in plaintext_grafs:
                if any(phrase.lower() in graf.lower() for phrase in FOIA_PHRASES):
                    article.matching_grafs.append(graf)

            if article.matching_grafs:
                print("Got one!")
                width = 60 if len(article.matching_grafs) == 1 else 35
                for graf in article.matching_grafs[:4]:
                    article.imgs.append(render_img(graf, width))

                tweet_article(article, twitter)
                article.tweeted = True

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
