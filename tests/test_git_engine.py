import json
import os
import re
import shlex
import subprocess
import unittest

import gitgraph
from gitgraph import canonical, engine_jobs, engine_matches, git_attempt, match_job, run_engine, run_git, run_job
from test_git_game import run_jobs as game_jobs

BRANCHED = ['git commit -m A', 'git checkout -b x', 'git commit -m X', 'git checkout main', 'git commit -m B']
CRISS_CROSS = ['git commit -m A', 'git checkout -b a', 'git commit -m X', 'git checkout -b b main', 'git commit -m Y',
               'git checkout a', 'git merge b', 'git checkout b', 'git merge a~1', 'git checkout a']

SCENARIOS = {
    'commit: root, child, non-ASCII message': ['git commit -m "Marmara University"', 'git commit -m "TÜSSİDE"'],
    'commit without -m gets a numbered message': ['git commit', 'git commit -m B', 'git commit'],
    'commit --amend -m replaces the tip': ['git commit -m A', 'git commit -m B', 'git commit --amend -m C'],
    'commit --amend keeps the message': ['git commit -m A', 'git commit -m B', 'git commit --amend'],
    'commit with two -m: the first is the subject': ['git commit -m First -m Second'],
    'branch at HEAD and at a rev, listing': ['git commit -m A', 'git commit -m B', 'git branch here',
                                            'git branch old HEAD~1', 'git branch'],
    'branch -d a merged branch': ['git commit -m A', 'git branch done', 'git commit -m B', 'git branch -d done'],
    'branch -D an unmerged branch orphans it': BRANCHED + ['git branch -D x'],
    'checkout -b, commit, back': ['git commit -m A', 'git checkout -b sony', 'git commit -m Sony',
                                  'git checkout main'],
    'checkout -b at a rev': ['git commit -m A', 'git commit -m B', 'git checkout -b old HEAD~1', 'git commit -m C'],
    'checkout a rev detaches HEAD': ['git commit -m A', 'git commit -m B', 'git checkout HEAD~1'],
    'checkout a tag detaches HEAD': ['git commit -m A', 'git tag v1', 'git commit -m B', 'git checkout v1'],
    'commit on detached HEAD, then leave it orphaned': ['git commit -m A', 'git checkout HEAD~0', 'git commit -m D',
                                                       'git checkout main'],
    'detached HEAD to detached HEAD': ['git commit -m A', 'git commit -m B', 'git checkout HEAD~1',
                                       'git checkout main~0'],
    'switch and switch -c at a rev': ['git commit -m A', 'git commit -m B', 'git switch -c topic HEAD~1',
                                      'git commit -m T', 'git switch main'],
    'merge fast-forward': ['git commit -m A', 'git checkout -b x', 'git commit -m X', 'git checkout main',
                           'git merge x'],
    'merge --no-ff makes a merge commit': ['git commit -m A', 'git checkout -b x', 'git commit -m X',
                                           'git checkout main', 'git merge --no-ff x'],
    'merge --no-ff after the rev': ['git commit -m A', 'git checkout -b x', 'git commit -m X',
                                    'git checkout main', 'git merge x --no-ff'],
    'merge already up to date': BRANCHED + ['git merge HEAD~1'],
    'three-way merge on main': BRANCHED + ['git merge x'],
    'three-way merge into another branch': BRANCHED + ['git checkout -b y', 'git merge x'],
    'three-way merge on detached HEAD': BRANCHED + ['git checkout HEAD~0', 'git merge x'],
    'merge a tag': BRANCHED + ['git tag t x', 'git merge t'],
    'merge the early part of a branch': BRANCHED + ['git checkout x', 'git commit -m X2', 'git checkout main',
                                                    'git merge x~1'],
    'rebase onto a moved main': ['git commit -m Intro', 'git checkout -b typofix', 'git commit -m "Fix typo"',
                                 'git checkout main', 'git commit -m Demo', 'git checkout typofix',
                                 'git rebase main'],
    'rebase with a branch argument': ['git commit -m A', 'git checkout -b t', 'git commit -m T1',
                                      'git commit -m T2', 'git checkout main', 'git commit -m B',
                                      'git rebase main t'],
    'rebase skips an already picked patch': ['git commit -m A', 'git checkout -b t', 'git commit -m T1',
                                             'git commit -m T2', 'git checkout main', 'git commit -m B',
                                             'git cherry-pick t~1', 'git rebase main t'],
    'rebase drops a merge commit': ['git commit -m A', 'git checkout -b t', 'git commit -m T1',
                                    'git checkout -b s', 'git commit -m S1', 'git checkout t',
                                    'git commit -m T2', 'git merge s', 'git commit -m T3',
                                    'git checkout main', 'git commit -m M', 'git rebase main t'],
    'rebase linearises a merge even on an up-to-date base': ['git commit -m A', 'git checkout -b t',
                                                             'git commit -m T1', 'git checkout -b s',
                                                             'git commit -m S1', 'git checkout t',
                                                             'git commit -m T2', 'git merge s',
                                                             'git checkout main', 'git rebase main t'],
    'rebase fast-forward': ['git commit -m A', 'git branch t', 'git commit -m B', 'git rebase main t'],
    'rebase no-op': ['git commit -m A', 'git checkout -b t', 'git commit -m T1', 'git checkout main',
                     'git rebase main t'],
    'rebase on detached HEAD': BRANCHED + ['git checkout x~0', 'git rebase main'],
    'rebase --onto': ['git commit -m Craftbase', 'git checkout -b services', 'git commit -m "Client A"',
                      'git checkout -b craftgate', 'git commit -m Gateway', 'git commit -m Launch',
                      'git checkout main', 'git rebase --onto main services craftgate'],
    'rebase --onto with HEAD~n upstream': ['git commit -m A', 'git checkout -b s', 'git commit -m S1',
                                           'git commit -m C1', 'git commit -m C2', 'git rebase --onto main HEAD~2'],
    'rebase --onto skips a patch picked on the upstream side': [
        'git commit -m A', 'git checkout -b t', 'git commit -m T1', 'git commit -m T2', 'git checkout -b n main',
        'git commit -m N', 'git checkout main', 'git commit -m B', 'git cherry-pick t~1',
        'git rebase --onto n main t'],
    'rebase --onto drops a patch the new base already has': [
        'git commit -m A', 'git checkout -b t', 'git commit -m T1', 'git commit -m T2', 'git checkout -b n main',
        'git commit -m N', 'git cherry-pick t~1', 'git rebase --onto n main t'],
    'rebase --onto with nothing to replay moves the branch to the new base': [
        'git commit -m A', 'git commit -m B', 'git commit -m C', 'git branch t HEAD~1', 'git checkout -b x HEAD~2',
        'git commit -m X', 'git rebase --onto x main t'],
    'rebase --onto no-op':['git commit -m A', 'git checkout -b c', 'git commit -m C1', 'git checkout main',
                            'git rebase --onto main main c'],
    'cherry-pick one commit': BRANCHED + ['git cherry-pick x'],
    'cherry-pick several, in the order given': ['git commit -m A', 'git checkout -b x', 'git commit -m X1',
                                                'git commit -m X2', 'git checkout main',
                                                'git cherry-pick x x~1'],
    'cherry-pick on detached HEAD': BRANCHED + ['git checkout HEAD~1', 'git cherry-pick x'],
    'reset --hard': ['git commit -m A', 'git commit -m B', 'git commit -m C', 'git reset --hard HEAD~2'],
    'reset --soft': ['git commit -m A', 'git commit -m B', 'git reset --soft HEAD~1', 'git commit -m C'],
    'reset --mixed then keep working': ['git commit -m A', 'git commit -m B', 'git reset --mixed HEAD~1',
                                        'git checkout -b other', 'git commit -m C'],
    'reset without mode, on detached HEAD': ['git commit -m A', 'git commit -m B', 'git checkout HEAD~0',
                                             'git reset HEAD~1'],
    'reset without a rev stays at HEAD': ['git commit -m A', 'git commit -m B', 'git reset --hard'],
    'revert makes Revert "msg"': ['git commit -m A', 'git commit -m B', 'git commit -m C', 'git revert HEAD~1'],
    'revert a revert reapplies': ['git commit -m A', 'git commit -m B', 'git revert HEAD', 'git revert HEAD'],
    'revert, reapply, then revert again': ['git commit -m A', 'git commit -m X', 'git revert HEAD',
                                           'git revert HEAD', 'git revert HEAD~2'],
    'cherry-pick a commit back after reverting it': ['git commit -m A', 'git commit -m X', 'git commit -m B',
                                                     'git revert HEAD~1', 'git cherry-pick HEAD~2'],
    'cherry-pick a revert onto a branch that has the commit': [
        'git commit -m A', 'git commit -m X', 'git checkout -b t', 'git revert HEAD', 'git checkout main',
        'git commit -m B', 'git cherry-pick t'],
    'cherry-pick a commit whose revert came in by a merge': [
        'git commit -m A', 'git commit -m X', 'git checkout -b t', 'git revert HEAD', 'git checkout main',
        'git commit -m B', 'git merge t', 'git cherry-pick HEAD~2'],
    'cherry-pick again after merging two copies and reverting one': [
        'git commit -m A', 'git checkout -b t', 'git commit -m X', 'git checkout main', 'git commit -m B',
        'git cherry-pick t', 'git merge t', 'git revert t', 'git cherry-pick t'],
    'after a criss-cross merge the merged merge bases decide what is there': CRISS_CROSS + [
        'git revert a~1', 'git checkout b', 'git merge a', 'git cherry-pick a~2'],
    'after a criss-cross merge the other merge base counts too': CRISS_CROSS + [
        'git revert HEAD^2', 'git checkout b', 'git merge a', 'git cherry-pick HEAD~2'],
    'rebase --onto replays a patch the new base picked and then reverted': [
        'git commit -m A', 'git checkout -b t', 'git commit -m X', 'git checkout -b n main', 'git commit -m N',
        'git cherry-pick t', 'git revert HEAD', 'git rebase --onto n main t'],
    'rebase skips a patch picked upstream even when upstream reverted it': [
        'git commit -m A', 'git checkout -b t', 'git commit -m X', 'git checkout main', 'git commit -m B',
        'git cherry-pick t', 'git revert HEAD', 'git rebase main t'],
    'rebase skips a reapply whose patch an upstream pick has': [
        'git commit -m A', 'git checkout -b t', 'git commit -m X', 'git revert HEAD', 'git revert HEAD',
        'git checkout main', 'git commit -m B', 'git cherry-pick t~2', 'git rebase main t'],
    'rebase drops a revert of a commit the new base never had': [
        'git commit -m A', 'git checkout -b t', 'git commit -m X', 'git revert HEAD', 'git checkout main',
        'git commit -m B', 'git rebase --onto main t~1 t'],
    'rebase replays a reapply onto a base that reverted the commit': [
        'git commit -m A', 'git commit -m X', 'git checkout -b t', 'git revert HEAD', 'git revert HEAD',
        'git checkout main', 'git commit -m B', 'git revert HEAD~1', 'git rebase --onto main t~2 t'],
    'tag at HEAD and at a rev, tag -d, listing': ['git commit -m A', 'git commit -m B', 'git tag v2',
                                                  'git tag v1 HEAD~1', 'git tag old', 'git tag -d old', 'git tag'],
    'revisions: ^, ^2, ~, @ and chains': BRANCHED + ['git merge x', 'git branch second HEAD^2',
                                                     'git branch first @^', 'git tag root main^2~1',
                                                     'git checkout @~1^'],
    'message tokens resolve per line': BRANCHED + ['git branch -D x', 'git branch back {X}',
                                                   'git cherry-pick {X}', 'git tag picked HEAD'],
    'log, status, reflog and help leave the graph alone': BRANCHED + [
        'git log', 'git log --oneline', 'git log --all', 'git log --oneline --all x', 'git status',
        'git reflog', 'git help'],
}

