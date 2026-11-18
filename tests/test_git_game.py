"""The git game's rules (assets/git-game.js), run in Node through tests/git_game_cli.js.

Expected values are written by hand from the game's rules and its UI strings,
with two exceptions read back from the code: the star margin, which the plan
makes a named knob (STAR_MARGIN), and a failed command's announcement, which is
the engine's own first output line. The page's DOM wiring (mounting, loadLevel,
event handlers) is checked in tests/test_git_game_dom.py, not here; TapTargets
reads the game's stylesheet and script as source.
"""

import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'git_game_cli.js')
GAME = os.path.join(ROOT, 'assets', 'git-game.js')
TIMEOUT = 60
TAP = 44

EXPORTED = ['MAX_STARS', 'STAR_MARGIN', 'builderChips', 'complete', 'createCompleter', 'createHistory', 'createPlay',
            'goalOf', 'initialLanes', 'layout', 'loadProgress', 'recordSolve', 'resultText', 'saveProgress',
            'sentences', 'starsFor', 'startLevel', 'totals']

UI = {
    'say_commit': 'commit {hash}.',
    'say_branch_new': 'branch-new {name} {to}.',
    'say_branch_moved': 'branch-moved {name} {from} {to}.',
    'say_branch_deleted': 'branch-deleted {name} {from}.',
    'say_tag_new': 'tag-new {name} {to}.',
    'say_tag_moved': 'tag-moved {name} {from} {to}.',
    'say_tag_deleted': 'tag-deleted {name} {from}.',
    'say_head_branch': 'head-on {name}.',
    'say_head_detached': 'head-at {hash}.',
    'say_nothing': 'unchanged.',
    'say_solved': 'solved with {stars}.',
    'stars_label': '{n}/{max}',
    'nothing_to_undo': 'nothing to undo.',
    'undone': 'undid {line}.',
    'builder': {'commit': ['--amend'], 'branch': ['-d', '-D'], 'checkout': ['-b'], 'switch': ['-c'],
                'merge': ['--no-ff'], 'rebase': ['--onto'], 'reset': ['--hard', '--soft'], 'tag': ['-d'],
                'log': ['--oneline', '--all']},
    'ranks': ['r0', 'r1', 'r2', 'r3', 'r4'],
    'result': '{solved}/{total} levels, {commands} for {par}, {stars}/{max}, {rank}, {url}',
    'flag_head': 'HEAD',
    'flag_current': 'HEAD -> {name}',
    'flag_tag': 'tag: {name}',
    'goal_new': 'new-commit',
    'goal_copy': 'copy-of {message}',
    'goal_amend': 'amended {message}',
    'goal_revert': 'undoes {message}',
    'goal_revert_some': 'a-revert',
    'goal_merge': 'a-merge',
    'goal_keep': 'kept {message}',
    'shape_right': 'shape {commit} | {want} | {how}',
    'shape_wrong_commit': 'wrong {commit} | {want}',
    'shape_how_amend': 'how-amend',
    'shape_how_revert': 'how-revert',
    'shape_how_copy': 'how-copy',
    'shape_how_keep': 'how-keep',
    'shape_how_merge': 'how-merge',
    'shape_how_new': 'how-new',
}

BRANCH_LEVEL = {
    'id': 'branch', 'par': 2,
    'setup': ['git commit -m "A"', 'git commit -m "B"'],
    'solution': ['git checkout -b feature', 'git commit -m "C"'],
}

NAMES_LEVEL = {
    'id': 'names', 'par': 4,
    'setup': ['git commit -m "A"', 'git checkout -b talk', 'git commit -m "B"', 'git checkout -b old',
              'git commit -m "C"', 'git checkout main', 'git branch -D old'],
    'solution': ['git branch old {C}', 'git checkout -b feature', 'git tag v1', 'git branch -D talk'],
}

LEVELS = [{'id': 'a', 'par': 1}, {'id': 'b', 'par': 2}, {'id': 'c', 'par': 1}, {'id': 'd', 'par': 3}]
EMPTY = {'solved': {}, 'level': 0}


def node():
    path = shutil.which('node')
    if not path:
        raise AssertionError('node is not on PATH. The git game tests need Node.js '
                             '(it ships on the ubuntu-latest CI runner); install node to run them.')
    return path


def run_jobs(*jobs):
    proc = subprocess.run([node(), CLI], input=json.dumps({'jobs': list(jobs)}).encode('utf-8'),
                          capture_output=True, timeout=TIMEOUT)
    if proc.returncode != 0:
        raise AssertionError(f'git_game_cli.js exited {proc.returncode}:\n' + proc.stderr.decode('utf-8', 'replace'))
    return json.loads(proc.stdout.decode('utf-8'))['results']


def run_job(op, **fields):
    return run_jobs(dict(op=op, **fields))[0]


def play(level, steps, ui=UI):
    return run_job('play', ui=ui, level=level, steps=steps)['steps']


def site_ui():
    with open(os.path.join(ROOT, 'content', 'home.json'), encoding='utf-8') as f:
        return json.load(f)['game']['ui']


def message_of(state, hash_):
    return state['commits'][hash_]['message']


def parent_messages(state, hash_):
    return [message_of(state, p) for p in state['commits'][hash_]['parents']]


def hash_with_message(state, message):
    found = [h for h, c in state['commits'].items() if c['message'] == message]
    if len(found) != 1:
        raise AssertionError(f'{len(found)} commits have the message {message!r}')
    return found[0]


class Exports(unittest.TestCase):
    def test_the_module_exports_exactly_the_functions_these_tests_drive(self):
        self.assertEqual(run_job('exports')['names'], EXPORTED)

    def test_the_page_itself_calls_every_exported_function(self):
        with open(GAME, encoding='utf-8') as f:
            source = f.read()
        functions = [name for name in EXPORTED if not name.isupper()]
        self.assertGreater(len(functions), 10)
        for name in functions:
            calls = len(re.findall(r'(?<![\w.])' + name + r'\(', source)) - source.count('function ' + name + '(')
            self.assertGreater(calls, 0, name)


