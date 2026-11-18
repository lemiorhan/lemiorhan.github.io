'use strict';

// Driver for tests/test_git_game_dom.py. Every mount is a page load: the built page's game
// section goes into a fresh tests/fake_dom.js document, and the page's scripts run in its order
// as classic scripts whose globals are that page's window, so assets/git-game.js mounts itself
// as it does in a browser.
// stdin: {"page": {tree, scripts, location}, "jobs": [job, ...]}; stdout: {"results": [...]}.
//   job: {narrow, storage: {key: value}, mounts: [[action, ...], ...]}
//     the mounts share the job's storage; each returns one result per action, with `handled`,
//     the number of listeners its events ran. The job also returns the storage it left.
//   actions:
//     ["look"]                    what the page shows (see look below)
//     ["type", text, caret?]      focus the input and type text; a {Message} token becomes the
//                                 hash of the live graph's commit with that message
//     ["enter"]                   Enter in the input, then the form's submit
//     ["tab", {shiftKey...}?]     Tab in the input -> {prevented}
//     ["tap", selector, index?]   pointerdown, then click -> {pointerdown, click}: whether each was prevented
//     ["tap-flag", name]          tap the hit rect of the live graph's flag that inserts name
//     ["refuse", kind, arg]       a call the double must refuse -> {error}: its message, or null
var fs = require('fs');
var vm = require('vm');
var path = require('path');
var dom = require(path.join(__dirname, 'fake_dom.js'));

function has(map, key) {
  return Object.prototype.hasOwnProperty.call(map, key);
}

function all(root, selector) {
  return ('body' in root ? root.body : root).querySelectorAll(selector);
}

function one(root, selector) {
  var found = all(root, selector);
  if (found.length !== 1) throw new Error(found.length + ' elements match ' + selector);
  return found[0];
}

function textOf(root, selector) {
  var n = root.querySelector(selector);
  return n ? n.textContent : null;
}

function box(node) {
  return node ? { width: Number(node.getAttribute('width')), height: Number(node.getAttribute('height')) } : null;
}

function graph(svg) {
  return {
    label: svg.getAttribute('aria-label'),
    rows: all(svg, '.gg-row').map(function (r) {
      return {
        hash: r.getAttribute('data-insert'), title: textOf(r, 'title'), shownHash: one(r, '.gg-hash').textContent,
        msg: one(r, '.gg-msg').textContent, label: r.getAttribute('aria-label'), cls: r.getAttribute('class'),
        hit: box(r.querySelector('.gg-hit'))
      };
    }),
    flags: all(svg, '.gg-flag').map(function (f) {
      return {
        insert: f.getAttribute('data-insert'), text: one(f, 'text').textContent, cls: f.getAttribute('class'),
        hit: box(f.querySelector('.gg-hit')), pill: box(one(f, '.gg-pill'))
      };
    })
  };
}

function card(c) {
  var stars = c.querySelector('.gg-stars');
  var summary = c.querySelector('.gg-summary');
  var link = c.querySelector('.gg-fact-link');
  return {
    hidden: c.hidden,
    title: textOf(c, '.gg-card-title'),
    stars: stars && {
      label: stars.getAttribute('aria-label'), all: all(stars, '.gg-star').length,
      on: all(stars, '.gg-star').filter(function (s) { return s.classList.contains('is-on'); }).length
    },
    score: textOf(c, '.gg-card-score'),
    fact: textOf(c, '.gg-fact'),
    link: link && { href: link.getAttribute('href'), text: link.textContent },
    next: all(c, '.gg-next').filter(function (b) { return !b.closest('.gg-summary'); }).map(function (b) { return b.textContent; }),
    summary: summary && {
      title: textOf(summary, '.gg-summary-title'),
      rank: textOf(summary, '.gg-rank'),
      list: all(summary, '.gg-summary-list div').map(function (d) { return [one(d, 'dt').textContent, one(d, 'dd').textContent]; }),
      result: textOf(summary, '.gg-result'),
      links: all(summary, '.gg-links a').map(function (a) { return [a.getAttribute('href'), a.textContent]; })
    }
  };
}

function look(page) {
  var d = page.doc;
  var input = one(d, '#gg-input');
  var opts = one(d, '.gg-opts');
  return {
    mount: { cls: one(d, '[data-git-game]').getAttribute('class'), fallback: all(d, '.gg-fallback').length },
    strip: all(d, '.gg-strip .gg-lv').map(function (b) {
      return { text: b.textContent, cls: b.getAttribute('class'), stars: b.getAttribute('data-stars'),
        current: b.getAttribute('aria-current'), label: b.getAttribute('aria-label') };
    }),
    count: one(d, '.gg-count').textContent,
    title: one(d, '.gg-title').textContent,
    out: one(d, '.gg-out').childNodes.map(function (p) { return { cls: p.getAttribute('class'), text: p.textContent }; }),
    said: one(d, '.sr-only[aria-live]').textContent,
    live: graph(one(d, '.gg-pane-live svg')),
    goal: graph(one(d, '.gg-pane-goal svg')),
    card: card(one(d, '.gg-card')),
    input: { value: input.value, caret: input.selectionStart, focused: d.activeElement === input },
    chips: {
      pressed: all(d, '.gg-cmds .gg-chip').filter(function (b) { return b.getAttribute('aria-pressed') === 'true'; })
        .map(function (b) { return b.textContent; }),
      options: all(opts, '.gg-chip').map(function (b) { return b.textContent; }),
      hidden: opts.hidden
    },
    dock: one(d, '.gg-dock').getAttribute('class'),
    stored: JSON.parse(JSON.stringify(page.stored))
  };
}

