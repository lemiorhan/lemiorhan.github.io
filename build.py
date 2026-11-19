#!/usr/bin/env python3
"""Builds the site's HTML pages from the JSON files in content/.

    python3 build.py              writes every page in place, next to this file
    python3 build.py --out _site  writes a deployable copy of the site into _site/

Every content/<name>.json is one page: home.json is the home page, 404.json the
not-found page, and any other file is served at /<name>/. site.json holds what
every page shares and is not a page itself.
"""
import argparse
import html
import itertools
import json
import math
import os
import re
import shutil
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, 'content')
WORLD = os.path.join(ROOT, 'data', 'world.json')
LINK = re.compile(r'\[([^\]]+)\]\(([^)\s"]+)\)')
REF = re.compile(r'\[\^([1-9]\d*)\]')
HYPHENATED = re.compile(r'(?<![\w/.-])(\w+-\w+)(?![\w/.-])')

MAP_WIDTH = 1000
MAP_NORTH, MAP_SOUTH = 84, -57


def equal_earth(lon, lat):
    a1, a2, a3, a4 = 1.340264, -0.081106, 0.000893, 0.003796
    m = math.sqrt(3) / 2
    t = math.asin(m * math.sin(math.radians(lat)))
    t2 = t * t
    t6 = t2 * t2 * t2
    x = math.radians(lon) * math.cos(t) / (m * (a1 + 3 * a2 * t2 + t6 * (7 * a3 + 9 * a4 * t2)))
    y = t * (a1 + a2 * t2 + t6 * (a3 + a4 * t2))
    return x, y


MAP_SCALE = MAP_WIDTH / (2 * equal_earth(180, 0)[0])
MAP_TOP = equal_earth(0, MAP_NORTH)[1]


def project(lon, lat):
    """Map units of the talks map: x in [0, MAP_WIDTH], y grows southwards. tools/world_map.py uses it too."""
    x, y = equal_earth(lon, lat)
    return MAP_WIDTH / 2 + x * MAP_SCALE, (MAP_TOP - y) * MAP_SCALE


MAP_HEIGHT = project(0, MAP_SOUTH)[1]


class BuildError(Exception):
    pass


