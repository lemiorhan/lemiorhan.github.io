"""The language swap of the built 404.html, run in Node through tests/not_found_swap_cli.js: GitHub Pages serves the
one file at any path it cannot find, so the path alone decides which language's text, title and lang the page shows."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

import i18n
from i18n import LANGS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'not_found_swap_cli.js')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


class Outline(HTMLParser):
    """In source order: each <template> and <script> with its attributes, the element it sits in and its text."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.lang, self.items, self.open = None, [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = {k: '' if v is None else v for k, v in attrs}
        if tag == 'html':
            self.lang = attrs.get('lang')
        if tag in ('template', 'script', 'title'):
            self.items.append({'tag': tag, 'attrs': attrs, 'in': [t for t in self.open], 'text': ''})
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag):
        while self.open and self.open.pop() != tag:
            pass

    def handle_data(self, data):
        if self.items and self.open and self.open[-1] in ('script', 'title') and self.items[-1]['tag'] == self.open[-1]:
            self.items[-1]['text'] += data


def setUpModule():
    global PAGE
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([sys.executable, os.path.join(ROOT, 'build.py'), '--out', tmp],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        with open(os.path.join(tmp, '404.html'), encoding='utf-8') as f:
            PAGE = Outline(f.read())


def items(tag, inside=None):
    return [i for i in PAGE.items if i['tag'] == tag and (inside is None or i['in'][-1:] == [inside])]


def swap_script():
    inline = [i for i in items('script', 'body') if not i['attrs']]
    if len(inline) != 1:
        raise AssertionError('the body has {} plain inline scripts, not the one swap'.format(len(inline)))
    return inline[0]


def swap(pathname):
    title, = items('title')
    page = {'script': swap_script()['text'], 'pathname': pathname, 'lang': PAGE.lang, 'title': title['text'],
            'templates': [{'lang': t['attrs']['data-lang'], 'title': t['attrs']['data-title']} for t in items('template', 'body')]}
    result = subprocess.run(['node', CLI], input=json.dumps(page), capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def shown(lang):
    return {'main': lang, 'lang': lang, 'title': i18n.content('404', lang)['title']}


class Swap(unittest.TestCase):
    def test_the_page_carries_a_template_for_each_language_but_the_roots_and_the_root_one_outside_them(self):
        self.assertEqual([t['attrs']['data-lang'] for t in items('template', 'body')], LANGS[1:])
        self.assertEqual(PAGE.lang, LANGS[0])
        self.assertGreater(len(LANGS), 1)

    def test_a_path_in_a_language_folder_shows_that_languages_text_title_and_lang(self):
        for lang in LANGS[1:]:
            for path in ('/{}/'.format(lang), '/{}/no/such/page/'.format(lang), '/{}'.format(lang)):
                with self.subTest(path=path):
                    self.assertEqual(swap(path), shown(lang))

    def test_any_other_path_keeps_the_root_languages_text_title_and_lang(self):
        for lang in LANGS[1:]:
            for path in ('/', '/no/such/page/', '/{}x/'.format(lang), '/talks/{}/'.format(lang), '/x{}/'.format(lang)):
                with self.subTest(path=path):
                    self.assertEqual(swap(path), shown(LANGS[0]))

    def test_the_swap_runs_after_every_template_is_parsed_and_before_any_script_that_reads_the_page(self):
        order = PAGE.items.index(swap_script())
        self.assertTrue(all(PAGE.items.index(t) < order for t in items('template')))
        loaded = [s['attrs'] for s in items('script') if s['attrs'].get('src')]
        self.assertIn('/assets/maze-game.js', [s['src'] for s in loaded])
        self.assertEqual([s['src'] for s in loaded if 'defer' not in s and s.get('type') != 'module'], [])


if __name__ == '__main__':
    unittest.main()