REFUSALS = {
    'branch -d of an unmerged branch': BRANCHED + ['git branch -d x'],
    'branch -d of the current branch': ['git commit -m A', 'git branch -d main'],
    'branch -D of the current branch': ['git commit -m A', 'git branch -D main'],
    'branch -d of an unknown branch': ['git commit -m A', 'git branch -d nope'],
    'creating a branch that exists': BRANCHED + ['git branch x'],
    'checkout -b of a branch that exists': BRANCHED + ['git checkout -b x'],
    'branch on an unborn HEAD': ['git branch x'],
    'checkout of an unknown name': ['git commit -m A', 'git checkout nope'],
    'switch to a commit': ['git commit -m A', 'git commit -m B', 'git switch HEAD~1'],
    'switch to an unknown name': ['git commit -m A', 'git switch nope'],
    'cherry-pick of an already applied commit': ['git commit -m A', 'git commit -m B', 'git cherry-pick HEAD~1'],
    'cherry-pick of a merge commit': BRANCHED + ['git merge x', 'git cherry-pick HEAD'],
    'revert of a merge commit': BRANCHED + ['git merge x', 'git revert HEAD'],
    'revert of a commit HEAD does not contain': BRANCHED + ['git revert x'],
    'revert of an already reverted commit': ['git commit -m A', 'git commit -m B', 'git revert HEAD',
                                             'git revert HEAD~1'],
    'cherry-pick of a revert onto a branch that never had the commit': [
        'git commit -m A', 'git checkout -b t', 'git commit -m X', 'git revert HEAD', 'git checkout main',
        'git cherry-pick t'],
    'revert of a revert while the commit is still there': [
        'git commit -m A', 'git commit -m X', 'git checkout -b t', 'git revert HEAD', 'git checkout main',
        'git commit -m B', 'git revert t'],
    'revert of a commit whose revert came in by a merge': [
        'git commit -m A', 'git commit -m X', 'git checkout -b t', 'git revert HEAD', 'git checkout main',
        'git commit -m B', 'git merge t', 'git revert HEAD~2'],
    'revert again after merging two copies and reverting once': [
        'git commit -m A', 'git checkout -b t', 'git commit -m X', 'git checkout main', 'git commit -m B',
        'git cherry-pick t', 'git merge t', 'git revert t', 'git revert t'],
    'amend on an unborn branch': ['git commit --amend'],
    'tag that exists': ['git commit -m A', 'git tag v', 'git tag v'],
    'tag -d of an unknown tag': ['git commit -m A', 'git tag -d nope'],
    'tag on an unborn HEAD': ['git tag v'],
    'reset to an unknown revision': ['git commit -m A', 'git reset --hard nope'],
    'merge of an unknown name': ['git commit -m A', 'git merge nope'],
    'log on an unborn branch': ['git log'],
    'an empty branch name': ['git commit -m A', 'git branch ""'],
    'a branch name starting with -': ['git commit -m A', 'git checkout -b -x'],
    'a branch named HEAD': ['git commit -m A', 'git branch HEAD'],
    'a branch name with a space': ['git commit -m A', 'git branch "a b"'],
    'a tag name with ~': ['git commit -m A', 'git tag a~1'],
    'a branch name with ^': ['git commit -m A', 'git switch -c a^'],
    'a branch name with :': ['git commit -m A', 'git branch a:b'],
    'a tag name with ?': ['git commit -m A', 'git tag "a?"'],
    'a branch name with *': ['git commit -m A', 'git branch "a*"'],
    'a branch name with [': ['git commit -m A', 'git branch "a["'],
    'a tag name with a backslash': ['git commit -m A', "git tag 'a\\b'"],
    'a branch name with ..': ['git commit -m A', 'git branch a..b'],
    'a branch name with @{': ['git commit -m A', "git branch 'a@{'"],
    'a branch name with //': ['git commit -m A', 'git branch a//b'],
    'a branch name starting with .': ['git commit -m A', 'git branch .a'],
    'a tag name with a part starting with .': ['git commit -m A', 'git tag a/.b'],
    'a branch name ending in /': ['git commit -m A', 'git branch a/'],
    'a tag name ending in .': ['git commit -m A', 'git tag a.'],
    'a tag name ending in .lock': ['git commit -m A', 'git tag v1.lock'],
    'a branch name with a part ending in .lock': ['git commit -m A', 'git checkout -b a/b.lock/c'],
    'a branch name starting with /': ['git commit -m A', 'git branch /a'],
}