class Stars(unittest.TestCase):
    def test_three_at_or_under_par_two_within_the_margin_one_beyond(self):
        probe = run_job('stars', cases=[])
        self.assertEqual(probe['max'], 3)
        margin = probe['margin']
        self.assertIsInstance(margin, int)
        self.assertGreaterEqual(margin, 1)
        for par in (1, 3):
            cases = [(0, 3), (par - 1, 3), (par, 3), (par + 1, 2), (par + margin, 2),
                     (par + margin + 1, 1), (par + margin + 10, 1)]
            got = run_job('stars', cases=[[count, par] for count, _ in cases])['stars']
            self.assertEqual(got, [stars for _, stars in cases], f'par {par}')


class Score(unittest.TestCase):
    def test_only_git_commands_that_change_the_graph_count_and_undo_does_not_refund(self):
        steps = ['git status', 'git log', 'git branch', 'git reflog', 'git help', 'git checkout nope',
                 'git frobnicate', 'help', 'hint', 'levels', 'clear', 'restart', '   ', 'undo',
                 'git commit -m "X"', 'undo', 'git branch tmp', 'git branch tmp', 'git commit', 'undo', 'undo']
        got = play(BRANCH_LEVEL, steps)
        self.assertEqual([s['used'] for s in got],
                         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 3])
        self.assertEqual([s['kind'] for s in got],
                         ['git'] * 7 + ['meta'] * 5 + [None, 'undo', 'git', 'undo', 'git', 'git', 'git', 'undo', 'undo'])
        self.assertEqual([s['word'] for s in got[7:12]], ['help', 'hint', 'levels', 'clear', 'restart'])
        self.assertEqual([s['ok'] for s in got[5:7]], [False, False])
        self.assertFalse(got[13]['ok'])
        self.assertEqual(got[13]['said'], 'nothing to undo.')
        start = got[0]['state']
        self.assertEqual(got[15]['state'], start)
        self.assertEqual(got[20]['state'], start)
        self.assertEqual(got[19]['state'], got[17]['state'])

    def test_what_each_command_announces(self):
        got = play(BRANCH_LEVEL, ['git status', 'git checkout nope', 'git commit -m "X"', 'undo'])
        self.assertEqual(got[0]['said'], 'unchanged.')
        self.assertEqual(got[1]['said'], got[1]['output'][0])
        self.assertTrue(got[1]['output'][0])
        b = hash_with_message(got[0]['state'], 'B')
        x = hash_with_message(got[2]['state'], 'X')
        self.assertEqual(got[2]['said'], f'commit {x}. branch-moved main {b} {x}.')
        self.assertEqual(got[3]['said'], f'undid git commit -m "X". branch-moved main {x} {b}.')


class Solving(unittest.TestCase):
    def test_solved_the_moment_the_graph_matches_the_goal(self):
        got = play(BRANCH_LEVEL, ['git checkout -b feature', 'git commit -m "anything"'])
        self.assertEqual([s['solvedNow'] for s in got], [False, True])
        self.assertEqual([s['onGoal'] for s in got], [False, True])
        self.assertEqual(got[1]['stars'], 3)
        self.assertEqual(got[1]['said'][-len(' solved with 3/3.'):], ' solved with 3/3.')

    def test_matching_refs_with_head_elsewhere_is_not_solved_yet(self):
        got = play(BRANCH_LEVEL, ['git checkout {B}', 'git commit', 'git branch feature', 'git checkout feature'])
        self.assertEqual([s['onGoal'] for s in got], [False, False, False, True])
        self.assertEqual([s['solvedNow'] for s in got], [False, False, False, True])
        self.assertEqual([s['solved'] for s in got], [False, False, False, True])
        self.assertEqual(got[3]['stars'], 2)

    def test_a_near_miss_never_solves(self):
        got = play(BRANCH_LEVEL, ['git branch feature', 'git commit', 'git checkout feature'])
        self.assertEqual([s['onGoal'] for s in got], [False, False, False])
        self.assertEqual([s['solved'] for s in got], [False, False, False])

    def test_the_solve_fires_once_even_when_the_graph_matches_again(self):
        got = play(BRANCH_LEVEL, ['git checkout -b feature', 'git commit', 'git tag x', 'git tag -d x', 'undo', 'undo'])
        self.assertEqual([s['onGoal'] for s in got], [False, True, False, True, False, True])
        self.assertEqual([s['solvedNow'] for s in got[:4]], [False, True, False, False])
        self.assertEqual([s['solved'] for s in got], [False, True, True, True, True, True])


def home_level(level_id):
    with open(os.path.join(ROOT, 'content', 'home.json'), encoding='utf-8') as f:
        level = next(lv for lv in json.load(f)['game']['levels'] if lv['id'] == level_id)
    return dict(level, par=len(level['solution']))


def amend_hint(commit):
    return (f'Your graph has the right shape, but {commit} was made another way: '
            'the goal has Slides, amended. Try git commit --amend.')


