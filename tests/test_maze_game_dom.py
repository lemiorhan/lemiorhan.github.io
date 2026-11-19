"""The 404 page's maze game mounted on the built page, run in Node on the hand-written DOM double
(tests/fake_dom.js) through tests/maze_game_dom_cli.js: what the HUD, the overlay and the pad
show, and what keys, taps, swipes, pausing, clearing a maze and the stored best score do.

A test without a layout loads the page as a browser does, so the game mounts itself on the maze
Math.random deals; the driver pins Math.random, so a test gets the same maze on every run. A test
with a layout mounts the game on that hand-drawn layout instead; on PLUS each way out of
the start scores differently, so the score says which way an input steered. Every box measures 0
unless a test places it, and nothing is drawn: how the board looks is checked only in a browser.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'maze_game_dom_cli.js')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
UI = None
PAGE = {}
BUILT = {}


class MainOf(HTMLParser):
    """The page's <main> as {tag, attrs, children} trees, with text nodes as strings, and the src
    of every script the page loads."""

    def __init__(self):
        super().__init__()
        self.scripts, self.main, self.open = [], None, []

    def handle_starttag(self, tag, attrs):
        attrs = [[k, '' if v is None else v] for k, v in attrs]
        if tag == 'script' and dict(attrs).get('src'):
            self.scripts.append(dict(attrs)['src'])
        if not self.open and tag != 'main':
            return
        node = {'tag': tag, 'attrs': attrs, 'children': []}
        if self.open:
            self.open[-1]['children'].append(node)
        else:
            self.main = node
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
    global UI
    tmp = tempfile.TemporaryDirectory()
    BUILT['tmp'] = tmp
    result = subprocess.run([sys.executable, os.path.join(ROOT, 'build.py'), '--out', tmp.name],
                            capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    page = MainOf()
    with open(os.path.join(tmp.name, '404.html'), encoding='utf-8') as f:
        page.feed(f.read())
    page.close()
    scripts = [s for s in page.scripts if s.endswith('/maze-game.js')]
    if page.main is None or len(scripts) != 1:
        raise AssertionError('the built 404.html needs one <main> and one maze-game.js script')
    PAGE.update(tree=page.main, script=os.path.join(tmp.name, scripts[0].lstrip('/')),
                location={'origin': 'http://localhost', 'pathname': '/no/such/page/'})
    with open(os.path.join(ROOT, 'content', '404.json'), encoding='utf-8') as f:
        UI = json.load(f)['maze']['ui']


def tearDownModule():
    BUILT['tmp'].cleanup()


def node():
    path = shutil.which('node')
    if not path:
        raise AssertionError('node is not on PATH; the maze game tests need Node.js.')
    return path


def job(*actions, storage=None, layout=None, random=None, reduce_motion=False):
    return {'actions': list(actions), 'storage': storage or {}, 'layout': layout, 'random': random,
            'reduceMotion': reduce_motion}


def load(*jobs):
    """Returns {"results": [...], "storage": ...} per job."""
    payload = {'page': PAGE, 'jobs': list(jobs)}
    proc = subprocess.run([node(), CLI], input=json.dumps(payload).encode('utf-8'), capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise AssertionError('maze_game_dom_cli.js exited {}:\n{}'.format(proc.returncode, proc.stderr.decode('utf-8', 'replace')))
    return json.loads(proc.stdout.decode('utf-8'))['results']


def page(*actions, **options):
    return load(job(*actions, **options))[0]


def hud(score=0, best=0, level=1, lives=3):
    return ['{} {}'.format(UI['score'], score), '{} {}'.format(UI['best'], best),
            '{} {}'.format(UI['level'], level), '{} {}'.format(UI['lives'], lives)]


def score(look):
    return int(look['hud'][0].rsplit(' ', 1)[1])


# On a random maze the start sits in the bottom row with a commit on each side
# (tests/test_maze_game.py GeneratedMazes), so a step left scores at once.
MOVE = 30
PLAY_LEFT = [['button'], ['key', 'ArrowLeft'], ['frames', MOVE]]

# Each arm out of the start holds a different number of commits and none holds them all, so the
# score after REACH frames says which way the player went and the level never clears.
PLUS = ['#########',
        '####.####',
        '##..P...#',
        '####.####',
        '####.####',
        '####.####',
        '####.####',
        '#########']
ARM = {'up': 10, 'left': 20, 'right': 30, 'down': 40}
REACH = 60
ONE_COMMIT = ['#####',
              '#.P##',
              '#####']
LINE = ['#' * 12,
        '#P' + '.' * 9 + '#',
        '#' * 12]


class Mount(unittest.TestCase):
    def test_mounting_shows_the_game_with_the_labels_404_json_gives_and_waits_for_play(self):
        look = page(['look'])['results'][0]
        self.assertFalse(look['hidden'])
        self.assertIn('has-maze', look['parent'].split())
        self.assertNotIn('is-on', look['cls'].split())
        self.assertEqual(look['hud'], hud())
        self.assertEqual(look['board'], UI['board'])
        self.assertEqual((look['role'], look['live']), ('img', 'polite'))
        self.assertEqual((look['said'], look['button']), (UI['start'], UI['play']))
        self.assertEqual(look['keys'], [['←', UI['left']], ['↑', UI['up']], ['↓', UI['down']], ['→', UI['right']]])
        self.assertFalse(look['running'])

    def test_a_best_score_stored_by_an_earlier_visit_shows_in_the_hud(self):
        look = page(['look'], storage={'maze-best': '230'})['results'][0]
        self.assertEqual(look['hud'], hud(best=230))

    def test_two_visits_whose_math_random_differs_get_different_mazes(self):
        actions = PLAY_LEFT + [['until', UI['caught'], GameOver.FRAMES, 'ArrowLeft'], ['look']]
        runs = [r['results'] for r in load(*(job(*actions, random=x) for x in (0.25, 0.75)))]
        played = [(r[3]['ran'], score(r[4])) for r in runs]
        self.assertTrue(all(points > 0 for _, points in played), played)
        self.assertNotEqual(played[0], played[1])


class Keys(unittest.TestCase):
    def test_before_play_an_arrow_key_is_left_to_the_page_while_the_maze_is_off_screen(self):
        for name, top, bottom in [('above', -600, 0), ('below', 800, 1400)]:
            with self.subTest(name):
                key, look = page(['place', '.maze-board', top, bottom], ['key', 'ArrowLeft'],
                                 ['frames', MOVE], ['look'])['results'][1::2]
                self.assertFalse(key['prevented'])
                self.assertEqual((look['said'], look['button'], look['running']), (UI['start'], UI['play'], False))

    def test_before_play_an_arrow_key_starts_the_game_once_the_maze_is_on_screen(self):
        key, look = page(['place', '.maze-board', 100, 600], ['place', '.maze-play', 60, 700],
                         ['key', 'ArrowLeft'], ['frames', MOVE], ['look'])['results'][2::2]
        self.assertTrue(key['prevented'])
        self.assertEqual((look['said'], look['button'], look['running']), (None, None, True))
        self.assertIn('is-on', look['cls'].split())
        self.assertGreater(score(look), 0)
        self.assertEqual(look['scrolls'], 0)

    def test_starting_the_game_with_the_maze_partly_off_screen_scrolls_it_into_view_once(self):
        key, play = ['key', 'ArrowLeft'], ['button']
        cases = [('below the fold', 700, 1200, 650, 1300, key, False, 'smooth'),
                 ('above the top', -300, 200, -340, 300, key, False, 'smooth'),
                 ('with reduced motion', 700, 1200, 650, 1300, key, True, 'auto'),
                 ('from Play', 700, 1200, 650, 1300, play, False, 'smooth')]
        more = [['key', 'ArrowUp'], ['tap', UI['down']], ['swipe', 40, -6], ['key', 'ArrowLeft']]
        for name, top, bottom, play_top, play_bottom, start, calm, behavior in cases:
            with self.subTest(name):
                look = page(['place', '.maze-board', top, bottom], ['place', '.maze-play', play_top, play_bottom],
                            start, *more, ['look'], reduce_motion=calm)['results'][-1]
                self.assertEqual((look['running'], look['scrolls']), (True, 1))
                self.assertEqual(look['scrolledWith'], {'block': 'nearest', 'behavior': behavior})

    def test_play_starts_the_game(self):
        look = page(['button'], ['look'])['results'][1]
        self.assertEqual((look['said'], look['button'], look['running']), (None, None, True))
        self.assertIn('is-on', look['cls'].split())

    GAME_KEYS = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'a', 'd', 'w', 's', 'A', 'D', 'W', 'S']

    def test_once_playing_the_arrows_and_wasd_are_the_games_and_other_keys_are_the_pages(self):
        modified = [['ArrowLeft', {'metaKey': True}], ['a', {'ctrlKey': True}], ['ArrowLeft', {'altKey': True}]]
        r = page(['button'], *(['key', k] for k in self.GAME_KEYS + ['x', 'Enter']),
                 *(['key', k, m] for k, m in modified))['results'][1:]
        self.assertEqual([x['prevented'] for x in r], [True] * len(self.GAME_KEYS) + [False] * (2 + len(modified)))

    KEY_WAYS = {'ArrowUp': 'up', 'w': 'up', 'W': 'up', 'ArrowLeft': 'left', 'a': 'left', 'A': 'left',
                'ArrowDown': 'down', 's': 'down', 'S': 'down', 'ArrowRight': 'right', 'd': 'right', 'D': 'right'}

    def test_each_arrow_and_wasd_key_steers_its_own_way(self):
        got = load(*(job(['button'], ['key', k], ['frames', REACH], ['look'], layout=PLUS) for k in self.KEY_WAYS))
        self.assertEqual({k: score(r['results'][-1]) for k, r in zip(self.KEY_WAYS, got)},
                         {k: ARM[way] for k, way in self.KEY_WAYS.items()})


class Pad(unittest.TestCase):
    WAYS = ['up', 'left', 'down', 'right']

    def test_a_tap_on_a_pad_arrow_starts_the_game_and_steers_its_own_way(self):
        got = load(*(job(['tap', UI[way]], ['frames', REACH], ['look'], layout=PLUS) for way in self.WAYS))
        for way, r in zip(self.WAYS, got):
            with self.subTest(way):
                tap, _, look = r['results']
                self.assertTrue(tap['prevented'])
                self.assertEqual((look['said'], look['running']), (None, True))
                self.assertIn('is-on', look['cls'].split())
                self.assertEqual(score(look), ARM[way])

    def test_a_pad_arrow_pressed_from_the_keyboard_steers_its_own_way(self):
        got = load(*(job(['press', UI[way]], ['frames', REACH], ['look'], layout=PLUS) for way in self.WAYS))
        self.assertEqual([score(r['results'][-1]) for r in got], [ARM[way] for way in self.WAYS])

    def test_lifting_the_finger_off_a_pad_arrow_is_not_a_second_move(self):
        for leave in [['key', 'p'], ['blur']]:
            with self.subTest(leave[0]):
                r = page(['hold', UI['left']], ['frames', 5], leave, ['lift', UI['left']], ['frames', REACH], ['look'],
                         layout=PLUS)['results']
                self.assertEqual((r[-1]['said'], r[-1]['button'], r[-1]['running']), (UI['paused'], UI['resume'], False))
                self.assertEqual(r[4]['ran'], 0)


class Swipe(unittest.TestCase):
    SWIPES = {'up': (6, -40), 'left': (-40, 6), 'down': (-6, 40), 'right': (40, -6)}

    def test_a_sideways_swipe_before_play_starts_the_game_and_an_up_or_down_one_is_the_pages(self):
        got = load(*(job(['swipe', dx, dy], ['frames', REACH], ['look'], layout=PLUS) for dx, dy in self.SWIPES.values()))
        for way, r in zip(self.SWIPES, got):
            with self.subTest(way):
                swipe, _, look = r['results']
                if way in ('left', 'right'):
                    self.assertTrue(swipe['prevented'])
                    self.assertEqual((look['said'], look['button'], look['running']), (None, None, True))
                    self.assertIn('is-on', look['cls'].split())
                    self.assertEqual(score(look), ARM[way])
                else:
                    self.assertFalse(swipe['prevented'])
                    self.assertEqual((look['said'], look['button'], look['running']), (UI['start'], UI['play'], False))
                    self.assertNotIn('is-on', look['cls'].split())

    def test_once_playing_a_swipe_steers_the_way_it_runs(self):
        got = load(*(job(['button'], ['swipe', dx, dy], ['frames', REACH], ['look'], layout=PLUS)
                     for dx, dy in self.SWIPES.values()))
        for way, r in zip(self.SWIPES, got):
            with self.subTest(way):
                self.assertTrue(r['results'][1]['prevented'])
                self.assertEqual(score(r['results'][-1]), ARM[way])

    def test_a_short_drag_does_not_steer(self):
        r = page(['button'], ['swipe', -8, 3], ['frames', REACH], ['look'], layout=PLUS)['results']
        self.assertFalse(r[1]['prevented'])
        self.assertEqual(score(r[-1]), 0)

    def test_a_drag_that_turns_steers_again_from_where_it_turned(self):
        r = page(['button'], ['pointer', 'pointerdown', 'canvas', 0, 0, 7], ['pointer', 'pointermove', 'canvas', -40, 0, 7],
                 ['pointer', 'pointermove', 'canvas', -45, -40, 7], ['frames', REACH], ['look'], layout=PLUS)['results']
        self.assertEqual(score(r[-1]), ARM['up'])

    def drag(self, *events):
        r = page(['button'], *events, ['frames', REACH], ['look'], layout=PLUS)['results']
        return r[len(events)]['prevented'], score(r[-1])

    def test_a_drag_that_starts_off_the_maze_itself_does_not_steer(self):
        self.assertEqual(self.drag(['pointer', 'pointerdown', '.maze-overlay', 0, 0, 7],
                                   ['pointer', 'pointermove', 'canvas', -40, 0, 7]), (False, 0))

    def test_a_second_finger_does_not_steer_the_first_ones_drag(self):
        self.assertEqual(self.drag(['pointer', 'pointerdown', 'canvas', 0, 0, 7],
                                   ['pointer', 'pointermove', 'canvas', -40, 0, 8]), (False, 0))

    def test_once_the_finger_lifts_or_the_browser_cancels_the_drag_moving_the_pointer_steers_nothing(self):
        for end in ['pointerup', 'pointercancel']:
            with self.subTest(end):
                self.assertEqual(self.drag(['pointer', 'pointerdown', 'canvas', 0, 0, 7], ['pointer', end, 'canvas', 0, 0, 7],
                                           ['pointer', 'pointermove', 'canvas', -40, 0, 7]), (False, 0))


class Pause(unittest.TestCase):
    def assertPaused(self, look):
        self.assertEqual((look['said'], look['button'], look['running']), (UI['paused'], UI['resume'], False))

    def assertPlaying(self, look):
        self.assertEqual((look['said'], look['button'], look['running']), (None, None, True))

    def test_p_and_escape_pause_and_resume_and_a_paused_game_stands_still(self):
        r = page(*PLAY_LEFT, ['key', 'p'], ['look'], ['frames', MOVE], ['look'], ['key', 'P'], ['look'],
                 ['key', 'Escape'], ['look'], ['key', 'Escape'], ['look'])['results'][3:]
        p, paused, frames, later, big_p, resumed, escape, again, _, back = r
        self.assertEqual([x['prevented'] for x in (p, big_p, escape)], [True, True, True])
        self.assertPaused(paused)
        self.assertEqual(frames['ran'], 0)
        self.assertEqual(later['hud'], paused['hud'])
        self.assertPlaying(resumed)
        self.assertPaused(again)
        self.assertPlaying(back)

    def test_before_play_p_and_escape_are_the_pages_and_leaving_the_page_changes_nothing(self):
        r = page(['key', 'p'], ['key', 'Escape'], ['blur'], ['hide'], ['look'])['results']
        self.assertEqual([x['prevented'] for x in r[:2]], [False, False])
        self.assertEqual((r[-1]['said'], r[-1]['button'], r[-1]['running']), (UI['start'], UI['play'], False))

    def test_resume_or_a_move_ends_a_pause(self):
        r = page(*PLAY_LEFT, ['key', 'p'], ['button'], ['look'], ['key', 'p'], ['key', 'ArrowRight'], ['look'])['results']
        self.assertPlaying(r[5])
        self.assertPlaying(r[8])

    def test_hiding_the_tab_or_leaving_the_window_pauses_the_game(self):
        r = page(*PLAY_LEFT, ['hide'], ['look'], ['button'], ['look'], ['blur'], ['look'])['results']
        self.assertPaused(r[4])
        self.assertPlaying(r[6])
        self.assertPaused(r[8])


class Levels(unittest.TestCase):
    def test_clearing_a_maze_says_so_then_offers_the_next_one_a_level_up(self):
        r = page(['button'], ['key', 'ArrowLeft'], ['frames', 20], ['look'], ['frames', 200], ['look'],
                 ['key', 'ArrowLeft'], ['look'], layout=ONE_COMMIT)['results']
        cleared, wait, next_up, moved = r[3], r[4], r[5], r[7]
        self.assertEqual((cleared['said'], cleared['button'], cleared['running']), (UI['cleared'], None, True))
        self.assertEqual(cleared['hud'], hud(score=10, best=10))
        self.assertLess(wait['ran'], 200)
        self.assertEqual((next_up['said'], next_up['button'], next_up['running']), (UI['next'], None, False))
        self.assertEqual(next_up['hud'], hud(score=10, best=10, level=2))
        self.assertEqual((moved['said'], moved['running']), (None, True))

    def test_the_live_message_is_written_once_per_message_however_many_frames_show_it(self):
        r = page(['button'], ['key', 'ArrowLeft'], ['look'], ['frames', 20], ['look'], ['frames', 200], ['look'],
                 layout=ONE_COMMIT)['results']
        moving, cleared, next_up = r[2], r[4], r[6]
        self.assertEqual([x['said'] for x in (moving, cleared, next_up)], [None, UI['cleared'], UI['next']])
        # Mounting writes the start text and Play writes ''.
        self.assertEqual(moving['msgWrites'], 2)
        self.assertEqual(cleared['msgWrites'] - moving['msgWrites'], 1)
        self.assertEqual(next_up['msgWrites'] - cleared['msgWrites'], 1)


class Frames(unittest.TestCase):
    def test_a_late_frame_moves_the_game_on_by_a_twentieth_of_a_second_at_most(self):
        r = page(['button'], ['key', 'ArrowRight'], ['frames', 20, 1000], ['look'], layout=LINE)['results']
        # 19 late frames after the first, at 1/20 s each, are 0.95 s, 7.1 tiles at 7.5 a second:
        # seven commits. At 16 ms each they would be two; unclamped, all nine.
        self.assertEqual(r[2]['ran'], 20)
        self.assertEqual(score(r[3]), 70)

    def test_the_first_frame_after_a_start_or_a_resume_moves_nothing(self):
        resumes = [['key', 'p'], ['key', 'p'], ['frames', 1, 1000]] * 29
        r = page(['button'], ['key', 'ArrowRight'], ['frames', 1, 1000], *resumes, ['look'], ['frames', 20], ['look'],
                 layout=LINE)['results']
        self.assertEqual((r[-3]['running'], score(r[-3])), (True, 0))
        self.assertEqual(score(r[-1]), 20)


class Best(unittest.TestCase):
    def test_the_best_score_is_stored_as_soon_as_it_rises_and_the_next_visit_shows_it(self):
        first = page(*PLAY_LEFT, ['look'])
        look = first['results'][-1]
        self.assertTrue(look['running'])
        self.assertGreater(score(look), 0)
        self.assertEqual(first['storage'], {'maze-best': str(score(look))})
        again = page(['look'], storage=first['storage'])['results'][0]
        self.assertEqual(again['hud'], hud(best=score(look)))

    def test_a_lower_score_leaves_the_stored_best_alone(self):
        r = page(*PLAY_LEFT, ['look'], storage={'maze-best': '9999'})
        self.assertGreater(score(r['results'][-1]), 0)
        self.assertEqual(r['results'][-1]['hud'][1], hud(best=9999)[1])
        self.assertEqual(r['storage'], {'maze-best': '9999'})


class GameOver(unittest.TestCase):
    FRAMES = 20000

    def test_a_bug_costs_a_life_and_after_the_last_one_play_again_starts_over(self):
        r = page(*PLAY_LEFT, ['until', UI['caught'], self.FRAMES, 'ArrowLeft'], ['look'], ['blur'], ['look'],
                 ['until', UI['over'], self.FRAMES, 'ArrowLeft'], ['look'],
                 ['key', 'ArrowLeft'], ['key', 'Escape'], ['tap', UI['up']], ['swipe', 6, -40], ['frames', MOVE], ['look'],
                 ['button'], ['look'])
        caught, blurred, over = r['results'][4], r['results'][6], r['results'][8]
        key, escape, after, fresh = r['results'][9], r['results'][10], r['results'][14], r['results'][16]
        self.assertEqual((caught['said'], caught['button'], caught['running']), (UI['caught'], None, False))
        self.assertEqual(caught['hud'][3], hud(lives=2)[3])
        self.assertEqual((blurred['said'], blurred['button']), (UI['caught'], None))
        self.assertEqual((over['said'], over['button'], over['running']), (UI['over'], UI['again'], False))
        final = score(over)
        self.assertGreater(final, 0)
        self.assertEqual(over['hud'], hud(score=final, best=final, lives=0))
        self.assertEqual(r['storage'], {'maze-best': str(final)})
        self.assertEqual((key['prevented'], escape['prevented']), (False, False))
        self.assertEqual((after['said'], after['button'], after['running'], after['hud']), (over['said'], over['button'], False, over['hud']))
        self.assertEqual(fresh['hud'], hud(best=final))
        self.assertEqual((fresh['said'], fresh['button'], fresh['running']), (None, None, True))


if __name__ == '__main__':
    unittest.main()