PARTIAL_CHERRY_PICK = BRANCHED + ['git cherry-pick x HEAD~1']

EXPECTED_COMMANDS = {'commit', 'branch', 'checkout', 'switch', 'merge', 'rebase', 'cherry-pick', 'reset',
                     'revert', 'tag', 'log', 'status', 'reflog', 'help'}
EXPECTED_OPTIONS = {
    'commit': {'-m', '--amend'}, 'branch': {'-d', '-D'}, 'checkout': {'-b'}, 'switch': {'-c'},
    'merge': {'--no-ff'}, 'rebase': {'--onto'}, 'reset': {'--soft', '--mixed', '--hard'}, 'tag': {'-d'},
    'log': {'--oneline', '--all'},
}
OPTIONS_ONLY_REFUSED = {'-i', '--interactive', '--'}
HELP_FLAGS = {'--help', '-h'}
ENGINE_SOURCE = os.path.join(gitgraph.ROOT, 'assets', 'git-engine.js')


def _all_lines():
    return [line for lines in list(SCENARIOS.values()) + list(REFUSALS.values()) for line in lines]


def _raw(state):
    return {k: state[k] for k in ('commits', 'branches', 'tags', 'head')}


class EngineAgreesWithRealGit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        every = list(SCENARIOS.values()) + list(REFUSALS.values()) + [PARTIAL_CHERRY_PICK]
        engine_jobs([run_job(lines) for lines in every])
        gitgraph.git_prefetch(every)

    def test_every_scenario_builds_the_same_graph_as_real_git(self):
        for name, lines in SCENARIOS.items():
            with self.subTest(name):
                self.assertEqual(canonical(run_engine(lines)), canonical(run_git(lines)))

    def test_every_refusal_fails_on_its_last_line_in_both_and_changes_nothing(self):
        for name, lines in REFUSALS.items():
            with self.subTest(name):
                last = len(lines) - 1
                real = git_attempt(lines)
                self.assertFalse(real['ok'], 'real git accepted the line, so it is not a refusal')
                self.assertEqual(real['index'], last)
                self.assertEqual(_raw(real['before']), _raw(real['state']))
                engine = gitgraph.engine_attempt(lines)
                self.assertFalse(engine['ok'], 'the engine accepted a line real git refuses')
                self.assertEqual(engine['index'], last)
                self.assertEqual(_raw(engine['before']), _raw(engine['state']))
                self.assertEqual(canonical(engine['state']), canonical(real['state']))

    def test_a_cherry_pick_list_that_fails_part_way_keeps_the_earlier_picks(self):
        real = git_attempt(PARTIAL_CHERRY_PICK)
        engine = gitgraph.engine_attempt(PARTIAL_CHERRY_PICK)
        last = len(PARTIAL_CHERRY_PICK) - 1
        self.assertEqual((real['ok'], real['index']), (False, last))
        self.assertEqual((engine['ok'], engine['index']), (False, last))
        self.assertNotEqual(canonical(engine['before']), canonical(engine['state']))
        self.assertEqual(canonical(engine['state']), canonical(real['state']))

    def test_the_scenarios_cover_every_command_and_option(self):
        self.assertTrue(SCENARIOS)
        self.assertTrue(REFUSALS)
        commands = engine_jobs([{'op': 'commands'}])[0]['commands']
        self.assertEqual(set(commands), EXPECTED_COMMANDS)
        used = {}
        for line in _all_lines():
            argv = shlex.split(line)
            used.setdefault(argv[1], set()).update(a for a in argv[2:] if a.startswith('-'))
        self.assertEqual(EXPECTED_COMMANDS - set(used), set())
        for command, options in EXPECTED_OPTIONS.items():
            self.assertEqual(options - used.get(command, set()), set(), command)

    def test_the_engine_recognises_no_option_beyond_the_expected_ones(self):
        with open(ENGINE_SOURCE, encoding='utf-8') as f:
            source = f.read()
        self.assertEqual(re.findall(r"indexOf\('-|case '-", source), [],
                         'options must be matched with === so this scan sees them')
        recognised = set(re.findall(r"[!=]== '(-[^']+)'", source))
        planned = set().union(*EXPECTED_OPTIONS.values()) | OPTIONS_ONLY_REFUSED | HELP_FLAGS
        self.assertEqual(recognised, planned)


