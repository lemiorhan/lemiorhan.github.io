"""The filters of the talks archive, setupArchive() and setupTalkMap() in assets/site.js, run in
Node on the hand-written DOM double (tests/fake_dom.js) through tests/archive_dom_cli.js.

The page is the one the build writes: its ui-text island and its archive, map included. Which
events, talks and years each choice should leave on screen is derived from content/talks.json,
and the status lines from its UI strings.

The double has no layout, so a tag click is pinned to scroll the page once, not by how much.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from html.parser import HTMLParser

import i18n

ROOT =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'archive_dom_cli.js')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}

ARCHIVE = i18n.content('talks')['archive']
UI = ARCHIVE['ui']
LABELS = ARCHIVE['themes']['items']
EVENTS = [('y' + year, ev) for year, evs in sorted(ARCHIVE['events'].items(), reverse=True) for ev in evs]

BUILT = {}


class ArchivePage(HTMLParser):
    """The ui-text island and <main class="archive"> of a built page as {tag, attrs, children}
    trees, text nodes as strings."""

    def __init__(self):
        super().__init__()
        self.trees, self.open = [], []

    def handle_starttag(self, tag, attrs):
        attrs = [[k, '' if v is None else v] for k, v in attrs]
        named = dict(attrs)
        if not self.open and not (named.get('id') == 'ui-text' or 'archive' in named.get('class', '').split()):
            return
        node = {'tag': tag, 'attrs': attrs, 'children': []}
        (self.open[-1]['children'] if self.open else self.trees).append(node)
        if tag not in VOID:
            self.open.append(node)

    def handle_endtag(self, tag):
        if self.open and tag not in VOID:
            node = self.open.pop()
            if node['tag'] != tag:
                raise AssertionError(f'</{tag}> closes <{node["tag"]}>')

    def handle_data(self, data):
        if self.open:
            self.open[-1]['children'].append(data)


def build_talks(site, out):
    result = subprocess.run([sys.executable, os.path.join(site, 'build.py'), '--out', out], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    page = ArchivePage()
    with open(os.path.join(out, 'talks', 'index.html'), encoding='utf-8') as f:
        page.feed(f.read())
    page.close()
    if [t['tag'] for t in page.trees] != ['script', 'main']:
        raise AssertionError('the built talks page should give the ui-text island and then the archive')
    return page.trees


def setUpModule():
    tmp = tempfile.TemporaryDirectory()
    BUILT['tmp'] = tmp
    BUILT['tree'] = build_talks(ROOT, tmp.name)
    BUILT['script'] = os.path.join(tmp.name, 'assets', 'site.js')


def tearDownModule():
    BUILT['tmp'].cleanup()


def run(*actions, tree=None):
    path = shutil.which('node')
    if not path:
        raise AssertionError('node is not on PATH. The archive tests need Node.js '
                             '(it ships on the ubuntu-latest CI runner); install node to run them.')
    request = {'tree': tree or BUILT['tree'], 'script': BUILT['script'], 'actions': [list(a) for a in actions]}
    proc = subprocess.run([path, CLI], input=json.dumps(request).encode('utf-8'), capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise AssertionError('archive_dom_cli.js exited {}:\n{}'.format(proc.returncode, proc.stderr.decode('utf-8', 'replace')))
    return [r for r, a in zip(json.loads(proc.stdout.decode('utf-8'))['results'], actions) if a[0] == 'look']


def fill(template, **values):
    for k, v in values.items():
        template = template.replace('{' + k + '}', str(v))
    return template


def plural(n):
    return fill(UI['event_one' if n == 1 else 'event_many'], n=n)


def about(talk, theme):
    return theme in talk.get('themes', [])


def where(ev):
    """(country, Turkish province) of an event, from talks.json's places."""
    key = ev.get('place')
    if not key or key == 'online':
        return (key or '', '')
    place = ARCHIVE['places'][key]
    return (place['country'], place.get('province', ''))


def shown(theme='', media='all', country='', region='', location_type='', events=None):
    """The events the page should show, each with which of its talks stay visible."""
    out = []
    for year, ev in events or EVENTS:
        talks = ev.get('talks', [])
        if media != 'all' and not any(t.get(media) for t in talks):
            continue
        if location_type and ev.get('locationType') != location_type:
            continue
        if theme and not any(about(t, theme) for t in talks):
            continue
        if country and where(ev)[0] != country or region and where(ev)[1] != region:
            continue
        out.append({'year': year, 'name': ev['name'], 'talks': [not theme or about(t, theme) for t in talks]})
    return out


