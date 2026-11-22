#!/usr/bin/env python3
"""Writes data/sharing.json and the thumbnails under assets/sharing/: the first
LATEST decks on Speaker Deck and the first LATEST available videos in the talk
recordings playlist on YouTube, in the order each source lists them.

    python3 tools/sharing_sources.py

Needs the network, yt-dlp and macOS's sips. The build reads only what this
writes, so run it again after a deck is uploaded or the playlist changes.
"""
import html
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from build import SHARING, thumb_path  # noqa: E402

SPEAKER_DECK = 'https://speakerdeck.com/lemiorhan'
PLAYLIST = 'https://www.youtube.com/playlist?list=PLQTv1b9jwvWdvUVfv0M55mRbTB8CMYT9R'
LATEST = 6
THUMB_WIDTH = 480
THUMB_QUALITY = '70'

DECK = re.compile(r'data-cover-image="([^"]+)">\s*'
                  r'<a class="deck-preview-link" href="(/lemiorhan/[^"]+)" title="([^"]*)"')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def parse_decks(page):
    return [{'url': 'https://speakerdeck.com' + path, 'title': ' '.join(html.unescape(title).split()),
             'cover': html.unescape(cover)} for cover, path, title in DECK.findall(page)]


def speaker_deck():
    return parse_decks(fetch(SPEAKER_DECK).decode('utf-8'))


def parse_playlist(listing):
    videos, gone = [], []
    for v in listing['entries']:
        if not v.get('title'):
            gone.append(v['id'])
            continue
        videos.append({'url': 'https://www.youtube.com/watch?v=' + v['id'],
                       'title': ' '.join(v['title'].split()), 'channel': v.get('channel') or '',
                       'cover': 'https://i.ytimg.com/vi/{}/hqdefault.jpg'.format(v['id'])})
    return videos, gone


def playlist():
    listing = json.loads(subprocess.run(['yt-dlp', '--flat-playlist', '-J', PLAYLIST],
                                        capture_output=True, text=True, check=True).stdout)
    videos, gone = parse_playlist(listing)
    if gone:
        print('skipped, no longer available: ' + ', '.join(gone))
    return videos


def save_thumb(item, crop):
    dest = os.path.join(ROOT, thumb_path(item['url']))
    new = not os.path.exists(dest)
    if new:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + '.part'
        # For a 16:9 video, hqdefault is 480x360 with black bars above and below the picture.
        shape = ['-c', str(THUMB_WIDTH * 9 // 16), str(THUMB_WIDTH)] if crop else ['--resampleWidth', str(THUMB_WIDTH)]
        try:
            with open(part, 'wb') as f:
                f.write(fetch(item['cover']))
            subprocess.run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', THUMB_QUALITY] + shape
                           + [part, '--out', dest], capture_output=True)
        finally:
            os.remove(part)
        # Its exit code does not tell: sips exits 0 on an empty file and writes nothing.
        if not os.path.exists(dest):
            sys.exit('{} from {} is not an image sips can convert'.format(thumb_path(item['url']), item['cover']))
    size = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', dest],
                          capture_output=True, text=True, check=True).stdout
    found = re.search(r'pixelWidth: (\d+)\s+pixelHeight: (\d+)', size)
    if not found:
        sys.exit('{} is not an image; delete it and run this again'.format(thumb_path(item['url'])))
    item['width'], item['height'] = int(found.group(1)), int(found.group(2))
    return new


def prune(folder, keep):
    removed = [name for name in sorted(os.listdir(folder)) if os.path.join(folder, name) not in keep]
    for name in removed:
        os.remove(os.path.join(folder, name))
    return removed


def snapshot(decks, videos):
    return {'decks': [{k: d[k] for k in ('url', 'title', 'width', 'height')} for d in decks],
            'recordings': [{k: v[k] for k in ('url', 'title', 'channel', 'width', 'height')} for v in videos]}


def main():
    decks, videos = speaker_deck()[:LATEST], playlist()[:LATEST]
    if not decks or not videos:
        sys.exit('found {} decks and {} recordings; nothing written, a source may have changed its pages'.format(
            len(decks), len(videos)))
    added = sum(save_thumb(d, crop=False) for d in decks) + sum(save_thumb(v, crop=True) for v in videos)
    keep = {os.path.join(ROOT, thumb_path(i['url'])) for i in decks + videos}
    for kind in ('decks', 'videos'):
        for name in prune(os.path.join(ROOT, 'assets', 'sharing', kind), keep):
            print('removed ' + os.path.join('assets', 'sharing', kind, name))
    with open(SHARING, 'w', encoding='utf-8') as f:
        json.dump(snapshot(decks, videos), f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('{} decks, {} recordings, {} new thumbnails'.format(len(decks), len(videos), added))


if __name__ == '__main__':
    main()