SETUP = ['git commit -m A', 'git commit -m B', 'git commit -m C']
TAG_LEVEL = ['git commit -m Craftbase', 'git commit -m Gateway', 'git commit -m "Public launch"',
             'git commit -m "Only Craftgate"']
RELEASE_LEVEL = ['git commit -m Idea', 'git checkout -b talk', 'git commit -m Outline', 'git commit -m Slides',
                 'git checkout main', 'git commit -m "CFP accepted"']
RELEASE_SOLUTION = ['git rebase main talk', 'git checkout main', 'git merge --no-ff talk', 'git tag devoxx',
                    'git branch -d talk']
REFLOG_LEVEL = ['git commit -m Community', 'git checkout -b scturkey', 'git commit -m "First meetup"',
                'git commit -m Coderetreat', 'git checkout main', 'git branch -D scturkey']

MATCH_CASES = [
    ('a player message and hash never matter', SETUP, ['git commit -m X'], ['git commit -m Y'], True),
    ('a plain commit does not satisfy an amend', SETUP, ['git commit --amend -m D'],
     ['git reset --hard HEAD~1', 'git commit -m D'], False),
    ('amend with or without -m is the same move', SETUP, ['git commit --amend -m D'], ['git commit --amend'], True),
    ('leaving the commit as it is does not satisfy an amend', SETUP, ['git commit --amend -m D'], [], False),
    ('amending a setup commit twice is one amend', SETUP, ['git commit --amend -m D'],
     ['git commit --amend -m E', 'git commit --amend -m F'], True),
    ('amending your own commit keeps it a plain commit', SETUP, ['git commit -m X'],
     ['git commit -m Y', 'git commit --amend -m Z'], True),
    ('amending your own revert keeps it a revert', SETUP, ['git revert HEAD~1'],
     ['git revert HEAD~1', 'git commit --amend -m R'], True),
    ('amending your own copy keeps it a copy', SETUP + ['git checkout -b x HEAD~2', 'git commit -m X',
                                                        'git checkout main'],
     ['git cherry-pick x'], ['git cherry-pick x', 'git commit --amend -m Y'], True),
    ('reverting the right commit by another name matches', SETUP, ['git revert HEAD~1'], ['git revert {B}'], True),
    ('reverting the wrong commit does not match', SETUP, ['git revert HEAD~1'], ['git revert HEAD'], False),
    ('a re-made base commit is not the base commit', SETUP, [], ['git reset --hard HEAD~1', 'git commit -m C'],
     False),
    ('HEAD attached vs detached at the same commit', SETUP, [], ['git checkout HEAD~0'], False),
    ('HEAD detached at the same commit by two routes', SETUP, ['git checkout HEAD~1'], ['git checkout main~1'],
     True),
    ('HEAD detached at different commits', SETUP, ['git checkout HEAD~1'], ['git checkout HEAD~2'], False),
    ('HEAD on another branch at the same commit', SETUP + ['git branch b'], [], ['git checkout b'], False),
    ('a missing branch', SETUP, ['git branch b'], [], False),
    ('an extra branch', SETUP, [], ['git branch b'], False),
    ('a branch at a different commit', SETUP, ['git branch b'], ['git branch b HEAD~1'], False),
    ('a missing tag', SETUP, ['git tag t'], [], False),
    ('an extra tag', SETUP, [], ['git tag t'], False),
    ('unreachable commits are ignored', SETUP, [], ['git commit -m X', 'git reset --hard HEAD~1'], True),
    ('a cherry-picked copy keeps its identity', SETUP + ['git checkout -b x HEAD~2', 'git commit -m X',
                                                         'git checkout main'],
     ['git cherry-pick x'], ['git merge x'], False),
    ('cherry-pick and rebase copies of the same commit match', SETUP + ['git checkout -b x HEAD~1',
                                                                         'git commit -m X', 'git checkout main'],
     ['git checkout x', 'git rebase main'], ['git checkout x', 'git reset --hard main', 'git cherry-pick {X}'],
     True),
    ('a tag on a copy while the original stays on main is not the goal', TAG_LEVEL, ['git tag launch HEAD~1'],
     ['git checkout HEAD~2', 'git cherry-pick {Public launch}', 'git tag launch', 'git checkout main'], False),
    ('two merge commits do not stand for the one merge of the goal', RELEASE_LEVEL, RELEASE_SOLUTION,
     RELEASE_SOLUTION[:4] + ['git reset --hard HEAD~1', 'git merge --no-ff talk', 'git branch -d talk'], False),
    ('a copy that replaces an unreachable original matches', REFLOG_LEVEL, ['git branch scturkey {Coderetreat}'],
     ['git checkout -b scturkey {First meetup}', 'git cherry-pick {Coderetreat}', 'git checkout main'], True),
    ('one commit does not stand for two goal commits', SETUP,
     ['git checkout -b a', 'git commit -m X', 'git checkout -b b main', 'git commit -m Y', 'git checkout main'],
     ['git checkout -b a', 'git commit -m X', 'git branch b', 'git checkout main'], False),
    ('HEAD detached at a copy of the commit main still has does not match', SETUP, ['git checkout HEAD~1'],
     ['git checkout HEAD~2', 'git cherry-pick {B}'], False),
]