function resolve(page, line) {
  var rows = graph(one(page.doc, '.gg-pane-live svg')).rows;
  return String(line).replace(/\{([^{}]+)\}/g, function (match, message) {
    var found = rows.filter(function (r) { return r.title === message; });
    if (found.length !== 1) throw new Error(found.length + ' commits in the live graph have the message ' + message);
    return found[0].hash;
  });
}

function submitForm(node) {
  var form = node.closest('form');
  if (!form) return;
  if (!dom.fire(form, 'submit', {}).prevented) throw new Error('the form would navigate away');
}

function tap(page, target) {
  var down = dom.fire(target, 'pointerdown', {});
  if (!down.prevented) {
    var focusable = target.closest('button, input, a[href], [tabindex]');
    if (focusable) focusable.focus();
    else page.doc._.active = null;
  }
  var click = dom.fire(target, 'click', {});
  var button = target.closest('button');
  if (!click.prevented && button && button.type === 'submit') submitForm(button);
  return { pointerdown: down.prevented, click: click.prevented };
}

var REFUSALS = {
  select: function (page, arg) { page.doc.querySelector(arg); },
  get: function (page, arg) { return one(page.doc, '#gg-input')[arg]; },
  set: function (page, arg) { one(page.doc, '#gg-input')[arg] = 'x'; },
  media: function (page, arg) { page.win.matchMedia(arg); },
  global: function (page, arg) { vm.runInContext(arg, page.context); },
  event: function (page, arg) { dom.fire(one(page.doc, '#gg-input'), arg, {}); },
  listen: function (page, arg) { one(page.doc, '#gg-input').addEventListener(arg, function () {}); },
  namespace: function (page, arg) { page.doc.createElementNS(arg, 'g'); },
  focus: function (page, arg) { one(page.doc, arg).focus(); },
  storage: function (page, arg) { return page.win.localStorage[arg]; },
  raise: function (page, arg) {
    var board = one(page.doc, '.gg-board');
    board.addEventListener('click', function () { throw new Error(arg); });
    dom.fire(board, 'click', {});
  }
};

var ACTIONS = {
  look: look,
  type: function (page, text, caret) {
    var input = one(page.doc, '#gg-input');
    input.focus();
    input.value = resolve(page, text);
    if (caret !== undefined) input.setSelectionRange(caret, caret);
    dom.fire(input, 'input', {});
    return {};
  },
  enter: function (page) {
    var input = one(page.doc, '#gg-input');
    if (!dom.fire(input, 'keydown', { key: 'Enter' }).prevented) submitForm(input);
    return {};
  },
  tab: function (page, modifiers) {
    return { prevented: dom.fire(one(page.doc, '#gg-input'), 'keydown', Object.assign({ key: 'Tab' }, modifiers || {})).prevented };
  },
  tap: function (page, selector, index) {
    var found = all(page.doc, selector);
    var target = found[index || 0];
    if (!target) throw new Error('nothing to tap at ' + selector + ' #' + (index || 0));
    return tap(page, target);
  },
  'tap-flag': function (page, name) {
    var flags = all(one(page.doc, '.gg-pane-live svg'), '.gg-flag').filter(function (f) { return f.getAttribute('data-insert') === name; });
    if (flags.length !== 1) throw new Error(flags.length + ' flags insert ' + name);
    return tap(page, one(flags[0], '.gg-hit'));
  },
  refuse: function (page, kind, arg) {
    if (!has(REFUSALS, kind)) throw new Error('unknown refusal ' + kind);
    try {
      REFUSALS[kind](page, arg);
    } catch (e) {
      return { error: e.message };
    }
    return { error: null };
  }
};

function load(spec, job, storage) {
  var doc = dom.createDocument();
  dom.build(doc, doc.body, spec.tree);
  var w = dom.createWindow({ narrow: job.narrow, storage: dom.createStorage(storage), location: spec.location });
  var win = w.window;
  var context = vm.createContext({
    window: win, document: doc, location: win.location,
    requestAnimationFrame: win.requestAnimationFrame, cancelAnimationFrame: win.cancelAnimationFrame
  });
  spec.scripts.forEach(function (file) {
    vm.runInContext(fs.readFileSync(file, 'utf8'), context, { filename: file });
  });
  w.flushFrames();
  return { doc: doc, win: win, context: context, flushFrames: w.flushFrames, stored: storage };
}

function runJob(spec, job) {
  var storage = JSON.parse(JSON.stringify(job.storage || {}));
  var mounts = job.mounts.map(function (actions) {
    var page = load(spec, job, storage);
    return actions.map(function (a) {
      if (!has(ACTIONS, a[0])) throw new Error('unknown action ' + a[0]);
      var before = page.doc._.handled;
      var result = ACTIONS[a[0]].apply(null, [page].concat(a.slice(1)));
      page.flushFrames();
      result.handled = page.doc._.handled - before;
      return result;
    });
  });
  return { mounts: mounts, storage: storage };
}

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function (chunk) { input += chunk; });
process.stdin.on('end', function () {
  var request = JSON.parse(input);
  var results = request.jobs.map(function (job) { return runJob(request.page, job); });
  process.stdout.write(JSON.stringify({ results: results }));
});
