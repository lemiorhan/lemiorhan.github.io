"""The 404 page's maze game, assets/maze-game.js, run in Node through tests/maze_game_cli.js.

Mazes are checked by walking them here, not by asking the game. The rules are checked on small
hand-drawn layouts (# wall, . commit, o test, P start, B bug home), with the expected scores, times
and positions worked out by hand from those layouts; the tests about a new maze per level and per
restart use generated ones. Bugs choose at random, so their steering is checked as how often they
take a way over a fixed list of seeds, on a junction drawn so that each wrong rule picks the
other way.
"""

import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'maze_game_cli.js')
SEEDS = range(1, 61)
STEPS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}


def run(*jobs):
    out = subprocess.run(['node', CLI], input=json.dumps({'jobs': list(jobs)}),
                         capture_output=True, text=True, timeout=120)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)['results']


def play(actions, layout=None, seed=1):
    return run({'op': 'play', 'layout': layout, 'seed': seed, 'actions': actions})[0]


def open_tiles(layout):
    return {(x, y) for y, row in enumerate(layout) for x, ch in enumerate(row) if ch != '#'}


def neighbours(tile, tiles):
    return [(tile[0] + dx, tile[1] + dy) for dx, dy in STEPS.values() if (tile[0] + dx, tile[1] + dy) in tiles]


def items(layout):
    return sum(row.count('.') + row.count('o') for row in layout)


class GeneratedMazes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mazes = [r['layout'] for r in run(*({'op': 'maze', 'seed': s} for s in SEEDS))]

    def test_every_seed_gives_a_maze(self):
        self.assertEqual(len(self.mazes), len(SEEDS))
        self.assertEqual(len({tuple(m) for m in self.mazes}), len(SEEDS))

    def test_a_maze_is_a_closed_mirrored_rectangle_with_one_start_four_bug_homes_and_four_tests(self):
        for layout in self.mazes:
            self.assertEqual({len(row) for row in layout}, {len(layout[0])})
            self.assertLessEqual(set(''.join(layout)), set('#.oPB'))
            self.assertEqual(set(layout[0] + layout[-1] + ''.join(row[0] + row[-1] for row in layout)), {'#'})
            self.assertEqual([row[::-1] for row in layout], layout)
            text = ''.join(layout)
            self.assertEqual((text.count('P'), text.count('B'), text.count('o')), (1, 4, 4))
            self.assertGreaterEqual(text.count('.'), 100)

    def test_every_open_tile_is_reachable_from_the_start(self):
        for layout in self.mazes:
            tiles = open_tiles(layout)
            start = next((x, y) for y, row in enumerate(layout) for x, ch in enumerate(row) if ch == 'P')
            seen, queue = {start}, [start]
            while queue:
                for n in neighbours(queue.pop(), tiles):
                    if n not in seen:
                        seen.add(n)
                        queue.append(n)
            self.assertEqual(seen, tiles)

    def test_no_corridor_is_a_dead_end_or_wider_than_one_tile(self):
        for layout in self.mazes:
            tiles = open_tiles(layout)
            self.assertEqual([t for t in tiles if len(neighbours(t, tiles)) < 2], [])
            blocks = [(x, y) for x, y in tiles if {(x + 1, y), (x, y + 1), (x + 1, y + 1)} <= tiles]
            self.assertEqual(blocks, [])

    def test_the_start_opens_to_a_commit_on_both_sides(self):
        for layout in self.mazes:
            y = next(i for i, row in enumerate(layout) if 'P' in row)
            x = layout[y].index('P')
            self.assertEqual(layout[y][x - 1] + layout[y][x + 1], '..')