class EngineMatches(unittest.TestCase):
    def test_hand_written_expectations(self):
        engine_jobs([match_job(s, g, a) for _, s, g, a, _ in MATCH_CASES])
        for name, setup, goal, attempt, expected in MATCH_CASES:
            with self.subTest(name):
                self.assertIs(engine_matches(setup, goal, attempt), expected)


AMEND_LEVEL = ['git commit -m Abstract', 'git commit -m Slides']
AMEND_SOLUTION = ['git commit --amend -m "Slides, with demo"']
REVERT_LEVEL = ['git commit -m "High Sierra"', 'git commit -m "Credential check"', 'git commit -m 10.13.1']
CHERRY_PICK_LEVEL = ['git commit -m Craftgate', 'git checkout -b experiments', 'git commit -m "Refunds, tested"',
                     'git commit -m "Spike, no tests"', 'git commit -m "Payouts, tested"', 'git checkout main']
CHERRY_PICK_SOLUTION = ['git cherry-pick experiments~2 experiments']


def identity(*cases):
    """GitEngine.identityDiff(attempt, goal) for (setup, goal lines, attempt lines) cases."""
    results = game_jobs(*({'op': 'identity', 'setup': s, 'goal': g, 'attempt': a} for s, g, a in cases))
    for r in results:
        if not r['ok']:
            raise AssertionError('engine: ' + r['error'])
    return results


def tip(state, steps_back=0):
    hash_ = state['branches']['main']
    for _ in range(steps_back):
        hash_ = state['commits'][hash_]['parents'][0]
    return hash_


class EngineIdentityDiff(unittest.TestCase):
    def test_a_graph_of_another_shape_has_no_identity_diff(self):
        cases = [
            ('the branch on another commit', AMEND_LEVEL, AMEND_SOLUTION, ['git reset --hard HEAD~1']),
            ('an extra branch', AMEND_LEVEL, AMEND_SOLUTION, ['git commit --amend', 'git branch b']),
            ('an extra tag', AMEND_LEVEL, AMEND_SOLUTION, ['git commit --amend', 'git tag t']),
            ('HEAD detached', AMEND_LEVEL, AMEND_SOLUTION, ['git commit --amend', 'git checkout HEAD~0']),
            ('one commit for two goal commits', SETUP,
             ['git checkout -b a', 'git commit -m X', 'git checkout -b b main', 'git commit -m Y', 'git checkout main'],
             ['git checkout -b a', 'git commit -m X', 'git branch b', 'git checkout main']),
        ]
        for (name, *_), r in zip(cases, identity(*(c[1:] for c in cases))):
            with self.subTest(name):
                self.assertIsNone(r['diff'])
                self.assertFalse(r['matches'])

    def test_the_right_shape_made_another_way_names_each_differing_pair(self):
        cases = [
            ('amend level, reset --soft and commit', AMEND_LEVEL, AMEND_SOLUTION,
             ['git reset --soft HEAD~1', 'git commit'], 'Commit 1', [0]),
            ('amend level, reset --hard and commit', AMEND_LEVEL, AMEND_SOLUTION,
             ['git reset --hard HEAD~1', 'git commit'], 'Commit 1', [0]),
            ('revert level, a plain commit in place of the revert', REVERT_LEVEL, ['git revert HEAD~1'],
             ['git commit -m Fix'], 'Fix', [0]),
            ('cherry-pick level, a plain commit in place of the second pick', CHERRY_PICK_LEVEL, CHERRY_PICK_SOLUTION,
             ['git cherry-pick experiments~2', 'git commit -m Payouts'], 'Payouts', [0]),
            ('cherry-pick level, plain commits in place of both picks, in the goal order', CHERRY_PICK_LEVEL,
             CHERRY_PICK_SOLUTION, ['git commit -m Refunds', 'git commit -m Payouts'], 'Payouts', [1, 0]),
        ]
        for (name, _, _, _, tip_message, back), r in zip(cases, identity(*(c[1:4] for c in cases))):
            with self.subTest(name):
                attempt, goal = r['attempt'], r['goal']
                self.assertEqual(attempt['commits'][tip(attempt)]['message'], tip_message)
                self.assertEqual(r['diff'], [{'hash': tip(attempt, n), 'goal': tip(goal, n)} for n in back])
                self.assertFalse(r['matches'])

    def test_identity_diff_is_empty_exactly_when_the_graph_matches(self):
        with open(os.path.join(gitgraph.ROOT, 'content', 'home.json'), encoding='utf-8') as f:
            levels = json.load(f)['game']['levels']
        self.assertTrue(levels, 'content/home.json game.levels is empty')
        cases = []
        for level in levels:
            cases.append((level['id'], 'solution', level['setup'], level['solution'], level['solution'], True))
            for kind, key, expected in (('alternative', 'alternatives', True), ('near miss', 'near_misses', False)):
                for lines in level['checks'][key]:
                    cases.append((level['id'], kind, level['setup'], level['solution'], lines, expected))
        cases += [('MATCH_CASES', name, setup, goal, attempt, expected)
                  for name, setup, goal, attempt, expected in MATCH_CASES]
        walked = {}
        for (where, kind, *_, lines, expected), r in zip(cases, identity(*(c[2:5] for c in cases))):
            with self.subTest(where=where, kind=kind, lines=lines):
                diff = r['diff']
                self.assertIs(r['matches'], diff == [])
                self.assertIs(r['matches'], expected)
                if not expected:
                    self.assertTrue(diff is None or len(diff) > 0, diff)
            walked.setdefault(where, []).append(kind)
        self.assertEqual(sorted(walked), sorted([level['id'] for level in levels] + ['MATCH_CASES']))
        for level in levels:
            self.assertEqual(set(walked[level['id']]), {'solution', 'alternative', 'near miss'}, level['id'])
        self.assertEqual(len(walked['MATCH_CASES']), len(MATCH_CASES))


def trace(lines):
    return engine_jobs([{'op': 'trace', 'lines': list(lines)}])[0]


HASH = '[0-9a-f]{7}'