class ShapeHint(unittest.TestCase):
    def test_a_near_miss_of_the_right_shape_says_the_goal_wants_an_amend(self):
        level = home_level('amend')
        line = amend_hint('Slides, with demo')
        for reset in ('git reset --hard HEAD~1', 'git reset --soft HEAD~1'):
            with self.subTest(reset):
                got = play(level, [reset, 'git commit -m "Slides, with demo"'], ui=site_ui())
                self.assertEqual([s['hint'] for s in got], [None, line])
                a = hash_with_message(got[0]['state'], 'Abstract')
                x = got[1]['state']['branches']['main']
                self.assertEqual(got[1]['said'], f'New commit {x}. main moved from {a} to {x}. {line}')
                self.assertEqual([s['used'] for s in got], [1, 2])
                self.assertEqual([(s['solved'], s['solvedNow'], 'stars' in s) for s in got], [(False, False, False)] * 2)

    def test_amending_your_own_commit_still_names_the_setup_commit_the_goal_amends(self):
        got = play(home_level('amend'), ['git reset --soft HEAD~1', 'git commit', 'git commit --amend'], ui=site_ui())
        self.assertEqual([s['hint'] for s in got], [None, amend_hint('Commit 1'), amend_hint('Commit 1')])
        self.assertEqual([s['onGoal'] for s in got], [False, False, False])

    def test_moving_head_away_and_back_gives_no_hint(self):
        got = play(home_level('amend'), ['git checkout HEAD~1', 'git checkout main'], ui=site_ui())
        self.assertEqual([s['changed'] for s in got], [True, True])
        self.assertEqual([s['hint'] for s in got], [None, None])
        self.assertEqual(message_of(got[1]['state'], got[1]['state']['branches']['main']), 'Slides')
        self.assertEqual(got[1]['said'], 'HEAD is on main.')

    def test_the_solution_solves_without_a_hint(self):
        level = home_level('amend')
        got = play(level, level['solution'], ui=site_ui())
        self.assertEqual([(s['solvedNow'], s['stars'], s['hint']) for s in got], [(True, 3, None)])
        self.assertEqual(got[0]['said'][-len(' Solved, 3 of 3 stars.'):], ' Solved, 3 of 3 stars.')

    def test_no_hint_once_the_level_is_solved(self):
        level = home_level('amend')
        got = play(level, level['solution'] + ['git reset --hard HEAD~1', 'git commit -m "Slides, with demo"'],
                   ui=site_ui())
        self.assertEqual([s['solved'] for s in got], [True, True, True])
        self.assertEqual([s['hint'] for s in got], [None, None, None])
        before = play(level, ['git reset --hard HEAD~1', 'git commit -m "Slides, with demo"'], ui=site_ui())
        self.assertEqual(before[1]['hint'], amend_hint('Slides, with demo'))

    KINDS = [
        ('amend', ['git commit -m "A"', 'git commit -m "B"'], ['git commit --amend -m "C"'],
         ['git reset --hard HEAD~1', 'git commit -m "D"'], 'shape D | amended B | how-amend'),
        ('revert', ['git commit -m "A"', 'git commit -m "B"', 'git commit -m "C"'], ['git revert HEAD~1'],
         ['git commit -m "X"'], 'shape X | undoes B | how-revert'),
        ('copy', ['git commit -m "A"', 'git checkout -b x', 'git commit -m "P"', 'git commit -m "Q"', 'git checkout main'],
         ['git cherry-pick x~1 x'], ['git commit -m "Y"', 'git commit -m "Z"'], 'shape Y | copy-of P | how-copy'),
        ('keep', ['git commit -m "A"', 'git commit -m "B"', 'git commit -m "C"'], ['git reset --hard HEAD~1'],
         ['git reset --hard HEAD~2', 'git commit -m "Y"'], 'shape Y | kept B | how-keep'),
        ('merge', ['git commit -m "A"', 'git checkout -b x', 'git commit -m "X"', 'git checkout main',
                   'git merge --no-ff x'],
         ['git reset --hard HEAD~1', 'git merge --no-ff x'], ['git commit --amend -m "M"'],
         'shape M | a-merge | how-merge'),
        ('new', ['git commit -m "A"', 'git commit -m "B"'], ['git commit -m "C"'], ['git revert HEAD'],
         'shape Revert "B" | new-commit | how-new'),
    ]

    def test_each_kind_of_goal_commit_names_the_command_that_makes_it(self):
        jobs = [{'op': 'play', 'ui': UI, 'steps': steps,
                 'level': {'id': kind, 'par': len(solution), 'setup': setup, 'solution': solution}}
                for kind, setup, solution, steps, _ in self.KINDS]
        results = run_jobs(*jobs)
        self.assertEqual(len(results), len(self.KINDS))
        for (kind, _, _, steps, line), got in zip(self.KINDS, results):
            with self.subTest(kind):
                self.assertEqual([s['hint'] for s in got['steps']], [None] * (len(steps) - 1) + [line])
                self.assertEqual([s['changed'] for s in got['steps']], [True] * len(steps))

    def test_a_setup_commit_left_as_it_was_is_passed_over_for_the_commit_the_player_made(self):
        level = {'id': 'pass-over', 'par': 2, 'setup': ['git commit -m "A"', 'git commit -m "S"'],
                 'solution': ['git commit --amend -m "T"', 'git commit -m "N"']}
        attempt = ['git revert HEAD']
        diff = run_job('identity', setup=level['setup'], goal=level['solution'], attempt=attempt)
        self.assertEqual([message_of(diff['attempt'], d['hash']) for d in diff['diff']], ['S', 'Revert "S"'])
        self.assertEqual(play(level, attempt)[0]['hint'], 'shape Revert "S" | new-commit | how-new')

    def last_hints(self, table, names):
        """Plays each synthetic level of the table and returns the hint of its last step, after checking
        that the steps before it gave none and that the table holds exactly the named rows."""
        self.assertEqual([row[0] for row in table], names)
        jobs = [{'op': 'play', 'ui': UI, 'steps': steps,
                 'level': {'id': 'synthetic', 'par': len(solution), 'setup': setup, 'solution': solution}}
                for _, setup, solution, steps, _ in table]
        hints = []
        for (name, _, _, steps, _), got in zip(table, run_jobs(*jobs)):
            self.assertEqual([s['hint'] for s in got['steps'][:-1]], [None] * (len(steps) - 1), name)
            self.assertEqual([s['solved'] for s in got['steps']], [False] * len(steps), name)
            hints.append(got['steps'][-1]['hint'])
        return hints

    def test_the_right_command_on_the_wrong_commit_says_which_commit_the_goal_has(self):
        for level_id, steps, line in [
            ('revert', ['git revert HEAD'], 'Right command, wrong commit: the goal has a commit that undoes Credential check.'),
            ('cherry-pick', ['git cherry-pick experiments experiments~2'],
             'Right command, wrong commit: the goal has a copy of Refunds, tested.'),
        ]:
            with self.subTest(level_id):
                got = play(home_level(level_id), steps, ui=site_ui())
                self.assertEqual([s['hint'] for s in got], [line])
                self.assertEqual(got[0]['said'][-len(line) - 1:], ' ' + line)
                self.assertEqual([s['solved'] for s in got], [False])

    WRONG_COMMIT = [
        ('amend', ['git commit -m "A"', 'git checkout -b side', 'git commit -m "Y"', 'git checkout main',
                   'git commit -m "X" -m "about X"'],
         ['git commit --amend -m "X2"', 'git branch -D side'],
         ['git checkout side', 'git commit --amend -m "Y2" -m "about Y2"', 'git branch -D main', 'git checkout -b main',
          'git branch -D side'],
         'wrong Y2 | amended X'),
        ('revert', ['git commit -m "A"', 'git commit -m "B"', 'git commit -m "C"'], ['git revert HEAD~1'],
         ['git revert HEAD'], 'wrong Revert "C" | undoes B'),
        ('copy', ['git commit -m "A"', 'git checkout -b x', 'git commit -m "P"', 'git commit -m "Q" -m "about Q"',
                  'git checkout main'],
         ['git cherry-pick x~1 x'], ['git cherry-pick x x~1'], 'wrong Q | copy-of P'),
        ('revert of a commit the setup never had', ['git commit -m "A"'], ['git commit -m "B"', 'git revert HEAD'],
         ['git commit -m "B"', 'git revert HEAD~1'], 'wrong Revert "A" | a-revert'),
    ]

    def test_a_commit_of_the_kind_the_goal_has_on_another_commit_gets_the_wrong_commit_line(self):
        names = ['amend', 'revert', 'copy', 'revert of a commit the setup never had']
        self.assertEqual(self.last_hints(self.WRONG_COMMIT, names), [row[4] for row in self.WRONG_COMMIT])

    FIRST_LINE = [
        ('amend', ['git commit -m "A"', 'git commit -m "B" -m "about B"'], ['git commit --amend -m "C"'],
         ['git reset --hard HEAD~1', 'git commit -m "D" -m "about D"'], 'shape D | amended B | how-amend'),
        ('revert', ['git commit -m "A"', 'git commit -m "B" -m "about B"', 'git commit -m "C"'], ['git revert HEAD~1'],
         ['git commit -m "X" -m "about X"'], 'shape X | undoes B | how-revert'),
        ('copy', ['git commit -m "A"', 'git checkout -b x', 'git commit -m "P" -m "about P"', 'git commit -m "Q"',
                  'git checkout main'],
         ['git cherry-pick x~1 x'], ['git commit -m "Y"', 'git commit -m "Z"'], 'shape Y | copy-of P | how-copy'),
        ('keep', ['git commit -m "A"', 'git commit -m "B" -m "about B"', 'git commit -m "C"'], ['git reset --hard HEAD~1'],
         ['git reset --hard HEAD~2', 'git commit -m "Y"'], 'shape Y | kept B | how-keep'),
    ]

    def test_hint_lines_and_goal_labels_show_a_message_by_its_first_line(self):
        line = ('Your graph has the right shape, but Slides was made another way: '
                'the goal has Slides, amended. Try git commit --amend.')
        got = play(home_level('amend'), ['git reset --soft HEAD~1', 'git commit -m "Slides" -m "with demo"'],
                   ui=site_ui())
        self.assertEqual(message_of(got[1]['state'], got[1]['state']['branches']['main']), 'Slides\n\nwith demo')
        self.assertEqual([s['hint'] for s in got], [None, line])
        names = ['amend', 'revert', 'copy', 'keep']
        self.assertEqual(self.last_hints(self.FIRST_LINE, names), [row[4] for row in self.FIRST_LINE])

    def test_a_goal_revert_of_a_commit_the_setup_never_had_is_a_revert_commit_made_with_git_revert(self):
        level = {'id': 'revert-new', 'par': 2, 'setup': ['git commit -m "A"'],
                 'solution': ['git commit -m "B"', 'git revert HEAD']}
        steps = ['git commit -m "B"', 'git commit -m "X"']
        self.assertEqual([s['hint'] for s in play(level, steps)], [None, 'shape X | a-revert | how-revert'])
        self.assertEqual([s['hint'] for s in play(level, steps, ui=site_ui())], [
            None, 'Your graph has the right shape, but X was made another way: '
                  'the goal has a revert commit. Try git revert.'])


