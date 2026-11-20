"""Runs build.py as a program and checks what it promises: broken content stops
the build with a message, and the pages it writes hold together.

    python3 -m unittest discover -s tests
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


def run_build(site, out):
    return subprocess.run([sys.executable, os.path.join(site, 'build.py'), '--out', out],
                          capture_output=True, text=True)


def read_json(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as f:
        return json.load(f)


def copy_site(tmp):
    site = os.path.join(tmp, 'site')
    os.mkdir(site)
    shutil.copy(os.path.join(ROOT, 'build.py'), site)
    for d in ('content', 'assets', 'data'):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(site, d))
    return site


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    @property
    def text(self):
        return ''.join(c for c in self.children if isinstance(c, str))

    def all_text(self):
        return ''.join(c if isinstance(c, str) else c.all_text() for c in self.children)

    def classes(self):
        return (self.attrs.get('class') or '').split()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def find(self, pred):
        return [n for n in self.walk() if pred(n)]


class Tree(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node('#root', [], None)
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def has_class(name):
    return lambda n: name in n.classes()


def plain(markdown):
    return re.sub(r'\[\^(\d+)\]', r'[\1]', re.sub(r'\[([^\]]+)\]\([^)\s]+\)', r'\1', markdown))


def blocks_of(data, kind):
    parts = [data.get('head', {})] + data.get('sections', [])
    return [b for part in parts for b in part.get('blocks', []) if isinstance(b, dict) and b.get('type') == kind]


def page_file(name):
    return {'home': 'index.html', '404': '404.html'}.get(name, name + '/index.html')


def path_box(d):
    xs, ys, x, y = [], [], 0, 0
    for cmd, a, b in re.findall(r'([Ml])(-?\d+),(-?\d+)', d):
        x, y = (int(a), int(b)) if cmd == 'M' else (x + int(a), y + int(b))
        xs.append(x)
        ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def rings(d):
    out = []
    for sub in re.findall(r'M[^M]*', d):
        x = y = 0
        ring = []
        for cmd, a, b in re.findall(r'([Ml])(-?\d+),(-?\d+)', sub):
            x, y = (int(a), int(b)) if cmd == 'M' else (x + int(a), y + int(b))
            ring.append((x, y))
        out.append(ring)
    return out


def inside(point, ring):
    x, y = point
    hit = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def jpeg_size(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:2] != b'\xff\xd8':
        raise AssertionError(path + ' is not a JPEG')
    i = 2
    while data[i] == 0xFF:
        while data[i] == 0xFF:
            i += 1
        marker, length = data[i], int.from_bytes(data[i + 1:i + 3], 'big')
        # C4, C8 and CC sit in the SOF range but are DHT, JPG and DAC, not frame headers.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 6:i + 8], 'big'), int.from_bytes(data[i + 4:i + 6], 'big')
        i += 1 + length
    raise AssertionError(path + ' has no frame header')


def webp_size(path):
    with open(path, 'rb') as f:
        data = f.read(30)
    if data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        raise AssertionError(path + ' is not a WebP')
    chunk = data[12:16]
    if chunk == b'VP8 ' and data[23:26] == b'\x9d\x01\x2a':
        return int.from_bytes(data[26:28], 'little') & 0x3FFF, int.from_bytes(data[28:30], 'little') & 0x3FFF
    if chunk == b'VP8L' and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], 'little')
        return (bits & 0x3FFF) + 1, (bits >> 14 & 0x3FFF) + 1
    if chunk == b'VP8X':
        return int.from_bytes(data[24:27], 'little') + 1, int.from_bytes(data[27:30], 'little') + 1
    raise AssertionError('{} has an unknown WebP chunk {!r}'.format(path, chunk))


def png_size(path):
    with open(path, 'rb') as f:
        data = f.read(24)
    if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise AssertionError(path + ' is not a PNG')
    return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')


def css_values(css, selector, prop):
    bodies = re.findall(r'(?m)^\s*' + re.escape(selector) + r'\s*\{([^}]*)\}', css)
    return [v.strip() for body in bodies for v in re.findall(r'(?:^|[;\s])' + re.escape(prop) + r':([^;]+);', body)]


class BrokenContentStopsTheBuild(unittest.TestCase):
    def build_with(self, change):
        with tempfile.TemporaryDirectory() as tmp:
            site = copy_site(tmp)
            change(site)
            return run_build(site, os.path.join(tmp, 'out'))

    def assertRejected(self, change, message):
        result = self.build_with(change)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('build failed: ', result.stderr)
        self.assertIn(message, result.stderr)

    def test_an_unchanged_copy_builds(self):
        result = self.build_with(lambda site: None)
        self.assertEqual(result.returncode, 0, result.stderr)

    # Content edits

    @staticmethod
    def edit(name, fn):
        def change(site):
            path = os.path.join(site, 'content', name + '.json')
            data = read_json(path)
            fn(data)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        return change

    @staticmethod
    def replace(name, old, new):
        def change(site):
            path = os.path.join(site, 'content', name + '.json')
            with open(path, encoding='utf-8') as f:
                source = f.read()
            assert old in source, old
            with open(path, 'w', encoding='utf-8') as f:
                f.write(source.replace(old, new, 1))
        return change

    @staticmethod
    def sources(data):
        return next(b for s in data['sections'] for b in s['blocks']
                    if isinstance(b, dict) and b.get('type') == 'sources' and b.get('cited'))

    @staticmethod
    def events(data):
        return [ev for evs in data['archive']['events'].values() for ev in evs]

    # Citations

    def test_a_citation_with_no_listed_source(self):
        self.assertRejected(self.edit('bio', lambda d: self.sources(d)['items'].pop()), 'cites sources that are not listed')

    def test_a_listed_source_never_cited(self):
        self.assertRejected(self.edit('root-bug', lambda d: self.sources(d)['items'].append('[x](https://example.com)')),
                            'sources listed but never cited')

    def test_a_zero_padded_citation(self):
        self.assertRejected(self.replace('bio', '[^1]', '[^01]'), '[^01] is not rendered as a citation')

    def test_a_citation_on_the_not_found_page(self):
        self.assertRejected(self.edit('404', lambda d: d['blocks'].append('Gone.[^1]')), 'cites sources that are not listed')

    def test_a_citation_in_a_field_that_renders_no_links(self):
        def label(d):
            d['sections'][0]['blocks'][0]['items'][0]['label'] += '[^1]'
        self.assertRejected(self.edit('bio', label), '[^1] is not rendered as a citation')

    def test_two_cited_source_blocks_on_one_page(self):
        def twice(d):
            d['sections'][0]['blocks'].append(json.loads(json.dumps(self.sources(d))))
        self.assertRejected(self.edit('bio', twice), 'the same ref-n ids')

    # Places

    def test_an_unknown_place(self):
        def atlantis(d):
            next(ev for ev in self.events(d) if ev.get('place'))['place'] = 'atlantis'
        self.assertRejected(self.edit('talks', atlantis), "which archive.places does not define")

    def test_a_place_without_a_country(self):
        self.assertRejected(self.edit('talks', lambda d: d['archive']['places']['kyiv'].pop('country')), 'needs "country"')

    def test_a_place_in_a_country_not_named(self):
        self.assertRejected(self.edit('talks', lambda d: d['archive']['countries'].pop('RO')),
                            'which archive.countries does not name')

    def test_a_country_with_no_outline(self):
        def nowhere(d):
            d['archive']['countries']['ZZ'] = 'Nowhere'
            d['archive']['places']['kyiv']['country'] = 'ZZ'
        self.assertRejected(self.edit('talks', nowhere), 'has no outline for country ZZ')

    def test_a_country_with_no_flag(self):
        self.assertRejected(lambda site: os.remove(os.path.join(site, 'assets', 'flags', 'ro.svg')),
                            'no flag for country RO')

    def test_a_place_in_turkiye_without_a_province(self):
        self.assertRejected(self.edit('talks', lambda d: d['archive']['places']['istanbul'].pop('province')),
                            'needs "province"')

    def test_a_place_abroad_without_a_latitude(self):
        self.assertRejected(self.edit('talks', lambda d: d['archive']['places']['kyiv'].pop('lat')),
                            'needs "lat" and "lon"')

    def test_a_place_abroad_without_a_longitude(self):
        self.assertRejected(self.edit('talks', lambda d: d['archive']['places']['kyiv'].pop('lon')),
                            'needs "lat" and "lon"')

    def test_a_place_abroad_without_a_city(self):
        self.assertRejected(self.edit('talks', lambda d: d['archive']['places']['kyiv'].pop('city')), 'needs "city"')

    def test_online_events_without_a_label(self):
        self.assertRejected(self.edit('talks', lambda d: d['archive'].pop('online')), 'archive.online gives no label')

    def test_a_map_with_only_online_events(self):
        def online(d):
            for ev in self.events(d):
                if ev.get('place'):
                    ev['place'] = 'online'
        self.assertRejected(self.edit('talks', online), 'needs at least one event at a place on the map')

    # Contact form

    @staticmethod
    def contact_form(data):
        return blocks_of(data, 'form')[0]

    def test_a_contact_form_without_an_access_key(self):
        self.assertRejected(self.edit('contact', lambda d: self.contact_form(d).pop('access_key')),
                            'content/contact.json: the form block needs the Web3Forms access_key of the form, a UUID; it has None')

    def test_a_contact_form_whose_access_key_is_not_a_uuid(self):
        self.assertRejected(self.edit('contact', lambda d: self.contact_form(d).update(access_key='YOUR_ACCESS_KEY_HERE')),
                            "the form block needs the Web3Forms access_key of the form, a UUID; it has 'YOUR_ACCESS_KEY_HERE'")

    def test_a_contact_form_whose_access_key_is_a_uuid_with_a_newline_after_it(self):
        key = '3e8b01e6-5277-4444-9f94-618c43765be8\n'
        self.assertRejected(self.edit('contact', lambda d: self.contact_form(d).update(access_key=key)),
                            'a UUID; it has {!r}'.format(key))

    def test_a_contact_form_without_one_of_its_status_lines(self):
        self.assertRejected(self.edit('contact', lambda d: self.contact_form(d)['status'].pop('failed')),
                            "a 'form' block is missing 'failed'")

    # Sharing

    def test_a_share_image_without_its_size(self):
        self.assertRejected(self.edit('site', lambda d: d['image'].pop('height')),
                            'share image assets/img/social.jpg needs "width" and "height" in pixels')

    def test_a_share_image_that_does_not_exist(self):
        def gone(d):
            d['image']['src'] = 'assets/img/nowhere.jpg'
        self.assertRejected(self.edit('site', gone), 'share image assets/img/nowhere.jpg does not exist')

    def test_a_share_image_whose_size_is_not_a_number(self):
        def flag(d):
            d['image']['width'] = True
        self.assertRejected(self.edit('site', flag),
                            'share image assets/img/social.jpg needs "width" and "height" in pixels')

    def test_a_person_image_that_does_not_exist(self):
        def gone(d):
            d['person']['image'] = 'assets/img/nowhere.jpg'
        self.assertRejected(self.edit('home', gone), 'person image assets/img/nowhere.jpg does not exist')

    # Themes

    def git_talk(self, d):
        return next(t for ev in self.events(d) if ev['name'] == 'Karabük Üniversitesi Programlama Günleri 2016'
                    for t in ev['talks'] if t.get('title') == 'Git: Not What You Think')

    def test_a_titled_talk_without_themes(self):
        self.assertRejected(self.edit('talks', lambda d: self.git_talk(d).pop('themes')),
                            "talk 'Git: Not What You Think' at 'Karabük Üniversitesi Programlama Günleri 2016' needs \"themes\"")

    def test_a_titled_talk_with_an_empty_theme_list(self):
        def empty(d):
            self.git_talk(d)['themes'] = []
        self.assertRejected(self.edit('talks', empty), "talk 'Git: Not What You Think' at 'Karabük Üniversitesi Programlama Günleri 2016' needs \"themes\"")

    def test_an_untitled_talk_without_themes(self):
        def untitled(d):
            ev = next(ev for ev in self.events(d) if ev['name'] == 'WeekEng 2021')
            ev['talks'][0].pop('themes')
        self.assertRejected(self.edit('talks', untitled),
                            "talk 'https://www.youtube.com/watch?v=FFYDNTWG-JI' at 'WeekEng 2021' needs \"themes\"")

    def test_an_untitled_talk_with_several_videos_is_named_by_its_first(self):
        def untitled(d):
            talk = next(ev for ev in self.events(d) if ev['name'] == 'WeekEng 2021')['talks'][0]
            talk.pop('themes')
            talk['video'] = [talk['video'], 'https://example.com/second']
        self.assertRejected(self.edit('talks', untitled),
                            "talk 'https://www.youtube.com/watch?v=FFYDNTWG-JI' at 'WeekEng 2021' needs \"themes\"")

    def test_themes_that_are_not_a_list(self):
        def bare(d):
            self.git_talk(d)['themes'] = 'git'
        self.assertRejected(self.edit('talks', bare), 'must be a list of theme keys')

    def test_themes_that_are_not_names(self):
        def numbered(d):
            self.git_talk(d)['themes'] = [7]
        self.assertRejected(self.edit('talks', numbered), 'must be a list of theme keys')

    def test_a_talk_about_a_theme_the_vocabulary_does_not_define(self):
        def kotlin(d):
            self.git_talk(d)['themes'].append('kotlin')
        self.assertRejected(self.edit('talks', kotlin), "is about 'kotlin', which archive.themes.items does not define")

    def test_a_talk_video_that_is_neither_a_url_nor_a_list_of_urls(self):
        for video in ([7], 7, {'url': 'https://example.com/v'}, '', ['']):
            def odd(d):
                self.git_talk(d)['video'] = video
            with self.subTest(video=video):
                self.assertRejected(self.edit('talks', odd), 'must be a URL or a list of URLs')

    def test_a_bad_video_on_a_recent_talk_is_blamed_on_talks_json(self):
        def newest(d):
            talk = next(t for _, evs in sorted(d['archive']['events'].items(), reverse=True) for ev in evs for t in ev.get('talks', []))
            talk.pop('slides', None)
            talk['video'] = 7
        self.assertRejected(self.edit('talks', newest), 'build failed: content/talks.json: video of a talk at')

    def test_a_bad_spoken_or_place_on_a_recent_talk_is_blamed_on_talks_json(self):
        def newest(d):
            return next(ev for _, evs in sorted(d['archive']['events'].items(), reverse=True) for ev in evs if ev.get('talks'))
        def spoken(d):
            newest(d)['spoken'] = ['tr']
        def place(d):
            newest(d)['place'] = 'atlantis'
        for change, message in ((spoken, '"spoken" of event'), (place, 'event')):
            with self.subTest(change=change.__name__):
                self.assertRejected(self.edit('talks', change), 'build failed: content/talks.json: ' + message)

    def test_an_event_that_states_no_spoken_language(self):
        for name in ('Devoxx Belgium 2022', 'Iqra – Okuyun', 'IT Serbia Podcast'):
            def unstated(d):
                next(ev for ev in self.events(d) if ev['name'] == name).pop('spoken')
            with self.subTest(event=name):
                self.assertRejected(self.edit('talks', unstated), 'content/talks.json: event {!r} needs "spoken"'.format(name))

    def test_a_spoken_value_that_is_not_a_language_code(self):
        for name in ('IT Serbia Podcast', 'Devoxx Belgium 2022'):
            for spoken in (['en'], {'x': 1}, 7, '', None):
                def odd(d):
                    next(ev for ev in self.events(d) if ev['name'] == name)['spoken'] = spoken
                with self.subTest(event=name, spoken=spoken):
                    self.assertRejected(self.edit('talks', odd), 'content/talks.json: "spoken" of event {!r} must be a language code'.format(name))

    def test_a_spoken_language_that_archive_spoken_gives_no_label_for(self):
        def german(d):
            next(ev for ev in self.events(d) if ev['name'] == 'IT Serbia Podcast')['spoken'] = 'de'
        self.assertRejected(self.edit('talks', german),
                            "content/talks.json: event 'IT Serbia Podcast' is in language 'de', which archive.spoken gives no label for")

    def test_a_talk_listing_one_theme_twice(self):
        def twice(d):
            self.git_talk(d)['themes'] = ['git', 'git']
        self.assertRejected(self.edit('talks', twice), 'lists a theme twice')

    def test_a_theme_no_talk_is_about(self):
        def cobol(d):
            d['archive']['themes']['items']['cobol'] = 'COBOL'
        self.assertRejected(self.edit('talks', cobol), 'archive.themes.items defines cobol, but no talk is about it')

    def test_a_theme_key_that_is_not_lowercase_words(self):
        def spaced(d):
            items = d['archive']['themes']['items']
            items['Code Review'] = items.pop('code-review')
            for ev in self.events(d):
                for t in ev.get('talks', []):
                    t['themes'] = ['Code Review' if k == 'code-review' else k for k in t.get('themes', [])]
        self.assertRejected(self.edit('talks', spaced), "theme key 'Code Review' must be lowercase words joined by hyphens")

    # Hero

    def test_hero_text_asking_for_a_number_nobody_computes(self):
        def ask(d):
            d['hero']['text'] += ' {talks} talks.'
        self.assertRejected(self.edit('home', ask), 'hero.text asks for {talks}, which build.py does not compute')

    def test_hero_naming_a_community_that_community_json_does_not_list(self):
        def rename(d):
            d['hero']['community'] = 'Nowhere Guild'
        self.assertRejected(self.edit('home', rename), "hero.community 'Nowhere Guild' needs an item of that title")

    def test_a_stage_photo_whose_talk_no_event_lists(self):
        def rename(d):
            d['hero']['photo']['talk'] = 'A Talk Never Given'
        self.assertRejected(self.edit('home', rename), "hero.photo.talk 'A Talk Never Given' must name a talk given at "
                            'exactly one event in content/talks.json; it was given at none')

    def test_a_stage_photo_whose_talk_was_given_at_several_events(self):
        talk = 'Unlearn Unit Testing'
        names = [ev['name'] for ev in self.events(read_json(ROOT, 'content', 'talks.json'))
                 if any(t.get('title') == talk for t in ev.get('talks', []))]
        self.assertGreater(len(names), 1)

        def rename(d):
            d['hero']['photo']['talk'] = talk
        self.assertRejected(self.edit('home', rename), 'it was given at ' + ', '.join(repr(n) for n in names))

    def test_a_photo_caption_or_alt_asking_for_a_fact_nobody_computes(self):
        for field in ('caption', 'alt'):
            with self.subTest(field=field):
                def ask(d):
                    d['hero']['photo'][field] += ' at {venue}'
                self.assertRejected(self.edit('home', ask),
                                    'hero.photo.{} asks for {{venue}}, which build.py does not compute'.format(field))

    # Game levels

    @staticmethod
    def level(fn, i=0):
        return BrokenContentStopsTheBuild.edit('home', lambda d: fn(d['game']['levels'][i]))

    def test_a_level_without_alternatives(self):
        self.assertRejected(self.level(lambda lv: lv['checks'].pop('alternatives')),
                            'game level \'first-commit\' needs "checks.alternatives"')

    def test_a_level_without_near_misses(self):
        self.assertRejected(self.level(lambda lv: lv['checks'].pop('near_misses')),
                            'game level \'first-commit\' needs "checks.near_misses"')

    def test_a_level_with_no_alternatives(self):
        self.assertRejected(self.level(lambda lv: lv['checks'].update(alternatives=[])),
                            'game level \'first-commit\' has an empty "checks.alternatives"')

    def test_a_level_with_no_near_misses(self):
        self.assertRejected(self.level(lambda lv: lv['checks'].update(near_misses=[])),
                            'game level \'first-commit\' has an empty "checks.near_misses"')

    def test_a_check_entry_that_is_one_line_instead_of_a_list(self):
        self.assertRejected(self.level(lambda lv: lv['checks'].update(near_misses=['git commit'])),
                            'game level \'first-commit\' lists "checks.near_misses" entries that are not lists')

    def test_a_level_fact_without_a_link(self):
        self.assertRejected(self.level(lambda lv: lv['fact'].pop('link'), 4), 'game level \'amend\' needs "fact.link"')

    def test_a_level_whose_teaches_is_not_a_list_of_non_empty_strings(self):
        for teaches in ('rebase', [], [''], ['   '], ['git commit', 3]):
            with self.subTest(teaches=teaches):
                self.assertRejected(self.level(lambda lv: lv.update(teaches=teaches), 2),
                                    'game level \'no-ff\' needs "teaches" as a non-empty list of non-empty strings')

    def test_a_level_fact_whose_text_or_link_is_not_a_non_empty_string(self):
        for key in ('text', 'link'):
            for value in ('', '   ', None, 7):
                with self.subTest(key=key, value=value):
                    self.assertRejected(self.level(lambda lv: lv['fact'].update({key: value}), 4),
                                        'game level \'amend\' needs "fact.{}" as a non-empty string'.format(key))

    def test_a_level_field_of_the_wrong_type(self):
        cases = [('fact', 'Read the docs', 'needs "fact" as an object'),
                 ('fact', ['Read the docs'], 'needs "fact" as an object'),
                 ('checks', 'git commit', 'needs "checks" as an object'),
                 ('checks', [['git commit']], 'needs "checks" as an object'),
                 ('setup', 'git commit -m "Abstract"', 'needs "setup" as a list'),
                 ('setup', 7, 'needs "setup" as a list'),
                 ('solution', 'git commit --amend', 'needs "solution" as a list'),
                 ('solution', {'git': 'commit'}, 'needs "solution" as a list'),
                 ('id', 7, 'needs "id" as a non-empty string'),
                 ('id', ['amend'], 'needs "id" as a non-empty string'),
                 ('id', '   ', 'needs "id" as a non-empty string')]
        for key, value, message in cases:
            with self.subTest(key=key, value=value):
                self.assertRejected(self.level(lambda lv: lv.update({key: value}), 4), message)

    def test_a_game_with_no_levels(self):
        self.assertRejected(self.edit('home', lambda d: d['game'].update(levels=[])), 'game.levels must list at least one level')

    def test_two_levels_with_one_id(self):
        def twin(d):
            d['game']['levels'][2]['id'] = d['game']['levels'][1]['id']
        self.assertRejected(self.edit('home', twin), "two game levels have the id 'branch'")

    def test_a_level_without_a_solution(self):
        self.assertRejected(self.level(lambda lv: lv.pop('solution')), 'game level \'first-commit\' needs "solution"')

    def test_a_level_with_an_empty_solution(self):
        self.assertRejected(self.level(lambda lv: lv.update(solution=[])), 'game level \'first-commit\' has an empty "solution"')

    def test_a_setup_line_that_is_not_git(self):
        self.assertRejected(self.level(lambda lv: lv['setup'].append('commit -m "x"'), 1),
                            'game level \'branch\' has a "setup" line that does not start with "git "')

    def test_a_solution_line_that_is_not_git(self):
        self.assertRejected(self.level(lambda lv: lv['solution'].append('gti commit'), 1),
                            'game level \'branch\' has a "solution" line that does not start with "git "')

    def test_an_alternative_line_that_is_not_git(self):
        self.assertRejected(self.level(lambda lv: lv['checks']['alternatives'][-1].append('undo'), 3),
                            'game level \'tag\' has a "checks.alternatives" line that does not start with "git "')

    def test_a_near_miss_line_that_is_not_git(self):
        self.assertRejected(self.level(lambda lv: lv['checks']['near_misses'][-1].append('hint'), 3),
                            'game level \'tag\' has a "checks.near_misses" line that does not start with "git "')


class ContentRendersAsText(unittest.TestCase):
    MARK = 'Mk&<xmark>x</xmark>"&lt;'
    ROLE = ('Tools & <b>tips</b>, co-founder of [Craft & gate](https://example.com/?a=1&b=2) '
            'and [pair-programming](https://example.com/watch?v=git-graph), full-time work.')
    KEEP = {'url', 'talk', 'community'}

    @classmethod
    def plant(cls, value, key=None):
        if isinstance(value, dict):
            return {k: cls.plant(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [cls.plant(v, key) for v in value]
        if isinstance(value, str) and key not in cls.KEEP:
            return value + ' ' + cls.MARK
        return value

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        site = copy_site(cls.tmp.name)
        path = os.path.join(site, 'content', 'home.json')
        data = read_json(path)
        data['hero']['role'] = cls.ROLE
        for part in ('hero', 'game'):
            data[part] = cls.plant(data[part])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        cls.game = data['game']
        path = os.path.join(site, 'content', '404.json')
        data = read_json(path)
        data['maze'] = cls.plant(data['maze'])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        cls.maze = data['maze']
        out = os.path.join(cls.tmp.name, 'out')
        result = run_build(site, out)
        if result.returncode:
            raise AssertionError(result.stderr)
        with open(os.path.join(out, 'index.html'), encoding='utf-8') as f:
            cls.source = f.read()
        cls.tree = Tree(cls.source).root
        with open(os.path.join(out, '404.html'), encoding='utf-8') as f:
            cls.not_found = f.read()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_hero_role_is_escaped_and_keeps_its_link_and_unbroken_words(self):
        self.assertEqual([line.strip() for line in self.source.splitlines() if 'class="hero-role"' in line],
                         ['<p class="hero-role">Tools &amp; &lt;b&gt;tips&lt;/b&gt;, <span class="nobr">co-founder</span> of '
                          '<a href="https://example.com/?a=1&amp;b=2">Craft &amp; gate</a> and '
                          '<a href="https://example.com/watch?v=git-graph"><span class="nobr">pair-programming</span></a>, '
                          '<span class="nobr">full-time</span> work. '
                          'Mk&amp;&lt;xmark&gt;x&lt;/xmark&gt;"&amp;lt;</p>'])

    def test_every_hero_and_game_string_renders_as_text(self):
        sections = self.tree.find(lambda n: n.attrs.get('id') in ('top', 'play'))
        self.assertEqual([n.tag for n in sections], ['section', 'section'])
        self.assertEqual(self.tree.find(lambda n: n.tag == 'xmark'), [])

        def place(node):
            while not node.classes():
                node = node.parent
            return node.classes()[0]

        found = set()
        for node in (n for s in sections for n in s.walk() if n.tag != 'script'):
            strings = [(place(node), c) for c in node.children if isinstance(c, str)]
            strings += [('{}[{}]'.format(node.tag, name), v) for name, v in node.attrs.items() if v]
            for where, s in strings:
                if 'Mk&' in s:
                    self.assertIn(self.MARK, s, where)
                    found.add(where)
        self.assertEqual(found, {'hero-name', 'hero-role', 'hero-intro', 'hero-play', 'hero-more', 'ul[aria-label]',
                                 'profiles', 'hero-ref', 'img[alt]', 'hero-caption', 'ol[aria-label]',
                                 'game-head', 'cmd', 'game-intro', 'gg-fallback'})

    def test_the_game_data_island_holds_no_angle_bracket_a_browser_could_end_it_on(self):
        start = self.source.index('<script type="application/json" id="git-game-data">')
        start = self.source.index('>', start) + 1
        body = self.source[start:self.source.index('</script>', start)]
        self.assertNotIn('<', body)
        island = json.loads(body)
        self.assertEqual(island['ui'], self.game['ui'])
        self.assertEqual([lv['story'] for lv in island['levels']], [lv['story'] for lv in self.game['levels']])
        self.assertIn(self.MARK, island['levels'][0]['story'])

    def test_the_maze_strings_render_as_text_and_its_island_holds_no_angle_bracket(self):
        tree = Tree(self.not_found).root
        self.assertEqual(tree.find(lambda n: n.tag == 'xmark'), [])
        section = tree.find(lambda n: 'data-maze' in n.attrs)[0]
        self.assertEqual([n.all_text() for n in section.find(lambda n: n.tag in ('h2', 'p'))],
                         [self.maze['title'], self.maze['intro']])
        self.assertIn(self.MARK, self.maze['title'])
        start = self.not_found.index('<script type="application/json" id="maze-data">')
        start = self.not_found.index('>', start) + 1
        body = self.not_found[start:self.not_found.index('</script>', start)]
        self.assertNotIn('<', body)
        self.assertEqual(json.loads(body), {'ui': self.maze['ui']})
        self.assertIn(self.MARK, self.maze['ui']['over'])


class NotFoundWithoutAMaze(unittest.TestCase):
    def test_without_a_maze_in_404_json_the_page_builds_with_no_trace_of_the_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = copy_site(tmp)
            path = os.path.join(site, 'content', '404.json')
            data = read_json(path)
            del data['maze']
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            out = os.path.join(tmp, 'out')
            result = run_build(site, out)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(os.path.join(out, '404.html'), encoding='utf-8') as f:
                html = f.read()
        self.assertNotIn('maze', html)
        self.assertEqual([n.all_text() for n in Tree(html).root.find(lambda n: n.tag == 'h1')], [data['heading']])


class BuiltSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = cls.tmp.name
        result = run_build(ROOT, cls.out)
        if result.returncode:
            raise AssertionError(result.stderr)
        names = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, 'content'))
                       if f.endswith('.json') and f != 'site.json')
        cls.html, cls.trees = {}, {}
        for name in names:
            with open(os.path.join(cls.out, page_file(name)), encoding='utf-8') as f:
                cls.html[name] = f.read()
            cls.trees[name] = Tree(cls.html[name]).root
        cls.talks = read_json(ROOT, 'content', 'talks.json')['archive']

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_content_file_became_a_page(self):
        self.assertIn('talks', self.trees)
        self.assertIn('bio', self.trees)
        self.assertIn('root-bug', self.trees)

    def test_fragment_links_reach_a_unique_id_on_their_page(self):
        for name, tree in self.trees.items():
            ids = [n.attrs['id'] for n in tree.walk() if n.attrs.get('id')]
            self.assertEqual([i for i, c in Counter(ids).items() if c > 1], [], name)
            targets = [n.attrs['href'][1:] for n in tree.walk() if (n.attrs.get('href') or '').startswith('#')]
            self.assertEqual(sorted(set(t for t in targets if t not in ids)), [], name)
        for name in ('bio', 'root-bug'):
            refs = re.findall(r'href="#ref-\d+"', self.html[name])
            contents = self.trees[name].find(lambda n: n.tag == 'a' and n.parent and n.parent.tag == 'li'
                                             and (n.attrs.get('href') or '').startswith('#')
                                             and not n.attrs['href'].startswith('#ref-'))
            self.assertGreater(len(refs), 0, name)
            self.assertGreater(len(contents), 0, name)

    def test_contents_lists_every_section_heading_in_order(self):
        seen = 0
        for name, tree in self.trees.items():
            data = read_json(ROOT, 'content', name + '.json')
            for _ in blocks_of(data, 'contents'):
                want = [('#' + s['id'], s['heading']) for s in data['sections'] if s.get('heading')]
                nav = tree.find(lambda n: n.tag == 'nav' and 'contents' in n.classes())[0]
                self.assertEqual([(a.attrs['href'], a.all_text()) for a in nav.find(lambda n: n.tag == 'a')], want, name)
                seen += 1
        self.assertGreaterEqual(seen, 2)

    def test_infobox_shows_every_item_of_its_block(self):
        seen = 0
        for name, tree in self.trees.items():
            boxes = blocks_of(read_json(ROOT, 'content', name + '.json'), 'infobox')
            rendered = tree.find(lambda n: n.tag == 'dl' and 'infobox' in n.classes())
            self.assertEqual(len(rendered), len(boxes), name)
            for box, dl in zip(boxes, rendered):
                rows = [d for d in dl.children if isinstance(d, Node) and d.tag == 'div']
                got = [(r.find(lambda n: n.tag == 'dt')[0].all_text(), r.find(lambda n: n.tag == 'dd')[0].all_text())
                       for r in rows]
                self.assertEqual(got, [(i['label'], plain(i['text'])) for i in box['items']], name)
                seen += 1
        self.assertGreaterEqual(seen, 2)

    def test_by_year_lists_every_item_under_its_year_newest_first(self):
        got_on = {}
        for name, tree in self.trees.items():
            blocks = blocks_of(read_json(ROOT, 'content', name + '.json'), 'by-year')
            rendered = tree.find(lambda n: n.tag == 'dl' and 'by-year' in n.classes())
            self.assertEqual(len(rendered), len(blocks), name)
            for block, dl in zip(blocks, rendered):
                rows = [c for c in dl.children if isinstance(c, Node)]
                self.assertEqual({row.tag for row in rows}, {'div'}, name)
                got = [(row.find(lambda n: n.tag == 'dt')[0].all_text(),
                        [(li.find(lambda n: n.tag == 'strong')[0].all_text(), li.find(lambda n: n.tag == 'span')[0].all_text())
                         for li in row.find(lambda n: n.tag == 'li')])
                       for row in rows]
                self.assertEqual(got, [(g['year'], [(plain(i['title']), plain(i['text'])) for i in g['items']])
                                       for g in block['groups']], name)
                years = [int(year) for year, _ in got]
                self.assertEqual(years, sorted(set(years), reverse=True), name)
                got_on.setdefault(name, []).extend(got)
        honors, = self.trees['career'].find(lambda n: n.attrs.get('id') == 'honors')
        self.assertEqual(honors.find(lambda n: n.tag == 'h2')[0].all_text(), 'Honors and awards')
        self.assertEqual(len(honors.find(has_class('by-year'))), 1)
        self.assertIn(('1999', ["Dean's Award", 'First Prize, Quality Improvement Teams Contest',
                                'Second Prize, Quality Improvement Teams Contest', "Dean's Award"]),
                      [(year, [title for title, _ in items]) for year, items in got_on['career']])

    def test_by_year_puts_the_year_in_the_stages_year_column_with_a_rule_between_years(self):
        with open(os.path.join(ROOT, 'assets', 'site.css'), encoding='utf-8') as f:
            css = f.read()
        self.assertTrue(self.trees['career'].find(lambda n: n.tag == 'dl' and n.classes() == ['by-year']))
        stages = css_values(css, '.stages > div', 'grid-template-columns')
        self.assertEqual(len(stages), 1, stages)
        self.assertEqual(css_values(css, '.by-year > div', 'display'), ['grid'])
        self.assertEqual(css_values(css, '.by-year > div', 'grid-template-columns'), stages)
        self.assertEqual(css_values(css, '.by-year > div', 'border-top'), ['1px solid var(--rule)'])
        self.assertEqual(css_values(css, '.by-year > div:first-child', 'border-top'), ['0'])

    def test_facts_groups_keep_the_same_gap_in_one_column_and_in_two(self):
        with open(os.path.join(ROOT, 'assets', 'site.css'), encoding='utf-8') as f:
            css = f.read()
        groups = blocks_of(read_json(ROOT, 'content', 'career.json'), 'facts')[0]['groups']
        self.assertGreater(len(groups), 2, 'with two groups or fewer the two-column grid has no second row to space')
        two = re.findall(r'@media \(min-width: ([\d.]+)rem\) \{\s*\.facts \{[^}]*row-gap: ([^;]+);', css)
        one = re.findall(r'@media \(max-width: ([\d.]+)rem\) \{\s*\.facts > div \+ div \{[^}]*margin-top: ([^;]+);', css)
        self.assertEqual(len(two), 1, two)
        self.assertEqual(len(one), 1, one)
        (wide, row_gap), (narrow, margin) = two[0], one[0]
        self.assertEqual(row_gap, margin)
        self.assertTrue(0 < float(wide) - float(narrow) < 0.1, (wide, narrow))
        self.assertEqual(css_values(css, '.facts', 'row-gap'), [row_gap])
        self.assertEqual(css_values(css, '.facts > div + div', 'margin-top'), [margin])
        self.assertEqual([g.split()[0] for g in css_values(css, '.facts', 'gap')], ['0'])

    def test_flags_point_at_files_that_exist(self):
        seen = 0
        for name, tree in self.trees.items():
            for img in tree.find(lambda n: n.tag == 'img' and 'assets/flags/' in (n.attrs.get('src') or '')):
                path = os.path.normpath(os.path.join(self.out, os.path.dirname(page_file(name)), img.attrs['src']))
                self.assertTrue(os.path.isfile(path), path)
                seen += 1
        self.assertGreater(seen, 0)

    def expected_places(self):
        countries, regions = Counter(), Counter()
        total = 0
        for evs in self.talks['events'].values():
            for ev in evs:
                total += 1
                key = ev.get('place')
                if key == 'online':
                    countries['online'] += 1
                elif key:
                    p = self.talks['places'][key]
                    countries[p['country']] += 1
                    regions[p['province'] if p['country'] == 'TR' else key] += 1
        return total, countries, regions

    def test_place_chips_count_the_events_in_talks_json(self):
        total, countries, regions = self.expected_places()
        tree = self.trees['talks']
        controls = tree.find(has_class('tmap-controls'))[0]
        chips = controls.find(lambda n: n.tag == 'button')
        count = {}
        for b in chips:
            n = int(b.find(has_class('n'))[0].text)
            count[b.attrs.get('data-region') or ('country', b.attrs['data-country'])] = n
        self.assertEqual(count[('country', '')], total)
        self.assertEqual({k[1]: v for k, v in count.items() if isinstance(k, tuple) and k[1]}, dict(countries))
        region_chips = {k: v for k, v in count.items() if not isinstance(k, tuple)}
        self.assertGreater(len(region_chips), 0)
        for region, n in region_chips.items():
            self.assertEqual(n, regions[region], region)

    def test_every_event_is_tagged_with_its_own_place(self):
        places = self.talks['places']
        expected = Counter()
        for evs in self.talks['events'].values():
            for ev in evs:
                key = ev.get('place')
                if key == 'online':
                    tag = ('online', None)
                elif key:
                    p = places[key]
                    tag = (p['country'], p['province'] if p['country'] == 'TR' else key)
                else:
                    tag = (None, None)
                expected[(ev['name'],) + tag] += 1
        events = self.trees['talks'].find(lambda n: n.tag == 'li' and 'ev' in n.classes())
        found = Counter((ev.find(has_class('ev-name'))[0].all_text(), ev.attrs.get('data-country'), ev.attrs.get('data-region'))
                        for ev in events)
        self.assertEqual(found, expected)
        self.assertGreater(len({tag[2] for tag in expected if tag[2]}), 1)

    def test_every_placed_event_matches_a_chip_and_a_map_shape(self):
        tree = self.trees['talks']
        events = tree.find(lambda n: n.tag == 'li' and 'ev' in n.classes())
        placed = [ev for ev in events if 'data-country' in ev.attrs]
        _, countries, _ = self.expected_places()
        self.assertEqual(len(placed), sum(countries.values()))
        svg = tree.find(has_class('tmap-svg'))[0]
        controls = tree.find(has_class('tmap-controls'))[0]
        country_chips = {b.attrs['data-country'] for b in controls.find(lambda n: n.tag == 'button')}
        shapes = svg.find(lambda n: n.tag in ('path', 'circle') and 'land' not in n.classes())
        shape_countries = {s.attrs.get('data-country') for s in shapes}
        shape_regions = {s.attrs['data-region'] for s in shapes if s.attrs.get('data-region')}
        for ev in placed:
            c, r = ev.attrs['data-country'], ev.attrs.get('data-region')
            self.assertIn(c, country_chips)
            if c != 'online':
                self.assertIn(c, shape_countries)
                self.assertIn(r, shape_regions)
                subs = controls.find(lambda n: 'chips-sub' in n.classes() and n.attrs.get('data-for') == c)
                if subs:
                    self.assertIn(r, {b.attrs.get('data-region') for b in subs[0].find(lambda n: n.tag == 'button')})
        self.assertEqual(shape_countries - {None}, country_chips - {'', 'online'})

    def test_city_dots_sit_on_their_city(self):
        places = self.talks['places']
        used = {ev['place'] for evs in self.talks['events'].values() for ev in evs if ev.get('place') in places}
        dots = self.trees['talks'].find(has_class('tmap-cities'))[0].find(lambda n: n.tag == 'circle')
        self.assertEqual({d.attrs['data-region'] for d in dots}, {k for k in used if places[k]['country'] != 'TR'})
        for dot in dots:
            p = places[dot.attrs['data-region']]
            x, y = map_point(p['lon'], p['lat'])
            self.assertAlmostEqual(float(dot.attrs['cx']), x * 10, delta=1, msg=dot.attrs['data-region'])
            self.assertAlmostEqual(float(dot.attrs['cy']), y * 10, delta=1, msg=dot.attrs['data-region'])

    def test_the_map_draws_exactly_the_countries_in_its_view(self):
        svg = self.trees['talks'].find(has_class('tmap-svg'))[0]
        x, y, w, h = (float(v) for v in svg.attrs['viewbox'].split())
        drawn, left_out = 0, 0
        for code, d in read_json(ROOT, 'data', 'world.json')['countries'].items():
            x0, y0, x1, y1 = path_box(d)
            if x1 < x or x0 > x + w or y1 < y or y0 > y + h:
                self.assertNotIn(d, self.html['talks'], code)
                left_out += 1
            else:
                self.assertIn(d, self.html['talks'], code)
                drawn += 1
        self.assertGreater(left_out, 0)
        self.assertGreater(drawn, len(self.talks['countries']))

    def test_province_shapes_sit_in_a_group_named_for_their_country(self):
        places = self.talks['places']
        used = {ev['place'] for evs in self.talks['events'].values() for ev in evs if ev.get('place') in places}
        expected = {places[k]['country'] for k in used if 'province' in places[k]}
        groups = self.trees['talks'].find(has_class('tmap-provinces'))
        self.assertGreater(len(expected), 0)
        self.assertEqual({g.attrs.get('data-for') for g in groups}, expected)
        for g in groups:
            paths = g.find(lambda n: n.tag == 'path')
            self.assertGreater(len(paths), 1)
            self.assertEqual({p.attrs.get('data-country') for p in paths}, {g.attrs['data-for']})

    def test_the_talks_page_has_one_static_live_region(self):
        live = self.trees['talks'].find(lambda n: 'aria-live' in n.attrs)
        self.assertEqual(len(live), 1)
        self.assertIn('filter-status', live[0].classes())

    def test_place_chips_carry_the_name_the_status_reads(self):
        places, names = self.talks['places'], self.talks['countries']
        provinces = read_json(ROOT, 'data', 'world.json')['provinces']
        controls = self.trees['talks'].find(has_class('tmap-controls'))[0]
        regions = 0
        for b in controls.find(lambda n: n.tag == 'button'):
            c, r = b.attrs['data-country'], b.attrs.get('data-region')
            if r:
                expected = '{}, {}'.format(provinces[r]['name'] if c == 'TR' else places[r]['city'], names[c])
                regions += 1
            else:
                expected = {'': self.talks['map']['everywhere'], 'online': self.talks['online']}.get(c) or names[c]
            self.assertEqual(b.attrs.get('data-label'), expected, c + ' ' + (r or ''))
        self.assertGreater(regions, 0)

    def test_every_talk_shows_and_carries_the_themes_talks_json_gives_it(self):
        labels = self.talks['themes']['items']
        tag_label = self.talks['themes']['tag_label']
        expected = [(ev['name'], [t.get('themes', []) for t in ev.get('talks', [])])
                    for _, evs in sorted(self.talks['events'].items(), reverse=True) for ev in evs]
        events = self.trees['talks'].find(lambda n: n.tag == 'li' and 'ev' in n.classes())
        found, tagged = [], 0
        for ev in events:
            talks = [li for ul in ev.find(has_class('ev-talks')) for li in ul.children if isinstance(li, Node)]
            keys = []
            for li in talks:
                tags = li.find(lambda n: n.tag == 'button' and 'data-theme' in n.attrs)
                mine = [b.attrs['data-theme'] for b in tags]
                self.assertEqual([b.all_text() for b in tags], [labels[k] for k in mine])
                self.assertEqual([b.attrs['aria-label'] for b in tags], [tag_label.replace('{theme}', labels[k]) for k in mine])
                self.assertEqual((li.attrs.get('data-themes') or '').split(), mine)
                keys.append(mine)
                tagged += bool(mine)
            found.append((ev.find(has_class('ev-name'))[0].all_text(), keys))
            self.assertEqual((ev.attrs.get('data-themes') or '').split(), sorted({k for ks in keys for k in ks}))
        self.assertEqual(found, expected)
        self.assertGreater(tagged, len(labels))

    def test_every_video_of_a_talk_gets_a_link_numbered_only_when_there_are_several(self):
        a = self.talks
        talks = [(ev, t) for _, evs in sorted(a['events'].items(), reverse=True) for ev in evs for t in ev.get('talks', [])]
        rows = [li for ul in self.trees['talks'].find(has_class('ev-talks')) for li in ul.children if isinstance(li, Node)]
        self.assertEqual(len(rows), len(talks))
        several = 0
        for (ev, t), li in zip(talks, rows):
            about = t.get('title') or ev['name']
            videos = [t['video']] if isinstance(t.get('video'), str) else t.get('video', [])
            several += len(videos) > 1
            labels = [a['video']] if len(videos) == 1 else [a['video_n'].replace('{n}', str(n)) for n in range(1, len(videos) + 1)]
            want = ([(t['slides'], a['slides'] + a['slides_hidden'].replace('{title}', about))] if t.get('slides') else []) + \
                [(url, label + a['video_hidden'].replace('{title}', about)) for url, label in zip(videos, labels)]
            got = [(n.attrs['href'], n.all_text()) for span in li.find(has_class('ev-links')) for n in span.find(lambda n: n.tag == 'a')]
            self.assertEqual(got, want, about)
            self.assertEqual(len({text for _, text in got}), len(got), 'two links of {!r} read the same'.format(about))
        self.assertGreater(several, 0)

    def test_each_recent_talk_on_home_links_its_slides_or_else_its_first_video(self):
        count = next(b['count'] for s in read_json(ROOT, 'content', 'home.json')['sections']
                     for b in s['blocks'] if b['type'] == 'latest-talks')
        self.assertGreaterEqual(count, 4, 'the fixture below sets up four recent talks')
        with tempfile.TemporaryDirectory() as tmp:
            site = copy_site(tmp)
            path = os.path.join(site, 'content', 'talks.json')
            data = read_json(path)
            newest = [t for _, evs in sorted(data['archive']['events'].items(), reverse=True) for ev in evs for t in ev.get('talks', [])]
            for t in newest[:4]:
                t.pop('slides', None)
                t.pop('video', None)
            newest[0]['video'] = ['https://example.com/v1', 'https://example.com/v2']
            newest[1]['video'] = 'https://example.com/v3'
            newest[2]['slides'], newest[2]['video'] = 'https://example.com/s', 'https://example.com/v4'
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            out = os.path.join(tmp, 'out')
            result = run_build(site, out)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(os.path.join(out, 'index.html'), encoding='utf-8') as f:
                tree = Tree(f.read()).root
        recent = tree.find(lambda n: n.attrs.get('id') == 'recent')[0]
        got = [n.attrs.get('href') for n in recent.find(has_class('entry-title'))]

        def link(t):
            videos = [t['video']] if isinstance(t.get('video'), str) else t.get('video', [])
            return t.get('slides') or next(iter(videos), None)
        self.assertEqual(got, ['https://example.com/v1', 'https://example.com/v3', 'https://example.com/s', None] +
                         [link(t) for t in newest[4:count]])

    def spoken_badges(self, node):
        return [b.all_text() for b in node.find(has_class('spoken'))]

    def langs_around(self, node):
        langs = set()
        while node is not None:
            langs.add(node.attrs.get('lang'))
            node = node.parent
        return langs - {None}

    def badges_by_event(self, tree):
        events = {}
        for ev in tree.find(has_class('ev')):
            events.setdefault(ev.find(has_class('ev-name'))[0].all_text(), []).append(self.spoken_badges(ev))
        return events

    def built_with_talks(self, change, page):
        with tempfile.TemporaryDirectory() as tmp:
            site = copy_site(tmp)
            path = os.path.join(site, 'content', 'talks.json')
            data = read_json(path)
            change(data)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            out = os.path.join(tmp, 'out')
            result = run_build(site, out)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(os.path.join(out, page), encoding='utf-8') as f:
                return Tree(f.read()).root

    def test_named_events_carry_the_badge_of_the_language_they_state(self):
        events = self.badges_by_event(self.trees['talks'])
        self.assertEqual(events['Karabük Üniversitesi Programlama Günleri 2016'], [['Turkish']])
        self.assertEqual(events['Devoxx Belgium 2022'], [['English']])
        self.assertEqual(events['Agile Tour Kaunas 2015'], [['English']])
        self.assertEqual(events['Teknasyon Tech Meetup #2'], [['Turkish']])
        self.assertEqual(events['IT Serbia Podcast'], [['English']])
        self.assertEqual(events['Kesişen Yollar'], [['Turkish']])
        self.assertEqual(events['Etohum Developers Day 2013'], [['Turkish']], 'an event with no place and no role')
        self.assertEqual(events['ITAKE Unconference 2020'], [['English']])
        self.assertEqual(events['Turkcell Agile Talks'], [['Turkish']], 'an event with no place, no role and no talks')

    def test_an_event_at_a_place_on_the_map_carries_the_language_it_states_not_its_countrys(self):
        def swap(data):
            every = [ev for evs in data['archive']['events'].values() for ev in evs]
            next(ev for ev in every if ev['name'] == 'Devoxx Belgium 2022')['spoken'] = 'tr'
            next(ev for ev in every if ev['name'] == 'Karabük Üniversitesi Programlama Günleri 2016')['spoken'] = 'en'
        events = self.badges_by_event(self.built_with_talks(swap, os.path.join('talks', 'index.html')))
        self.assertEqual(events['Devoxx Belgium 2022'], [['Turkish']])
        self.assertEqual(events['Karabük Üniversitesi Programlama Günleri 2016'], [['English']])

    def test_every_event_carries_the_one_badge_its_spoken_language_names(self):
        label = {'tr': 'Turkish', 'en': 'English'}
        want = Counter((ev['name'], label[ev['spoken']]) for evs in self.talks['events'].values() for ev in evs)
        got = Counter()
        for ev in self.trees['talks'].find(has_class('ev')):
            badges = self.spoken_badges(ev)
            self.assertEqual(len(badges), 1, ev.all_text())
            got[ev.find(has_class('ev-name'))[0].all_text(), badges[0]] += 1
        self.assertEqual(got, want)
        self.assertLessEqual({'Turkish', 'English'}, {b for _, b in want})

    def test_every_event_at_a_place_on_the_map_states_turkish_in_turkiye_and_english_abroad(self):
        placed = [ev for evs in self.talks['events'].values() for ev in evs if ev.get('place') not in (None, 'online')]
        in_turkiye = {id(ev): self.talks['places'][ev['place']]['country'] == 'TR' for ev in placed}
        self.assertEqual([ev['name'] for ev in placed if ev['spoken'] != ('tr' if in_turkiye[id(ev)] else 'en')], [])
        self.assertEqual(set(in_turkiye.values()), {True, False}, 'no event in Türkiye or none abroad, so one side of the rule is unchecked')

    def siblings(self, node):
        return [c for c in node.parent.children if isinstance(c, Node)]

    def test_every_badge_on_the_talks_page_ends_its_events_meta_line_under_no_lang_but_the_pages(self):
        badges = self.trees['talks'].find(has_class('spoken'))
        self.assertGreater(len(badges), 0)
        for b in badges:
            self.assertIn('ev-meta', b.parent.classes(), b.parent.all_text())
            self.assertIs([c for c in b.parent.children if not isinstance(c, str) or c.strip()][-1], b, b.parent.all_text())
            self.assertEqual(self.langs_around(b), {'en'}, b.parent.all_text())
        self.assertTrue(any(b.parent.text.strip(' ·') for b in badges), 'no badge shares its line with a role, so its order against text is unchecked')

    def test_each_recent_talk_on_home_carries_the_badge_of_its_own_event_beside_its_title(self):
        count = next(b['count'] for s in read_json(ROOT, 'content', 'home.json')['sections']
                     for b in s['blocks'] if b['type'] == 'latest-talks')
        pattern = (('en', 'istanbul', True), ('tr', 'kyiv', False), ('en', 'online', False), ('tr', None, True))
        self.assertGreaterEqual(count, len(pattern), 'the fixture below needs a recent talk for each of its rows')
        label = {'en': ['English'], 'tr': ['Turkish']}
        want = []
        def mix(data):
            events = [ev for _, evs in sorted(data['archive']['events'].items(), reverse=True) for ev in evs if ev.get('talks')]
            for i, ev in enumerate(events[:count]):
                language, place, linked = pattern[i % len(pattern)]
                ev.pop('place', None)
                ev['spoken'] = language
                if place:
                    ev['place'] = place
                ev['talks'] = ev['talks'][:1]
                ev['talks'][0].pop('slides', None)
                ev['talks'][0].pop('video', None)
                if linked:
                    ev['talks'][0]['slides'] = 'https://example.com/s{}'.format(i)
                want.append(label[language])
        tree = self.built_with_talks(mix, 'index.html')
        items = tree.find(lambda n: n.attrs.get('id') == 'recent')[0].find(lambda n: n.tag == 'li')
        self.assertEqual([self.spoken_badges(li) for li in items], want)
        self.assertEqual(len(items), count)
        seen = set()
        for li in items:
            title = li.find(has_class('entry-title'))[0]
            for b in li.find(has_class('spoken')):
                row = self.siblings(b)
                self.assertGreater(row.index(b), 0, li.all_text())
                self.assertIs(row[row.index(b) - 1], title, li.all_text())
                self.assertEqual(self.langs_around(b), {'en'}, li.all_text())
                seen.add((title.tag, b.all_text()))
        self.assertEqual(seen, {(tag, b) for tag in ('a', 'span') for b in ('English', 'Turkish')},
                         'the fixture should badge both a linked and an unlinked title in both languages')

    def test_theme_chips_count_the_events_about_each_theme(self):
        labels = self.talks['themes']['items']
        count = Counter(k for evs in self.talks['events'].values() for ev in evs
                        for k in {k for t in ev.get('talks', []) for k in t.get('themes', [])})
        cloud = self.trees['talks'].find(has_class('cloud'))[0]
        everything, *chips = cloud.find(lambda n: n.tag == 'button')
        got = {b.attrs['data-theme']: (b.attrs['data-label'], int(b.find(has_class('n'))[0].text)) for b in chips}
        self.assertEqual(got, {k: (labels[k], count[k]) for k in labels})
        self.assertGreater(len(chips), 1)
        events = sum(len(evs) for evs in self.talks['events'].values())
        self.assertEqual((everything.attrs.get('data-theme'), everything.attrs.get('aria-pressed')), ('', 'true'))
        self.assertEqual(everything.all_text().split(), self.talks['themes']['all'].split() + [str(events)])

    def test_the_theme_cloud_waits_for_js_lists_chips_by_label_and_only_the_themes_section_rules_name_a_mark_the_place_chips_lack(self):
        th = self.talks['themes']
        section, = self.trees['talks'].find(has_class('themes'))
        self.assertIn('hidden', section.attrs, 'without JS the chips would show and do nothing')
        heading = [n for n in self.trees['talks'].walk() if n.attrs.get('id') == section.attrs.get('aria-labelledby')]
        self.assertEqual([h.all_text() for h in heading], [th['heading']])
        cloud, = section.find(has_class('cloud'))
        self.assertEqual((cloud.attrs.get('role'), cloud.attrs.get('aria-label')), ('group', th['label']))
        chips = cloud.find(lambda n: n.tag == 'button')[1:]
        self.assertEqual([c.attrs['data-label'] for c in chips], sorted(th['items'].values(), key=str.lower))
        self.assertEqual({c.attrs.get('aria-pressed') for c in chips}, {'false'})
        places = self.trees['talks'].find(has_class('tmap-controls'))[0].find(lambda n: n.attrs.get('role') == 'group')
        self.assertIn('chips', places[0].classes())
        self.assertIn('chips', cloud.classes(), 'the cloud should take its look from the place chips')
        self.assertEqual(sorted(cloud.attrs), ['aria-label', 'class', 'role'])
        self.assertEqual([sorted(b.attrs) for b in cloud.find(lambda n: n.tag == 'button')],
                         [['aria-pressed', 'data-theme', 'type']] + [['aria-pressed', 'data-label', 'data-theme', 'type']] * len(chips),
                         'a class or a style on a chip could size it apart from the place chips')
        self.assertEqual([(n.tag, n.attrs) for b in cloud.find(lambda n: n.tag == 'button') for n in b.find(lambda n: n is not b)],
                         [('span', {'class': 'n'})] * (len(chips) + 1), 'a class or a style on a count could size it apart')

        def marks(group):
            out, node = set(), group
            while node is not None:
                out |= {'.' + c for c in node.classes()} | {'[' + a for a in node.attrs if a != 'class'}
                out |= {'#' + node.attrs['id']} if node.attrs.get('id') else set()
                node = node.parent
            return out | {'[' + a for b in group.find(lambda n: n.tag == 'button') for a in b.attrs}
        own = marks(cloud) - marks(places[0]) | {'"{}"'.format(cloud.attrs['aria-label'])}
        self.assertTrue({'.cloud', '.themes', '[data-theme'} <= own, own)
        with open(os.path.join(ROOT, 'assets', 'site.css'), encoding='utf-8') as f:
            css = re.sub(r'/\*.*?\*/', '', f.read(), flags=re.S)
        css = re.sub(r''':root(?::not\()?\[data-theme=["']\w+["']\]\)?''', ':root', css)
        selectors = [s.strip() for group in re.findall(r'([^{}@;]+)\{', css) for s in group.split(',')]
        self.assertEqual([s for s in selectors if any(re.search(re.escape(m) + r'(?![\w-])', s) for m in own)],
                         ['.themes', '.themes .sub'], 'a rule naming a mark of the cloud that the place chips lack could size its chips apart')

    def test_the_tags_on_each_talk_wait_for_js_like_the_cloud(self):
        spans = self.trees['talks'].find(has_class('ev-themes'))
        talks = sum(bool(t.get('themes')) for evs in self.talks['events'].values() for ev in evs for t in ev.get('talks', []))
        self.assertEqual(len(spans), talks)
        self.assertEqual([s.all_text() for s in spans if 'hidden' not in s.attrs], [], 'without JS these buttons would do nothing')
        self.assertGreater(talks, 1)

    def test_the_talks_page_gives_every_ui_string_site_js_reads(self):
        with open(os.path.join(ROOT, 'assets', 'site.js'), encoding='utf-8') as f:
            read = set(re.findall(r'\bui\.([a-z_]+)', f.read()))
        self.assertIn('theme_status', read)
        island = [n for n in self.trees['talks'].walk() if n.attrs.get('id') == 'ui-text']
        self.assertEqual(len(island), 1)
        self.assertEqual(sorted(read - set(json.loads(island[0].all_text()))), [])

    def test_every_talk_photo_is_the_size_its_thumbnail_declares(self):
        photos = self.trees['talks'].find(has_class('ev-photo'))
        expected = sum(1 for evs in self.talks['events'].values() for ev in evs if ev.get('photo'))
        self.assertEqual(len(photos), expected)
        self.assertGreater(expected, 1)
        for a in photos:
            img = a.find(lambda n: n.tag == 'img')[0]
            declared = (int(img.attrs['width']), int(img.attrs['height']))
            self.assertEqual(jpeg_size(os.path.join(self.out, 'talks', img.attrs['src'])), declared, img.attrs['src'])
            self.assertTrue(os.path.isfile(os.path.join(self.out, 'talks', a.attrs['href'])), a.attrs['href'])

    def test_every_file_in_assets_talks_is_used_by_a_built_page(self):
        folder = os.path.join(ROOT, 'assets', 'talks')
        files = {f for f in os.listdir(folder) if not f.startswith('.')}
        self.assertGreater(len(files), 1)
        unused = {f for f in files if not any('assets/talks/' + f in html for html in self.html.values())}
        self.assertEqual(unused, set())

    # Sharing

    def test_every_page_shares_an_image_of_the_size_it_declares(self):
        site = read_json(ROOT, 'content', 'site.json')
        shared = 0
        for name, tree in self.trees.items():
            if name == '404':
                continue
            meta = {n.attrs.get('property') or n.attrs.get('name'): n.attrs.get('content')
                    for n in tree.find(lambda n: n.tag == 'meta')}
            self.assertTrue(meta['og:image'].startswith(site['url']), meta['og:image'])
            path = os.path.join(self.out, meta['og:image'][len(site['url']):])
            size = jpeg_size(path)
            self.assertEqual(size, (int(meta['og:image:width']), int(meta['og:image:height'])), name)
            # X shows a large card only for an image of at least 300x157.
            self.assertEqual(meta['twitter:card'], 'summary_large_image', name)
            self.assertTrue(size[0] >= 300 and size[1] >= 157, (name, size))
            # Large cards are cropped to about 1.91:1, so an image at that ratio shows whole.
            self.assertAlmostEqual(size[0] / size[1], 1.91, delta=0.02, msg=(name, size))
            self.assertEqual(meta['og:site_name'], site['name'], name)
            self.assertEqual(meta['og:url'], site['url'] + ('' if name == 'home' else name + '/'))
            canonical = tree.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == 'canonical')
            self.assertEqual([c.attrs['href'] for c in canonical], [meta['og:url']], name)
            shared += 1
        self.assertEqual(shared, len(self.trees) - 1)
        self.assertGreater(shared, 1)

    def test_the_home_page_describes_lemi_with_an_image_on_this_site(self):
        site = read_json(ROOT, 'content', 'site.json')
        person = read_json(ROOT, 'content', 'home.json')['person']
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', self.html['home'], re.S)
        self.assertEqual(len(blocks), 1)
        built = json.loads(blocks[0])
        self.assertEqual(built['image'], site['url'] + person['image'])
        self.assertTrue(os.path.isfile(os.path.join(self.out, person['image'])), person['image'])
        self.assertEqual({k: v for k, v in built.items() if k != 'image'}, {k: v for k, v in person.items() if k != 'image'})

    def test_the_hidden_attribute_beats_a_class_that_sets_display(self):
        with open(os.path.join(ROOT, 'assets', 'site.css'), encoding='utf-8') as f:
            css = f.read()
        self.assertEqual(css_values(css, '[hidden]', 'display'), ['none !important'])
        self.assertNotEqual(css_values(css, '.ev-themes', 'display'), [], 'without a display rule on a hidden element this guard has nothing to beat')

    def test_every_icon_a_page_links_to_exists_at_the_size_it_declares(self):
        for name, tree in self.trees.items():
            links = tree.find(lambda n: n.tag == 'link' and n.attrs.get('rel') in ('icon', 'apple-touch-icon'))
            self.assertEqual(sorted(link.attrs['rel'] for link in links), ['apple-touch-icon', 'icon', 'icon'], name)
            here = os.path.dirname(os.path.join(self.out, page_file(name)))
            for link in links:
                href = link.attrs['href']
                path = os.path.join(self.out, href[1:]) if href.startswith('/') else os.path.join(here, href)
                if link.attrs.get('type') == 'image/svg+xml':
                    with open(path, encoding='utf-8') as f:
                        box = re.search(r'viewBox="0 0 (\S+) (\S+)"', f.read())
                    self.assertEqual(box.group(1), box.group(2), path)
                else:
                    # Apple's touch icon is 180 px square and the link names no size.
                    self.assertEqual('{}x{}'.format(*png_size(path)), link.attrs.get('sizes', '180x180'), path)

    # Home: hero and git game

    @staticmethod
    def career_stretches():
        """The career log, oldest item first, folded into one (year, org, side branch) per stretch at an org; newest first."""
        log = blocks_of(read_json(ROOT, 'content', 'career.json'), 'log')[0]
        rows = []
        for item in reversed(log['items']):
            row = (re.search(r'\d{4}', item['when']).group(), plain(item['org']), bool(item.get('branch')))
            if not rows or rows[-1][1:] != row[1:]:
                rows.append(row)
        return rows[::-1]

    def test_the_hero_path_is_the_career_log_one_commit_per_stretch(self):
        hero = self.trees['home'].find(has_class('hero'))[0]
        items = hero.find(has_class('hero-path'))[0].find(lambda n: n.tag == 'li')
        got = [(li.find(lambda n: n.tag == 'time')[0].all_text(), li.find(has_class('hero-org'))[0].all_text(),
                'side' in li.classes()) for li in items]
        want = self.career_stretches()
        self.assertEqual(got, want)
        self.assertGreater(sum(side for _, _, side in want), 0)
        self.assertLess(len(want), len(blocks_of(read_json(ROOT, 'content', 'career.json'), 'log')[0]['items']))

    def test_every_number_in_the_hero_comes_from_the_content(self):
        home = read_json(ROOT, 'content', 'home.json')['hero']
        community = blocks_of(read_json(ROOT, 'content', 'community.json'), 'items')
        meta = next(i['meta'] for b in community for i in b['items'] if i['title'] == home['community'])
        founded = re.search(r'\d{4}', meta).group()
        stretches = self.career_stretches()
        since = stretches[-1][0]
        event = self.stage_photo_event()
        hero = self.trees['home'].find(has_class('hero'))[0]
        intro = hero.find(has_class('hero-intro'))[0].all_text()
        self.assertEqual(intro, plain(home['text']).replace('{since}', since).replace('{founded}', founded))
        numbers = set(re.findall(r'\d+', hero.all_text()))
        self.assertIn(since, numbers)
        self.assertIn(founded, numbers)
        allowed = {year for year, _, _ in stretches} | {founded} | set(re.findall(r'\d+', event))
        self.assertEqual(sorted(numbers - allowed), [])

    def test_the_hero_content_types_no_numbers(self):
        def strings(value, key=None):
            if isinstance(value, dict):
                return [s for k, v in value.items() for s in strings(v, k)]
            if isinstance(value, list):
                return [s for v in value for s in strings(v, key)]
            return [] if key == 'url' else [(key, value)]
        found = strings(read_json(ROOT, 'content', 'home.json')['hero'])
        self.assertIn('text', {key for key, _ in found})
        self.assertEqual([(key, s) for key, s in found if re.search(r'\d', s)], [])

    def stage_photo_event(self):
        talk = read_json(ROOT, 'content', 'home.json')['hero']['photo']['talk']
        names = [ev['name'] for evs in self.talks['events'].values() for ev in evs
                 if any(t.get('title') == talk for t in ev.get('talks', []))]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def test_the_stage_photo_names_the_one_event_its_talk_was_given_at(self):
        photo = read_json(ROOT, 'content', 'home.json')['hero']['photo']
        self.assertIn('{event}', photo['caption'])
        self.assertIn('{event}', photo['alt'])
        event = self.stage_photo_event()
        heads = self.trees['home'].find(has_class('hero-head'))
        self.assertEqual([h.tag for h in heads], ['figure'])
        captions = heads[0].find(lambda n: n.tag == 'figcaption')
        self.assertEqual([c.all_text() for c in captions], [photo['caption'].replace('{event}', event)])
        imgs = heads[0].find(lambda n: n.tag == 'img')
        self.assertEqual([i.attrs.get('alt') for i in imgs], [photo['alt'].replace('{event}', event)])

    def test_the_hero_keeps_one_h1_and_loads_the_stage_photo_first(self):
        tree = self.trees['home']
        self.assertEqual(len(tree.find(lambda n: n.tag == 'h1')), 1)
        pictures = tree.find(has_class('hero-photo'))
        self.assertEqual([p.tag for p in pictures], ['picture'])
        children = [c for c in pictures[0].children if isinstance(c, Node)]
        self.assertEqual([c.tag for c in children], ['source', 'img'])
        source, img = children
        self.assertEqual(source.attrs.get('type'), 'image/webp')
        self.assertIs(tree.find(lambda n: n.tag == 'img')[0], img)
        self.assertNotIn('loading', img.attrs)
        self.assertEqual(img.attrs.get('fetchpriority'), 'high')
        self.assertTrue(img.attrs.get('sizes'))
        self.assertEqual(source.attrs.get('sizes'), img.attrs['sizes'])

        def file_of(url):
            path = os.path.normpath(os.path.join(self.out, url))
            self.assertTrue(os.path.isfile(path), path)
            return path

        referenced = {os.path.basename(img.attrs['src'])}
        for node, size_of in ((source, webp_size), (img, jpeg_size)):
            candidates = [c.split() for c in node.attrs.get('srcset', '').split(',') if c.strip()]
            self.assertTrue(candidates, node.tag)
            for url, descriptor in candidates:
                self.assertEqual(descriptor, '{}w'.format(size_of(file_of(url))[0]), url)
                referenced.add(os.path.basename(url))
        width, height = jpeg_size(file_of(img.attrs['src']))
        self.assertEqual((img.attrs.get('width'), img.attrs.get('height')), (str(width), str(height)))
        on_disk = {f for f in os.listdir(os.path.join(ROOT, 'assets', 'img')) if f.startswith('lemi-stage-')}
        self.assertEqual(referenced, on_disk)

    def test_the_photo_sizes_follow_the_two_column_css(self):
        with open(os.path.join(ROOT, 'assets', 'site.css'), encoding='utf-8') as f:
            css = f.read()
        columns = re.findall(r'@media \(min-width: ([\d.]+)rem\) \{\s*\.hero \{\s*--photo-w: min\((\d+)vw, ([\d.]+)rem\);', css)
        self.assertEqual(len(columns), 1, columns)
        breakpoint, vw, cap = columns[0]
        sizes = self.trees['home'].find(has_class('hero-photo'))[0].find(lambda n: n.tag == 'img')[0].attrs['sizes']
        self.assertIn('(min-width: {}rem) {}vw'.format(breakpoint, vw), sizes)
        capped = re.findall(r'\(min-width: ([\d.]+)rem\) {}rem'.format(re.escape(cap)), sizes)
        self.assertEqual(len(capped), 1, sizes)
        self.assertLess(abs(float(capped[0]) - float(cap) * 100 / int(vw)), 1)

    def test_the_talks_intro_runs_as_wide_as_the_paragraph_under_it_and_no_other_intro_does(self):
        with open(os.path.join(ROOT, 'assets', 'site.css'), encoding='utf-8') as f:
            css = f.read()
        self.assertEqual(css_values(css, '.archive .intro', 'max-width'), ['none'])
        self.assertEqual(css_values(css, '.intro', 'max-width'), ['40rem'])
        main, = [n for n in self.trees['talks'].walk() if n.tag == 'main']
        self.assertIn('archive', main.classes())
        self.assertEqual(len(main.find(has_class('intro'))), 1)
        self.assertEqual([p for p, t in self.trees.items() if t.find(has_class('archive'))], ['talks'])

    def test_the_lane_svg_and_the_css_multiples_of_row_agree(self):
        with open(os.path.join(ROOT, 'assets', 'site.css'), encoding='utf-8') as f:
            css = f.read()

        def multiple(selector, prop, pattern):
            values = css_values(css, selector, prop)
            self.assertEqual(len(values), 1, (selector, prop, values))
            found = re.fullmatch(pattern, values[0])
            self.assertTrue(found, (selector, prop, values[0]))
            return float(found.group(1))

        offset = r'calc\(var\(--lane\) - ([\d.]+) \* var\(--row\)\)'
        main_dx = multiple('.hero-lanes', 'left', offset)
        lanes_w = multiple('.hero-lanes', 'width', r'calc\(([\d.]+) \* var\(--row\)\)')
        lanes_h = multiple('.hero-lanes', 'height', r'calc\(\(var\(--rows\) \+ ([\d.]+)\) \* var\(--row\)\)')
        side_dx = multiple('.hero-path li.side .hero-dot', 'left', offset)
        pad = 1 / multiple('.hero-path ol', 'padding', r'calc\(var\(--row\) / ([\d.]+)\) 0 0')
        self.assertEqual(css_values(css, '.hero-path li', 'height'), ['var(--row)'])

        path = self.trees['home'].find(has_class('hero-path'))[0]
        items = path.find(lambda n: n.tag == 'li')
        rows = int(re.search(r'--rows:(\d+)', path.attrs['style']).group(1))
        self.assertEqual(rows, len(items))
        svg = path.find(has_class('hero-lanes'))[0]
        _, _, view_w, view_h = map(float, svg.attrs['viewbox'].split())
        row = view_w / lanes_w
        self.assertAlmostEqual(view_h, (rows + lanes_h) * row, places=2)
        trunk = [round((pad + i + 0.5) * row, 2) for i, li in enumerate(items) if 'side' not in li.classes()]
        mains = svg.find(has_class('lane-main'))
        self.assertEqual(len(mains), 1)
        main_x, bottom = map(float, re.fullmatch(r'M([\d.]+) ([\d.]+)V0', mains[0].attrs['d']).groups())
        self.assertAlmostEqual(main_x, main_dx * row, places=2)
        self.assertAlmostEqual(bottom, trunk[-1], places=2)
        sides = svg.find(has_class('lane-side'))
        self.assertTrue(sides)
        for side in sides:
            numbers = [float(x) for x in re.findall(r'[\d.]+', side.attrs['d'])]
            xs, ys = numbers[0::2], numbers[1::2]
            self.assertEqual({round(x, 2) for x in xs}, {round(main_x, 2), round(main_x - side_dx * row, 2)})
            self.assertIn(round(ys[0], 2), trunk)
            self.assertIn(round(ys[-1], 2), trunk)

    def game_island(self):
        scripts = self.trees['home'].find(lambda n: n.tag == 'script' and n.attrs.get('id') == 'git-game-data')
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0].attrs.get('type'), 'application/json')
        return json.loads(scripts[0].all_text())

    def test_the_game_island_carries_every_level_without_its_checks(self):
        game = read_json(ROOT, 'content', 'home.json')['game']
        want = []
        for level in game['levels']:
            level = {k: v for k, v in level.items() if k != 'checks'}
            level['par'] = len(level['solution'])
            want.append(level)
        island = self.game_island()
        self.assertGreater(len(want), 0)
        self.assertEqual(island['levels'], want)
        self.assertEqual(island['ui'], game['ui'])
        mount = self.trees['home'].find(lambda n: 'data-git-game' in n.attrs)
        self.assertEqual(len(mount), 1)
        self.assertEqual(mount[0].parent.parent.attrs.get('id'), 'play')
        fallback = mount[0].all_text()
        for level in game['levels']:
            self.assertIn(level['title'], fallback)

    def test_no_level_checks_reach_any_page(self):
        self.game_island()
        for name, source in self.html.items():
            for leak in ('"checks"', 'near_misses', '"alternatives"'):
                self.assertNotIn(leak, source, name)

    GAME_ASSETS = ['assets/git-game.css', 'assets/git-engine.js', 'assets/git-game.js']

    def test_only_pages_with_a_game_load_its_assets(self):
        with_game, without = [], 0
        for name, tree in self.trees.items():
            folder = os.path.dirname(page_file(name))
            loaded = [n for n in tree.find(lambda n: n.tag in ('link', 'script'))
                      if os.path.normpath(os.path.join(folder, n.attrs.get('href') or n.attrs.get('src') or '.')) in self.GAME_ASSETS]
            if not read_json(ROOT, 'content', name + '.json').get('game'):
                self.assertEqual(loaded, [], name)
                without += 1
                continue
            with_game.append(name)
            head = tree.find(lambda n: n.tag == 'head')[0]
            self.assertEqual([n for n in loaded if n not in head.walk()], [], name)
            paths = [os.path.normpath(os.path.join(folder, n.attrs.get('href') or n.attrs['src'])) for n in loaded]
            self.assertEqual(paths, self.GAME_ASSETS, name)
            self.assertEqual([n.attrs.get('rel') for n in loaded if n.tag == 'link'], ['stylesheet'], name)
            for script in (n for n in loaded if n.tag == 'script'):
                self.assertIn('defer', script.attrs, name)
            for path in paths:
                self.assertTrue(os.path.isfile(os.path.join(self.out, path)), path)
        self.assertIn('home', with_game)
        self.assertGreater(without, 0)

    # 404.html is served at whatever path was asked for, so its assets must not be relative.
    MAZE_ASSETS = ['/assets/maze-game.css', '/assets/maze-game.js']

    def test_only_the_not_found_page_loads_the_maze_game_from_root_absolute_paths_in_its_head(self):
        loaders = {}
        for name, tree in self.trees.items():
            refs = [n for n in tree.find(lambda n: n.tag in ('link', 'script'))
                    if 'maze-game' in (n.attrs.get('href') or n.attrs.get('src') or '')]
            if refs:
                loaders[name] = refs
        self.assertEqual({name: [n.attrs.get('href') or n.attrs['src'] for n in refs] for name, refs in loaders.items()},
                         {'404': self.MAZE_ASSETS})
        head = self.trees['404'].find(lambda n: n.tag == 'head')[0]
        self.assertEqual([n for n in loaders['404'] if n not in head.walk()], [])
        self.assertEqual([n.attrs.get('rel') for n in loaders['404'] if n.tag == 'link'], ['stylesheet'])
        self.assertIn('defer', [n for n in loaders['404'] if n.tag == 'script'][0].attrs)
        for path in self.MAZE_ASSETS:
            self.assertTrue(os.path.isfile(os.path.join(self.out, path.lstrip('/'))), path)

    def test_the_not_found_page_mounts_the_maze_hidden_with_the_ui_strings_404_json_gives(self):
        maze = read_json(ROOT, 'content', '404.json')['maze']
        tree = self.trees['404']
        mounts = tree.find(lambda n: 'data-maze' in n.attrs)
        self.assertEqual(len(mounts), 1)
        self.assertIn('hidden', mounts[0].attrs)
        self.assertEqual([n.all_text() for n in mounts[0].find(lambda n: n.tag in ('h2', 'p'))],
                         [maze['title'], maze['intro']])
        self.assertEqual(tree.find(lambda n: n.attrs.get('id') == mounts[0].attrs['aria-labelledby']),
                         mounts[0].find(lambda n: n.tag == 'h2'))
        islands = tree.find(lambda n: n.attrs.get('id') == 'maze-data')
        self.assertEqual(len(islands), 1)
        self.assertEqual(json.loads(islands[0].text), {'ui': maze['ui']})

    def test_the_maze_game_reads_every_ui_string_404_json_has_and_no_other(self):
        with open(os.path.join(ROOT, 'assets', 'maze-game.js'), encoding='utf-8') as f:
            read = set(re.findall(r'\bui\.([a-z_]+)', f.read()))
        self.assertIn('play', read)
        self.assertEqual(read, set(read_json(ROOT, 'content', '404.json')['maze']['ui']))

    HCAPTCHA = 'https://js.hcaptcha.com/1/api.js?recaptchacompat=off'

    def test_the_contact_form_sends_web3forms_the_fields_its_api_reads_and_waits_for_js(self):
        block = blocks_of(read_json(ROOT, 'content', 'contact.json'), 'form')
        self.assertEqual(len(block), 1)
        block = block[0]
        forms = self.trees['contact'].find(lambda n: n.tag == 'form')
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form.attrs.get('action'), 'https://api.web3forms.com/submit')
        self.assertEqual(form.attrs.get('method'), 'post')
        self.assertIn('hidden', form.attrs, 'the captcha needs JS, so without it the form could only fail')
        fields = {n.attrs['name']: n for n in form.walk() if n.tag in ('input', 'textarea')}
        self.assertEqual(sorted(fields), ['access_key', 'email', 'from_name', 'message', 'name', 'subject'])
        for name in ('access_key', 'subject', 'from_name'):
            self.assertEqual(fields[name].attrs.get('type'), 'hidden', name)
            self.assertEqual(fields[name].attrs.get('value'), block[name], name)
        # Web3Forms sets the reply-to of the mail it sends from the field named "email".
        self.assertEqual(fields['email'].attrs.get('type'), 'email')
        for name in ('name', 'email', 'message'):
            self.assertIn('required', fields[name].attrs, name)
            self.assertEqual((fields[name].parent.tag, fields[name].parent.text), ('label', block['labels'][name]), name)
        captcha = form.find(has_class('h-captcha'))
        self.assertEqual([c.attrs.get('data-sitekey') for c in captcha], ['50b2fe65-b00b-4b9e-ad62-3ba471098be2'])
        self.assertEqual(len(form.find(lambda n: n.tag == 'button' and n.attrs.get('type') == 'submit' and 'send' in n.classes())), 1)
        self.assertEqual(len(form.find(lambda n: 'form-status' in n.classes() and n.attrs.get('role') == 'status')), 1)

    def test_the_contact_form_carries_every_status_line_site_js_says_and_no_other(self):
        block = blocks_of(read_json(ROOT, 'content', 'contact.json'), 'form')[0]
        with open(os.path.join(ROOT, 'assets', 'site.js'), encoding='utf-8') as f:
            said = set(re.findall(r"\bsay\('([a-z]+)'\)", f.read()))
        self.assertIn('sent', said)
        self.assertEqual(said, set(block['status']))
        form = self.trees['contact'].find(lambda n: n.tag == 'form')[0]
        self.assertEqual({k: form.attrs.get('data-' + k) for k in said}, block['status'])

    def test_only_the_contact_page_loads_hcaptcha_and_it_loads_it_once(self):
        loading = {}
        for name, tree in self.trees.items():
            scripts = [n.attrs['src'] for n in tree.find(lambda n: n.tag == 'script' and 'hcaptcha' in n.attrs.get('src', ''))]
            if scripts:
                loading[name] = scripts
        self.assertEqual(loading, {'contact': [self.HCAPTCHA]})

    # The address as a reader or a scraper sees it: the local part, "@", the domain, "." and "org",
    # where "@" and "." may be the character, a decimal, hex or named HTML entity, or the word, and
    # only blanks, non-breaking spaces, brackets or tags stand between them. Each alternative has a
    # spelling in the test below that needs it. Out of its reach: percent-encoding, full-width or
    # zero-width characters, text a binary keeps as UTF-16 or compressed, and an address that JS
    # assembles from parts, which the old renderer's markup names stand in for.
    LOCAL, DOMAIN = 'lemiorhan', 'scturkey'
    _GAP = r'(?:[\s\[\](){}]|<[^>]*>|&nbsp;|&#0*160;?|&#x0*a0;?)*'
    _AT = r'(?:@|&#0*64;?|&#x0*40;?|&commat;|\bat\b)'
    _DOT = r'(?:\.|&#0*46;?|&#x0*2e;?|&period;|\bdot\b)'
    ADDRESS = re.compile(LOCAL + r'(?:' + _GAP + _AT + r')+' + _GAP + DOMAIN + _GAP + _DOT + _GAP + 'org', re.I)

    def test_no_built_file_spells_out_the_mail_address_or_carries_the_old_renderers_split_of_it(self):
        sources = {}
        for folder, _, names in os.walk(self.out):
            for name in names:
                path = os.path.join(folder, name)
                with open(path, 'rb') as f:
                    raw = f.read()
                try:
                    sources[os.path.relpath(path, self.out)] = raw.decode('utf-8')
                except UnicodeDecodeError:
                    sources[os.path.relpath(path, self.out)] = raw.decode('latin-1')
        for path, source in sources.items():
            self.assertIsNone(self.ADDRESS.search(source), path)
            for trace in ('mailto:', 'data-domain', 'mail-link'):
                self.assertNotIn(trace, source, path)
        self.assertLessEqual({page_file(n) for n in self.trees} | {os.path.join('assets', 'site.js'), os.path.join('assets', 'flags', 'LICENSE'),
                                                                   os.path.join('assets', 'img', 'stage.jpg')},
                             set(sources))
        at = '@'
        for between_local_and_domain, between_domain_and_org in (
                (at, '.'), (' [at] ', ' [dot] '), (' (at) ', '.'), ('{at}', '.'),
                ('&#64;', '&#46;'), ('&#64', '&#46'), ('&#x40;', '&#x2E;'), ('&#x40', '&#x2e'), ('&commat;', '&period;'),
                ('&nbsp;' + at + '&#160;', '&#xa0;.'), ('&#160' + at, '&#xa0.'),
                ('<span aria-hidden="true">' + at + '</span><span class="sr-only"> at </span>', '.')):
            spelling = self.LOCAL + between_local_and_domain + self.DOMAIN + between_domain_and_org + 'org'
            self.assertIsNotNone(self.ADDRESS.search(spelling), spelling)
            self.assertIsNotNone(self.ADDRESS.search(spelling.upper()), spelling.upper())
        for prose in ('@lemiorhan at SCTurkey', 'lemiorhan at SCTurkey meetups'):
            self.assertIsNone(self.ADDRESS.search(prose), prose)

    BEACON = 'https://static.cloudflareinsights.com/beacon.min.js'

    def test_every_page_loads_the_cloudflare_beacon_once_with_the_token_site_json_gives(self):
        token = read_json(ROOT, 'content', 'site.json')['cloudflare_analytics_token']
        pages = sorted(os.path.relpath(os.path.join(folder, f), self.out)
                       for folder, _, files in os.walk(self.out) for f in files if f.endswith(('.html', '.htm')))
        for page in pages:
            with open(os.path.join(self.out, page), encoding='utf-8') as f:
                tree = Tree(f.read()).root
            beacons = tree.find(lambda n: n.tag == 'script' and n.attrs.get('src') == self.BEACON)
            self.assertEqual(len(beacons), 1, page)
            self.assertEqual(beacons[0].attrs.get('type'), 'module', page)
            self.assertEqual(json.loads(beacons[0].attrs['data-cf-beacon']), {'token': token}, page)
        self.assertIn('index.html', pages)
        self.assertIn('404.html', pages)
        self.assertLessEqual({page_file(n) for n in self.trees}, set(pages))

    GAME_UI_KEYS_BUILT_BY_NAME = {'say_branch_new', 'say_branch_moved', 'say_branch_deleted',
                                  'say_tag_new', 'say_tag_moved', 'say_tag_deleted'}

    def test_the_game_reads_every_ui_string_home_json_has_and_no_other(self):
        with open(os.path.join(ROOT, 'assets', 'git-game.js'), encoding='utf-8') as f:
            source = f.read()
        read = set(re.findall(r'\bui\.([a-z_]+)', source))
        self.assertIn('run', read)
        self.assertIn("ui['say_' + what + key]", source)
        ui = set(read_json(ROOT, 'content', 'home.json')['game']['ui'])
        self.assertEqual(sorted(read - ui), [])
        self.assertEqual(ui - read, self.GAME_UI_KEYS_BUILT_BY_NAME)

    def test_the_game_intro_cites_the_talk_and_the_fallback_links_its_slides_first(self):
        game = read_json(ROOT, 'content', 'home.json')['game']
        talk = game['talk']
        section = self.trees['home'].find(lambda n: n.attrs.get('id') == 'play')[0]
        intro = section.find(has_class('game-intro'))[0]
        self.assertNotIn('{', intro.all_text())
        self.assertEqual([(a.attrs, a.all_text()) for a in intro.find(lambda n: n.tag == 'a')],
                         [({'href': talk['url']}, talk['title'])])
        fallback = section.find(has_class('gg-fallback'))[0]
        first = fallback.find(lambda n: n.tag == 'a')[0]
        self.assertEqual((first.attrs.get('href'), first.all_text()), (talk['url'], game['slides']))

    def test_the_hero_first_calls_to_play_the_game(self):
        hero = self.trees['home'].find(has_class('hero'))[0]
        links = hero.find(has_class('hero-actions'))[0].find(lambda n: n.tag == 'a')
        self.assertEqual([(a.classes(), a.attrs.get('href')) for a in links][0], (['hero-play'], '#play'))
        self.assertEqual(len(self.trees['home'].find(lambda n: n.attrs.get('id') == 'play')), 1)

    def test_the_game_section_is_labelled_by_its_heading(self):
        heading = read_json(ROOT, 'content', 'home.json')['game']['heading']
        section = self.trees['home'].find(lambda n: n.attrs.get('id') == 'play')[0]
        label = section.attrs.get('aria-labelledby')
        self.assertEqual([(n.tag, n.all_text()) for n in self.trees['home'].find(lambda n: n.attrs.get('id') == label)],
                         [('h2', heading)])

    def test_the_hero_lists_every_profile(self):
        hero = read_json(ROOT, 'content', 'home.json')['hero']
        lists = self.trees['home'].find(has_class('hero'))[0].find(has_class('profiles'))
        self.assertEqual([n.attrs.get('aria-label') for n in lists], [hero['profiles_label']])
        self.assertEqual([(a.attrs.get('href'), a.all_text()) for a in lists[0].find(lambda n: n.tag == 'a')],
                         [(p['url'], p['label']) for p in hero['profiles']])
        self.assertTrue(hero['profiles'])


def equal_earth(lon, lat):
    """Šavrič, Patterson and Jenny, "The Equal Earth map projection" (2018), equations 1 and 2."""
    a1, a2, a3, a4 = 1.340264, -0.081106, 0.000893, 0.003796
    t = math.asin(math.sqrt(3) / 2 * math.sin(math.radians(lat)))
    x = 2 * math.sqrt(3) * math.radians(lon) * math.cos(t) / (3 * (9 * a4 * t ** 8 + 7 * a3 * t ** 6 + 3 * a2 * t ** 2 + a1))
    y = a4 * t ** 9 + a3 * t ** 7 + a2 * t ** 3 + a1 * t
    return x, y


MAP_WIDTH, MAP_NORTH, MAP_SOUTH = 1000, 84, -57


def map_point(lon, lat):
    scale = MAP_WIDTH / (2 * equal_earth(180, 0)[0])
    x, y = equal_earth(lon, lat)
    return MAP_WIDTH / 2 + x * scale, (equal_earth(0, MAP_NORTH)[1] - y) * scale


class Borders(unittest.TestCase):
    def setUp(self):
        self.world = read_json(ROOT, 'data', 'world.json')

    def owners(self, lon, lat):
        point = tuple(v * 10 for v in map_point(lon, lat))
        return [code for code, d in self.world['countries'].items() if any(inside(point, r) for r in rings(d))]

    def test_the_world_file_header_matches_this_frame(self):
        self.assertEqual(self.world['width'], MAP_WIDTH)
        self.assertAlmostEqual(self.world['height'], map_point(0, MAP_SOUTH)[1], delta=0.05)

    def test_crimea_is_drawn_inside_ukraine(self):
        self.assertEqual(self.owners(34.10, 44.95), ['UA'])
        self.assertEqual(self.owners(33.52, 44.60), ['UA'])

    def test_kosovo_is_drawn_as_its_own_country(self):
        self.assertEqual(self.owners(21.17, 42.67), ['XK'])
        self.assertEqual(self.owners(20.46, 44.82), ['RS'])


if __name__ == '__main__':
    unittest.main()