def load(name):
    path = os.path.join(CONTENT, name + '.json')
    with open(path, encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as err:
            raise BuildError('content/{}.json: {}'.format(name, err))


def attr(s):
    return html.escape(s, quote=True)


def text(s):
    return html.escape(s, quote=False)


def inline(s):
    s = LINK.sub(r'<a href="\2">\1</a>', text(s))
    return REF.sub(r'<sup class="ref"><a href="#ref-\1">[\1]</a></sup>', s)


def fill(template, **values):
    for key, value in values.items():
        template = template.replace('{' + key + '}', value)
    return template


def indent(lines, n):
    pad = ' ' * n
    return [pad + line if line else line for line in lines]


def cls(base, extra):
    return base + ' ' + extra if extra else base


class Page:
    def __init__(self, name, data, site):
        self.name = name
        self.data = data
        self.site = site
        self.path = '' if name == 'home' else name + '/'
        self.prefix = '../' * self.path.count('/')

    def month_year(self, date):
        year, month = date.split('-')[:2]
        return '{} {}'.format(self.site['months'][int(month) - 1], year)

    def day_month(self, date):
        _, month, day = date.split('-')
        return '{} {}'.format(int(day), self.site['months'][int(month) - 1])

    def fail(self, message):
        raise BuildError('content/{}.json: {}'.format(self.name, message))


# Blocks: a string is a paragraph; any other block is an object with a "type".

def block_p(b, page):
    c = ' class="{}"'.format(attr(b['class'])) if b.get('class') else ''
    return ['<p{}>{}</p>'.format(c, inline(b['text']))]


def block_h3(b, page):
    return ['<h3 class="sub">{}</h3>'.format(inline(b['text']))]


def block_quote(b, page):
    caption = inline(b['caption'])
    if b.get('original'):
        caption += ' <span lang="{}">{}</span>'.format(attr(b['original_lang']), text(b['original']))
    return ['<figure class="pull">',
            '  <blockquote>',
            '    <p>{}</p>'.format(inline(b['text'])),
            '  </blockquote>',
            '  <figcaption>{}</figcaption>'.format(caption),
            '</figure>']


def block_log(b, page):
    items = b['items']
    out = ['<ol class="log" aria-label="{}">'.format(attr(b['label']))]
    for i, item in enumerate(items):
        flags = (' data-head' if i == 0 else '') + (' data-root' if i == len(items) - 1 else '')
        out.append('  <li data-lane="{}"{}>'.format(1 if item.get('branch') else 0, flags))
        out.append('    <span class="node" aria-hidden="true"></span>')
        out.append('    <p class="when">{}</p>'.format(text(item['when'])))
        out.append('    <h3>{}</h3>'.format(inline(item['title'])))
        if item.get('org'):
            out.append('    <p class="org">{}</p>'.format(inline(item['org'])))
        if item.get('note'):
            out.append('    <p class="note">{}</p>'.format(inline(item['note'])))
        out.append('  </li>')
    out.append('</ol>')
    return out


def block_entries(b, page):
    out = ['<ol class="entries">']
    for item in b['items']:
        out.append('  <li>')
        if item.get('date'):
            out.append('    <time datetime="{}">{}</time>'.format(attr(item['date']), page.month_year(item['date'])))
        else:
            out.append('    <span class="kind">{}</span>'.format(text(item['kind'])))
        lang = ' lang="{}"'.format(attr(item['lang'])) if item.get('lang') else ''
        out.append('    <div>')
        out.append('      <a class="entry-title" href="{}"{}>{}</a>'.format(attr(item['url']), lang, text(item['title'])))
        if item.get('text'):
            out.append('      <p>{}</p>'.format(inline(item['text'])))
        out.append('    </div>')
        out.append('  </li>')
    out.append('</ol>')
    return out


def points(items):
    out = ['<ul class="plain">']
    for item in items:
        out.append('  <li><strong>{}</strong><span>{}</span></li>'.format(inline(item['title']), inline(item['text'])))
    out.append('</ul>')
    return out


def block_points(b, page):
    return points(b['items'])


def block_facts(b, page):
    out = ['<div class="facts">']
    for group in b['groups']:
        out.append('  <div>')
        out.append('    <h3 class="sub">{}</h3>'.format(inline(group['heading'])))
        out += indent(points(group['items']), 4)
        out.append('  </div>')
    out.append('</div>')
    return out


def block_items(b, page):
    out = []
    for item in b['items']:
        title = text(item['title'])
        if item.get('url'):
            title = '<a href="{}">{}</a>'.format(attr(item['url']), title)
        out.append('<article class="item">')
        out.append('  <h3>{}</h3>'.format(title))
        if item.get('meta'):
            out.append('  <p class="meta">{}</p>'.format(inline(item['meta'])))
        out.append('  <p>{}</p>'.format(inline(item['text'])))
        out.append('</article>')
    return out


def block_sources(b, page):
    ids = [' id="ref-{}"'.format(i) if b.get('cited') else '' for i in range(1, len(b['items']) + 1)]
    return ['<ol class="sources">'] + ['  <li{}>{}</li>'.format(i, inline(s)) for i, s in zip(ids, b['items'])] + ['</ol>']


def block_infobox(b, page):
    return (['<dl class="infobox">']
            + ['  <div><dt>{}</dt><dd>{}</dd></div>'.format(text(item['label']), inline(item['text'])) for item in b['items']]
            + ['</dl>'])


def block_contents(b, page):
    items = ['    <li><a href="#{}">{}</a></li>'.format(attr(sec['id']), text(sec['heading']))
             for sec in page.data['sections'] if sec.get('heading')]
    return ['<nav class="contents" aria-label="{}">'.format(attr(b['label'])), '  <ol>'] + items + ['  </ol>', '</nav>']


def block_toc(b, page):
    out = ['<ul class="toc">']
    for item in b['items']:
        out.append('  <li><a href="{}{}"><span class="toc-name">{}</span><span class="toc-desc">{}</span></a></li>'.format(
            page.prefix, attr(item['path']), text(item['name']), inline(item['text'])))
    out.append('</ul>')
    return out


def block_mail(b, page):
    return ['<p class="mail"><a class="mail-link" data-user="{u}" data-domain="{d}" href="#main">{u}'
            '<span aria-hidden="true">@</span><span class="sr-only">{at}</span>{d}</a></p>'.format(
                u=attr(b['user']), d=attr(b['domain']), at=text(b['at']))]


def block_stage_photo(b, page):
    img = page.prefix + 'assets/img/'
    return ['<picture class="stage">',
            '  <source media="(max-width: 640px)" srcset="{}stage-800.webp" type="image/webp">'.format(img),
            '  <source media="(max-width: 640px)" srcset="{}stage-800.jpg">'.format(img),
            '  <source srcset="{}stage.webp" type="image/webp">'.format(img),
            '  <img src="{}stage.jpg" width="1500" height="500" loading="lazy" alt="{}">'.format(img, attr(b['alt'])),
            '</picture>']


def block_bio(b, page):
    return ['<div class="bio">',
            '  <p id="bio-text">{}</p>'.format(text(b['text'])),
            '  <button class="copy" type="button" data-copy="bio-text" hidden>{}</button>'.format(text(b['copy'])),
            '</div>']


def block_stages(b, page):
    return (['<dl class="stages">']
            + ['  <div><dt>{}</dt><dd>{}</dd></div>'.format(text(item['year']), inline(item['text'])) for item in b['items']]
            + ['</dl>'])


def block_latest_talks(b, page):
    talks_page = Page('talks', load('talks'), page.site)
    every_talk = ((year, ev, t)
                  for year, events in archive_years(talks_page.data['archive'], talks_page)
                  for ev in events
                  for t in ev.get('talks', []))
    out = ['<ol class="entries">']
    for year, ev, t in itertools.islice(every_talk, b['count']):
        out.append('  <li>')
        if ev.get('date'):
            out.append('    <time datetime="{}">{}</time>'.format(attr(ev['date']), page.month_year(ev['date'])))
        else:
            out.append('    <time datetime="{0}">{0}</time>'.format(year))
        out.append('    <div>')
        title = t.get('title') or ev['name']
        lang = t.get('lang') if t.get('title') else ev.get('lang')
        lang = ' lang="{}"'.format(attr(lang)) if lang else ''
        link = t.get('slides') or next(iter(talk_videos(t, ev, talks_page)), None)
        if link:
            out.append('      <a class="entry-title" href="{}"{}>{}</a>'.format(attr(link), lang, text(title)))
        else:
            out.append('      <span class="entry-title"{}>{}</span>'.format(lang, text(title)))
        if t.get('title'):
            ev_lang = ' lang="{}"'.format(attr(ev['lang'])) if ev.get('lang') else ''
            out.append('      <p class="entry-meta"{}>{}</p>'.format(ev_lang, text(ev['name'])))
        if t.get('summary'):
            out.append('      <p>{}</p>'.format(inline(t['summary'])))
        out.append('    </div>')
        out.append('  </li>')
    out.append('</ol>')
    return out


BLOCKS = {
    'p': block_p,
    'h3': block_h3,
    'quote': block_quote,
    'log': block_log,
    'entries': block_entries,
    'points': block_points,
    'facts': block_facts,
    'items': block_items,
    'sources': block_sources,
    'infobox': block_infobox,
    'contents': block_contents,
    'toc': block_toc,
    'mail': block_mail,
    'stage-photo': block_stage_photo,
    'bio': block_bio,
    'stages': block_stages,
    'latest-talks': block_latest_talks,
}


def blocks(items, page):
    out = []
    for b in items:
        if isinstance(b, str):
            b = {'type': 'p', 'text': b}
        render = BLOCKS.get(b.get('type'))
        if not render:
            page.fail('unknown block type {!r}; known types: {}'.format(b.get('type'), ', '.join(sorted(BLOCKS))))
        try:
            out += render(b, page)
        except KeyError as err:
            page.fail('a {!r} block is missing {}'.format(b['type'], err))
    return out


# Page parts

def section(sec, page):
    body = blocks(sec['blocks'], page)
    if 'heading' not in sec:
        return (['<section class="{}">'.format(cls('page-body', sec.get('class'))), '  <div class="wrap">']
                + indent(body, 4) + ['  </div>', '</section>'])
    sid = attr(sec['id'])
    head = ['    <div class="section-head">', '      <h2 id="{}-title">{}</h2>'.format(sid, text(sec['heading']))]
    if sec.get('cmd'):
        head.append('      <p class="cmd" aria-hidden="true">{}</p>'.format(text(sec['cmd'])))
    head.append('    </div>')
    return (['<section class="section" id="{0}" aria-labelledby="{0}-title">'.format(sid),
             '  <div class="wrap section-grid">']
            + head + ['    <div class="{}">'.format(cls('section-body', sec.get('class')))]
            + indent(body, 6) + ['    </div>', '  </div>', '</section>'])


def page_head(head, archive, page):
    out = ['<section class="page-head" aria-labelledby="page-title">',
           '  <div class="wrap">',
           '    <h1 id="page-title" class="page-title">{}</h1>'.format(text(head['heading']))]
    if head.get('cmd'):
        out.append('    <p class="cmd" aria-hidden="true">{}</p>'.format(text(head['cmd'])))
    out += indent(blocks(head.get('blocks', []), page), 4)
    if archive and archive.get('map'):
        out += [''] + indent(talk_map(archive, page), 4)
    if archive and archive.get('themes'):
        out += [''] + indent(theme_cloud(archive, page), 4)
    if archive:
        out += indent(archive_controls(archive, page), 4)
    out += ['  </div>', '</section>']
    return out


YEAR = re.compile(r'\b(\d{4})\b')


def first_year(s):
    m = YEAR.search(s or '')
    return m.group(1) if m else None


def blocks_in(data, kind):
    return [b for sec in data.get('sections', []) for b in sec.get('blocks', [])
            if isinstance(b, dict) and b.get('type') == kind]


def career_path(page):
    """content/career.json's log as git history, newest first: one commit per stretch at one org."""
    logs = blocks_in(load('career'), 'log')
    if not logs:
        page.fail('the hero draws the "log" block of content/career.json, and that file has none')
    rows = []
    for item in logs[0]['items']:
        org, year = LINK.sub(r'\1', item.get('org', '')), first_year(item.get('when'))
        if not org or not year:
            page.fail('the hero needs an org and a year in "when" for every item of the career log; {!r} lacks one'.format(
                item.get('title')))
        branch = bool(item.get('branch'))
        if rows and (rows[-1]['org'], rows[-1]['branch']) == (org, branch):
            rows[-1]['year'] = year
        else:
            rows.append({'year': year, 'org': org, 'branch': branch})
    return rows


def photo_event(photo, page):
    events = [ev for evs in load('talks')['archive']['events'].values() for ev in evs
              if any(t.get('title') == photo['talk'] for t in ev.get('talks', []))]
    if len(events) != 1:
        page.fail('hero.photo.talk {!r} must name a talk given at exactly one event in content/talks.json; it was given at {}'.format(
            photo['talk'], ', '.join(repr(ev['name']) for ev in events) or 'none'))
    return events[0]


def hero_facts(h, path, page):
    facts = {'since': path[-1]['year'], 'event': photo_event(h['photo'], page)['name']}
    if h.get('community'):
        items = [i for b in blocks_in(load('community'), 'items') for i in b['items'] if i.get('title') == h['community']]
        founded = first_year(items[0].get('meta')) if items else None
        if not founded:
            page.fail('hero.community {!r} needs an item of that title in content/community.json with a year in "meta"'.format(
                h['community']))
        facts['founded'] = founded
    return facts


def hero_fill(field, template, facts, page):
    out = fill(template, **facts)
    unknown = re.search(r'\{(\w+)\}', out)
    if unknown:
        page.fail('hero.{} asks for {{{}}}, which build.py does not compute; it computes {}'.format(
            field, unknown.group(1), ', '.join('{' + k + '}' for k in sorted(facts))))
    return out


HERO_ROW = 20
HERO_MAIN_X, HERO_SIDE_X, HERO_LANES_W = 24, 6, 30

HERO_PHOTO = 'lemi-stage'
HERO_PHOTO_WIDTHS = (640, 960, 1440)
HERO_PHOTO_HEIGHT = 5 / 4
# Mirrors the width of .hero-head in site.css; a test pins the two-column entries.
HERO_PHOTO_SIZES = '(min-width: 89rem) 32rem, (min-width: 56rem) 36vw, (min-width: 34rem) 30rem, calc(100vw - 2rem)'


def num(x):
    return '{:g}'.format(round(x, 2))


def hero_path(path, h):
    """The SVG draws in units of HERO_ROW per row; site.css sizes it from --row and --rows, so the two must agree."""
    n = len(path)
    ys = [(i + 1) * HERO_ROW for i in range(n)]
    bottom = max(ys[i] for i, r in enumerate(path) if not r['branch'])

    def t(y):
        return num(min(1, max(0, (bottom - y) / bottom)))

    lanes = ['<path class="lane-main" d="M{} {}V0" pathLength="1"/>'.format(HERO_MAIN_X, bottom)]
    i = 0
    while i < n:
        if not path[i]['branch']:
            i += 1
            continue
        first = i
        while i + 1 < n and path[i + 1]['branch']:
            i += 1
        last, i = i, i + 1
        if first == 0 or last == n - 1:
            continue
        yc, yp, o = ys[first - 1], ys[last + 1], HERO_ROW / 3
        m, s = HERO_MAIN_X, HERO_SIDE_X
        d = 'M{m} {a}C{m} {b} {s} {b} {s} {c}L{s} {e}C{s} {f} {m} {f} {m} {g}'.format(
            m=m, s=s, a=num(yp), b=num(yp - o), c=num(yp - 2 * o), e=num(yc + 2 * o), f=num(yc + o), g=num(yc))
        lanes.append('<path class="lane-side" d="{}" pathLength="1" style="--t:{};--len:{}"/>'.format(
            d, t(yp), num(float(t(yc)) - float(t(yp)))))
    out = ['<div class="hero-path" style="--rows:{}">'.format(n),
           '  <svg class="hero-lanes" viewBox="0 0 {} {}" aria-hidden="true" focusable="false">'.format(
               HERO_LANES_W, num((n + 0.5) * HERO_ROW))]
    out += ['    ' + p for p in lanes]
    out += ['  </svg>', '  <ol aria-label="{}">'.format(attr(h['path_label']))]
    for row, y in zip(path, ys):
        out.append('    <li{} style="--t:{}"><span class="hero-dot" aria-hidden="true"></span>'
                   '<time datetime="{y}">{y}</time> <span class="hero-org">{}</span></li>'.format(
                       ' class="side"' if row['branch'] else '', t(y), text(row['org']), y=row['year']))
    out += ['  </ol>', '</div>']
    return out


def hero_photo(h, facts, page):
    photo = h['photo']
    stem = page.prefix + 'assets/img/' + HERO_PHOTO

    def srcset(ext):
        return ', '.join('{}-{}.{} {}w'.format(stem, w, ext, w) for w in HERO_PHOTO_WIDTHS)

    w = HERO_PHOTO_WIDTHS[1]
    return ['<figure class="hero-head">',
            '  <picture class="hero-photo">',
            '    <source type="image/webp" srcset="{}" sizes="{}">'.format(srcset('webp'), HERO_PHOTO_SIZES),
            '    <img src="{}-{}.jpg" srcset="{}" sizes="{}" width="{}" height="{}" fetchpriority="high" alt="{}">'.format(
                stem, w, srcset('jpg'), HERO_PHOTO_SIZES, w, round(w * HERO_PHOTO_HEIGHT),
                attr(hero_fill('photo.alt', photo['alt'], facts, page))),
            '  </picture>',
            '  <p class="hero-ref" aria-hidden="true">{}</p>'.format(text(h['head'])),
            '  <figcaption class="hero-caption">{}</figcaption>'.format(text(hero_fill('photo.caption', photo['caption'], facts, page))),
            '</figure>']


def nobr(s):
    return HYPHENATED.sub(r'<span class="nobr">\1</span>', s)


def hero(h, page):
    parts = LINK.split(text(h['role']))
    role = nobr(parts[0]) + ''.join('<a href="{}">{}</a>{}'.format(url, nobr(label), nobr(after))
                                    for label, url, after in zip(parts[1::3], parts[2::3], parts[3::3]))
    path = career_path(page)
    facts = hero_facts(h, path, page)
    intro = hero_fill('text', h['text'], facts, page)
    actions = ' '.join('<a class="{}" href="{}">{}</a>'.format('hero-play' if i == 0 else 'hero-more', attr(a['url']), text(a['label']))
                       for i, a in enumerate(h.get('actions', [])))
    out = ['<section class="hero" id="top" aria-labelledby="name">',
           '  <div class="wrap hero-grid">',
           '    <div class="hero-main">',
           '      <h1 id="name" class="hero-name">{}</h1>'.format(' '.join('<span>{}</span>'.format(text(n)) for n in h['name'])),
           '      <div class="hero-text">',
           '        <p class="hero-role">{}</p>'.format(role),
           '        <p class="hero-intro">{}</p>'.format(inline(intro))]
    if actions:
        out.append('        <p class="hero-actions">{}</p>'.format(actions))
    out += ['        <ul class="profiles" aria-label="{}">'.format(attr(h['profiles_label']))]
    out += ['          <li><a href="{}">{}</a></li>'.format(attr(p['url']), text(p['label'])) for p in h['profiles']]
    out += ['        </ul>', '      </div>', '    </div>', '    <div class="hero-side">']
    out += indent(hero_photo(h, facts, page), 6)
    out += indent(hero_path(path, h), 6)
    out += ['    </div>', '  </div>', '</section>']
    return out


# The git game

LEVEL_KEYS = ('id', 'title', 'teaches', 'story', 'task', 'setup', 'solution', 'hint', 'fact', 'checks')
CHECK_KEYS = ('alternatives', 'near_misses')


def game_levels(g, page):
    """Validates game.levels and returns them as the page's data island carries them: no "checks", plus "par"."""
    if not g.get('levels'):
        page.fail('game.levels must list at least one level')
    seen, out = set(), []
    for n, lv in enumerate(g['levels'], 1):
        name = repr(lv['id']) if lv.get('id') else '#{}'.format(n)

        def bad(message):
            page.fail('game level {} {}'.format(name, message))

        for key in LEVEL_KEYS:
            if key not in lv:
                bad('needs "{}"'.format(key))
        if not isinstance(lv['id'], str) or not lv['id'].strip():
            bad('needs "id" as a non-empty string')
        for key, kind, word in (('setup', list, 'a list'), ('solution', list, 'a list'),
                                ('fact', dict, 'an object'), ('checks', dict, 'an object')):
            if not isinstance(lv[key], kind):
                bad('needs "{}" as {}'.format(key, word))
        teaches = lv['teaches']
        if not isinstance(teaches, list) or not teaches or not all(isinstance(t, str) and t.strip() for t in teaches):
            bad('needs "teaches" as a non-empty list of non-empty strings')
        for key in ('text', 'link'):
            value = lv['fact'].get(key)
            if not isinstance(value, str) or not value.strip():
                bad('needs "fact.{}" as a non-empty string'.format(key))
        for key in CHECK_KEYS:
            if key not in lv['checks']:
                bad('needs "checks.{}"'.format(key))
            if not lv['checks'][key]:
                bad('has an empty "checks.{}"; give at least one list of command lines'.format(key))
            if not all(isinstance(seq, list) for seq in lv['checks'][key]):
                bad('lists "checks.{}" entries that are not lists of command lines'.format(key))
        if lv['id'] in seen:
            page.fail('two game levels have the id {!r}; level ids must be unique'.format(lv['id']))
        seen.add(lv['id'])
        if not lv['solution']:
            bad('has an empty "solution"; give at least one command line')
        lines = ([('setup', line) for line in lv['setup']] + [('solution', line) for line in lv['solution']]
                 + [('checks.' + key, line) for key in CHECK_KEYS for seq in lv['checks'][key] for line in seq])
        for field, line in lines:
            if not isinstance(line, str) or not line.startswith('git '):
                bad('has a "{}" line that does not start with "git ": {!r}'.format(field, line))
        level = {k: v for k, v in lv.items() if k != 'checks'}
        level['par'] = len(lv['solution'])
        out.append(level)
    return out


def game(g, page):
    levels = game_levels(g, page)
    island = json.dumps({'ui': g['ui'], 'levels': levels}, ensure_ascii=False).replace('<', '\\u003c')
    talk = g['talk']
    cited = '<a href="{}">{}</a>'.format(attr(talk['url']), text(talk['title']))
    out = ['<section class="game" id="play" aria-labelledby="play-title">',
           '  <div class="wrap">',
           '    <div class="game-head">',
           '      <h2 id="play-title">{}</h2>'.format(text(g['heading']))]
    if g.get('cmd'):
        out.append('      <p class="cmd" aria-hidden="true">{}</p>'.format(text(g['cmd'])))
    out += ['      <p class="game-intro">{}</p>'.format(fill(inline(g['intro']), talk=cited)),
            '    </div>',
            '    <div class="gg" data-git-game>',
            '      <div class="gg-fallback">',
            '        <p>{}</p>'.format(inline(g['fallback'])),
            '        <ol>']
    out += ['          <li><strong>{}</strong> {}</li>'.format(text(lv['title']), text(lv['task'])) for lv in levels]
    out += ['        </ol>',
            '        <p><a href="{}">{}</a></p>'.format(attr(talk['url']), text(g['slides'])),
            '      </div>',
            '    </div>',
            '    <script type="application/json" id="git-game-data">{}</script>'.format(island),
            '  </div>',
            '</section>']
    return out


# Talks archive

def archive_years(archive, page):
    years = sorted(archive['events'].items(), key=lambda kv: kv[0], reverse=True)
    for year, events in years:
        for ev in events:
            if ev.get('date') and not ev['date'].startswith(year + '-'):
                page.fail('event {!r} is dated {} but listed under {}'.format(ev['name'], ev['date'], year))
    return years


_world = None


def world():
    global _world
    if _world is None:
        with open(WORLD, encoding='utf-8') as f:
            _world = json.load(f)
    return _world


def flag(code, page):
    name = code.lower() + '.svg'
    if not os.path.isfile(os.path.join(ROOT, 'assets', 'flags', name)):
        page.fail('no flag for country {}: add assets/flags/{}'.format(code, name))
    return '<img class="flag" src="{}assets/flags/{}" width="20" height="15" alt="">'.format(page.prefix, name)


def place_of(ev, archive, page):
    key = ev.get('place')
    if not key:
        return None
    if key == 'online':
        if not archive.get('online'):
            page.fail('event {!r} is online, but archive.online gives no label for that'.format(ev['name']))
        return {'country': 'online', 'region': None, 'label': archive['online'], 'flag': ''}
    p = archive.get('places', {}).get(key)
    if not p:
        page.fail('event {!r} is at place {!r}, which archive.places does not define'.format(ev['name'], key))
    code = p.get('country')
    if not code:
        page.fail('place {!r} needs "country"'.format(key))
    if code not in archive.get('countries', {}):
        page.fail('place {!r} is in country {}, which archive.countries does not name'.format(key, code))
    if code not in world()['countries']:
        page.fail('data/world.json has no outline for country {}; see tools/world_map.py'.format(code))
    country = archive['countries'][code]
    if code == 'TR':
        province = world()['provinces'].get(p.get('province'))
        if not province:
            page.fail('place {!r} needs "province", a TR-nn code from data/world.json'.format(key))
        region, region_name, point = p['province'], province['name'], None
    else:
        if 'lat' not in p or 'lon' not in p:
            page.fail('place {!r} needs "lat" and "lon" to be drawn on the map'.format(key))
        if not p.get('city'):
            page.fail('place {!r} needs "city"'.format(key))
        region, region_name, point = key, p['city'], project(p['lon'], p['lat'])
    parts = [p.get('city'), region_name, country]
    label = ', '.join(part for i, part in enumerate(parts) if part and part not in parts[:i])
    return {'country': code, 'country_name': country, 'region': region, 'region_name': region_name,
            'point': point, 'label': label, 'flag': flag(code, page)}


MAP_LEVELS = (3, 10)
MAP_ASPECT = 2
MAP_PADDING = 1.2
MAP_DOT = 0.006


def level(n):
    return 1 + sum(n >= t for t in MAP_LEVELS)


def path_box(d):
    xs, ys, x, y = [], [], 0, 0
    for cmd, a, b in re.findall(r'([Ml])(-?\d+),(-?\d+)', d):
        x, y = (int(a), int(b)) if cmd == 'M' else (x + int(a), y + int(b))
        xs.append(x)
        ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def home_view(boxes):
    """The map opens framed on the places talked in, not on the whole world, which would leave them a few pixels wide."""
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    w, h = (x1 - x0) * MAP_PADDING, (y1 - y0) * MAP_PADDING
    w, h = max(w, h * MAP_ASPECT), max(h, w / MAP_ASPECT)
    return [round((x0 + x1 - w) / 2), round((y0 + y1 - h) / 2), round(w), round(h)]


def overlaps(box, view):
    x, y, w, h = view
    return box[0] <= x + w and box[2] >= x and box[1] <= y + h and box[3] >= y


def events_text(n, archive):
    return fill(archive['ui']['event_one' if n == 1 else 'event_many'], n=str(n))


def talk_map(archive, page):
    m = archive['map']
    total = 0
    countries, regions = {}, {}
    for _, events in archive_years(archive, page):
        for ev in events:
            total += 1
            p = place_of(ev, archive, page)
            if not p:
                continue
            c = countries.setdefault(p['country'], {'n': 0, 'name': p.get('country_name', p['label']), 'flag': p['flag']})
            c['n'] += 1
            if p['region']:
                r = regions.setdefault(p['region'], dict(p, n=0))
                r['n'] += 1
    by_count = sorted((k for k in countries if k != 'online'), key=lambda k: (-countries[k]['n'], countries[k]['name']))
    w = world()

    def path(d, cls, attrs='', title=''):
        t = '<title>{}</title>'.format(text(title)) if title else ''
        return '<path class="{}"{} d="{}">{}</path>'.format(cls, attrs, d, t)

    def tip(name, n):
        return '{}: {}'.format(name, events_text(n, archive))

    boxes = [path_box(w['countries'][k]) for k in by_count]
    points = [(round(r['point'][0] * 10), round(r['point'][1] * 10)) for r in regions.values() if r['point']]
    boxes += [(x, y, x, y) for x, y in points]
    if not boxes:
        page.fail('the talks map needs at least one event at a place on the map, not only online')
    home = home_view(boxes)
    land = ''.join(d for code, d in w['countries'].items() if code not in countries and overlaps(path_box(d), home))
    svg = ['<svg class="tmap-svg" viewBox="{}" role="img" aria-labelledby="tmap-desc" focusable="false">'.format(
               ' '.join(str(n) for n in home)),
           '  <desc id="tmap-desc">{}</desc>'.format(text(fill(m['desc'], countries=', '.join(countries[k]['name'] for k in by_count)))),
           '  ' + path(land, 'land'),
           '  <g class="tmap-countries">']
    svg += ['    ' + path(w['countries'][k], 'lv{}'.format(level(countries[k]['n'])), ' data-country="{}"'.format(k),
                          tip(countries[k]['name'], countries[k]['n'])) for k in by_count]
    svg.append('  </g>')
    if 'TR' in countries:
        quiet = ''.join(p['d'] for code, p in w['provinces'].items() if code not in regions)
        svg += ['  <g class="tmap-provinces" data-for="TR">', '    ' + path(quiet, 'land', ' data-country="TR"')]
        svg += ['    ' + path(w['provinces'][code]['d'], 'lv{}'.format(level(r['n'])),
                              ' data-country="TR" data-region="{}"'.format(code), tip(r['region_name'], r['n']))
                for code, r in sorted(regions.items()) if r['country'] == 'TR']
        svg.append('  </g>')
    svg.append('  <g class="tmap-cities">')
    for key, r in sorted(regions.items()):
        if r['point']:
            x, y = r['point']
            svg.append('    <circle data-country="{}" data-region="{}" cx="{}" cy="{}" r="{}"><title>{}</title></circle>'.format(
                r['country'], attr(key), round(x * 10), round(y * 10), round(home[2] * MAP_DOT, 1),
                text(tip(r['region_name'], r['n']))))
    svg += ['  </g>', '</svg>']

    def chip(label, n, attrs, pressed=False, icon='', full=None):
        return '<button type="button"{} data-label="{}" aria-pressed="{}">{}{} <span class="n">{}</span></button>'.format(
            attrs, attr(full or label), 'true' if pressed else 'false', icon, text(label), n)

    chips = [chip(m['everywhere'], total, ' data-country=""', pressed=True)]
    chips += [chip(countries[k]['name'], countries[k]['n'], ' data-country="{}"'.format(k), icon=countries[k]['flag'])
              for k in by_count]
    if 'online' in countries:
        chips.append(chip(archive['online'], countries['online']['n'], ' data-country="online"'))
    out = ['<section class="tmap" aria-labelledby="tmap-title">',
           '  <h2 class="sub" id="tmap-title">{}</h2>'.format(text(m['heading'])),
           '  <div class="tmap-frame">']
    out += indent(svg, 4)
    out += ['    <button class="tmap-back" type="button" hidden>{}</button>'.format(text(m['back'])), '  </div>',
            '  <div class="tmap-controls" hidden>',
            '    <div class="chips" role="group" aria-label="{}">'.format(attr(m['countries_label']))]
    out += indent(chips, 6)
    out.append('    </div>')
    for k in by_count:
        mine = sorted(((code, r) for code, r in regions.items() if r['country'] == k), key=lambda cr: (-cr[1]['n'], cr[1]['region_name']))
        if len(mine) < 2:
            continue
        out.append('    <div class="chips chips-sub" role="group" aria-label="{}" data-for="{}" hidden>'.format(
            attr(fill(m['regions_label'], country=countries[k]['name'])), k))
        out += indent([chip(r['region_name'], r['n'], ' data-country="{}" data-region="{}"'.format(k, attr(code)),
                            full='{}, {}'.format(r['region_name'], countries[k]['name']))
                       for code, r in mine], 6)
        out.append('    </div>')
    out += ['    <p class="tmap-status"></p>', '  </div>', '</section>']
    return out


THEME_KEY = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')


def talk_themes(t, ev, archive, page):
    items = archive.get('themes', {}).get('items', {})
    keys = t.get('themes', [])
    name = t.get('title') or next(iter(talk_videos(t, ev, page)), None) or t.get('slides')
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        page.fail('themes of a talk at {!r} must be a list of theme keys'.format(ev['name']))
    if not keys:
        page.fail('talk {!r} at {!r} needs "themes", one or more keys of archive.themes.items'.format(name, ev['name']))
    for k in keys:
        if k not in items:
            page.fail('talk {!r} at {!r} is about {!r}, which archive.themes.items does not define'.format(name, ev['name'], k))
    if len(set(keys)) != len(keys):
        page.fail('talk {!r} at {!r} lists a theme twice'.format(name, ev['name']))
    return keys


def talk_videos(t, ev, page):
    urls = t.get('video', [])
    urls = [urls] if isinstance(urls, str) else urls
    if not isinstance(urls, list) or not all(isinstance(u, str) and u for u in urls):
        page.fail('video of a talk at {!r} must be a URL or a list of URLs'.format(ev['name']))
    return urls


def theme_cloud(archive, page):
    th = archive['themes']
    items = th.get('items') or {}
    for key in items:
        if not THEME_KEY.match(key):
            page.fail('theme key {!r} must be lowercase words joined by hyphens'.format(key))
    count = Counter()
    total = 0
    for _, events in archive_years(archive, page):
        total += len(events)
        for ev in events:
            count.update({k for t in ev.get('talks', []) for k in talk_themes(t, ev, archive, page)})
    unused = sorted(k for k in items if not count[k])
    if unused:
        page.fail('archive.themes.items defines {}, but no talk is about it'.format(', '.join(unused)))
    # site.js treats an empty data-theme as "no theme chosen", so this chip clears the choice.
    buttons = ['<button type="button" data-theme="" aria-pressed="true">{} <span class="n">{}</span></button>'.format(
        text(th['all']), total)]
    buttons += ['<button type="button" data-theme="{}" data-label="{}" aria-pressed="false">{} <span class="n">{}</span></button>'.format(
                    attr(k), attr(items[k]), text(items[k]), count[k])
                for k in sorted(items, key=lambda k: items[k].lower())]
    return (['<section class="themes" aria-labelledby="themes-title" hidden>',
             '  <h2 class="sub" id="themes-title">{}</h2>'.format(text(th['heading'])),
             '  <div class="chips cloud" role="group" aria-label="{}">'.format(attr(th['label']))]
            + indent(buttons, 4) + ['  </div>', '</section>'])


def archive_controls(archive, page):
    strip =['<li><a href="#y{0}" aria-label="{0}"><span class="bar"></span>'
             '<span class="yr" aria-hidden="true"><span class="yr-c">{1}</span>{2}</span></a></li>'.format(y, y[:2], y[2:])
             for y, _ in reversed(archive_years(archive, page))]
    f = archive['filters']
    return (['', '<nav class="years-nav" aria-label="{}">'.format(attr(archive['years_label'])), '  <ol class="years">']
            + indent(strip, 4) + ['  </ol>', '</nav>', '',
                                  '<div class="filters" role="group" aria-label="{}" hidden>'.format(attr(archive['filters_label'])),
                                  '  <button type="button" data-filter="all" aria-pressed="true">{}</button>'.format(text(f['all'])),
                                  '  <button type="button" data-filter="video" aria-pressed="false">{}</button>'.format(text(f['video'])),
                                  '  <button type="button" data-filter="slides" aria-pressed="false">{}</button>'.format(text(f['slides'])),
                                  '</div>',
                                  '<p class="filter-status sr-only" aria-live="polite"></p>'])


def event(ev, archive, page):
    talks = ev.get('talks', [])
    themes = [talk_themes(t, ev, archive, page) for t in talks]
    flags = (' data-slides' if any(t.get('slides') for t in talks) else '') + \
            (' data-video' if any(t.get('video') for t in talks) else '')
    union = sorted({k for keys in themes for k in keys})
    if union:
        flags += ' data-themes="{}"'.format(attr(' '.join(union)))
    place = place_of(ev, archive, page)
    if place:
        flags += ' data-country="{}"'.format(place['country'])
        if place['region']:
            flags += ' data-region="{}"'.format(attr(place['region']))
    out = ['<li class="ev"{}>'.format(flags)]
    if ev.get('date'):
        out.append('  <time class="ev-when" datetime="{}">{}</time>'.format(attr(ev['date']), page.day_month(ev['date'])))
    else:
        out.append('  <span class="ev-when"></span>')
    out.append('  <div class="ev-body">')
    name = text(ev['name'])
    if ev.get('url'):
        name = '<a href="{}">{}</a>'.format(attr(ev['url']), name)
    lang = ' lang="{}"'.format(attr(ev['lang'])) if ev.get('lang') else ''
    out.append('    <h3 class="ev-name"{}>{}</h3>'.format(lang, name))
    meta = []
    if place:
        meta.append('<span class="ev-place">{}{}</span>'.format(place['flag'], text(place['label'])))
    if ev.get('role'):
        meta.append(text(ev['role']))
    if meta:
        out.append('    <p class="ev-meta">{}</p>'.format(' · '.join(meta)))
    if talks:
        out.append('    <ul class="ev-talks">')
        for t, keys in zip(talks, themes):
            about = text(t.get('title') or ev['name'])
            links = []
            if t.get('slides'):
                links.append('<a href="{}">{}<span class="sr-only">{}</span></a>'.format(
                    attr(t['slides']), text(archive['slides']), fill(text(archive['slides_hidden']), title=about)))
            videos = talk_videos(t, ev, page)
            for n, url in enumerate(videos, 1):
                label = archive['video'] if len(videos) == 1 else fill(archive['video_n'], n=str(n))
                links.append('<a href="{}">{}<span class="sr-only">{}</span></a>'.format(
                    attr(url), text(label), fill(text(archive['video_hidden']), title=about)))
            parts = []
            if t.get('title'):
                tlang = ' lang="{}"'.format(attr(t['lang'])) if t.get('lang') else ''
                parts.append('<span class="ev-title"{}>{}</span>'.format(tlang, text(t['title'])))
            if links:
                parts.append('<span class="ev-links">' + ' '.join(links) + '</span>')
            if keys:
                items = archive['themes']['items']
                parts.append('<span class="ev-themes" hidden>' + ' '.join(
                    '<button type="button" data-theme="{}" aria-pressed="false" aria-label="{}">{}</button>'.format(
                        attr(k), attr(fill(archive['themes']['tag_label'], theme=items[k])), text(items[k]))
                    for k in keys) + '</span>')
            if t.get('summary'):
                parts.append('<span class="ev-summary">{}</span>'.format(inline(t['summary'])))
            li = '<li data-themes="{}">'.format(attr(' '.join(keys))) if keys else '<li>'
            out.append('      ' + li + ' '.join(parts) + '</li>')
        out.append('    </ul>')
    if ev.get('photo'):
        out += indent(event_photo(ev, page), 4)
    out += ['  </div>', '</li>']
    return out


def event_photo(ev, page):
    photo = ev['photo']
    if not photo.get('file') or not photo.get('alt'):
        page.fail('photo of {!r} needs both "file" and "alt"'.format(ev['name']))
    name = photo['file']
    for suffix in ('', '-640'):
        if not os.path.isfile(os.path.join(ROOT, 'assets', 'talks', name + suffix + '.jpg')):
            page.fail('photo of {!r}: assets/talks/{}{}.jpg does not exist'.format(ev['name'], name, suffix))
    src = page.prefix + 'assets/talks/' + attr(name)
    lang = ' data-caption-lang="{}"'.format(attr(ev['lang'])) if ev.get('lang') else ''
    return ['<a class="ev-photo" href="{}.jpg" data-lightbox data-caption="{}"{}>'.format(src, attr(ev['name']), lang),
            '  <img src="{}-640.jpg" width="640" height="427" loading="lazy" alt="{}">'.format(src, attr(photo['alt'])),
            '</a>']


def archive_sections(archive, page):
    parts = []
    for year, events in archive_years(archive, page):
        rows = []
        for ev in events:
            rows += event(ev, archive, page)
        parts.append(['<section class="year" id="y{0}" aria-labelledby="h{0}">'.format(year),
                      '  <div class="wrap section-grid">',
                      '    <div class="section-head">',
                      '      <h2 id="h{0}">{0}</h2>'.format(year),
                      '    </div>',
                      '    <ol class="evs">']
                     + indent(rows, 6) + ['    </ol>', '  </div>', '</section>'])
    parts.append(['<p class="wrap empty-note" hidden>{}</p>'.format(text(archive['empty']))])
    return parts


# Documents

def shell(page, body):
    d, site, p = page.data, page.site, page.prefix
    title = d['title']
    image = d.get('image', site['image'])
    if not all(type(image.get(k)) is int and image[k] > 0 for k in ('width', 'height')):
        page.fail('share image {} needs "width" and "height" in pixels'.format(image.get('src')))
    if not os.path.isfile(os.path.join(ROOT, image['src'])):
        page.fail('share image {} does not exist'.format(image['src']))
    nav = ['<a href="{}{}"{}>{}</a>'.format(p, attr(item['path']), ' aria-current="page"' if item['path'] == page.path else '',
                                             text(item['label'])) for item in site['nav']]
    extra = []
    if d.get('profile'):
        extra = ['  <meta property="profile:first_name" content="{}">'.format(attr(d['profile']['first_name'])),
                 '  <meta property="profile:last_name" content="{}">'.format(attr(d['profile']['last_name']))]
    jsonld = []
    if d.get('person'):
        person = dict(d['person'])
        if not os.path.isfile(os.path.join(ROOT, person.get('image', ''))):
            page.fail('person image {} does not exist'.format(person.get('image')))
        person['image'] = site['url'] + person['image']
        data = json.dumps(person, ensure_ascii=False, indent=2).replace('</', '<\\/')
        jsonld = ['', '  <script type="application/ld+json">'] + indent(data.split('\n'), 2) + ['  </script>']
    ui = dict(site['ui'])
    ui.update(d.get('archive', {}).get('ui', {}))
    ui_json = json.dumps(ui, ensure_ascii=False).replace('</', '<\\/')
    main_class = ' class="archive"' if d.get('archive') else ''
    game_css, game_js = [], []
    if d.get('game'):
        game_css = ['  <link rel="stylesheet" href="{}assets/git-game.css">'.format(p)]
        game_js = ['  <script src="{}assets/git-engine.js" defer></script>'.format(p),
                   '  <script src="{}assets/git-game.js" defer></script>'.format(p)]
    lines = [
        '<!doctype html>',
        '<!-- Generated by build.py from content/{}.json and content/site.json. Edit those, not this file. -->'.format(page.name),
        '<html lang="en">',
        '<head>',
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        '  <title>{}</title>'.format(text(title)),
        '  <meta name="description" content="{}">'.format(attr(d['description'])),
        '  <meta name="author" content="{}">'.format(attr(site['name'])),
        '  <meta name="color-scheme" content="light dark">',
        '  <meta name="theme-color" content="#F4F6FA" media="(prefers-color-scheme: light)">',
        '  <meta name="theme-color" content="#0B1A30" media="(prefers-color-scheme: dark)">',
        '  <link rel="canonical" href="{}{}">'.format(site['url'], page.path),
        '',
        '  <meta property="og:type" content="{}">'.format(attr(d.get('og_type', 'website'))),
        '  <meta property="og:site_name" content="{}">'.format(attr(site['name'])),
        '  <meta property="og:url" content="{}{}">'.format(site['url'], page.path),
        '  <meta property="og:title" content="{}">'.format(attr(d.get('og_title', title))),
        '  <meta property="og:description" content="{}">'.format(attr(d.get('og_description', d['description']))),
        '  <meta property="og:image" content="{}{}">'.format(site['url'], attr(image['src'])),
        '  <meta property="og:image:width" content="{}">'.format(image['width']),
        '  <meta property="og:image:height" content="{}">'.format(image['height']),
        '  <meta property="og:image:alt" content="{}">'.format(attr(image['alt'])),
    ] + extra + [
        '  <meta name="twitter:card" content="summary_large_image">',
        '  <meta name="twitter:site" content="{}">'.format(attr(site['twitter'])),
        '',
        '  <link rel="icon" href="{}assets/favicon.svg" type="image/svg+xml">'.format(p),
        '  <link rel="icon" href="{}assets/favicon-32.png" sizes="32x32" type="image/png">'.format(p),
        '  <link rel="apple-touch-icon" href="{}assets/apple-touch-icon.png">'.format(p),
        '',
        '  <link rel="preconnect" href="https://fonts.googleapis.com">',
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wdth,wght@12..96,75..100,200..800&display=swap">',
        '  <link rel="stylesheet" href="{}assets/site.css">'.format(p),
    ] + game_css + [
        '',
        '  <script>',
        '    try {',
        "      var t = localStorage.getItem('theme');",
        "      if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;",
        '    } catch (e) {}',
        '  </script>',
        '  <script type="application/json" id="ui-text">{}</script>'.format(ui_json),
        '  <script src="{}assets/site.js" defer></script>'.format(p),
    ] + game_js + jsonld + [
        '</head>',
        '<body>',
        '  <a class="skip" href="#main">{}</a>'.format(text(site['skip'])),
        '',
        '  <header class="site-header">',
        '    <div class="wrap header-row">',
        '      <a class="brand" href="{}">{}</a>'.format(p or './', text(site['name'])),
        '      <nav class="site-nav" aria-label="{}">'.format(attr(site['nav_label'])),
    ] + indent(nav, 8) + [
        '      </nav>',
        '      <button class="theme-toggle" type="button" aria-label="{}" hidden>'.format(attr(site['theme_toggle'])),
        '        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z"/></svg>',
        '      </button>',
        '    </div>',
        '  </header>',
        '',
        '  <main id="main"{}>'.format(main_class),
        body,
        '  </main>',
        '',
        '  <footer class="site-footer">',
        '    <div class="wrap footer-row">',
    ] + ['      <p>{}</p>'.format(text(line)) for line in site['footer']] + [
        '    </div>',
        '  </footer>',
        '</body>',
        '</html>',
        '',
    ]
    return '\n'.join(lines)


def render_page(page):
    d = page.data
    parts = []
    if d.get('hero'):
        parts.append(hero(d['hero'], page))
    if d.get('game'):
        parts.append(game(d['game'], page))
    if d.get('head'):
        parts.append(page_head(d['head'], d.get('archive'), page))
    if d.get('archive'):
        parts += archive_sections(d['archive'], page)
    parts += [section(sec, page) for sec in d.get('sections', [])]
    body = '\n\n'.join('\n'.join(indent(part, 4)) for part in parts)
    return shell(page, body)


def check_refs(html_text, page):
    stray = re.search(r'\[\^[^\]]*\]', html_text)
    if stray:
        page.fail('{} is not rendered as a citation: write [^n] with n from 1, in a field that renders links'.format(stray.group()))
    ids = re.findall(r'id="ref-(\d+)"', html_text)
    if len(ids) != len(set(ids)):
        page.fail('more than one cited sources block lists the same ref-n ids')
    cited = set(re.findall(r'href="#ref-(\d+)"', html_text))
    listed = set(ids)
    if cited - listed:
        page.fail('[^n] cites sources that are not listed: {}'.format(sorted(cited - listed)))
    if listed - cited:
        page.fail('sources listed but never cited with [^n]: {}'.format(sorted(listed - cited)))


def render_not_found(page):
    d = page.data
    lines = [
        '<!doctype html>',
        '<!-- Generated by build.py from content/404.json. Edit that, not this file. -->',
        '<html lang="en">',
        '<head>',
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        '  <title>{}</title>'.format(text(d['title'])),
        '  <meta name="robots" content="noindex">',
        '  <meta name="color-scheme" content="light dark">',
        '  <link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">',
        '  <link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">',
        '  <link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">',
        '  <link rel="preconnect" href="https://fonts.googleapis.com">',
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wdth,wght@12..96,75..100,200..800&display=swap">',
        '  <link rel="stylesheet" href="/assets/site.css">',
        '  <script>',
        '    try {',
        "      var t = localStorage.getItem('theme');",
        "      if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;",
        '    } catch (e) {}',
        '  </script>',
        '</head>',
        '<body>',
        '  <main class="wrap notfound">',
        '    <h1>{}</h1>'.format(text(d['heading'])),
        '    <p><code>{}</code></p>'.format(text(d['code'])),
    ] + indent(blocks(d['blocks'], page), 4) + [
        '  </main>',
        '</body>',
        '</html>',
        '',
    ]
    return '\n'.join(lines)


def build(out):
    site = load('site')
    names = sorted(f[:-5] for f in os.listdir(CONTENT) if f.endswith('.json') and f != 'site.json')
    written = []
    for name in names:
        page = Page(name, load(name), site)
        if name == '404':
            target, html_text = '404.html', render_not_found(page)
        else:
            target, html_text = os.path.join(page.path, 'index.html'), render_page(page)
        check_refs(html_text, page)
        dest = os.path.join(out, target)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'w', encoding='utf-8') as f:
            f.write(html_text)
        written.append(target)
    if os.path.abspath(out) != ROOT:
        shutil.copytree(os.path.join(ROOT, 'assets'), os.path.join(out, 'assets'), dirs_exist_ok=True)
    return written


def main():
    parser = argparse.ArgumentParser(description='Build the site from content/*.json.')
    parser.add_argument('--out', default=ROOT, help='directory to write the site into (default: in place)')
    args = parser.parse_args()
    try:
        written = build(args.out)
    except BuildError as err:
        sys.exit('build failed: {}'.format(err))
    print('built {} pages: {}'.format(len(written), ', '.join(written)))


if __name__ == '__main__':
    main()