class Goal(unittest.TestCase):
    def test_the_goal_is_setup_plus_solution_with_tokens_resolved_line_by_line(self):
        level = {'id': 'tok', 'setup': ['git commit -m "A"'],
                 'solution': ['git commit -m "B"', 'git tag t {B}', 'git checkout -b side {A}']}
        got = run_job('goal', level=level)
        self.assertTrue(got['ok'], got.get('error'))
        state = got['state']
        self.assertEqual(sorted(state['branches']), ['main', 'side'])
        self.assertEqual(message_of(state, state['branches']['main']), 'B')
        self.assertEqual(parent_messages(state, state['branches']['main']), ['A'])
        self.assertEqual(message_of(state, state['branches']['side']), 'A')
        self.assertEqual(list(state['tags']), ['t'])
        self.assertEqual(state['tags']['t'], state['branches']['main'])
        self.assertEqual(state['head'], {'type': 'branch', 'name': 'side'})

    def test_a_solution_line_that_fails_names_the_level_and_the_line(self):
        got = run_job('goal', level={'id': 'broken', 'setup': ['git commit -m "A"'], 'solution': ['git checkout nope']})
        self.assertFalse(got['ok'])
        self.assertIn('broken', got['error'])
        self.assertIn('git checkout nope', got['error'])


class Progress(unittest.TestCase):
    SOLVES = [['a', 2, 4], ['a', 3, 2], ['a', 1, 9], ['b', 1, 9]]
    AFTER = {'solved': {'a': {'stars': 3, 'best': 2}, 'b': {'stars': 1, 'best': 9}}, 'level': 2}

    def progress(self, storage, **fields):
        return run_job('progress', storage=storage, ui=UI, levels=LEVELS, **fields)

    def test_saved_progress_comes_back_on_the_next_load(self):
        got = self.progress('memory', solves=self.SOLVES, level=2)
        self.assertEqual(got['loaded'], EMPTY)
        self.assertEqual(got['start'], 0)
        self.assertEqual(got['progress'], self.AFTER)
        self.assertEqual(list(got['stored']), ['git-game'])
        self.assertEqual(json.loads(got['stored']['git-game']), self.AFTER)
        self.assertEqual(got['reloaded'], self.AFTER)

    def test_a_returning_player_starts_on_the_saved_level(self):
        saved = {'solved': {'c': {'stars': 2, 'best': 4}}, 'level': 3}
        got = self.progress('memory', initial={'git-game': json.dumps(saved)})
        self.assertEqual(got['loaded'], saved)
        self.assertEqual(got['start'], 3)

    def test_unusable_saved_data_starts_a_fresh_game(self):
        for raw in ('not json', 'null', '{"level": 2}', '{"solved": null, "level": 2}', '[]', '""'):
            got = self.progress('memory', initial={'git-game': raw})
            self.assertEqual(got['loaded'], EMPTY, raw)
            self.assertEqual(got['start'], 0, raw)
        for level in (4, -1, 1.5, '2', None):
            got = self.progress('memory', initial={'git-game': json.dumps({'solved': {}, 'level': level})})
            self.assertEqual(got['start'], 0, level)

    def test_the_game_plays_the_same_without_storage(self):
        with_storage = self.progress('memory', solves=self.SOLVES, level=2)
        for kind in ('absent', 'missing', 'getter-throws', 'methods-throw'):
            got = self.progress(kind, solves=self.SOLVES, level=2)
            self.assertEqual(got['loaded'], EMPTY, kind)
            self.assertEqual(got['start'], 0, kind)
            self.assertEqual(got['progress'], self.AFTER, kind)
            self.assertEqual(got['totals'], with_storage['totals'], kind)
            self.assertEqual(got['reloaded'], EMPTY, kind)
            self.assertEqual(got['stored'], {}, kind)