def years(events):
    return sorted({e['year'] for e in events}, reverse=True)


class ThemeFilter(unittest.TestCase):
    def test_on_load_the_cloud_and_the_tags_appear_with_every_event_shown_and_no_theme_chosen(self):
        look, = run(['look'])
        everything = shown()
        self.assertFalse(look['cloudHidden'])
        tagged = sum(bool(t.get('themes')) for _, ev in EVENTS for t in ev.get('talks', []))
        self.assertEqual(look['tagsHidden'], [False] * tagged)
        self.assertGreater(tagged, 1)
        self.assertEqual(look['events'], everything)
        self.assertEqual(look['years'], years(everything))
        self.assertEqual(look['themes'], [''])
        self.assertEqual(look['status'], fill(UI['showing_all'], events=plural(len(EVENTS))))
        self.assertGreater(len(everything), 1)

    def test_the_all_themes_chip_clears_the_chosen_theme_and_stays_chosen_when_clicked_again(self):
        before, cleared, again = run(['look'], ['click', '.cloud button[data-theme="git"]'],
                                     ['click', '.cloud button[data-theme=""]'], ['look'],
                                     ['click', '.cloud button[data-theme=""]'], ['look'])
        self.assertEqual(cleared, before)
        self.assertEqual(again, before)
        self.assertEqual(before['themes'], [''])
        self.assertLess(len(shown(theme='git')), len(EVENTS))

    def test_each_chip_shows_exactly_the_events_with_a_talk_about_its_theme(self):
        actions = []
        for key in LABELS:
            actions += [['click', '.cloud button[data-theme="{}"]'.format(key)], ['look']]
        looks = run(*actions)
        self.assertEqual(len(looks), len(LABELS))
        stepped_aside = 0
        for key, look in zip(LABELS, looks):
            with self.subTest(theme=key):
                want = shown(theme=key)
                self.assertEqual(look['events'], want)
                self.assertEqual(look['years'], years(want))
                tags = sum(about(t, key) for _, ev in EVENTS for t in ev.get('talks', []))
                self.assertEqual(look['themes'], [key] * (1 + tags))
                self.assertEqual(look['status'], fill(UI['theme_status'], events=plural(len(want)), theme=LABELS[key]))
                self.assertTrue(look['emptyHidden'])
                self.assertEqual(look['scrolls'], [])
                stepped_aside += sum(not v for e in want for v in e['talks'])
        self.assertGreater(len(LABELS), 1)
        self.assertGreater(stepped_aside, 0, 'no theme hides a talk inside a shown event, so that path goes unchecked')

    def test_a_second_click_on_the_chosen_chip_brings_everything_back(self):
        before, after = run(['look'], ['click', '.cloud button[data-theme="git"]'],
                            ['click', '.cloud button[data-theme="git"]'], ['look'])
        self.assertEqual(after, before)
        self.assertLess(len(shown(theme='git')), len(EVENTS))

    def test_a_tag_on_a_talk_filters_like_its_chip_and_scrolls_the_page_once(self):
        look, = run(['click', '.ev-talks button[data-theme="lean"]'], ['look'])
        self.assertEqual(look['events'], shown(theme='lean'))
        tags = sum(about(t, 'lean') for _, ev in EVENTS for t in ev.get('talks', []))
        self.assertEqual(look['themes'], ['lean'] * (1 + tags))
        self.assertEqual(look['scrolls'], [0])

    def test_a_theme_and_a_media_filter_combine_and_the_media_filter_stays_when_the_theme_goes(self):
        both, media_only = run(['click', '.filters button[data-filter="slides"]'],
                               ['click', '.cloud button[data-theme="lean"]'], ['look'],
                               ['click', '.cloud button[data-theme="lean"]'], ['look'])
        want = shown(theme='lean', media='slides')
        self.assertEqual(both['events'], want)
        self.assertEqual(both['media'], ['slides'])
        self.assertEqual(both['status'], fill(UI['theme_status'], events=plural(len(want)), theme=LABELS['lean']))
        self.assertLess(len(want), len(shown(theme='lean')))
        slides = shown(media='slides')
        self.assertEqual(media_only['events'], slides)
        self.assertEqual(media_only['themes'], [''])
        self.assertEqual(media_only['status'], fill(UI['showing_some'], visible=len(slides), events=plural(len(EVENTS))))

    def test_a_theme_and_a_country_narrow_each_other_and_the_status_names_both(self):
        country = '.tmap-controls button[data-country="TR"]'
        everywhere = '.tmap-controls button[data-country=""]'
        both, theme_only, place_only, neither = run(
            ['click', country], ['click', '.cloud button[data-theme="agile"]'], ['look'],
            ['click', everywhere], ['look'],
            ['click', country], ['click', '.cloud button[data-theme=""]'], ['look'],
            ['click', everywhere], ['look'])
        place, theme = ARCHIVE['countries']['TR'], LABELS['agile']
        want = shown(theme='agile', country='TR')
        self.assertTrue(0 < len(want) < min(len(shown(theme='agile')), len(shown(country='TR'))))
        self.assertEqual(both['events'], want)
        self.assertEqual(both['status'], fill(UI['theme_place_status'], events=plural(len(want)), theme=theme, place=place))
        self.assertEqual(both['mapStatus'], fill(UI['place_status'], events=plural(len(want)), place=place))

        agile = shown(theme='agile')
        self.assertEqual(theme_only['events'], agile)
        self.assertEqual(theme_only['status'], fill(UI['theme_status'], events=plural(len(agile)), theme=theme))
        self.assertEqual(theme_only['mapStatus'], '')

        turkiye = shown(country='TR')
        self.assertEqual(place_only['events'], turkiye)
        self.assertEqual(place_only['status'], fill(UI['place_status'], events=plural(len(turkiye)), place=place))
        self.assertEqual(place_only['mapStatus'], place_only['status'])

        self.assertEqual(neither['events'], shown())
        self.assertEqual(neither['status'], fill(UI['showing_all'], events=plural(len(EVENTS))))
        self.assertEqual(neither['mapStatus'], '')

    def test_a_theme_and_a_province_narrow_each_other_and_the_status_names_the_province(self):
        look, = run(['click', '.tmap-controls button[data-country="TR"]'],
                    ['click', '.tmap-controls button[data-region="TR-34"]'],
                    ['click', '.cloud button[data-theme="agile"]'], ['look'])
        want = shown(theme='agile', region='TR-34')
        self.assertTrue(0 < len(want) < min(len(shown(theme='agile', country='TR')), len(shown(region='TR-34'))))
        self.assertEqual(look['events'], want)
        place = 'İstanbul, ' + ARCHIVE['countries']['TR']
        self.assertEqual(look['status'], fill(UI['theme_place_status'], events=plural(len(want)), theme=LABELS['agile'], place=place))
        self.assertEqual(look['mapStatus'], fill(UI['place_status'], events=plural(len(want)), place=place))


