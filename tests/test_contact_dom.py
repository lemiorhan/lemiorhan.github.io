"""The contact form, setupContactForm() in assets/site.js, run in Node on the hand-written DOM double
(tests/fake_dom.js) through tests/contact_dom_cli.js.

The page is the one the build writes: its ui-text island and its form. The status lines come from
content/contact.json. Web3Forms, hCaptcha and FormData are stubs in the driver; the real ones were
only ever exercised by hand in a browser.
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

ROOT =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, 'tests', 'contact_dom_cli.js')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
WEB3FORMS = 'https://api.web3forms.com/submit'

FORM = next(b for s in i18n.content('contact')['sections'] for b in s['blocks']
            if isinstance(b, dict) and b.get('type') == 'form')
SAY = FORM['status']
VISITOR = {'name': 'Ada Lovelace', 'email': 'ada@example.com', 'message': 'Would you speak at our meetup?'}
FIXED = {'access_key': FORM['access_key'], 'subject': FORM['subject'], 'from_name': FORM['from_name']}

BUILT = {}


class ContactPage(HTMLParser):
    """The ui-text island and <form class="contact-form"> of a built page as {tag, attrs, children}
    trees, text nodes as strings."""

    def __init__(self):
        super().__init__()
        self.trees, self.open = [], []

    def handle_starttag(self, tag, attrs):
        attrs = [[k, '' if v is None else v] for k, v in attrs]
        named = dict(attrs)
        if not self.open and not (named.get('id') == 'ui-text' or 'contact-form' in named.get('class', '').split()):
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
    page = ContactPage()
    with open(os.path.join(tmp.name, 'contact', 'index.html'), encoding='utf-8') as f:
        page.feed(f.read())
    page.close()
    if [t['tag'] for t in page.trees] != ['script', 'form']:
        raise AssertionError('the built contact page should give the ui-text island and then the form')
    BUILT['tree'] = page.trees
    BUILT['script'] = os.path.join(tmp.name, 'assets', 'site.js')


def tearDownModule():
    BUILT['tmp'].cleanup()


def run(*actions):
    path = shutil.which('node')
    if not path:
        raise AssertionError('node is not on PATH. The contact form tests need Node.js '
                             '(it ships on the ubuntu-latest CI runner); install node to run them.')
    request = {'tree': BUILT['tree'], 'script': BUILT['script'], 'actions': [list(a) for a in actions]}
    proc = subprocess.run([path, CLI], input=json.dumps(request).encode('utf-8'), capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise AssertionError('contact_dom_cli.js exited {}:\n{}'.format(proc.returncode, proc.stderr.decode('utf-8', 'replace')))
    results = json.loads(proc.stdout.decode('utf-8'))['results']
    return [r for r, a in zip(results, actions) if a[0] in ('look', 'submit', 'sent')]


def write(visitor=VISITOR):
    return [('fill', k, v) for k, v in visitor.items()]


EMPTY = {'name': '', 'email': '', 'message': ''}


class ContactForm(unittest.TestCase):
    def test_the_form_the_page_ships_hidden_shows_once_site_js_runs(self):
        look, = run(['look'])
        self.assertFalse(look['hidden'])
        self.assertEqual((look['status'], look['disabled'], look['resets']), ('', False, 0))
        self.assertEqual(look['values'], dict(FIXED, **EMPTY))

    def test_without_a_captcha_answer_it_asks_for_one_and_sends_nothing(self):
        submit, look, sent = run(*write(), ['submit'], ['settle'], ['look'], ['sent'])
        self.assertTrue(submit['prevented'])
        self.assertEqual(look['status'], SAY['captcha'])
        self.assertFalse(look['disabled'])
        self.assertEqual(look['values'], dict(FIXED, **VISITOR))
        self.assertEqual(sent, [])

    def test_a_send_posts_every_field_as_json_to_web3forms_then_clears_the_form_and_thanks(self):
        submit, look, sent = run(*write(), ['token', 'tok-1'], ['reply', 'json', {'success': True}],
                                 ['submit'], ['settle'], ['look'], ['sent'])
        self.assertTrue(submit['prevented'])
        self.assertEqual((submit['at_once']['status'], submit['at_once']['disabled']), (SAY['sending'], True))
        self.assertEqual(sent, [{'url': WEB3FORMS, 'method': 'POST',
                                 'headers': {'Content-Type': 'application/json', 'Accept': 'application/json'},
                                 'body': dict(FIXED, **VISITOR, **{'h-captcha-response': 'tok-1'})}])
        self.assertEqual((look['status'], look['disabled'], look['resets']), (SAY['sent'], False, 1))
        self.assertEqual({k: look['values'][k] for k in EMPTY}, EMPTY)
        self.assertEqual({k: look['values'][k] for k in FIXED}, FIXED)

    def test_every_send_of_a_session_goes_out_with_its_own_answer_and_spends_it(self):
        second = {'name': 'Grace Hopper', 'email': 'grace@example.com', 'message': 'And a podcast?'}
        _, first_look, _, second_look, sent = run(
            *write(), ['token', 'tok-1'], ['reply', 'json', {'success': True}], ['submit'], ['settle'], ['look'],
            *write(second), ['token', 'tok-2'], ['submit'], ['settle'], ['look'], ['sent'])
        self.assertEqual([s['body'] for s in sent],
                         [dict(FIXED, **VISITOR, **{'h-captcha-response': 'tok-1'}),
                          dict(FIXED, **second, **{'h-captcha-response': 'tok-2'})])
        self.assertEqual([(l['status'], l['resets']) for l in (first_look, second_look)], [(SAY['sent'], 1), (SAY['sent'], 2)])

    def test_anything_but_success_true_keeps_the_message_and_says_it_was_not_sent(self):
        replies = [('json', {'success': False, 'body': {'message': 'Invalid access key'}}),
                   ('json', {'success': 'true'}),
                   ('json', {'statusCode': 500, 'error': 'Something went wrong on server.'}),
                   ('not-json', None),
                   ('reject', None)]
        for kind, body in replies:
            with self.subTest(kind=kind, body=body):
                submit, look, sent = run(*write(), ['token', 'tok-1'], ['reply', kind, body],
                                         ['submit'], ['settle'], ['look'], ['sent'])
                self.assertEqual(len(sent), 1)
                self.assertEqual((look['status'], look['disabled'], look['resets']), (SAY['failed'], False, 1))
                self.assertEqual(look['values'], dict(FIXED, **VISITOR, **{'h-captcha-response': ''}))


if __name__ == '__main__':
    unittest.main()