class Rules(unittest.TestCase):
    def test_commits_score_ten_a_test_fifty_and_clearing_them_all_moves_to_the_next_maze(self):
        layout = ['#######',
                  '#P...o#',
                  '#######']
        r = play([['steer', 'right'], ['step', 1], ['look'], ['step', 2], ['look']], layout)
        cleared, nxt = r['looks']
        self.assertEqual((cleared['mode'], cleared['score'], cleared['left'], cleared['player']['x']), ('cleared', 80, 0, 5))
        self.assertEqual((nxt['mode'], nxt['level'], nxt['score'], nxt['left'], nxt['player']['x']), ('ready', 2, 80, 4, 1))
        self.assertEqual(r['events'], ['dot', 'dot', 'dot', 'power', 'cleared', 'level'])

    def test_walls_stop_the_player(self):
        layout = ['#####',
                  '#P#.#',
                  '#####']
        r = play([['steer', 'right'], ['step', 1], ['look'], ['steer', 'up'], ['step', 1], ['look']], layout)
        for look in r['looks']:
            self.assertEqual((look['mode'], look['score'], look['player']['px'], look['player']['py']), ('playing', 0, 1, 1))

    CORRIDOR = ['#########',
                '#P.....B#',
                '#########']

    def test_nothing_moves_before_the_first_move_and_a_bug_costs_a_life_then_everyone_goes_home(self):
        r = play([['step', 2], ['look'],
                  ['steer', 'left'], ['step', 2], ['look'],
                  ['step', 1], ['look']], self.CORRIDOR)
        idle, caught, back = r['looks']
        self.assertEqual((idle['mode'], idle['lives'], idle['bugs'][0]['px']), ('ready', 3, 7))
        self.assertEqual((caught['mode'], caught['lives'], caught['left']), ('dying', 2, 5))
        self.assertLess(caught['bugs'][0]['px'], 2)
        self.assertEqual((back['mode'], back['lives'], back['player']['px'], back['bugs'][0]['px']), ('ready', 2, 1, 7))
        self.assertEqual(r['events'], ['caught'])

    def test_the_third_bug_ends_the_game_and_nothing_moves_or_scores_after_it(self):
        lose = [['steer', 'right'], ['step', 3]]
        r = play(lose * 3 + [['look'], ['steer', 'left'], ['step', 1], ['look']], self.CORRIDOR)
        over, later = r['looks']
        self.assertEqual((over['mode'], over['lives']), ('over', 0))
        self.assertGreater(over['score'], 0)
        self.assertEqual(later, over)
        self.assertEqual([e for e in r['events'] if e != 'dot'], ['caught', 'caught', 'caught', 'over'])

    def test_a_restart_after_the_game_is_over_starts_level_one_again_with_every_life_and_no_score(self):
        lose = [['steer', 'right'], ['step', 3]]
        r = play(lose * 3 + [['look'], ['restart'], ['look'], ['steer', 'left'], ['step', 0.1], ['look']], self.CORRIDOR)
        over, fresh, moving = r['looks']
        self.assertEqual((over['mode'], over['lives']), ('over', 0))
        self.assertGreater(over['score'], 0)
        self.assertEqual((fresh['mode'], fresh['level'], fresh['score'], fresh['lives'], fresh['left']), ('ready', 1, 0, 3, 5))
        self.assertEqual((fresh['player']['px'], fresh['bugs'][0]['px']), (1, 7))
        self.assertEqual(moving['mode'], 'playing')

    def test_a_restart_deals_a_new_maze(self):
        r = play([['look'], ['restart'], ['look']], seed=7)
        before, after = r['looks']
        self.assertNotEqual(after['layout'], before['layout'])
        self.assertEqual(after['left'], items(after['layout']))

    def test_a_test_lets_the_player_squash_a_bug_which_comes_back_dangerous(self):
        layout = ['#######',
                  '#Po  B#',
                  '#######',
                  '##.####',
                  '#######']
        r = play([['steer', 'right'], ['step', 1], ['look'],
                  ['steer', 'left'], ['step', 2.5], ['look'],
                  ['step', 1], ['look']], layout)
        squashed, back, caught = r['looks']
        self.assertEqual((squashed['mode'], squashed['score'], squashed['lives']), ('playing', 150, 3))
        self.assertTrue(squashed['bugs'][0]['gone'])
        self.assertEqual((back['lives'], back['bugs'][0]['gone'], back['bugs'][0]['scared']), (3, False, False))
        self.assertEqual((caught['mode'], caught['lives']), ('dying', 2))
        self.assertEqual(r['events'], ['power', 'squash', 'caught'])

    # The player parks against the top wall until both bugs are out (the second leaves home one
    # release after the first), then eats the test; in a corridor no bug has a choice to make.
    @staticmethod
    def chase(second_test):
        row = '#Po' + '.' * 17 + 'BB#'
        if second_test:
            row = row[:8] + 'o' + row[9:]
        return ['#' * 23, row, '#' * 23, '#.' + '#' * 21, '#' * 23]

    def test_each_bug_squashed_on_one_test_is_worth_more_and_a_new_test_starts_the_count_again(self):
        for second_test, kinds, squashes in ((False, ['power', 'squash', 'squash'], 100 + 200),
                                              (True, ['power', 'squash', 'power', 'squash'], 100 + 100)):
            with self.subTest(second_test=second_test):
                layout = self.chase(second_test)
                r = play([['steer', 'up'], ['step', 2.6], ['steer', 'right'], ['step', 2], ['look']], layout)
                look = r['looks'][0]
                kept = [e for e in r['events'] if e != 'dot']
                self.assertEqual(kept, kinds)
                eaten = items(layout) - look['left']
                tests = kept.count('power')
                self.assertEqual(look['score'] - 10 * (eaten - tests) - 50 * tests, squashes)
                self.assertEqual((look['mode'], look['lives']), ('playing', 3))

    # Bug 0 runs up and down a corridor of its own; bugs 1 and 2 are walled into their homes. The
    # commits in bug 0's corridor keep the level from clearing when the player eats the test.
    LEVELS = ['###########',
              '#Po########',
              '###########',
              '#B........#',
              '###########',
              '#B#B#######',
              '###########']
    SAMPLE = 0.05

    def timeline(self, before):
        """Steers right, then looks every SAMPLE seconds for eight seconds, half a sample off the
        whole numbers so no look lands on the instant something changes. Returns (time, look)."""
        actions = before + [['steer', 'right'], ['step', self.SAMPLE / 2]]
        times = [self.SAMPLE / 2 + k * self.SAMPLE for k in range(int(8 / self.SAMPLE))]
        for _ in times:
            actions += [['look'], ['step', self.SAMPLE]]
        r = play(actions, self.LEVELS)
        return list(zip(times, r['looks'][len(r['looks']) - len(times):]))

    @staticmethod
    def first(timeline, pred, after=0):
        return next(t for t, look in timeline if t > after and pred(look))

    def flips(self, timeline):
        scared = self.first(timeline, lambda look: look['bugs'][0]['scared'])
        return {
            'scared': scared,
            'calm': self.first(timeline, lambda look: not look['bugs'][0]['scared'], after=scared),
            'out1': self.first(timeline, lambda look: not look['bugs'][1]['waiting']),
            'out2': self.first(timeline, lambda look: not look['bugs'][2]['waiting']),
            'run': timeline[1][1]['bugs'][0]['px'],
        }

    def test_a_test_scares_the_bugs_already_out_for_seven_seconds_and_bugs_leave_home_two_and_a_half_seconds_apart(self):
        line = self.timeline([])
        self.assertEqual({look['level'] for _, look in line}, {1})
        self.assertEqual({look['mode'] for _, look in line}, {'playing'})
        got = self.flips(line)
        # The player reaches the test one tile in, at 1/7.5 s; each look is the first after a change.
        self.assertAlmostEqual(got['scared'], 0.175)
        self.assertAlmostEqual(got['calm'] - got['scared'], 7)
        self.assertAlmostEqual(got['out1'], 2.525)
        self.assertAlmostEqual(got['out2'], 5.025)
        self.assertEqual([t for t, look in line if look['bugs'][1]['scared'] or look['bugs'][2]['scared']], [])

    def test_on_the_next_level_bugs_run_faster_leave_home_sooner_and_a_test_scares_them_for_less_time(self):
        reach = [['only', 2, 1], ['steer', 'right'], ['step', 2], ['look']]
        r = play(reach, self.LEVELS)
        self.assertEqual((r['looks'][0]['mode'], r['looks'][0]['level']), ('ready', 2))
        one, two = self.flips(self.timeline([])), self.flips(self.timeline(reach))
        self.assertGreater(two['run'], one['run'])
        self.assertLess(two['out1'], one['out1'])
        self.assertLess(two['out2'], one['out2'])
        self.assertLess(two['calm'] - two['scared'], one['calm'] - one['scared'])

    # Bug 0 runs right along a nineteen-tile corridor; the player, sealed in above, either eats the
    # test one tile in or turns into the wall, which starts the game without scaring anything.
    SPEED = ['#' * 22,
             '#Po#.' + '#' * 17,
             '#' * 22,
             '#B' + '.' * 19 + '#',
             '#' * 22]

    def test_a_scared_bug_runs_slower_than_a_calm_one(self):
        def run_from(first):
            r = play([['steer', first], ['step', 0.5], ['look'], ['step', 2], ['look']], self.SPEED)
            a, b = (look['bugs'][0] for look in r['looks'])
            return (b['px'] - a['px']) / 2, a['scared'] and b['scared'], a['py'] == b['py'] == 3
        scared, calm = run_from('right'), run_from('left')
        self.assertEqual(scared[1:], (True, True))
        self.assertEqual(calm[1:], (False, True))
        self.assertAlmostEqual(scared[0], 3.6)
        self.assertAlmostEqual(calm[0], 5.6)

    def test_a_bug_still_waiting_at_home_does_not_catch_the_player_passing_through(self):
        layout = ['########',
                  '#B#P.B.#',
                  '########',
                  '#.######',
                  '########']
        r = play([['steer', 'right'], ['step', 1], ['look']], layout)
        look = r['looks'][0]
        self.assertTrue(look['bugs'][1]['waiting'])
        self.assertEqual((look['mode'], look['lives'], look['player']['px']), ('playing', 3, 6))

    def test_turning_back_mid_tile_turns_at_once_from_where_the_player_is(self):
        layout = ['#########',
                  '#...P...#',
                  '#########']
        r = play([['steer', 'right'], ['step', 0.05], ['look'], ['steer', 'left'], ['look'], ['step', 0.1], ['look']], layout)
        going, turned, back = (look['player'] for look in r['looks'])
        self.assertEqual(going['dir'], 'right')
        self.assertGreater(going['px'], 4)
        self.assertEqual(turned['dir'], 'left')
        self.assertAlmostEqual(turned['px'], going['px'])
        self.assertLess(back['px'], going['px'])

    JUNCTION = ['#######',
                '#P....#',
                '###.###',
                '###.###',
                '#######']

    def test_a_turn_pressed_while_resting_on_a_tile_centre_is_taken_from_that_tile(self):
        corridor = ['#########',
                    '#...P...#',
                    '#########']
        # 16 ticks of 1/120 s carry the player exactly one tile, so it stops on a centre still
        # heading the way it went; the first look checks that.
        cases = [(corridor, 'left', 16 / 120, (5, 1), lambda p: p['px'] < 5 and p['py'] == 1),
                 (self.JUNCTION, 'down', 32 / 120, (3, 1), lambda p: p['px'] == 3 and p['py'] > 1)]
        for layout, turn, travel, centre, turned in cases:
            with self.subTest(turn=turn):
                r = play([['steer', 'right'], ['step', travel], ['look'], ['steer', turn], ['step', 0.05], ['look']], layout)
                at, after = (look['player'] for look in r['looks'])
                self.assertEqual(((at['x'], at['y']), at['t'], at['dir']), (centre, 0, 'right'))
                self.assertTrue(turned(after), after)
                self.assertEqual(after['dir'], turn)

    def test_a_turn_pressed_before_a_junction_is_taken_at_the_first_tile_that_allows_it(self):
        r = play([['steer', 'right'], ['step', 0.1], ['steer', 'down'], ['look'], ['step', 0.5], ['look']], self.JUNCTION)
        early, late = (look['player'] for look in r['looks'])
        self.assertEqual(early['dir'], 'right')
        self.assertLess(early['px'], 2)
        self.assertEqual((late['px'], late['py']), (3, 3))

    def test_the_next_level_is_a_new_maze_with_one_more_bug(self):
        first = play([['look']], seed=7)['looks'][0]
        layout = first['layout']
        start = (first['player']['x'], first['player']['y'])
        way, tile = next((d, (start[0] + dx, start[1] + dy)) for d, (dx, dy) in STEPS.items()
                         if layout[start[1] + dy][start[0] + dx] == '.')
        r = play([['only', tile[0], tile[1]], ['steer', way], ['step', 1], ['look'], ['step', 2], ['look']], seed=7)
        cleared, nxt = r['looks']
        self.assertEqual((cleared['mode'], cleared['score'], len(cleared['bugs'])), ('cleared', 10, 3))
        self.assertEqual((nxt['mode'], nxt['level'], nxt['score'], len(nxt['bugs'])), ('ready', 2, 10, 4))
        self.assertNotEqual(nxt['layout'], layout)
        self.assertEqual(nxt['left'], items(nxt['layout']))


