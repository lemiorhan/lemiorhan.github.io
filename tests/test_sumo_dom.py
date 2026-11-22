"""The live block of the sumo page, setupSumoLive() in assets/site.js, run in Node on the hand-written
DOM double (tests/fake_dom.js) through tests/sumo_dom_cli.js.

The page is the one the build writes: its ui-text island and its .sumo-live block, with the strings
of content/sumo.json. Its schedule is swapped for SCHEDULE below, so that adding next year's dates
to the content or dropping past ones leaves these tests as they are. Sumo API is a fetch stub. Its
bodies under tests/fixtures/sumo/ are real answers fetched on 2026-11-22, with each rikishi's bout
list ("record") cut out because the page never reads it. Where a test needs a shape no fetch could
give that day, such as a tournament still running, one whose lower divisions already have winners,
or a banzuke out before its tournament starts, it builds that shape from them; those shapes are
guesses at the API, not verified against it.
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import build  # noqa: E402

CLI = os.path.join(ROOT, 'tests', 'sumo_dom_cli.js')
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures', 'sumo')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
JAPAN = timezone(timedelta(hours=9))

with open(os.path.join(ROOT, 'content', 'sumo.json'), encoding='utf-8') as f:
    BLOCK = next(b for s in json.load(f)['sections'] for b in s['blocks'] if isinstance(b, dict) and b.get('type') == 'sumo-live')
T = BLOCK['text']
API = BLOCK['api']

BUILT = {}
SCHEDULE = [
    {'start': '2026-11-08', 'end': '2026-11-22', 'banzuke': '2026-10-26', 'place': 'Fukuoka, Fukuoka Kokusai Center'},
    {'start': '2027-01-10', 'end': '2027-01-24', 'banzuke': '2026-12-21', 'place': 'Tokyo, Kokugikan'},
]


def fixture(kind, basho_id):
    with open(os.path.join(FIXTURES, '{}-{}.json'.format(kind, basho_id)), encoding='utf-8') as f:
        return json.load(f)


def basho_url(basho_id):
    return '{}/basho/{}'.format(API, basho_id)


def banzuke_url(basho_id):
    return '{}/basho/{}/banzuke/Makuuchi'.format(API, basho_id)


NOT_YET_BASHO = fixture('basho', '202701')
NOT_YET_BANZUKE = fixture('banzuke', '202701')


def running(basho_id):
    basho = fixture('basho', basho_id)
    del basho['yusho'], basho['specialPrizes']
    return basho


def island(tree):
    return next(c for c in tree[1]['children'] if isinstance(c, dict) and c['tag'] == 'script')


def before_it_starts(banzuke, basho_id):
    banzuke = copy.deepcopy(banzuke)
    banzuke['bashoId'] = basho_id
    for r in banzuke['east'] + banzuke['west']:
        r.update(wins=0, losses=0, absences=0)
    return banzuke


class SumoPage(HTMLParser):
    """The ui-text island and <div class="sumo-live"> of a built page as {tag, attrs, children} trees,
    text nodes as strings."""

    def __init__(self):
        super().__init__()
        self.trees, self.open = [], []

    def handle_starttag(self, tag, attrs):
        attrs = [[k, '' if v is None else v] for k, v in attrs]
        named = dict(attrs)
        if not self.open and not (named.get('id') == 'ui-text' or 'sumo-live' in named.get('class', '').split()):
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


def setUpModule():
    tmp = tempfile.TemporaryDirectory()
    BUILT['tmp'] = tmp
    result = subprocess.run([sys.executable, os.path.join(ROOT, 'build.py'), '--out', tmp.name],
                            capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    page = SumoPage()
    with open(os.path.join(tmp.name, 'sumo', 'index.html'), encoding='utf-8') as f:
        page.feed(f.read())
    page.close()
    if [t['tag'] for t in page.trees] != ['script', 'div']:
        raise AssertionError('the built sumo page should give the ui-text island and then the sumo-live block')
    BUILT['tree'] = page.trees
    BUILT['data'] = json.loads(''.join(island(page.trees)['children']))
    BUILT['script'] = os.path.join(tmp.name, 'assets', 'site.js')


def tearDownModule():
    BUILT['tmp'].cleanup()


def run(now, responses=None, fail=None):
    path = shutil.which('node')
    if not path:
        raise AssertionError('node is not on PATH. The sumo page tests need Node.js '
                             '(it ships on the ubuntu-latest CI runner); install node to run them.')
    tree = copy.deepcopy(BUILT['tree'])
    island(tree)['children'] = [json.dumps(dict(BUILT['data'], schedule=SCHEDULE), ensure_ascii=False)]
    request = {'tree': tree, 'script': BUILT['script'], 'now': int(now.timestamp() * 1000),
               'responses': responses or {}, 'fail': fail}
    proc = subprocess.run([path, CLI], input=json.dumps(request).encode('utf-8'), capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise AssertionError('sumo_dom_cli.js exited {}:\n{}'.format(proc.returncode, proc.stderr.decode('utf-8', 'replace')))
    return json.loads(proc.stdout.decode('utf-8'))


def in_japan(*args):
    return datetime(*args, tzinfo=JAPAN)


HEAD = [[T['east'], 'col'], [T['rank'], 'col'], [T['west'], 'col']]
KYUSHU_2026 = 'Kyūshū Basho, Kasım 2026'
KYUSHU_2026_RESULT = [
    [T['last'], KYUSHU_2026],
    [T['champion'], 'Onosato, 13-2'],
    [T['prizes'], 'Atamifuji (shukun-shō), Kinbozan (kantō-shō), Tamawashi (kantō-shō), Wakamotoharu (ginō-shō)'],
]
KYUSHU_2026_ROWS = [
    ['Onosato 13-2', 'Yokozuna', 'Hoshoryu 9-6'],
    ['Aonishiki 7-8', 'Ōzeki', 'Kotozakura 8-7'],
    ['Kirishima 10-5', 'Ōzeki', ''],
    ['Fujinokawa 7-8', 'Sekiwake', 'Atamifuji 11-4'],
    ['Churanoumi 4-11', 'Komusubi', 'Yoshinofuji 7-8'],
]
HATSU_2027 = [T['next'], 'Hatsu Basho · 10–24 Ocak 2027 · Tokyo, Kokugikan']
FINISHED_KYUSHU_2026 = {basho_url('202611'): fixture('basho', '202611'),
                        banzuke_url('202701'): NOT_YET_BANZUKE,
                        banzuke_url('202611'): fixture('banzuke', '202611')}


class SumoLive(unittest.TestCase):
    def test_the_built_block_carries_the_settings_and_schedule_of_the_content(self):
        self.assertEqual(BUILT['data'], {k: BLOCK[k] for k in ('api', 'names', 'months', 'ranks', 'prizes', 'schedule', 'text')})

    def test_the_build_requires_every_text_line_site_js_reads(self):
        with open(os.path.join(ROOT, 'assets', 'site.js'), encoding='utf-8') as f:
            source = f.read()
        body = source[source.index('function setupSumoLive()'):source.index('function setupLightbox()')]
        self.assertEqual(set(re.findall(r'\btext\.(\w+)', body)) | {'noscript'}, set(build.SUMO_TEXT))

    def test_the_built_block_says_it_needs_javascript_and_site_js_replaces_that_with_loading(self):
        status = next(c for c in BUILT['tree'][1]['children'] if isinstance(c, dict) and c['tag'] == 'p')
        self.assertEqual(status['children'], [T['noscript']])
        out = run(in_japan(2026, 11, 23, 10), FINISHED_KYUSHU_2026)
        self.assertEqual(out['at_once'], {'status': T['loading'], 'lists': 0, 'facts': [], 'caption': None, 'head': [],
                                          'rows': [], 'row_heads': [], 'note': None})

    def test_after_a_tournament_it_shows_its_result_its_banzuke_and_the_next_tournament(self):
        out = run(in_japan(2026, 11, 23, 10), FINISHED_KYUSHU_2026)
        self.assertEqual(out['requests'], [basho_url('202611'), banzuke_url('202701'), banzuke_url('202611')])
        self.assertEqual(out['settled'], {
            'status': None,
            'lists': 1,
            'facts': KYUSHU_2026_RESULT + [HATSU_2027, [T['banzuke_day'], '21 Aralık 2026']],
            'caption': T['banzuke'].replace('{basho}', KYUSHU_2026),
            'head': HEAD,
            'rows': KYUSHU_2026_ROWS,
            'row_heads': ['row'] * 5,
            'note': T['record'],
        })

    def test_on_the_final_evening_the_finished_tournament_is_not_also_shown_as_running(self):
        out = run(in_japan(2026, 11, 22, 20), FINISHED_KYUSHU_2026)
        self.assertEqual(out['settled']['facts'], KYUSHU_2026_RESULT + [HATSU_2027, [T['banzuke_day'], '21 Aralık 2026']])

    def test_once_the_next_banzuke_is_out_the_table_shows_it_with_no_counts(self):
        # 08:00 on the day it is announced in Japan is still the day before in UTC.
        out = run(in_japan(2026, 12, 21, 8), {
            basho_url('202611'): fixture('basho', '202611'),
            banzuke_url('202701'): before_it_starts(fixture('banzuke', '202611'), '202701'),
            banzuke_url('202611'): fixture('banzuke', '202611')})
        self.assertEqual(out['settled']['facts'], KYUSHU_2026_RESULT + [HATSU_2027])
        self.assertEqual(out['settled']['caption'], T['banzuke'].replace('{basho}', 'Hatsu Basho, Ocak 2027'))
        self.assertEqual(out['settled']['rows'], [[c.split(' ')[0] for c in row] for row in KYUSHU_2026_ROWS])
        self.assertIsNone(out['settled']['note'])

    def test_during_a_tournament_it_reports_the_one_before_and_counts_the_running_one_so_far(self):
        out = run(in_japan(2026, 11, 15, 10), {
            basho_url('202611'): running('202611'),
            basho_url('202609'): fixture('basho', '202609'),
            banzuke_url('202611'): fixture('banzuke', '202611'),
            banzuke_url('202609'): fixture('banzuke', '202609')})
        self.assertEqual(out['requests'], [basho_url('202611'), basho_url('202609'), banzuke_url('202611'), banzuke_url('202609')])
        self.assertEqual(out['settled']['facts'], [
            [T['last'], 'Aki Basho, Eylül 2026'],
            [T['champion'], 'Onosato, 12-3'],
            [T['prizes'], 'Fujinokawa (kantō-shō), Churanoumi (kantō-shō)'],
            [T['running'], 'Kyūshū Basho · 8–22 Kasım 2026 · Fukuoka, Fukuoka Kokusai Center'],
        ])
        self.assertEqual(out['settled']['caption'], T['banzuke'].replace('{basho}', KYUSHU_2026))
        self.assertEqual(out['settled']['rows'], KYUSHU_2026_ROWS)
        self.assertEqual(out['settled']['note'], T['record_live'])

    def test_days_a_rikishi_missed_are_a_third_number_that_the_note_explains(self):
        out = run(in_japan(2026, 10, 1, 10), {
            basho_url('202609'): fixture('basho', '202609'),
            banzuke_url('202611'): NOT_YET_BANZUKE,
            banzuke_url('202609'): fixture('banzuke', '202609')})
        self.assertEqual(out['settled']['facts'][-2:], [
            [T['next'], 'Kyūshū Basho · 8–22 Kasım 2026 · Fukuoka, Fukuoka Kokusai Center'],
            [T['banzuke_day'], '26 Ekim 2026'],
        ])
        self.assertEqual(out['settled']['rows'], [
            ['Onosato 12-3', 'Yokozuna', 'Hoshoryu 0-0-15'],
            ['Kirishima 8-7', 'Ōzeki', 'Kotozakura 9-6'],
            ['Aonishiki 11-4', 'Ōzeki', ''],
            ['Atamifuji 8-7', 'Sekiwake', 'Fujinokawa 11-4'],
            ['Hakunofuji 5-10', 'Komusubi', 'Daieisho 5-10'],
        ])
        self.assertEqual(out['settled']['note'], T['record'] + ' ' + T['absences'])

    def test_the_champion_is_found_wherever_the_banzuke_lists_them(self):
        out = run(in_japan(2026, 7, 28, 10), {
            basho_url('202607'): fixture('basho', '202607'),
            banzuke_url('202609'): NOT_YET_BANZUKE,
            banzuke_url('202607'): fixture('banzuke', '202607')})
        self.assertEqual(out['settled']['facts'][:3], [
            [T['last'], 'Nagoya Basho, Temmuz 2026'],
            [T['champion'], 'Aonishiki, 12-3'],
            [T['prizes'], 'Fujinokawa (shukun-shō), Atamifuji (kantō-shō), Kotoeiho (kantō-shō), Takayasu (kantō-shō), '
                          'Aonishiki (ginō-shō)'],
        ])
        self.assertEqual(out['settled']['rows'], [
            ['Hoshoryu 7-7-1', 'Yokozuna', 'Onosato 9-6'],
            ['Kirishima 12-3', 'Ōzeki', 'Kotozakura 8-7'],
            ['Atamifuji 12-3', 'Sekiwake', 'Kotoshoho 6-9'],
            ['Wakatakakage 0-0-15', 'Sekiwake', 'Aonishiki 12-3'],
            ['Yoshinofuji 6-9', 'Komusubi', 'Oho 2-13'],
        ])

    def test_the_champion_is_the_makuuchi_winner_wherever_the_winners_list_puts_them(self):
        basho = fixture('basho', '202611')
        basho['yusho'].reverse()
        self.assertNotEqual(basho['yusho'][0]['type'], 'Makuuchi')
        out = run(in_japan(2026, 11, 23, 10), dict(FINISHED_KYUSHU_2026, **{basho_url('202611'): basho}))
        self.assertEqual(out['settled']['facts'][:2], KYUSHU_2026_RESULT[:2])

    def test_a_tournament_whose_lower_divisions_have_winners_but_makuuchi_has_none_is_still_running(self):
        basho = fixture('basho', '202611')
        basho['yusho'] = [y for y in basho['yusho'] if y['type'] != 'Makuuchi']
        del basho['specialPrizes']
        out = run(in_japan(2026, 11, 15, 10), {
            basho_url('202611'): basho,
            basho_url('202609'): fixture('basho', '202609'),
            banzuke_url('202611'): fixture('banzuke', '202611'),
            banzuke_url('202609'): fixture('banzuke', '202609')})
        self.assertEqual(out['requests'], [basho_url('202611'), basho_url('202609'), banzuke_url('202611'), banzuke_url('202609')])
        self.assertEqual(out['settled']['facts'][:2], [[T['last'], 'Aki Basho, Eylül 2026'], [T['champion'], 'Onosato, 12-3']])

    def test_a_rank_only_the_west_holds_still_sits_in_rank_order(self):
        banzuke = fixture('banzuke', '202611')
        kirishima = next(r for r in banzuke['east'] if r['rank'] == 'Ozeki 2 East')
        banzuke['east'].remove(kirishima)
        banzuke['west'].insert(2, dict(kirishima, side='West', rank='Ozeki 2 West'))
        out = run(in_japan(2026, 11, 23, 10), dict(FINISHED_KYUSHU_2026, **{banzuke_url('202611'): banzuke}))
        self.assertEqual(out['settled']['rows'][:4], KYUSHU_2026_ROWS[:2] + [['', 'Ōzeki', 'Kirishima 10-5'], KYUSHU_2026_ROWS[3]])

    def test_a_tournament_that_gave_no_special_prizes_has_no_prizes_row(self):
        basho = fixture('basho', '202611')
        del basho['specialPrizes']
        out = run(in_japan(2026, 11, 23, 10), dict(FINISHED_KYUSHU_2026, **{basho_url('202611'): basho}))
        self.assertEqual(out['settled']['facts'], KYUSHU_2026_RESULT[:2] + [HATSU_2027, [T['banzuke_day'], '21 Aralık 2026']])

    def test_when_sumo_api_fails_it_says_so_and_still_shows_the_next_tournament(self):
        for fail in ('reject', 500):
            with self.subTest(fail=fail):
                out = run(in_japan(2026, 11, 23, 10), fail=fail)
                self.assertEqual(out['requests'], [basho_url('202611')])
                self.assertEqual(out['settled'], {
                    'status': T['failed'], 'lists': 1, 'facts': [HATSU_2027, [T['banzuke_day'], '21 Aralık 2026']],
                    'caption': None, 'head': [], 'rows': [], 'row_heads': [], 'note': None})

    def test_it_looks_back_three_tournaments_at_most_and_past_the_schedule_shows_nothing_else(self):
        out = run(in_japan(2029, 1, 5, 10), {basho_url(i): NOT_YET_BASHO for i in ('202901', '202811', '202809', '202807')})
        self.assertEqual(out['requests'], [basho_url('202901'), basho_url('202811'), basho_url('202809')])
        self.assertEqual((out['settled']['status'], out['settled']['lists']), (T['failed'], 0))


if __name__ == '__main__':
    unittest.main()