DOUBLE_QUOTES = '"“”'
SINGLE_QUOTES = "'‘’"
QUOTE_PAIRS = [
    ('git commit -m "Demo 1"', 'Demo 1'),
    ('git commit -m "Demo 2“', 'Demo 2'),
    ('git commit -m "Demo 3”', 'Demo 3'),
    ('git commit -m “Demo 4"', 'Demo 4'),
    ('git commit -m “Demo 5“', 'Demo 5'),
    ('git commit -m “Demo 6”', 'Demo 6'),
    ('git commit -m ”Demo 7"', 'Demo 7'),
    ('git commit -m ”Demo 8“', 'Demo 8'),
    ('git commit -m ”Demo 9”', 'Demo 9'),
    ("git commit -m 'Demo 10'", 'Demo 10'),
    ("git commit -m 'Demo 11‘", 'Demo 11'),
    ("git commit -m 'Demo 12’", 'Demo 12'),
    ("git commit -m ‘Demo 13'", 'Demo 13'),
    ('git commit -m ‘Demo 14‘', 'Demo 14'),
    ('git commit -m ‘Demo 15’', 'Demo 15'),
    ("git commit -m ’Demo 16'", 'Demo 16'),
    ('git commit -m ’Demo 17‘', 'Demo 17'),
    ('git commit -m ’Demo 18’', 'Demo 18'),
]
QUOTE_CONTENTS = [
    ('git commit -m “Lemi’s talk”', 'Lemi’s talk'),
    ('git commit -m ”it\'s ‘fine’ now“', 'it\'s ‘fine’ now'),
    ("git commit -m ‘say “hi” and \"bye”’", 'say “hi” and "bye”'),
    ('git commit -m ‘Q&A’', 'Q&A'),
    ('git commit -m "say \\"hi\\" now"', 'say "hi" now'),
    ('git commit -m “say \\”hi\\“ now”', 'say ”hi“ now'),
    ('git commit -m ‘back\\slash’', 'back\\slash'),
    (r'git commit -m "back\\slash"', r'back\slash'),
    (r'git commit -m “back\\slash”', r'back\slash'),
    (r'git commit -m "keep\q"', r'keep\q'),
    ('git commit -m "She said “hi” to me"', 'She said hi to me'),
    ("git commit -m 'She said ‘hi' to me'", 'She said hi to me'),
]
MID_WORD_APOSTROPHES = [
    ('git commit -m Lemi’s', 'Lemi’s'),
    ('git commit -m Lemi‘s', 'Lemi‘s'),
    (r'git commit -m Lemi\ ’s', 'Lemi ’s'),
    ('git commit -m ‘it\\’s’', 'it\\s’'),
]
UNTERMINATED_QUOTES = ['git commit -m “open', 'git commit -m ”open', 'git commit -m ‘open', 'git commit -m ’open',
                       'git commit -m “Demo’', 'git commit -m ‘Demo”', "git commit -m Lemi's",
                       "git commit -m 'it\\'s'", "git commit -m 'She said ‘hi’ to me'"]


