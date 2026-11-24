"""The git game's page code, mount() in assets/git-game.js, run in Node on a hand-written DOM
double (tests/fake_dom.js) through tests/git_game_dom_cli.js.

The page is the one the build writes: build.py runs into a temp dir, and the game section of its
index.html and the game's scripts, in the page's order, make every page load here. The scripts
run as classic scripts, so the game mounts itself as it does in a browser.

Expected values are written by hand from the game's UI strings and levels in content/home.json.
Content the page shows as it is given (level titles, the welcome line, a level's fact, the talk URL,
the slides text) and the par, the sum of the solutions' lengths, are read from content/home.json.
Commit hashes are read off the graph the page draws, as a player reads them.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'git_game_dom_cli.js')
TIMEOUT = 120
TAP = 44
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
GAME_SCRIPTS = ['assets/git-engine.js', 'assets/git-game.js']
LOCATION = {'origin': 'https://example.test', 'pathname': '/'}

GAME = i18n.content('home')['game']
LEVELS = GAME['levels']

PAGE = {}
BUILT = {}


class GamePage(HTMLParser):
    """The <section id="play"> of a built page as {tag, attrs, children} trees, with text nodes
    as strings, and the src of every script the page loads, in order."""

    def __init__(self):
        super().__init__()
        self.scripts, self.section, self.open = [], None, []

    def handle_starttag(self, tag, attrs):
        attrs = [[k, '' if v is None else v] for k, v in attrs]
        named = dict(attrs)
        if tag == 'script' and named.get('src'):
            self.scripts.append(named['src'])
        if not self.open:
            if tag != 'section' or named.get('id') != 'play':
                return
            if self.section is not None:
                raise AssertionError('the page has two sections with id "play"')
        node = {'tag': tag, 'attrs': attrs, 'children': []}
        if self.open:
            self.open[-1]['children'].append(node)
        else:
            self.section = node
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
    page = GamePage()
    with open(os.path.join(tmp.name, 'index.html'), encoding='utf-8') as f:
        page.feed(f.read())
    page.close()
    if page.section is None:
        raise AssertionError('the built index.html has no <section id="play">')
    BUILT['scripts'] = [s for s in page.scripts if os.path.basename(s).startswith('git-')]
    PAGE.update(tree=page.section, location=LOCATION,
                scripts=[os.path.join(tmp.name, s) for s in BUILT['scripts']])


def tearDownModule():
    BUILT['tmp'].cleanup()


def node():
    path = shutil.which('node')
    if not path:
        raise AssertionError('node is not on PATH. The git game tests need Node.js '
                             '(it ships on the ubuntu-latest CI runner); install node to run them.')
    return path


def session(*mounts, narrow=False, storage=None):
    """Loads the page once per list of actions, all on one storage, and returns
    {"mounts": [[result per action], ...], "storage": what the page left in it}."""
    job = {'narrow': narrow, 'storage': storage or {}, 'mounts': [list(m) for m in mounts]}
    proc = subprocess.run([node(), CLI], input=json.dumps({'page': PAGE, 'jobs': [job]}).encode('utf-8'),
                          capture_output=True, timeout=TIMEOUT)
    if proc.returncode != 0:
        raise AssertionError(f'git_game_dom_cli.js exited {proc.returncode}:\n' + proc.stderr.decode('utf-8', 'replace'))
    return json.loads(proc.stdout.decode('utf-8'))['results'][0]


def number(level_id):
    return [lv['id'] for lv in LEVELS].index(level_id) + 1


def go_to(level_id):
    return ['tap', '.gg-strip .gg-lv', number(level_id) - 1]


def note(text):
    return {'cls': 'gg-o gg-o-note', 'text': text}


def cmd(text):
    return {'cls': 'gg-o gg-o-cmd', 'text': text}


def out(text):
    return {'cls': 'gg-o gg-o-out', 'text': text}


def hashes(look):
    return {r['title']: r['hash'] for r in look['live']['rows']}


class Mount(unittest.TestCase):
    def test_the_built_page_loads_the_engine_then_the_game(self):
        self.assertEqual(BUILT['scripts'], GAME_SCRIPTS)

    def test_mounting_replaces_the_fallback_with_the_level_strip_and_both_graphs(self):
        got = session([['look']])['mounts'][0][0]
        n = len(LEVELS)
        self.assertEqual(got['mount'], {'cls': 'gg is-live', 'fallback': 0})
        self.assertEqual([b['text'] for b in got['strip']], [str(i) for i in range(1, n + 1)])
        self.assertEqual([b['current'] for b in got['strip']], ['step'] + [None] * (n - 1))
        self.assertEqual(got['strip'][0]['label'], 'Level 1: Hello, 2001')
        self.assertEqual((got['count'], got['title']), (f'Level 1 of {n}', 'Hello, 2001'))
        self.assertEqual(got['out'], [note('# Level 1: Hello, 2001'), note(GAME['ui']['welcome_help'])])
        live = got['live']
        self.assertEqual([(r['title'], r['shownHash'], r['msg']) for r in live['rows']],
                         [('Marmara University', live['rows'][0]['hash'], 'Marmara University')])
        self.assertEqual([(f['insert'], f['text']) for f in live['flags']], [('main', 'HEAD -> main')])
        goal = got['goal']
        self.assertEqual(goal['label'], 'Goal: main at a new commit. HEAD on main. 3 commits, 0 of them unreachable.')
        self.assertEqual([(r['shownHash'], r['msg'], r['hit']) for r in goal['rows']], [
            ('·······', 'a new commit', None), ('·······', 'a new commit', None),
            (live['rows'][0]['hash'], 'Marmara University', None)])
        self.assertEqual([(f['text'], f['hit']) for f in goal['flags']], [('HEAD -> main', None)])
        self.assertTrue(got['card']['hidden'])


class PhoneTargets(unittest.TestCase):
    # Each level's flags as its setup leaves them, written by hand from content/home.json.
    FLAGS = {
        'first-commit': ['HEAD -> main'],
        'branch': ['HEAD -> main'],
        'no-ff': ['HEAD -> main', 'air-force'],
        'tag': ['HEAD -> main'],
        'amend': ['HEAD -> main'],
        'rebase': ['HEAD -> main', 'typofix'],
        'cherry-pick': ['HEAD -> main', 'experiments'],
        'reset': ['HEAD -> main'],
        'revert': ['HEAD -> main'],
        'reflog': ['HEAD -> main'],
        'onto': ['HEAD -> main', 'craftgate', 'services'],
        'release': ['HEAD -> main', 'talk'],
    }

    def test_on_a_phone_every_flag_and_commit_row_has_a_fingertip_hit_rect(self):
        self.assertEqual(list(self.FLAGS), [lv['id'] for lv in LEVELS])
        actions = []
        for lv in LEVELS:
            actions += [go_to(lv['id']), ['look']]
        got = session(actions, narrow=True)['mounts'][0]
        self.assertEqual(len(got), 2 * len(LEVELS))
        for lv, tap, look in zip(LEVELS, got[0::2], got[1::2]):
            with self.subTest(lv['id']):
                self.assertGreaterEqual(tap['handled'], 1)
                self.assertEqual(look['title'], lv['title'])
                flags = look['live']['flags']
                self.assertEqual(sorted(f['text'] for f in flags), self.FLAGS[lv['id']])
                for f in flags:
                    self.assertGreaterEqual(f['hit']['width'], TAP, f['text'])
                    self.assertGreaterEqual(f['hit']['height'], TAP, f['text'])
                self.assertTrue(look['live']['rows'])
                for r in look['live']['rows']:
                    self.assertGreaterEqual(r['hit']['height'], TAP, r['title'])


class HintLine(unittest.TestCase):
    def test_the_amend_near_miss_prints_its_hint_as_a_note_and_says_it(self):
        line = ('Your graph has the right shape, but Slides, with demo was made another way: '
                'the goal has Slides, amended. Try git commit --amend.')
        got = session([go_to('amend'), ['type', 'git reset --soft HEAD~1'], ['enter'],
                       ['type', 'git commit -m "Slides, with demo"'], ['enter'], ['look']])['mounts'][0]
        look = got[-1]
        a, x = hashes(look)['Abstract'], hashes(look)['Slides, with demo']
        self.assertEqual(look['out'], [
            note(f'# Level {number("amend")}: Forgot something'),
            cmd('git reset --soft HEAD~1'),
            cmd('git commit -m "Slides, with demo"'),
            out(f'[main {x}] Slides, with demo'),
            note(line),
        ])
        self.assertEqual(look['said'], f'New commit {x}. main moved from {a} to {x}. {line}')
        self.assertEqual([r['handled'] >= 1 for r in got[:-1]], [True] * 5)


class RowText(unittest.TestCase):
    def test_a_commit_row_its_title_and_its_label_carry_the_first_line_of_the_message(self):
        got = session([go_to('amend'), ['type', 'git reset --soft HEAD~1'], ['enter'],
                       ['type', 'git commit -m "Slides" -m "with demo"'], ['enter'], ['look']])['mounts'][0]
        self.assertEqual([r['handled'] >= 1 for r in got[:-1]], [True] * 5)
        rows = {r['cls']: r for r in got[-1]['live']['rows']}
        self.assertEqual(len(got[-1]['live']['rows']), 3)
        new, old, a = (rows[c]['hash'] for c in ('gg-row is-head', 'gg-row is-lost', 'gg-row'))
        tail = '. Enter puts the hash on the command line.'
        self.assertEqual({c: (r['msg'], r['title'], r['label']) for c, r in rows.items()}, {
            'gg-row is-head': ('Slides', 'Slides', f'Commit {new}, Slides{tail}'),
            'gg-row is-lost': ('Slides', 'Slides', f'Commit {old}, Slides, unreachable{tail}'),
            'gg-row': ('Abstract', 'Abstract', f'Commit {a}, Abstract{tail}'),
        })


class Solve(unittest.TestCase):
    def test_the_amend_solution_shows_the_card_saves_progress_and_a_fresh_page_starts_there_solved(self):
        n = number('amend')
        solved_label = f'Level {n}: Forgot something, solved with 3 of 3 stars'
        got = session([go_to('amend'), ['type', 'git commit --amend -m "Slides, with demo"'], ['enter'], ['look']],
                      [['look']])
        solved, fresh = got['mounts'][0][-1], got['mounts'][1][0]
        s, x = hashes(solved)['Slides'], hashes(solved)['Slides, with demo']
        self.assertEqual(solved['card'], {
            'hidden': False, 'title': 'Your graph matches the goal.',
            'stars': {'label': '3 of 3 stars', 'all': 3, 'on': 3},
            'score': '1 command, par 1',
            'fact': LEVELS[n - 1]['fact']['text'],
            'link': {'href': 'https://speakerdeck.com/lemiorhan/git-bildiginiz-gibi-degil', 'text': 'The slides of the talk'},
            'next': ['Next level'], 'summary': None,
        })
        self.assertEqual(solved['said'], f'New commit {x}. main moved from {s} to {x}. Solved, 3 of 3 stars.')
        self.assertEqual(json.loads(solved['stored']['git-game']),
                         {'solved': {'amend': {'stars': 3, 'best': 1}}, 'level': n - 1})
        self.assertEqual(solved['strip'][n - 1]['label'], solved_label)
        for look in (solved, fresh):
            self.assertEqual([(b['stars'], 'is-solved' in b['cls'].split()) for b in look['strip']],
                             [('3', True) if i == n else ('0', False) for i in range(1, len(LEVELS) + 1)])
        self.assertEqual(fresh['strip'][n - 1]['label'], solved_label)
        self.assertEqual(fresh['strip'][n - 1]['current'], 'step')
        self.assertEqual((fresh['count'], fresh['title']), (f'Level {n} of {len(LEVELS)}', 'Forgot something'))
        self.assertTrue(fresh['card']['hidden'])


class FlagTap(unittest.TestCase):
    def test_tapping_a_flag_puts_its_name_on_the_command_line_without_taking_the_focus(self):
        got = session([go_to('no-ff'), ['tap', '.gg-cmds [data-cmd="merge"]'], ['tap-flag', 'air-force'], ['look'],
                       ['type', 'git merge air-force '], ['tap-flag', 'main'], ['look']], narrow=True)['mounts'][0]
        self.assertEqual(got[3]['input'], {'value': 'git merge air-force ', 'caret': 20, 'focused': False})
        self.assertEqual(got[3]['chips'], {'pressed': ['merge'], 'options': ['--no-ff'], 'hidden': False})
        self.assertEqual(got[6]['input'], {'value': 'git merge air-force main ', 'caret': 25, 'focused': True})
        for tap in (got[2], got[5]):
            self.assertEqual((tap['pointerdown'], tap['handled'] >= 2), (True, True))

    def test_tapping_a_command_button_while_typing_keeps_the_focus_on_the_input(self):
        got = session([['type', 'git '], ['tap', '.gg-cmds [data-cmd="merge"]'], ['look']], narrow=True)['mounts'][0]
        self.assertEqual(got[1]['pointerdown'], True)
        self.assertEqual(got[2]['input']['focused'], True)
        self.assertEqual(got[2]['chips']['pressed'], ['merge'])


class TabKey(unittest.TestCase):
    def test_a_tab_that_completes_is_used_and_a_second_tab_on_the_same_list_is_not(self):
        got = session([['type', 'git reb'], ['look'], ['tab'], ['look'],
                       ['type', 'git reset --'], ['tab'], ['look'], ['tab'], ['look'],
                       ['type', 'git sta'], ['tab', {'shiftKey': True}], ['look']])['mounts'][0]
        typed, fill, filled = got[1], got[2], got[3]
        self.assertEqual(typed['chips'], {'pressed': [], 'options': [], 'hidden': True})
        self.assertEqual((fill['prevented'], fill['handled']), (True, 1))
        self.assertEqual(filled['input'], {'value': 'git rebase ', 'caret': 11, 'focused': True})
        self.assertEqual(filled['chips'], {'pressed': ['rebase'], 'options': ['--onto'], 'hidden': False})
        first, listed, second, after = got[5], got[6], got[7], got[8]
        self.assertEqual((first['prevented'], first['handled']), (True, 1))
        self.assertEqual(listed['out'], filled['out'] + [out('--hard  --soft')])
        self.assertEqual((second['prevented'], second['handled']), (False, 1))
        self.assertEqual(after['out'], listed['out'])
        self.assertEqual(after['input']['value'], 'git reset --')
        shift, shifted = got[10], got[11]
        self.assertEqual((shift['prevented'], shift['handled']), (False, 1))
        self.assertEqual((shifted['input']['value'], shifted['out']), ('git sta', listed['out']))


class AllLevels(unittest.TestCase):
    def test_every_level_solved_through_the_page_ends_on_the_summary(self):
        n = len(LEVELS)
        par = sum(len(lv['solution']) for lv in LEVELS)
        for narrow in (False, True):
            with self.subTest(narrow=narrow):
                actions, looks = [], []
                for i, lv in enumerate(LEVELS):
                    if i:
                        actions.append(['tap', '.gg-card .gg-next'])
                    for line in lv['solution']:
                        actions += [['type', line], ['enter']]
                    looks.append(len(actions))
                    actions.append(['look'])
                got = session(actions, narrow=narrow)['mounts'][0]
                self.assertEqual([r['handled'] >= 1 for i, r in enumerate(got) if i not in looks],
                                 [True] * (len(actions) - n))
                for i, (lv, at) in enumerate(zip(LEVELS, looks)):
                    look = got[at]
                    self.assertEqual((look['count'], look['title']), (f'Level {i + 1} of {n}', lv['title']), lv['id'])
                    self.assertEqual([o['cls'] for o in look['out'] if o['cls'] == 'gg-o gg-o-err'], [], lv['id'])
                    self.assertEqual((look['card']['hidden'], look['card']['stars']['on']), (False, 3), lv['id'])
                last = got[looks[-1]]
                self.assertEqual(last['card']['next'], [])
                self.assertEqual(last['card']['summary'], {
                    'title': 'Your result', 'rank': 'Software crafter',
                    'list': [['Levels solved', f'{n} of {n}'], ['Commands', str(par)], ['Par', str(par)],
                             ['Stars', f'{3 * n} of {3 * n}']],
                    'result': f"I played Git is a graph, Lemi Orhan Ergin's git game: {n} of {n} levels, "
                              f"{par} commands for a par of {par}, {3 * n} of {3 * n} stars. "
                              "Rank: Software crafter. https://example.test/#play",
                    'links': [[GAME['talk']['url'], GAME['slides']], ['talks/', 'Every talk, year by year']],
                })
                self.assertEqual([(b['stars'], 'is-solved' in b['cls'].split()) for b in last['strip']], [('3', True)] * n)
                self.assertEqual(json.loads(last['stored']['git-game'])['solved'],
                                 {lv['id']: {'stars': 3, 'best': len(lv['solution'])} for lv in LEVELS})


class Double(unittest.TestCase):
    REFUSALS = [
        ('select', 'div + p', 'unsupported selector "div + p"'),
        ('select', '> p', 'unsupported selector "> p"'),
        ('select', 'div > > p', 'unsupported selector "div > > p"'),
        ('select', 'li:first-child', 'unsupported selector "li:first-child"'),
        ('get', 'innerHTML', '<input> has no innerHTML'),
        ('set', 'onclick', 'cannot set <input>.onclick'),
        ('get', 'href', 'would be a resolved URL'),
        ('media', '(min-width: 64rem)', 'unsupported media query (min-width: 64rem)'),
        ('global', 'navigator', 'navigator is not defined'),
        ('global', 'ResizeObserver', 'ResizeObserver is not defined'),
        ('event', 'focus', 'no focus events'),
        ('listen', 'change', 'no change events'),
        ('namespace', 'http://www.w3.org/1999/xhtml', 'unsupported namespace'),
        ('focus', '.gg-board', '<div> cannot take focus'),
        ('storage', 'removeItem', 'localStorage has no removeItem'),
        ('raise', 'a listener failed', 'a listener failed'),
    ]

    def test_the_double_throws_on_what_it_does_not_implement(self):
        got = session([['refuse', kind, arg] for kind, arg, _ in self.REFUSALS])['mounts'][0]
        self.assertEqual(len(got), len(self.REFUSALS))
        for (kind, arg, message), result in zip(self.REFUSALS, got):
            with self.subTest(kind=kind, arg=arg):
                self.assertIsNotNone(result['error'])
                self.assertIn(message, result['error'])


if __name__ == '__main__':
    unittest.main()