class Rank(unittest.TestCase):
    def test_totals_count_only_solved_levels_of_this_game(self):
        solved = {'a': {'stars': 3, 'best': 1}, 'b': {'stars': 2, 'best': 4}, 'd': {'stars': 1, 'best': 9},
                  'gone': {'stars': 3, 'best': 1}}
        got = run_job('totals', ui=UI, levels=LEVELS, solved=solved)
        self.assertEqual(got, {'solved': 3, 'total': 4, 'commands': 14, 'par': 6, 'stars': 6, 'max': 12, 'rank': 'r1'})

    def test_rank_steps_up_at_each_boundary(self):
        # Four levels and five ranks: 4 stars (one per level) is the bottom rank, 12 the top.
        table = [
            ({}, 'r0'),
            ({'a': 3}, 'r0'),
            ({'a': 1, 'b': 1, 'c': 1, 'd': 1}, 'r0'),
            ({'a': 2, 'b': 1, 'c': 1, 'd': 1}, 'r1'),
            ({'a': 2, 'b': 2, 'c': 1, 'd': 1}, 'r1'),
            ({'a': 2, 'b': 2, 'c': 2, 'd': 1}, 'r2'),
            ({'a': 2, 'b': 2, 'c': 2, 'd': 2}, 'r2'),
            ({'a': 3, 'b': 2, 'c': 2, 'd': 2}, 'r3'),
            ({'a': 3, 'b': 3, 'c': 2, 'd': 2}, 'r3'),
            ({'a': 3, 'b': 3, 'c': 3, 'd': 2}, 'r4'),
            ({'a': 3, 'b': 3, 'c': 3, 'd': 3}, 'r4'),
        ]
        jobs = [{'op': 'totals', 'ui': UI, 'levels': LEVELS,
                 'solved': {k: {'stars': v, 'best': 1} for k, v in stars.items()}} for stars, _ in table]
        got = [t['rank'] for t in run_jobs(*jobs)]
        self.assertEqual(got, [rank for _, rank in table])


class Result(unittest.TestCase):
    TOTALS = {'solved': 3, 'total': 4, 'commands': 14, 'par': 6, 'stars': 6, 'max': 12, 'rank': 'Committer'}

    def test_the_result_line_carries_every_total(self):
        got = run_job('result', ui=UI, totals=self.TOTALS, url='https://example.test/#play')['text']
        self.assertEqual(got, '3/4 levels, 14 for 6, 6/12, Committer, https://example.test/#play')

    def test_the_copied_text_reads_as_the_site_writes_it(self):
        got = run_job('result', ui=site_ui(), totals=self.TOTALS, url='https://example.test/#play')['text']
        self.assertEqual(got, "I played Git is a graph, Lemi Orhan Ergin's git game: 3 of 4 levels, "
                              "14 commands for a par of 6, 6 of 12 stars. Rank: Committer. https://example.test/#play")


def commit(hash_, parents, message, seq):
    return {'hash': hash_, 'parents': parents, 'message': message, 'patch': 'p' + hash_, 'seq': seq, 'cls': 'base:' + hash_}


class Announcements(unittest.TestCase):
    A = commit('aaaaaaa', [], 'A', 1)
    B = commit('bbbbbbb', ['aaaaaaa'], 'B', 2)
    C = commit('ccccccc', ['bbbbbbb'], 'C', 3)
    BEFORE = {'commits': {'aaaaaaa': A, 'bbbbbbb': B},
              'branches': {'main': 'bbbbbbb', 'old': 'aaaaaaa', 'gone': 'aaaaaaa'},
              'tags': {'v1': 'aaaaaaa', 't2': 'aaaaaaa'},
              'head': {'type': 'branch', 'name': 'main'}, 'reflog': []}

    def test_every_kind_of_change_is_said_in_words(self):
        after = {'commits': {'aaaaaaa': self.A, 'bbbbbbb': self.B, 'ccccccc': self.C},
                 'branches': {'main': 'ccccccc', 'old': 'aaaaaaa', 'fresh': 'bbbbbbb'},
                 'tags': {'v1': 'bbbbbbb', 't3': 'ccccccc'},
                 'head': {'type': 'detached', 'hash': 'ccccccc'}, 'reflog': []}
        got = run_job('sentences', ui=UI, before=self.BEFORE, after=after)['text']
        self.assertEqual(got, 'commit ccccccc. branch-new fresh bbbbbbb. branch-deleted gone aaaaaaa. '
                              'branch-moved main bbbbbbb ccccccc. tag-deleted t2 aaaaaaa. tag-new t3 ccccccc. '
                              'tag-moved v1 aaaaaaa bbbbbbb. head-at ccccccc.')

    def test_head_moving_to_a_branch_and_no_change(self):
        after = dict(self.BEFORE, head={'type': 'branch', 'name': 'old'})
        got = run_jobs({'op': 'sentences', 'ui': UI, 'before': self.BEFORE, 'after': after},
                       {'op': 'sentences', 'ui': UI, 'before': self.BEFORE, 'after': self.BEFORE})
        self.assertEqual([g['text'] for g in got], ['head-on old.', ''])

    def test_the_site_says_which_pointer_moved_where(self):
        before = {'commits': {'3fa1c2e': commit('3fa1c2e', [], 'A', 1)}, 'branches': {'main': '3fa1c2e'},
                  'tags': {}, 'head': {'type': 'branch', 'name': 'main'}, 'reflog': []}
        after = dict(before, commits={'3fa1c2e': before['commits']['3fa1c2e'],
                                      '9b02d4a': commit('9b02d4a', ['3fa1c2e'], 'B', 2)},
                     branches={'main': '9b02d4a'})
        got = run_job('sentences', ui=site_ui(), before=before, after=after)['text']
        self.assertEqual(got, 'New commit 9b02d4a. main moved from 3fa1c2e to 9b02d4a.')


