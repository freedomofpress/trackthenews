# Parses a collection of news outlet RSS feeds for recently published articles,
# then converts those articles to plaintext and searches them for mentions of
# given words or phrases, and posts the results to Twitter.

from __future__ import unicode_literals

import argparse
import importlib
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

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from readability import Document
from twython import Twython, TwythonError

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
        self.imgs = []
        self.tweeted = False

    def canonicalize_url(self):
        """Process article URL to produce something roughly canonical."""
        # These outlets use redirect links in their RSS feeds.
        # Follow those links, then store only the final destination.
        if self.redirects:
            res = requests.head(self.url, allow_redirects=True, timeout=30)
            self.url = res.headers['location'] if 'location' in res.headers \
                else res.url

        # Some outlets' URLs don't play well with modifications, so those we 
        # store crufty. Otherwise, decruft with extreme prejudice.
        if not self.delicate:
            self.url = decruft_url(self.url)

    def clean(self):
        """Download the article and strip it of HTML formatting."""
        self.res = requests.get(self.url, headers={'User-Agent':ua}, timeout=30)
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
        plaintext_grafs = self.plaintext.split('\n')

        if blocklist_loaded and blocklist.check(self):
            pass
        else:
            for graf in plaintext_grafs:
                if (any(word.lower() in graf.lower() for word in matchwords) or \
                    any(word in graf for word in matchwords_case_sensitive)):
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

        source = self.outlet + ": " if self.outlet else ''

        # Truncate title to fit in remaining characters.
        # As of 2019-03-03:
        # - Tweets can be 280 characters.
        # - Minus the length of the `source` string.
        # - Minus three more characters for the ellipsis (a two-byte character) and space between the title and the URL.
        # - Links count for 23 characters once they've been wrapped in a t.co URL.
        remaining_chars = 280 - len(source) - 3 - 23
        title = (self.title[:remaining_chars] + '…') if len(self.title) > remaining_chars else self.title

        status = "{}{} {}".format(source, title, self.url)

        twitter.update_status(status=status, media_ids=media_ids)
        print(status)

        self.tweeted = True


def get_twitter_instance():
    """Return an authenticated twitter instance."""
    app_key = config['twitter']['api_key']
    app_secret = config['twitter']['api_secret']
    oauth_token = config['twitter']['oauth_token']
    oauth_token_secret = config['twitter']['oauth_secret']

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
    font_name = config['font']
    font_dir = os.path.join(os.path.dirname(__file__), 'fonts')
    font_path = os.path.join(font_dir, font_name)
    fnt = ImageFont.truetype(font_path, size=36)
    spacing = 12 # Just a nice spacing number, visually

    graf = graf.lstrip('#>—-• ')

    if square is True:
        ts = {w: get_textsize(graf, w, fnt, spacing) \
                for w in range(20, width)}
        width = min(ts, key=lambda w: abs(ts.get(w)[1]-ts.get(w)[0]))

    textsize = get_textsize(graf, width, fnt, spacing)
    wrapped = '\n'.join(textwrap.wrap(graf, width))

    border = 60

    size = tuple(side + border * 2 for side in textsize)
    xy = (border, border)

    im = Image.new('RGB', size, color=config['color'])
    draw_obj = ImageDraw.Draw(im)
    draw_obj.multiline_text(xy, wrapped, fill='#000000', font=fnt, spacing=12)

    return im


def decruft_url(url):
    """Attempt to remove extraneous characters from a given URL and return it."""
    url = url.split('?')[0].split('#')[0]
    return url


def parse_feed(outlet, url, delicate, redirects):
    """Take the URL of an RSS feed and return a list of Article objects."""
    feed = feedparser.parse(url)

    articles = []

    for entry in feed['entries']:
        """If for some reason the entry is missing a title or URL, just leave them empty."""
        title = entry.get('title', '')
        url = entry.get('link', '')

        if not url:
            print("Entry is missing a URL. Skipping!")
            continue

        article = Article(outlet, title, url, delicate, redirects)

        articles.append(article)

    return articles


def config_twitter(config):
    if 'twitter' in config.keys():
        replace = input("Twitter configuration already exists. Replace? (Y/n) ")
        if replace.lower() in ['n','no']:
            return config

    input("Create a new Twitter app at https://apps.twitter.com/app/new to post matching stories. For this step, you can be logged in as yourself or with the posting account, if they're different. Fill out Name, Description, and Website with values meaningful to you. These are not used in trackthenews config but may be publicly visible. Then click the \"Keys and Access Tokens\" tab. ")

    api_key = input("Enter the provided API key: ")
    api_secret = input("Enter the provided API secret: ")

    input("Now ensure you are logged in with the account that will do the posting. ")

    tw = Twython(api_key, api_secret)
    auth = tw.get_authentication_tokens()

    oauth_token = auth['oauth_token']
    oauth_secret = auth['oauth_token_secret']

    tw = Twython(api_key, api_secret, oauth_token, oauth_secret)

    pin = input("Enter the pin found at {} ".format(auth['auth_url']))

    final_step = tw.get_authorized_tokens(pin)

    oauth_token = final_step['oauth_token']
    oauth_secret = final_step['oauth_token_secret']

    twitter = {'api_key': api_key, 'api_secret': api_secret,
            'oauth_token': oauth_token, 'oauth_secret': oauth_secret}

    config['twitter'] = twitter 

    return config

def setup_db(config):
    database = os.path.join(home, config['db'])
    if not os.path.isfile(database):
        conn = sqlite3.connect(database)
        schema_script = """create table articles (
            id          integer primary key not null,
            title       text,
            outlet      text,
            url         text,
            tweeted     boolean,
            recorded_at datetime
        );"""
        conn.executescript(schema_script)
        conn.commit()
        conn.close()


