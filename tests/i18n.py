"""Content as each language's page reads it, worked out here rather than by build.py, so a test that
compares a built page with its content does not take the build's own reading of the content as given."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_json(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as f:
        return json.load(f)


LANGS = [lg['code'] for lg in read_json(ROOT, 'content', 'site.json')['languages']]


def localized(value, lang):
    if isinstance(value, list):
        return [localized(v, lang) for v in value]
    if isinstance(value, dict):
        if set(value) == {'@' + code for code in LANGS}:
            return value['@' + lang]
        return {k: localized(v, lang) for k, v in value.items()}
    return value


def content(name, lang=LANGS[0], root=ROOT):
    return localized(read_json(root, 'content', name + '.json'), lang)


TURKISH = 'a b c ç d e f g ğ h ı i j k l m n o ö p q r s ş t u ü v w x y z'.split()


def alphabet_key(lang):
    """How a reader of the language orders labels, ignoring case; Turkish puts ç after c, ı before i, and so on."""
    if lang != 'tr':
        return str.lower
    def key(s):
        low = s.replace('I', 'ı').replace('İ', 'i').lower()
        return [TURKISH.index(c) if c in TURKISH else len(TURKISH) + ord(c) for c in low]
    return key


def lang_dir(lang):
    return '' if lang == LANGS[0] else lang + '/'


def page_file(name, lang=LANGS[0]):
    """404.html is one file for every language; GitHub Pages serves it at any path it cannot find."""
    if name == '404':
        return '404.html'
    return lang_dir(lang) + ('index.html' if name == 'home' else name + '/index.html')
