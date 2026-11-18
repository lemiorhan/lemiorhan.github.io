import json
import os
import unittest
from collections import namedtuple

import gitgraph
from gitgraph import canonical, engine_jobs, engine_matches, match_job, run_engine, run_git, run_job

HOME = os.path.join(gitgraph.ROOT, 'content', 'home.json')
REACHES_GOAL = {'setup alone': False, 'solution': True, 'alternative': True, 'near miss': False}
RUN_IN_GIT = {'solution', 'alternative', 'near miss'}

Attempt = namedtuple('Attempt', 'level label kind lines')


def home_levels():
    with open(HOME, encoding='utf-8') as f:
        return json.load(f)['game']['levels']


def attempts(levels):
    found = []
    for level in levels:
        found.append(Attempt(level, 'setup alone', 'setup alone', []))
        found.append(Attempt(level, 'solution', 'solution', level['solution']))
        for kind, key in (('alternative', 'alternatives'), ('near miss', 'near_misses')):
            for i, lines in enumerate(level['checks'][key], 1):
                found.append(Attempt(level, f'{kind} {i}', kind, lines))
    return found


def key(a):
    return a.level['id'], a.label


ATTEMPTS = attempts(home_levels())
GIT_RUNS = [(a, a.level['setup'] + a.lines) for a in ATTEMPTS if a.kind in RUN_IN_GIT]
PREFIXES = [(a, a.lines[:n]) for a in ATTEMPTS for n in range(len(a.lines) + 1)]


class LevelsPlayAsDesigned(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runs = engine_jobs([run_job(lines) for _, lines in GIT_RUNS])
        engine_jobs([match_job(a.level['setup'], a.level['solution'], lines) for a, lines in PREFIXES])
        # A list the engine rejects fails its own subTest. Real git would raise on it inside the
        # thread pool (an unknown {message} token, say) and error the whole class instead.
        gitgraph.git_prefetch([lines for (_, lines), run in zip(GIT_RUNS, runs) if run['ok']])

    def test_the_engine_builds_the_graph_real_git_builds(self):
        for a, lines in GIT_RUNS:
            with self.subTest(level=a.level['id'], check=a.label):
                self.assertEqual(canonical(run_engine(lines)), canonical(run_git(lines)))

    def test_the_game_solves_each_attempt_after_its_last_line_or_never(self):
        prefixes = {}
        for a, lines in PREFIXES:
            prefixes.setdefault(key(a), []).append(lines)
        for a in ATTEMPTS:
            expected = [len(a.lines)] if REACHES_GOAL[a.kind] else []
            with self.subTest(level=a.level['id'], check=a.label):
                on_goal = [len(lines) for lines in prefixes[key(a)]
                           if engine_matches(a.level['setup'], a.level['solution'], lines)]
                self.assertEqual(on_goal, expected,
                                 f'{a.label} {a.lines!r}: the line counts after which the graph matches the goal; '
                                 'the game solves at the first one')

    def test_every_attempt_is_checked_after_each_of_its_lines(self):
        walked = {}
        for a, lines in PREFIXES:
            self.assertEqual(lines, a.lines[:len(lines)])
            walked.setdefault(key(a), []).append(len(lines))
        self.assertEqual(walked, {key(a): list(range(len(a.lines) + 1)) for a in ATTEMPTS})

    def test_every_level_on_the_home_page_is_checked_with_each_kind_of_attempt(self):
        with open(HOME, encoding='utf-8') as f:
            ids = [level['id'] for level in json.load(f)['game']['levels']]
        self.assertTrue(ids, 'content/home.json game.levels is empty')
        for name, cases, kinds in (('engine', ATTEMPTS, set(REACHES_GOAL)),
                                   ('real git', [a for a, _ in GIT_RUNS], RUN_IN_GIT)):
            seen = {}
            for a in cases:
                seen.setdefault(a.level['id'], set()).add(a.kind)
            self.assertEqual(sorted(seen), sorted(ids), f'levels the {name} checks cover')
            for level_id in ids:
                with self.subTest(level=level_id, checks=name):
                    self.assertEqual(seen.get(level_id), kinds)


if __name__ == '__main__':
    unittest.main()