class BugSteering(unittest.TestCase):
    """The bug leaves its home below the junction and must go left or right. Left is the shorter
    way to the player along the corridors and the longer one in a straight line, so a bug that
    measured straight-line distance would take the other way about as often as a corridor-follower
    takes this one."""

    JUNCTION = ['#########',
                '#.....oP#',
                '#.#######',
                '#......##',
                '####B####',
                '#########']
    # Bugs 0 and 1 are walled in, so the bug at the junction is bug 2, out after two releases.
    THIRD = ['#########',
             '#B#B#####',
             '#########'] + JUNCTION[1:]
    RUNS = range(1, 1001)

    @classmethod
    def setUpClass(cls):
        clear = [['only', 6, 1], ['steer', 'left'], ['step', 2]]
        cases = {
            'chase': (cls.JUNCTION, [['steer', 'up'], ['step', 0.4], ['look']]),
            'flee': (cls.JUNCTION, [['steer', 'left'], ['step', 0.4], ['look']]),
            'level5': (cls.JUNCTION, clear * 4 + [['steer', 'up'], ['step', 0.4], ['look']]),
            'third': (cls.THIRD, [['steer', 'up'], ['step', 5.4], ['look']]),
        }
        jobs = [{'op': 'play', 'layout': layout, 'seed': s, 'actions': actions}
                for layout, actions in cases.values() for s in cls.RUNS]
        looks = [r['looks'][0] for r in run(*jobs)]
        cls.looks = {name: looks[i * len(cls.RUNS):(i + 1) * len(cls.RUNS)] for i, name in enumerate(cases)}
        cls.rows = {name: max(y for y, row in enumerate(layout) if 'B' in row) - 1 for name, (layout, _) in cases.items()}

    def went_left(self, name):
        looks = self.looks[name]
        self.assertEqual({look['mode'] for look in looks}, {'playing'})
        bug = [look['bugs'][-1] for look in looks]
        self.assertEqual([b for b in bug if b['px'] == 4 or b['py'] != self.rows[name]], [])
        return sum(b['px'] < 4 for b in bug) / len(bug)

    def test_a_bug_mostly_takes_the_shorter_way_along_the_corridors_to_the_player(self):
        self.assertEqual({look['level'] for look in self.looks['chase']}, {1})
        self.assertGreater(self.went_left('chase'), 0.65)

    def test_a_scared_bug_mostly_takes_the_longer_way(self):
        self.assertEqual({look['bugs'][0]['scared'] for look in self.looks['flee']}, {True})
        self.assertLess(self.went_left('flee'), 0.3)

    def test_bugs_chase_more_often_on_later_levels(self):
        self.assertEqual({look['level'] for look in self.looks['level5']}, {5})
        self.assertGreater(self.went_left('level5') - self.went_left('chase'), 0.075)

    def test_each_bug_after_the_first_chases_less_often(self):
        self.assertEqual({len(look['bugs']) for look in self.looks['third']}, {3})
        self.assertGreater(self.went_left('chase') - self.went_left('third'), 0.075)


if __name__ == '__main__':
    unittest.main()