TURKIYE = '.tmap-controls button[data-country="TR"]'
KINDS = ARCHIVE['locationTypes']['items']


def chip(kind):
    return '.filter-bar .location-types button[data-location-type="{}"]'.format(kind)


def chip_counts(tree):
    """(location type, count on its chip) for every chip of a built talks page."""
    def walk(node):
        if isinstance(node, str):
            return
        attrs = dict(node['attrs'])
        if node['tag'] == 'button' and 'data-location-type' in attrs:
            n = next(c for c in node['children'] if not isinstance(c, str) and dict(c['attrs']).get('class') == 'n')
            yield attrs['data-location-type'], int(''.join(n['children']))
        for c in node['children']:
            yield from walk(c)
    return [kc for t in tree for kc in walk(t)]


class LocationTypeFilter(unittest.TestCase):
    def test_on_load_every_chip_appears_off_with_every_event_shown(self):
        look, = run(['look'])
        self.assertFalse(look['barHidden'])
        self.assertEqual(look['locationTypes'], [])
        self.assertEqual(look['events'], shown())

    def test_a_chip_shows_exactly_the_events_of_its_type_and_a_second_click_brings_everything_back(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                before, on, off = run(['look'], ['click', chip(kind)], ['look'], ['click', chip(kind)], ['look'])
                want = shown(location_type=kind)
                self.assertTrue(0 < len(want) < len(EVENTS))
                self.assertEqual(on['events'], want)
                self.assertEqual(on['years'], years(want))
                self.assertEqual((on['locationTypes'], on['media'], on['themes']), ([kind], ['all'], ['']))
                self.assertEqual(on['status'], fill(UI['showing_some'], visible=len(want), events=plural(len(EVENTS))))
                self.assertEqual(off, before)
        self.assertGreater(len(KINDS), 0)

    def test_choosing_another_type_switches_to_it_and_each_chip_counts_its_own_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = os.path.join(tmp, 'site')
            os.mkdir(site)
            shutil.copy(os.path.join(ROOT, 'build.py'), site)
            for d in ('content', 'assets', 'data'):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(site, d))
            path = os.path.join(site, 'content', 'talks.json')
            data = i18n.localized(i18n.read_json(path), i18n.LANGS[0])
            labels = data['archive']['locationTypes']['items']
            self.assertNotIn('bootcamp', labels)
            labels['bootcamp'] = 'Training camps'
            events = [('y' + year, ev) for year, evs in sorted(data['archive']['events'].items(), reverse=True) for ev in evs]
            camps = [ev for _, ev in events if 'locationType' not in ev][:3]
            for ev in camps:
                ev['locationType'] = 'bootcamp'
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            tree = build_talks(site, os.path.join(tmp, 'out'))
        count = Counter(ev['locationType'] for _, ev in events if 'locationType' in ev)
        by_label = sorted(count.items(), key=lambda kc: labels[kc[0]].lower())
        self.assertEqual(chip_counts(tree), by_label)
        self.assertNotEqual(by_label, sorted(count.items()), 'the labels should sort apart from the keys')
        universities, camped, both_off = run(['click', chip('university')], ['look'], ['click', chip('bootcamp')], ['look'],
                                             ['click', chip('bootcamp')], ['look'], tree=tree)
        self.assertEqual(len(shown(location_type='bootcamp', events=events)), len(camps))
        self.assertEqual(universities['events'], shown(location_type='university', events=events))
        self.assertEqual(universities['locationTypes'], ['university'])
        self.assertEqual(camped['events'], shown(location_type='bootcamp', events=events))
        self.assertEqual(camped['locationTypes'], ['bootcamp'])
        self.assertEqual(both_off['events'], shown(events=events))
        self.assertEqual(both_off['locationTypes'], [])

    def test_the_chip_and_each_other_filter_narrow_each_other_and_the_other_stays_when_the_chip_goes(self):
        kind = max(KINDS, key=lambda k: len(shown(location_type=k)))
        istanbul = 'İstanbul, ' + ARCHIVE['countries']['TR']
        others = (
            ('ethics', [['click', '.cloud button[data-theme="ethics"]']], {'theme': 'ethics'},
             lambda n: fill(UI['theme_status'], events=plural(n), theme=LABELS['ethics'])),
            ('online', [['click', '.tmap-controls button[data-country="online"]']], {'country': 'online'},
             lambda n: fill(UI['place_status'], events=plural(n), place=ARCHIVE['online'])),
            ('istanbul', [['click', TURKIYE], ['click', '.tmap-controls button[data-region="TR-34"]']], {'region': 'TR-34'},
             lambda n: fill(UI['place_status'], events=plural(n), place=istanbul)),
            ('slides', [['click', '.filters button[data-filter="slides"]']], {'media': 'slides'},
             lambda n: fill(UI['showing_some'], visible=n, events=plural(len(EVENTS)))),
        )
        for name, choose, other, status in others:
            with self.subTest(other=name):
                both, alone = run(*choose, ['click', chip(kind)], ['look'], ['click', chip(kind)], ['look'])
                want, rest = shown(location_type=kind, **other), shown(**other)
                self.assertTrue(0 < len(want) < min(len(rest), len(shown(location_type=kind))))
                self.assertEqual(both['events'], want)
                self.assertEqual(both['years'], years(want))
                self.assertEqual(both['status'], status(len(want)))
                self.assertEqual(alone['events'], rest)
                self.assertEqual(alone['status'], status(len(rest)))
                self.assertEqual(alone['locationTypes'], [])


if __name__ == '__main__':
    unittest.main()
