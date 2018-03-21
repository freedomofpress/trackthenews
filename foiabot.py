#!/usr/bin/env python3
# Parses a collection of news outlet RSS feeds for recently published articles,
# then converts those articles to plaintext and searches them for mentions of
# FOIA or other public records law, then tweets matching excerpts.

import feedparser
import html2text
import os
import requests
import textwrap
import time
import yaml
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from readability import Document
from twython import Twython

FOIA_PHRASES = [
'F.O.I.A.',
'FOIA',
'Freedom of Information Act',
'freedom of information act',
'Foia',
'open records',
'public records']

fullpath = os.path.dirname(os.path.realpath(__file__))
CONFIGFILE = os.path.join(fullpath, 'config.yaml')

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

def render_img(graf):
    # Take a paragraph of text and return an Image object that consists of that text rendered onto a plain background.

    wrapped_list = textwrap.wrap(graf)
    wrapped = '\n'.join(wrapped_list)

    blank_im = Image.new('RGB', (0,0))
    blank_d = ImageDraw.Draw(blank_im)

    font_path = os.path.join(fullpath, 'fonts', 'LiberationSerif-Regular.ttf')
    fnt = ImageFont.truetype(font_path, size=36)

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
        if outlet == 'ProPublica':
            res = requests.get(url)
            url = res.url
        elif outlet == 'New York Times' and '/video/' in url:
            continue

        title = entry['title']

        articles.append(Article(outlet, title, url))

    return articles

def main():
    rss_urls = {
        'AP':'http://hosted.ap.org/lineups/TOPHEADS.rss?SITE=PAREA&SECTION=HOME',
        'New York Times':
            'http://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml',
        'Washington Post':'http://feeds.washingtonpost.com/rss/national',
        'ProPublica':'http://feeds.propublica.org/propublica/main',
        'Buzzfeed':'https://www.buzzfeed.com/usnews.xml',
        'LA Times':'http://www.latimes.com/rss2.0.xml'}
    
    twitter = get_twitter_instance()

    for outlet in rss_urls:
        url = rss_urls[outlet]
        articles = parse_feed(outlet, url)
        
        for counter, article in enumerate(articles, 1):
            res = requests.get(article.url)
            doc = Document(res.text)

            plaintext_article = clean_article(doc)
            matching_grafs = []

            print("Checking {} article {}/{}".format(article.outlet, counter, len(articles)))

            plaintext_grafs = plaintext_article.split('\n')
            
            for graf in plaintext_grafs:
                if any(phrase in graf for phrase in FOIA_PHRASES):
                    article.matching_grafs.append(graf)

            if article.matching_grafs:
                for graf in article.matching_grafs[:4]:
                    article.imgs.append(render_img(graf))

                tweet_article(article, twitter)
                article.tweeted = True

            time.sleep(1)

if __name__ == '__main__':
    main()