class NameChips(unittest.TestCase):
    def chips(self, values, steps=()):
        return run_job('chips', ui=UI, level=NAMES_LEVEL, steps=list(steps), values=values)['chips']

    def test_naming_commands_offer_the_names_the_goal_needs(self):
        values = ['git checkout ', 'git checkout -b ', 'git checkout -b feature', 'git tag ', 'git branch ',
                  'git switch -c ']
        got = self.chips(values)
        self.assertEqual([(c['cmd'], c['options'], sorted(c['names'])) for c in got], [
            ('checkout', ['-b'], ['feature', 'old', 'v1']),
            ('checkout', [], ['feature', 'old', 'v1']),
            ('checkout', [], ['old', 'v1']),
            ('tag', ['-d'], ['feature', 'old', 'v1']),
            ('branch', ['-d', '-D'], ['feature', 'old', 'v1']),
            ('switch', [], ['feature', 'old', 'v1']),
        ])

    def test_a_name_that_already_exists_is_not_offered(self):
        got = self.chips(['git branch ', 'git tag '], steps=['git checkout -b feature', 'git tag v1'])
        self.assertEqual([sorted(c['names']) for c in got], [['old'], ['old']])

    def test_other_commands_offer_options_only(self):
        got = self.chips(['git merge ', 'git commit ', 'git rebase ', 'git log --all '])
        self.assertEqual([(c['cmd'], c['options'], c['names']) for c in got], [
            ('merge', ['--no-ff'], []), ('commit', ['--amend'], []), ('rebase', ['--onto'], []), ('log', ['--oneline'], []),
        ])

    def test_no_chips_without_a_known_command(self):
        got = self.chips(['', 'ls', 'git', 'git stash ', 'checkout '])
        self.assertEqual(got, [{'cmd': None, 'options': [], 'names': []}] * 5)


class Completion(unittest.TestCase):
    SETUP = ['git commit -m "A"', 'git checkout -b typofix', 'git commit -m "B"', 'git checkout main', 'git tag v1']

    def complete(self, cases):
        got = run_job('complete', ui=UI, setup=self.SETUP, cases=[list(c) for c in cases])
        return got['state'], got['results']

    def test_tab_fills_commands_options_and_ref_names(self):
        cases = [('git sta', None), ('git log --one', None), ('git checkout ty', None), ('git rebase m', None),
                 ('git checkout v', None), ('git checkout H', None), ('res', None), ('g', None), ('git ch', None),
                 ('git ch main', 6)]
        _, got = self.complete(cases)
        self.assertEqual(got, [
            {'value': 'git status ', 'caret': 11},
            {'value': 'git log --oneline ', 'caret': 18},
            {'value': 'git checkout typofix ', 'caret': 21},
            {'value': 'git rebase main ', 'caret': 16},
            {'value': 'git checkout v1 ', 'caret': 16},
            {'value': 'git checkout HEAD ', 'caret': 18},
            {'value': 'restart ', 'caret': 8},
            {'value': 'git ', 'caret': 4},
            {'value': 'git che', 'caret': 7},
            {'value': 'git che main', 'caret': 7},
        ])

    def test_tab_completes_a_hash_prefix(self):
        state, _ = self.complete([])
        b = hash_with_message(state, 'B')
        self.assertEqual([h for h in state['commits'] if h.startswith(b[:4])], [b])
        _, got = self.complete([('git checkout ' + b[:4], None)])
        self.assertEqual(got, [{'value': f'git checkout {b} ', 'caret': 21}])

    def test_several_matches_are_listed(self):
        _, got = self.complete([('git c', None), ('git reset --', None), ('h', None), ('git c main', 5)])
        self.assertEqual([sorted(g['list']) for g in got], [
            ['checkout', 'cherry-pick', 'commit'], ['--hard', '--soft'], ['help', 'hint'],
            ['checkout', 'cherry-pick', 'commit']])

    def test_nothing_to_complete(self):
        _, got = self.complete([('', None), ('git checkout zzz', None), ('ls', None), ('foo ba', None),
                                ('git log --zz', None)])
        self.assertEqual(got, [None] * 5)

    def test_completing_a_word_in_the_middle_of_a_line_leaves_one_space_and_the_caret_after_it(self):
        got = run_job('complete', ui=UI, setup=self.SETUP + ['git branch feature'],
                      cases=[['git checkout fea main', 16], ['git checkout main main', 17], ['git checkout fea', None]])
        self.assertEqual(got['results'], [
            {'value': 'git checkout feature main', 'caret': 21},
            {'value': 'git checkout main main', 'caret': 18},
            {'value': 'git checkout feature ', 'caret': 21},
        ])


