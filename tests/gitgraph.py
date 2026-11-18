"""Run git command lines in the game engine and in real git, and compare the graphs.

The real-git side is the oracle. Each line runs in a throwaway repository with
an isolated environment; the translation from a game line to real git is:
every commit adds one new file, `commit --amend` adds one more before amending,
a commit without -m gets the message the engine picks (AUTO_MESSAGE), merge and
revert get --no-edit, and a --soft/--mixed reset is followed by a clean-up so
the work tree never blocks a later line (the engine models only the graph).
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'git_engine_cli.js')
TOKEN = re.compile(r'\{([^{}]+)\}')
AUTO_MESSAGE = 'Commit {n}'
DATE = '2016-04-01T12:00:00+0000'
TIMEOUT = 60

_engine_cache = {}
_git_cache = {}


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise AssertionError(
            f'{name} is not on PATH. The git game tests need Node.js and git '
            f'(both ship on the ubuntu-latest CI runner); install {name} to run them.')
    return path


def _key(job):
    return json.dumps(job, sort_keys=True, ensure_ascii=False)


def engine_jobs(jobs):
    """Run engine jobs (see git_engine_cli.js) in one node process; results are cached."""
    jobs = list(jobs)
    missing = {}
    for job in jobs:
        key = _key(job)
        if key not in _engine_cache:
            missing[key] = job
    if missing:
        proc = subprocess.run(
            [_tool('node'), CLI], input=json.dumps({'jobs': list(missing.values())}).encode('utf-8'),
            capture_output=True, timeout=TIMEOUT)
        if proc.returncode != 0:
            raise AssertionError(f'git_engine_cli.js exited {proc.returncode}:\n'
                                 + proc.stderr.decode('utf-8', 'replace'))
        results = json.loads(proc.stdout.decode('utf-8'))['results']
        for key, result in zip(missing, results):
            _engine_cache[key] = result
    return [_engine_cache[_key(job)] for job in jobs]


def run_job(lines):
    return {'op': 'run', 'lines': list(lines)}


def match_job(setup, goal_lines, attempt_lines):
    return {'op': 'match', 'setup': list(setup), 'goal': list(goal_lines), 'attempt': list(attempt_lines)}


def engine_attempt(lines):
    return engine_jobs([run_job(lines)])[0]


def run_engine(lines):
    result = engine_attempt(lines)
    if not result['ok']:
        i = result['index']
        raise AssertionError(f'engine: line {i + 1} {lines[i]!r} failed: ' + ' / '.join(result['output']))
    return result['state']


def engine_matches(setup, goal_lines, attempt_lines):
    result = engine_jobs([match_job(setup, goal_lines, attempt_lines)])[0]
    if not result['ok']:
        raise AssertionError('engine: ' + result['error'])
    return result['matches']


def _env(tmp):
    config = os.path.join(tmp, 'gitconfig')
    open(config, 'w').close()
    return {
        'PATH': os.environ.get('PATH', ''),
        'HOME': tmp,
        'LC_ALL': 'C',
        'LANG': 'C',
        'GIT_CONFIG_GLOBAL': config,
        'GIT_CONFIG_SYSTEM': config,
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CEILING_DIRECTORIES': tmp,
        'GIT_AUTHOR_NAME': 'Player',
        'GIT_AUTHOR_EMAIL': 'player@example.com',
        'GIT_COMMITTER_NAME': 'Player',
        'GIT_COMMITTER_EMAIL': 'player@example.com',
        'GIT_AUTHOR_DATE': DATE,
        'GIT_COMMITTER_DATE': DATE,
        'GIT_EDITOR': 'true',
        'GIT_SEQUENCE_EDITOR': 'true',
        'GIT_PAGER': 'cat',
        'PAGER': 'cat',
        'GIT_TERMINAL_PROMPT': '0',
    }


class _Git:
    def __init__(self, tmp):
        self.repo = os.path.join(tmp, 'repo')
        os.mkdir(self.repo)
        templates = os.path.join(tmp, 'templates')
        os.mkdir(templates)
        self.env = _env(tmp)
        self.exe = _tool('git')
        self.files = 0
        self.auto = 0
        self.must('init', '-q', '-b', 'main', f'--template={templates}')
        top = self.must('rev-parse', '--show-toplevel').strip()
        if os.path.realpath(top) != os.path.realpath(self.repo):
            raise AssertionError(f'real git resolved its repository to {top}, not the temp dir {self.repo}')

    def call(self, *args):
        proc = subprocess.run([self.exe, *args], cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=TIMEOUT)
        return proc.returncode, (proc.stdout + proc.stderr).decode('utf-8', 'replace')

    def must(self, *args):
        code, out = self.call(*args)
        if code != 0:
            raise AssertionError(f'git {" ".join(args)} exited {code}: {out}')
        return out

    def add_file(self):
        self.files += 1
        name = f'f{self.files}'
        with open(os.path.join(self.repo, name), 'w') as f:
            f.write(name + '\n')
        self.must('add', '--', name)

    def commits(self):
        code, _ = self.call('rev-parse', '-q', '--verify', 'HEAD')
        refs = self.must('for-each-ref', '--format=%(objectname)', 'refs/heads', 'refs/tags').split()
        if code != 0 and not refs:
            return {}
        out = self.must('log', '--all', '--reflog', '-z', '--format=%H%x1f%P%x1f%s')
        commits = {}
        for entry in out.split('\0'):
            entry = entry.strip('\n')
            if not entry:
                continue
            hash_, parents, subject = entry.split('\x1f')
            commits[hash_] = {'hash': hash_, 'parents': parents.split(), 'message': subject}
        return commits

    def state(self):
        branches, tags = {}, {}
        for row in self.must('for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads', 'refs/tags').splitlines():
            ref, hash_ = row.rsplit(' ', 1)
            if ref.startswith('refs/heads/'):
                branches[ref[len('refs/heads/'):]] = hash_
            else:
                tags[ref[len('refs/tags/'):]] = hash_
        code, out = self.call('symbolic-ref', '-q', 'HEAD')
        if code == 0:
            head = {'type': 'branch', 'name': out.strip()[len('refs/heads/'):]}
        else:
            head = {'type': 'detached', 'hash': self.must('rev-parse', 'HEAD').strip()}
        return {'commits': self.commits(), 'branches': branches, 'tags': tags, 'head': head}

    def resolve(self, line):
        def one(match):
            found = [h for h, c in self.commits().items() if c['message'] == match.group(1)]
            if len(found) != 1:
                raise AssertionError(f'real git: {len(found)} commits have the message {match.group(1)!r}')
            return found[0]
        return TOKEN.sub(one, line)

    def run(self, line):
        argv = shlex.split(self.resolve(line))
        if len(argv) < 2 or argv[0] != 'git':
            raise AssertionError(f'not a git line: {line!r}')
        cmd, rest = argv[1], argv[2:]
        if cmd == 'help':
            return 0, ''
        if cmd == 'commit':
            amend = '--amend' in rest
            has_message = '-m' in rest
            self.add_file()
            extra = []
            if not has_message and amend:
                extra = ['--no-edit']
            elif not has_message:
                self.auto += 1
                extra = ['-m', AUTO_MESSAGE.format(n=self.auto)]
            return self.call('commit', '-q', *rest, *extra)
        if cmd in ('merge', 'revert'):
            return self.call(cmd, '--no-edit', *rest)
        if cmd == 'reset':
            code, out = self.call(cmd, *rest)
            if code == 0:
                self.must('reset', '-q', '--hard')
                self.must('clean', '-fdq')
            return code, out
        return self.call(cmd, *rest)


def git_attempt(lines):
    """Run lines in real git until one exits non-zero; results are cached.

    Returns {ok, state} or {ok: False, index, output, before, state}; `before`
    (the state just before the failing line) is read only when it is the last line.
    """
    key = tuple(lines)
    if key not in _git_cache:
        _git_cache[key] = _git_attempt(list(lines))
    return _git_cache[key]


def git_prefetch(line_lists):
    """Run many line lists in real git in parallel, so later git_attempt/run_git calls hit the cache."""
    todo = list(dict.fromkeys(tuple(lines) for lines in line_lists if tuple(lines) not in _git_cache))
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        for key, result in zip(todo, pool.map(_git_attempt, [list(k) for k in todo])):
            _git_cache[key] = result


def _git_attempt(lines):
    with tempfile.TemporaryDirectory(prefix='gitgraph-') as tmp:
        git = _Git(os.path.realpath(tmp))
        for i, line in enumerate(lines):
            before = git.state() if i == len(lines) - 1 else None
            code, out = git.run(line)
            if code != 0:
                return {'ok': False, 'index': i, 'output': out.splitlines(), 'before': before, 'state': git.state()}
        return {'ok': True, 'state': git.state()}


def run_git(lines):
    result = git_attempt(lines)
    if not result['ok']:
        i = result['index']
        raise AssertionError(f'real git: line {i + 1} {lines[i]!r} failed: ' + ' / '.join(result['output']))
    return result['state']


def canonical(state):
    """Branches, tags and HEAD, each mapped to the (subject, parents) tree of its commit. Hash-free."""
    commits = state['commits']
    memo = {}

    def node(hash_):
        if hash_ not in memo:
            commit = commits[hash_]
            memo[hash_] = (commit['message'].split('\n')[0], tuple(node(p) for p in commit['parents']))
        return memo[hash_]

    head = state['head']
    return {
        'branches': {name: node(h) for name, h in state['branches'].items()},
        'tags': {name: node(h) for name, h in state['tags'].items()},
        'head': ('branch', head['name']) if head['type'] == 'branch' else ('detached', node(head['hash'])),
    }
