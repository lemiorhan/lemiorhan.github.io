"""The back-to-top link, setupToTop() in assets/site.js, run in Node on the hand-written DOM double
(tests/fake_dom.js) through tests/to_top_dom_cli.js.

The page is the talks page the build writes: its ui-text island and its back-to-top link. The window
is 800px tall, so a page scrolled past 800px is more than a screen away from the top.
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
CLI = os.path.join(ROOT, 'tests', 'to_top_dom_cli.js')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
SCREEN = 800

BUILT = {}


class ToTopPage(HTMLParser):
    """The ui-text island and <a class="to-top"> of a built page as {tag, attrs, children} trees, text nodes as strings."""

    def __init__(self):
        super().__init__()
        self.trees, self.open = [], []

    def handle_starttag(self, tag, attrs):
        attrs = [[k, '' if v is None else v] for k, v in attrs]
        named = dict(attrs)
        if not self.open and not (named.get('id') == 'ui-text' or 'to-top' in named.get('class', '').split()):
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
    page = ToTopPage()
    with open(os.path.join(tmp.name, 'talks', 'index.html'), encoding='utf-8') as f:
        page.feed(f.read())
    page.close()
    if [t['tag'] for t in page.trees] != ['script', 'a']:
        raise AssertionError('the built talks page should give the ui-text island and then the back-to-top link')
    BUILT['tree'] = page.trees
    BUILT['script'] = os.path.join(tmp.name, 'assets', 'site.js')


def tearDownModule():
    BUILT['tmp'].cleanup()


def shown(*steps, start=0, load_dock=None):
    """Whether the link shows once a page scrolled to start has loaded, then after each step. load_dock is a dock the
    game builds while the page loads, after site.js has run."""
    path = shutil.which('node')
    if not path:
        raise AssertionError('node is not on PATH. The back-to-top tests need Node.js '
                             '(it ships on the ubuntu-latest CI runner); install node to run them.')
    request = {'tree': BUILT['tree'], 'script': BUILT['script'], 'start': start, 'loadDock': load_dock, 'steps': list(steps)}
    proc = subprocess.run([path, CLI], input=json.dumps(request).encode('utf-8'), capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise AssertionError('to_top_dom_cli.js exited {}:\n{}'.format(proc.returncode, proc.stderr.decode('utf-8', 'replace')))
    return json.loads(proc.stdout.decode('utf-8'))['shown']


def at(y, dock=None, event='scroll'):
    return {'scrollY': y, 'dock': dock, 'event': event}


def dock(top, position='sticky'):
    return {'top': top, 'bottom': top + 120, 'position': position}


class BackToTop(unittest.TestCase):
    def test_it_shows_only_while_the_top_is_more_than_a_screen_away(self):
        self.assertEqual(shown(at(SCREEN), at(SCREEN + 1), at(5000), at(SCREEN), at(0)),
                         [False, False, True, True, False, False])

    def test_a_page_opened_far_down_shows_it_before_any_scroll(self):
        self.assertEqual(shown(start=2000), [True])

    def test_a_page_opened_on_the_pinned_dock_the_game_builds_while_loading_keeps_it_hidden_before_any_scroll(self):
        self.assertEqual(shown(start=2000, load_dock=dock(SCREEN - 120)), [False])
        self.assertEqual(shown(start=2000, load_dock=dock(-120)), [True])

    def test_it_steps_aside_while_the_pinned_git_game_dock_is_on_screen(self):
        self.assertEqual(shown(at(2000), at(2000, dock(SCREEN - 120)), at(2600, dock(-120)), at(1400, dock(SCREEN))),
                         [False, True, False, True, True])

    def test_a_dock_that_is_not_pinned_leaves_it_in_place(self):
        self.assertEqual(shown(at(2000, dock(SCREEN - 120, position='static'))), [False, True])

    def test_a_dock_pinned_after_a_resize_hides_it_without_a_scroll(self):
        self.assertEqual(shown(at(2000, dock(SCREEN - 120, position='static')),
                               at(2000, dock(SCREEN - 120), event='resize')),
                         [False, True, False])


if __name__ == '__main__':
    unittest.main()