class TabKey(unittest.TestCase):
    SETUP = Completion.SETUP
    LIST = '--hard  --soft'

    def presses(self, *events):
        return run_job('completer', ui=UI, setup=self.SETUP, events=[list(e) for e in events])['results']

    def test_a_second_tab_on_the_same_list_is_not_used_so_the_focus_moves_on(self):
        got = self.presses(('tab', 'git reset --', None, 'git status'), ('tab', 'git reset --', None, self.LIST),
                           ('tab', 'git reset --', None, self.LIST))
        self.assertEqual(got, [{'line': self.LIST}, None, None])

    def test_the_list_is_printed_again_once_the_terminal_has_moved_on(self):
        got = self.presses(('tab', 'git reset --', None, ''), ('tab', 'git reset --', None, 'git status'),
                           ('tab', 'git reset --', None, self.LIST))
        self.assertEqual(got, [{'line': self.LIST}, {'line': self.LIST}, None])

    def test_the_same_list_for_another_line_or_caret_is_printed_again(self):
        got = self.presses(('tab', 'git reset -- --', 12, ''), ('tab', 'git reset -- HEAD --', 12, self.LIST),
                           ('tab', 'git reset -- HEAD --', 20, self.LIST), ('tab', 'git reset -- HEAD --', 20, self.LIST))
        self.assertEqual(got, [{'line': self.LIST}] * 3 + [None])

    def test_a_graph_change_that_changes_the_list_prints_the_new_one(self):
        got = self.presses(('run', 'git branch tz'), ('tab', 'git checkout t', None, ''), ('run', 'git branch tzz'),
                           ('tab', 'git checkout t', None, 'typofix  tz'),
                           ('tab', 'git checkout t', None, 'typofix  tz  tzz'))
        self.assertEqual(got, [True, {'line': 'typofix  tz'}, True, {'line': 'typofix  tz  tzz'}, None])

    def test_a_fill_is_always_used_and_nothing_to_complete_never_is(self):
        got = self.presses(('tab', 'git sta', None, ''), ('tab', 'git sta', None, ''), ('tab', '', None, ''),
                           ('tab', 'git checkout zzz', None, ''))
        self.assertEqual(got, [{'value': 'git status ', 'caret': 11}, {'value': 'git status ', 'caret': 11}, None, None])


class History(unittest.TestCase):
    def history(self, ops, max_=60):
        return run_job('history', max=max_, ops=ops)['results']

    def test_up_walks_back_and_down_returns_to_the_draft(self):
        got = self.history([['push', 'a'], ['push', 'b'], ['push', 'b'], ['up', 'draft'], ['up', 'x'], ['up', 'y'],
                            ['down'], ['down'], ['down']])
        self.assertEqual(got, [None, None, None, 'b', 'a', 'a', 'b', 'draft', None])

    def test_empty_history_recalls_nothing(self):
        self.assertEqual(self.history([['up', 'draft'], ['down']]), [None, None])

    def test_a_new_command_resets_the_walk(self):
        got = self.history([['push', 'a'], ['up', 'draft'], ['push', 'c'], ['down'], ['up', 'next'], ['down']])
        self.assertEqual(got, [None, 'a', None, None, 'c', 'next'])

    def test_history_keeps_only_the_newest_commands(self):
        got = self.history([['push', 'a'], ['push', 'b'], ['push', 'c'], ['up', ''], ['up', ''], ['up', '']], max_=2)
        self.assertEqual(got, [None, None, None, 'c', 'b', 'b'])


class FlagTargets(unittest.TestCase):
    SETUP = ['git commit -m "A"', 'git commit -m "B"', 'git branch x', 'git branch ab', 'git branch typofix',
             'git tag v', 'git tag launch', 'git checkout HEAD~1']

    def test_every_flag_on_a_phone_has_a_fingertip_hit_area_that_no_other_flag_shares(self):
        for narrow in (True, False):
            got = run_job('layout', ui=UI, setup=self.SETUP, kind='live', width=320, narrow=narrow)
            flags = [f for r in got['rows'] for f in r['flags']]
            self.assertEqual(len(flags), 7)
            self.assertEqual(max(len(r['flags']) for r in got['rows']), 6)
            for row in got['rows']:
                if narrow:
                    self.assertGreaterEqual(row['h'], TAP)
                end = None
                for f in row['flags']:
                    hit = f['hit']
                    left = f['x'] + hit['x']
                    if narrow:
                        self.assertGreaterEqual(hit['w'], TAP, f['text'])
                        self.assertGreaterEqual(hit['h'], TAP, f['text'])
                    self.assertLessEqual(hit['x'], 0, f['text'])
                    self.assertGreaterEqual(hit['x'] + hit['w'], f['w'], f['text'])
                    self.assertLessEqual(hit['y'], -got['z']['flagH'] / 2, f['text'])
                    self.assertGreaterEqual(hit['y'] + hit['h'], got['z']['flagH'] / 2, f['text'])
                    if end is not None:
                        self.assertGreaterEqual(left, end - 1e-9, f['text'])
                    end = left + hit['w']


class RowText(unittest.TestCase):
    def test_a_row_shows_a_message_by_its_first_line(self):
        body = 'with demo, ' * 6 + 'and the notes'
        setup = ['git commit -m "Abstract"', f'git commit -m "Slides" -m "{body}"']
        got = run_job('layout', ui=UI, setup=setup, kind='live', width=320, narrow=True)
        self.assertEqual([(r['message'], r['shown'], r['wrap']) for r in got['rows']],
                         [('Slides', 'Slides', False), ('Abstract', 'Abstract', False)])