class EngineInterface(unittest.TestCase):
    def test_output_reads_like_git(self):
        t = trace(['git commit -m A', 'git checkout -b t', 'git commit -m T', 'git checkout main',
                   'git commit -m B', 'git checkout nope', 'git rebase main t', 'git checkout HEAD~1',
                   'git commit', 'git log --oneline'])
        out = [s['output'] for s in t['steps']]
        self.assertRegex(out[0][0], rf'^\[main \(root-commit\) {HASH}\] A$')
        self.assertEqual(out[1], ["Switched to a new branch 't'"])
        self.assertRegex(out[2][0], rf'^\[t {HASH}\] T$')
        self.assertEqual(out[3], ["Switched to branch 'main'"])
        self.assertEqual(out[5], ["error: pathspec 'nope' did not match any file(s) known to git"])
        self.assertEqual(out[6][-1], 'Successfully rebased and updated refs/heads/t.')
        self.assertEqual(out[7][0], "Note: switching to 'HEAD~1'.")
        self.assertRegex(out[8][0], rf'^\[detached HEAD {HASH}\] Commit 1$')
        self.assertEqual([re.sub(HASH, 'H', line, count=1) for line in out[9]],
                         ['H (HEAD) Commit 1', 'H (main) B', 'H A'])

    def test_rebase_reports_up_to_date_fast_forward_and_skips(self):
        t = trace(['git commit -m A', 'git checkout -b t', 'git commit -m T', 'git rebase main',
                   'git checkout -b f main', 'git rebase t', 'git checkout -b u main', 'git cherry-pick t',
                   'git rebase u t', 'git checkout main', 'git commit -m B', 'git checkout t~0', 'git rebase main'])
        out = [s['output'] for s in t['steps']]
        self.assertEqual(out[3], ['Current branch t is up to date.'])
        self.assertEqual(out[5], ['Successfully rebased and updated refs/heads/f.'])
        self.assertRegex(out[8][0], rf'^warning: skipped previously applied commit {HASH}$')
        self.assertEqual(out[12], ['Successfully rebased and updated detached HEAD.'])

    def test_reattaching_at_the_same_commit_prints_only_the_switch(self):
        t = trace(['git commit -m A', 'git checkout HEAD~0', 'git checkout main'])
        self.assertEqual(t['steps'][2]['output'], ["Switched to branch 'main'"])

    def test_reflog_lists_head_movements_newest_first(self):
        t = trace(['git commit -m A', 'git commit -m B', 'git reset --hard HEAD~1', 'git reflog'])
        lines = [re.sub(rf'^{HASH}( \([^)]*\))?', 'H', line) for line in t['steps'][-1]['output']]
        self.assertEqual(lines, ['H HEAD@{0}: reset: moving to HEAD~1', 'H HEAD@{1}: commit: B',
                                 'H HEAD@{2}: commit (initial): A'])

    def test_help_lists_every_command(self):
        out = '\n'.join(trace(['git help'])['steps'][0]['output'])
        for command in EXPECTED_COMMANDS:
            self.assertRegex(out, rf'(?m)^   {re.escape(command)} +\S')

    def test_bad_input_fails_cleanly_and_changes_nothing(self):
        lines = ['git commit -m A', 'git', 'git commit -m "open', 'ls -la', 'git stash', 'git frobnicate',
                 'git commit --bogus', 'git rebase -i HEAD~1', 'git checkout']
        t = trace(lines)
        for line, step in zip(lines[1:-1], t['steps'][1:-1]):
            with self.subTest(line):
                self.assertFalse(step['ok'])
                self.assertFalse(step['changed'])
                self.assertTrue(step['output'])
                self.assertNotIn('internal error', ' '.join(step['output']))
        self.assertIn('not supported in this game', ' '.join(t['steps'][4]['output']))

    def test_forms_real_git_has_but_the_game_does_not_are_refused_without_a_change(self):
        setup = BRANCHED + ['git branch y', 'git tag v', 'git tag w']
        lines = ['git branch -d y main', 'git branch --delete y', 'git branch -l', 'git branch --list',
                 'git tag -d v w', 'git tag --delete v', 'git tag -l', 'git revert HEAD HEAD~1',
                 'git merge --ff x', 'git merge --no-edit x', 'git commit --message=C', 'git commit --message C',
                 'git commit -mC', 'git switch --create z', 'git rebase --onto=main x']
        t = trace(setup + lines)
        for line, step in zip(lines, t['steps'][len(setup):]):
            with self.subTest(line):
                self.assertFalse(step['ok'])
                self.assertFalse(step['changed'])
                self.assertTrue(step['output'])
                self.assertNotIn('internal error', ' '.join(step['output']))

    def test_a_bare_dash_or_double_dash_is_refused_as_a_cut_form(self):
        commands = [c for c in engine_jobs([{'op': 'commands'}])[0]['commands'] if c != 'help']
        self.assertLessEqual({'checkout', 'switch', 'merge', 'rebase', 'cherry-pick', 'revert'}, set(commands))
        lines = [f'git {c} {dash}' for c in commands for dash in ('-', '--')]
        t = trace(BRANCHED + lines)
        for line, step in zip(lines, t['steps'][len(BRANCHED):]):
            with self.subTest(line):
                text = ' '.join(step['output'])
                self.assertFalse(step['ok'])
                self.assertFalse(step['changed'])
                self.assertIn('is not supported in this game', text)
                self.assertNotIn("`'", text)

    def test_help_prints_a_usage_for_each_command_and_the_list_for_any_other_name(self):
        commands = engine_jobs([{'op': 'commands'}])[0]['commands']
        self.assertEqual(set(commands), EXPECTED_COMMANDS)
        others = ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'frobnicate']
        t = trace([f'git help {name}' for name in commands + others])
        for name, step in zip(commands + others, t['steps']):
            with self.subTest(name):
                self.assertTrue(step['ok'])
                self.assertNotIn('undefined', '\n'.join(step['output']))
                if name in commands:
                    self.assertRegex(step['output'][0], rf'^usage: git {re.escape(name)}( |$)')
                else:
                    self.assertEqual(step['output'][0], 'These are the git commands this game understands:')

    def test_smart_quotes_from_phone_keyboards_quote_like_straight_ones(self):
        lines = [line for line, _ in QUOTE_PAIRS + QUOTE_CONTENTS] + ['git tag “v1.0”'] + UNTERMINATED_QUOTES
        t = trace(lines)
        steps = dict(zip(lines, t['steps']))
        for line, message in QUOTE_PAIRS + QUOTE_CONTENTS:
            with self.subTest(line):
                self.assertTrue(steps[line]['ok'], steps[line]['output'])
                made = [d['hash'] for d in steps[line]['diff'] if d['type'] == 'commit']
                self.assertEqual([t['state']['commits'][h]['message'] for h in made], [message])
        self.assertTrue(steps['git tag “v1.0”']['ok'])
        self.assertEqual(list(t['state']['tags']), ['v1.0'])
        for line in UNTERMINATED_QUOTES:
            with self.subTest(line):
                self.assertEqual((steps[line]['ok'], steps[line]['changed'], steps[line]['output']),
                                 (False, False, ['error: unterminated quote']))

    def test_a_curly_single_quote_inside_a_word_is_an_apostrophe(self):
        t = trace([line for line, _ in MID_WORD_APOSTROPHES])
        for (line, message), step in zip(MID_WORD_APOSTROPHES, t['steps']):
            with self.subTest(line):
                self.assertTrue(step['ok'], step['output'])
                made = [d['hash'] for d in step['diff'] if d['type'] == 'commit']
                self.assertEqual([t['state']['commits'][h]['message'] for h in made], [message])

    def test_the_quote_rows_pair_every_opener_with_every_closer_of_its_family(self):
        prefix = 'git commit -m '
        accepted = QUOTE_PAIRS + QUOTE_CONTENTS + MID_WORD_APOSTROPHES
        self.assertTrue(all(line.startswith(prefix) for line, _ in accepted))
        lines = [line for line, _ in accepted] + UNTERMINATED_QUOTES
        self.assertEqual(len(set(lines)), len(lines), 'the smart-quote test looks each step up by its line')
        pairs = {(line[len(prefix)], line[-1]) for line, _ in QUOTE_PAIRS}
        self.assertEqual(pairs, {(o, c) for family in (DOUBLE_QUOTES, SINGLE_QUOTES) for o in family for c in family})
        other = {DOUBLE_QUOTES: SINGLE_QUOTES, SINGLE_QUOTES: DOUBLE_QUOTES}
        inside = {DOUBLE_QUOTES: set(), SINGLE_QUOTES: set()}
        for line, message in QUOTE_CONTENTS:
            family = DOUBLE_QUOTES if line[len(prefix)] in DOUBLE_QUOTES else SINGLE_QUOTES
            inside[family] |= set(message) & set(other[family])
        self.assertEqual(inside, {family: set(chars) for family, chars in other.items()})

    def test_the_quote_rows_keep_a_row_for_each_decided_case(self):
        prefix = 'git commit -m '
        quotes = DOUBLE_QUOTES + SINGLE_QUOTES
        curly = {'"': DOUBLE_QUOTES[1:], "'": SINGLE_QUOTES[1:]}
        cases = {
            '’ inside a word': (MID_WORD_APOSTROPHES, lambda a: a[0] not in quotes and '’' in a and '\\' not in a),
            '‘ inside a word': (MID_WORD_APOSTROPHES, lambda a: a[0] not in quotes and '‘' in a and '\\' not in a),
            'an apostrophe after an escaped space': (MID_WORD_APOSTROPHES, lambda a: '\\ ' in a),
            'an apostrophe right after a closed quote': (MID_WORD_APOSTROPHES, lambda a: a[0] in SINGLE_QUOTES[1:]),
            "a straight ' inside a word": (UNTERMINATED_QUOTES, lambda a: a[0] not in quotes and "'" in a),
            'a straight double quote escaping a backslash': (QUOTE_CONTENTS, lambda a: a[0] == '"' and '\\\\' in a),
            'a curly double quote escaping a backslash': (QUOTE_CONTENTS, lambda a: a[0] in curly['"'] and '\\\\' in a),
            'a double quote keeping a backslash that escapes nothing': (
                QUOTE_CONTENTS, lambda a: a[0] in DOUBLE_QUOTES and '\\' in re.sub(r'\\[\\"“”]', '', a)),
            'a curly double quote inside a straight one': (
                QUOTE_CONTENTS, lambda a: a[0] == '"' and set(a[1:-1]) & set(curly['"'])),
            'a curly single quote inside a straight one': (
                QUOTE_CONTENTS, lambda a: a[0] == "'" and set(a[1:-1]) & set(curly["'"])),
            'a curly single quote pair inside a straight one': (
                UNTERMINATED_QUOTES, lambda a: a[0] == "'" and set(curly["'"]) <= set(a[1:-1])),
        }
        for name, (rows, holds) in cases.items():
            with self.subTest(name):
                lines = [row if isinstance(row, str) else row[0] for row in rows]
                self.assertTrue(any(holds(line[len(prefix):]) for line in lines))

    def test_first_line_is_exported_for_the_game(self):
        script = 'process.stdout.write(JSON.stringify(require(process.argv[1]).firstLine("Slides\\n\\nwith demo")))'
        proc = subprocess.run([gitgraph._tool('node'), '-e', script, ENGINE_SOURCE],
                              capture_output=True, text=True, timeout=gitgraph.TIMEOUT)
        self.assertEqual((proc.returncode, proc.stdout), (0, '"Slides"'), proc.stderr)

    def test_a_short_hash_two_commits_share_is_ambiguous(self):
        lines = ['git commit -m A', 'git commit -m "Draft 10002"']
        first, second = sorted(trace(lines)['state']['commits'])
        self.assertEqual(first[:4], second[:4], 'the fixture must give two hashes that share 4 characters')
        self.assertNotEqual(first[:5], second[:5])
        t = trace(lines + [f'git checkout {first[:4]}', f'git checkout {second[:5]}'])
        ambiguous, longer = t['steps'][2], t['steps'][3]
        self.assertFalse(ambiguous['ok'])
        self.assertFalse(ambiguous['changed'])
        self.assertEqual(ambiguous['output'][0], f'error: short object ID {first[:4]} is ambiguous')
        self.assertTrue(longer['ok'])
        self.assertEqual(t['state']['head'], {'type': 'detached', 'hash': second})

    def test_names_git_allows_but_the_engine_reserves_are_refused_cleanly(self):
        lines = ['git branch __proto__', 'git tag __proto__', 'git checkout -b __proto__', 'git branch @',
                 'git tag @', 'git switch -c @']
        t = trace(['git commit -m A'] + lines)
        for line, step in zip(lines, t['steps'][1:]):
            with self.subTest(line):
                self.assertFalse(step['ok'])
                self.assertFalse(step['changed'])
                self.assertRegex(step['output'][0], r"^fatal: '(__proto__|@)' is not a valid (branch|tag) name")

    def test_changed_and_diff_describe_each_move(self):
        t = trace(['git commit -m A', 'git log', 'git checkout -b x', 'git commit -m X', 'git checkout HEAD~1',
                   'git checkout main', 'git branch -D x', 'git tag v'])
        steps = t['steps']
        self.assertEqual([s['changed'] for s in steps], [True, False, True, True, True, True, True, True])
        a = steps[0]['diff'][0]['hash']
        self.assertEqual(steps[0]['diff'], [{'type': 'commit', 'hash': a},
                                            {'type': 'ref', 'kind': 'branch', 'name': 'main', 'from': None, 'to': a}])
        self.assertEqual(steps[1]['diff'], [])
        self.assertEqual(steps[2]['diff'], [{'type': 'ref', 'kind': 'branch', 'name': 'x', 'from': None, 'to': a},
                                            {'type': 'head', 'from': {'type': 'branch', 'name': 'main'},
                                             'to': {'type': 'branch', 'name': 'x'}}])
        x = steps[3]['diff'][0]['hash']
        self.assertEqual(steps[3]['diff'][1], {'type': 'ref', 'kind': 'branch', 'name': 'x', 'from': a, 'to': x})
        self.assertEqual(steps[4]['diff'], [{'type': 'head', 'from': {'type': 'branch', 'name': 'x'},
                                             'to': {'type': 'detached', 'hash': a}}])
        self.assertEqual(steps[6]['diff'], [{'type': 'ref', 'kind': 'branch', 'name': 'x', 'from': x, 'to': None}])
        self.assertEqual(steps[7]['diff'], [{'type': 'ref', 'kind': 'tag', 'name': 'v', 'from': None, 'to': a}])
        self.assertEqual(t['reachable'], [a])
        self.assertIn(x, t['state']['commits'])

    def test_snapshot_and_restore_undo_a_move(self):
        t = trace(['git commit -m A', '#snapshot', 'git commit -m B', 'git checkout -b y', '#restore'])
        restored = t['state']
        self.assertEqual(list(restored['branches']), ['main'])
        self.assertEqual(len(restored['commits']), 1)
        self.assertEqual(restored['head'], {'type': 'branch', 'name': 'main'})

    def test_hashes_are_deterministic_and_prefixes_resolve(self):
        lines = ['git commit -m A', 'git commit -m B']
        first, second = trace(lines), trace(lines + ['git log'])
        self.assertEqual(first['state']['commits'], second['state']['commits'])
        a = next(h for h, c in first['state']['commits'].items() if c['message'] == 'A')
        t = trace(lines + [f'git checkout {a[:4]}'])
        self.assertEqual(t['state']['head'], {'type': 'detached', 'hash': a})

    def test_resolve_needs_exactly_one_commit_with_the_message(self):
        lines = ['git commit -m A', 'git commit -m B', 'git commit -m B']
        unique, missing, twice = engine_jobs([{'op': 'resolve', 'lines': lines, 'line': f'git tag t {{{m}}}'}
                                              for m in ('A', 'Z', 'B')])
        self.assertTrue(unique['ok'])
        self.assertRegex(unique['line'], rf'^git tag t {HASH}$')
        self.assertFalse(missing['ok'])
        self.assertFalse(twice['ok'])


if __name__ == '__main__':
    unittest.main()
