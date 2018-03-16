#!/usr/bin/env python3
# For right now, converts news articles to plain text.
# Will soon collect those news articles, parse through them for FOIA docs,
# generate an image showing the evidence of those docs, post all that
# to Twitter, and probably save the resulting text to a database.

import feedparser
import html2text
import requests
from readability import Document
import time

FOIA_PHRASES = [
'F.O.I.A',
'FOIA',
'Freedom of Information Act',
'freedom of information act',
'Foia']

def clean_article(doc):
    # Take a Readability doc and return a long string corresponding to the plain text of that article.

    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_emphasis = True
    h.body_width = 0

    plaintext_article = h.handle(doc.summary())
    return plaintext_article

def parse_feed(url):
    # Take the URL of an RSS feed and return a list of article URLs
    feed = feedparser.parse(url)
    if 'propublica.org' in url:
        links = []
        raw_links = [article['link'] for article in feed['entries']]
        for link in raw_links:
            res = requests.get(link)
            links.append(res.url)
    else:
        links = [article['link'] for article in feed['entries']]
        links = [link for link in links if '/video/' not in link]
        
    return links

def main():
    rss_urls = ['http://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml',
                'http://feeds.washingtonpost.com/rss/national',
                'http://feeds.propublica.org/propublica/main',
                'https://www.buzzfeed.com/usnews.xml',
                'http://www.latimes.com/rss2.0.xml']
                
    for url in rss_urls:
        links = parse_feed(url)
        
        for counter, link in enumerate(links, 1):
            res = requests.get(link)
            doc = Document(res.text)

            plaintext_article = clean_article(doc)
            matching_grafs = []

            print("Checking article {}/{}".format(counter, len(links)))

            plaintext_grafs = plaintext_article.split('\n')
            
            for graf in plaintext_grafs:
                for phrase in FOIA_PHRASES:
                    if phrase in graf:
                        matching_grafs.append(graf)
                        continue

            if matching_grafs:
                print(doc.title())
                print(link)
                print('\n\n'.join(matching_grafs))

            time.sleep(1)

if __name__ == '__main__':
    main()