def css_rules(css):
    """(media queries around the rule, selector, declarations) for every style rule, in source order."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    rules, stack, text = [], [], ''
    for ch in css:
        if ch == '{':
            stack.append(' '.join(text.split()))
            text = ''
        elif ch == '}':
            head = stack.pop()
            if not head.startswith('@'):
                body = dict((k.strip(), v.strip()) for k, v in re.findall(r'([\w-]+)\s*:\s*([^;]+)', text))
                rules.append((tuple(s for s in stack if s.startswith('@')), head, body))
            text = ''
        else:
            text += ch
    return rules


def rem(value):
    m = re.fullmatch(r'([\d.]+)(rem|px)', value)
    if not m:
        return None
    return float(m.group(1)) * (16 if m.group(2) == 'rem' else 1)


NEVER, MAYBE, SURE = 0, 1, 2
CSS_TOKEN = re.compile(r'::?[\w-]+(?:\([^)]*\))?|[.#]?[\w-]+|\[[^\]]*\]|\*')


def compounds(selector):
    return [c for c in re.split(r'\s*[\s>+~]\s*', selector.strip()) if c]


def css_tokens(compound):
    found = CSS_TOKEN.findall(compound)
    if ''.join(found) != compound:
        raise AssertionError(f'TapTargets cannot read the selector part {compound!r}')
    return found


def specificity(selector):
    a = b = c = 0
    for compound in compounds(selector):
        for t in css_tokens(compound):
            if t.startswith(':not('):
                x, y, z = specificity(t[5:-1])
                a, b, c = a + x, b + y, c + z
            elif t.startswith('#'):
                a += 1
            elif t.startswith(('.', '[')) or (t.startswith(':') and not t.startswith('::')):
                b += 1
            elif t != '*':
                c += 1
    return a, b, c


def subject_match(selector, tag, classes):
    """SURE when the selector is one compound that holds for an element built as <tag class=classes>,
    MAYBE when it also needs an ancestor, a state class, an attribute or a pseudo-class, NEVER otherwise.
    Which ancestors an element has is not read from the script, so an ancestor makes a rule MAYBE."""
    parts = compounds(selector)
    level = SURE if len(parts) == 1 else MAYBE
    for t in css_tokens(parts[-1]):
        if t.startswith('::') or t in (':before', ':after'):
            return NEVER
        if t.startswith('.') and t[1:] not in classes:
            if not t.startswith('.is-'):
                return NEVER
            level = MAYBE
        elif t.startswith(('[', ':', '#')):
            level = MAYBE
        elif not t.startswith('.') and t not in ('*', tag):
            return NEVER
    return level


def media_feature(name, value, widths):
    if name in ('min-width', 'max-width'):
        px = rem(value)
        holds = [w >= px if name == 'min-width' else w <= px for w in widths]
        return SURE if all(holds) else MAYBE if any(holds) else NEVER
    if (name, value) == ('hover', 'hover'):
        return NEVER
    if (name, value) == ('hover', 'none'):
        return SURE
    if name in ('prefers-color-scheme', 'prefers-reduced-motion'):
        return MAYBE
    raise AssertionError(f'TapTargets does not model the media feature ({name}: {value})')


def media_on_a_phone(heads, widths):
    """SURE, MAYBE or NEVER: whether the at-rules around a rule apply on a portrait phone at every width.
    Nested at-rules all have to apply; a comma media list applies when any of its queries does."""
    level = SURE
    for head in heads:
        if head.startswith('@keyframes '):
            return NEVER
        if not head.startswith('@media '):
            raise AssertionError(f'TapTargets does not model the at-rule {head!r}')
        best = NEVER
        for query in head[len('@media '):].split(','):
            features = re.findall(r'\(\s*([\w-]+)\s*:\s*([^)]+?)\s*\)', query)
            words = re.sub(r'\([^)]*\)', ' ', query).split()
            if query.count('(') != len(features) or set(words) - {'and', 'only', 'screen', 'all', 'print'}:
                raise AssertionError(f'TapTargets does not model the media query {query.strip()!r}')
            q = NEVER if 'print' in words else min([SURE] + [media_feature(n, v, widths) for n, v in features])
            best = max(best, q)
        level = min(level, best)
    return level


class TapTargets(unittest.TestCase):
    PHONE_WIDTHS = (360, 390)
    BUILDS = re.compile(r"(?<!function )\b(?:button\(|el\('(button|a)'(?=[,)]),?\s*)")
    BUILT = {('button', 'gg-lv'), ('button', 'gg-toggle'), ('button', 'gg-tool'), ('button', 'gg-more'),
             ('button', 'gg-erase'), ('button', 'gg-run'), ('button', 'gg-run gg-dock-next'), ('button', 'gg-chip'),
             ('button', 'gg-chip gg-chip-opt'), ('button', 'gg-chip gg-chip-name'), ('button', 'gg-next'),
             ('a', 'gg-fact-link'), ('a', 'gg-link')}

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'assets', 'git-game.css'), encoding='utf-8') as f:
            cls.rules = css_rules(f.read())
        with open(GAME, encoding='utf-8') as f:
            cls.script = f.read()

    def builds(self):
        """(call, tag, class string or None when the class is not one string literal) for every
        button( and el('button'|'a' … call in the script."""
        calls = []
        for m in self.BUILDS.finditer(self.script):
            lit = re.match(r"'([^']*)'\s*[,)]", self.script[m.end():])
            call = self.script[m.start():self.script.index(')', m.end())]
            calls.append((call, m.group(1) or 'button', lit.group(1) if lit else None))
        return calls

    def elements(self):
        return {(tag, cls) for call, tag, cls in self.builds() if cls}

    def deciding(self, tag, classes, prop):
        """(selector, px) for each declaration of prop that can be the one a phone uses on the element: by the
        cascade (specificity, then source order), every candidate down to the first that surely applies."""
        found = []
        for order, (media, head, body) in enumerate(self.rules):
            if prop not in body:
                continue
            on = media_on_a_phone(media, self.PHONE_WIDTHS)
            for sel in head.split(','):
                level = min(on, subject_match(sel, tag, classes))
                if level:
                    found.append((specificity(sel), order, level, sel.strip(), rem(body[prop]) or 0))
        out = []
        for spec, order, level, sel, px in sorted(found, reverse=True):
            out.append((sel, px))
            if level == SURE:
                break
        return out

    def test_every_button_and_link_the_game_builds_carries_a_class(self):
        calls = self.builds()
        self.assertGreaterEqual(len([c for c in calls if c[1] == 'a']), 3)
        self.assertGreaterEqual(len([c for c in calls if c[1] == 'button']), 14)
        self.assertEqual([call for call, tag, cls in calls if cls is None], ["el('button', cls, text"])
        self.assertEqual([call for call, tag, cls in calls if cls is not None and not cls.strip()], [])

    def test_the_buttons_and_links_the_game_builds_are_these(self):
        self.assertEqual(self.elements(), self.BUILT)

    def test_every_button_and_link_the_game_builds_is_a_fingertip_box_on_a_phone(self):
        for tag, cls in sorted(self.elements()):
            for props in (('min-height', 'height'), ('min-width', 'width')):
                with self.subTest(element=f'<{tag} class="{cls}">', size=props[0]):
                    deciding = [self.deciding(tag, set(cls.split()), p) for p in props]
                    self.assertTrue(any(deciding), 'sets no {} for phones'.format(' or '.join(props)))
                    worst = max(min(px for sel, px in d) if d else 0 for d in deciding)
                    self.assertGreaterEqual(worst, TAP, deciding)

    def test_dock_chips_keep_their_width_and_hit_areas_stay_invisible(self):
        chip = [body['flex'] for media, head, body in self.rules if head == '.gg-chip' and 'flex' in body]
        self.assertEqual(chip, ['none'])
        hit = [body['fill'] for media, head, body in self.rules if head == '.gg-hit' and not media]
        self.assertEqual(hit, ['transparent'])


if __name__ == '__main__':
    unittest.main()