def setup_matchlist():
    path = os.path.join(home, 'matchlist.txt')
    path_case_sensitive = os.path.join(home, 'matchlist_case_sensitive.txt')
    
    if os.path.isfile(path):
        print("A matchlist already exists at {path}.".format(**locals()))
    else:
        with open(path, 'w') as f:
            f.write('')
        print("A new matchlist has been generated at {path}. You can add case insensitive entries to match, one per line.".format(**locals()))
       
    if os.path.isfile(path_case_sensitive):
            print("A case-sensitive matchlist already exists at {path_case_sensitive}.".format(**locals()))
    else:
        with open(path_case_sensitive, 'w') as f:
            f.write('')
        print("A new case-sensitive matchlist has been generated at {path_case_sensitive}. You can add case-sensitive entries to match, one per line.".format(**locals()))
    
    return


def setup_rssfeedsfile():
    path = os.path.join(home, 'rssfeeds.json')

    if os.path.isfile(path):
        print("An RSS feeds file already exists at {path}.".format(**locals()))
        return
    else:
        with open(path, 'w') as f:
            f.write('')
            print("A new RSS feeds file has been generated at {path}.".format(**locals()))

    return


def initial_setup():
    configfile = os.path.join(home, 'config.yaml')

    if os.path.isfile(configfile):
        with open(configfile, 'r', encoding="utf-8") as f:
            config = yaml.load(f)
    else:
        to_configure = input("It looks like this is the first time you've run trackthenews, or you've moved or deleted its configuration files.\nWould you like to create a new configuration in {}? (Y/n) ".format(home))

        config = {}
    
        if to_configure.lower() in ['n','no','q','exit','quit']:
            sys.exit("Ok, quitting the program without configuring.")

    if sys.version_info.major > 2:
        os.makedirs(home, exist_ok=True)
    else:
        try:
            os.makedirs(home)
        except:
            pass

    if 'db' not in config:
        config['db'] = 'trackthenews.db'

    if 'user-agent' not in config:
        ua = input("What would you like your script's user-agent to be? This should be something that is meaningful to you and may show up in the logs of the sites you are tracking. ")

        ua = ua + " / powered by trackthenews (a project of freedom.press)"

        config['user-agent'] = ua

    if 'color' not in config:
        config['color'] = '#F5F5F5'

    if 'font' not in config:
        config['font'] = 'NotoSerif-Regular.ttf'

    setup_matchlist()
    setup_rssfeedsfile()
    setup_db(config)
    config = config_twitter(config)

    with open(configfile, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    return config


def main():
    parser = argparse.ArgumentParser(description="Track articles from RSS feeds for a custom list of keywords and act on the matches.")

    parser.add_argument('-c', '--config', help="Run configuration process",
            action="store_true")
    parser.add_argument('dir', nargs='?',
            help="The directory to store or find the configuration files.",
            default=os.path.join(os.getcwd(), 'ttnconfig'))

    args = parser.parse_args()
    
    global home
    home = os.path.abspath(args.dir)

    print("Running with configuration files in {}".format(home))

    if args.config:
        initial_setup()
        sys.exit("Created new configuration files. Now go populate the RSS Feed file and the list of matchwords!")

    configfile = os.path.join(home, 'config.yaml')
    if not os.path.isfile(configfile):
        initial_setup()

    global config
    with open(configfile, encoding="utf-8") as f:
        config = yaml.load(f)

    global ua
    ua = config['user-agent']

    database = os.path.join(home, config['db'])
    if not os.path.isfile(database):
        setup_db(config)

    conn = sqlite3.connect(database)

    matchlist = os.path.join(home, 'matchlist.txt')
    matchlist_case_sensitive = os.path.join(home, 'matchlist_case_sensitive.txt')
    if not (os.path.isfile(matchlist) and \
            os.path.isfile(matchlist_case_sensitive)):
        setup_matchlist()

    global matchwords
    global matchwords_case_sensitive
    with open(matchlist, 'r', encoding="utf-8") as f:
        matchwords = [w for w in f.read().split('\n') if w]
    with open(matchlist_case_sensitive, 'r', encoding="utf-8") as f:
        matchwords_case_sensitive = [w for w in f.read().split('\n') if w]
 
    if not (matchwords or matchwords_case_sensitive):
            sys.exit("You must add words to at least one of the matchwords lists, located at {} and {}.".format(matchlist, matchlist_case_sensitive))

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
        print("Matching against the following case-sensitive words: {}".format(
            matchwords_case_sensitive))

    rssfeedsfile = os.path.join(home, 'rssfeeds.json')
    if not os.path.isfile(rssfeedsfile):
        setup_rssfeedsfile()

    with open(rssfeedsfile, 'r', encoding="utf-8") as f:
        try:
            rss_feeds = json.load(f)
        except json.JSONDecodeError:
            sys.exit("You must add RSS feeds to the RSS feeds list, located at {}.".format(rssfeedsfile))

    for feed in rss_feeds:
        outlet = feed['outlet'] if 'outlet' in feed else ''
        url = feed['url']
        delicate = True if 'delicateURLs' in feed and feed['delicateURLs'] \
                else False
        redirects = True if 'redirectLinks' in feed and feed['redirectLinks'] \
                else False

        articles = parse_feed(outlet, url, delicate, redirects)
        deduped = []

        for article in articles:
            article_exists = conn.execute('select * from articles where url = ?',
                    (article.url,)).fetchall()
            if not article_exists:
                deduped.append(article)

        for counter, article in enumerate(deduped, 1):
            print('Checking {} article {}/{}'.format(
                article.outlet, counter, len(deduped)))

            try:
                article.check_for_matches()
            except:
                print('Having trouble with that article. Skipping for now.')
                pass

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
