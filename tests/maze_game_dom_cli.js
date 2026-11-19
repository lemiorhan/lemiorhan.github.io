'use strict';

// Driver for tests/test_maze_game_dom.py. Every job is a page load: the built 404 page's <main>
// goes into a fresh tests/fake_dom.js document and assets/maze-game.js runs as a classic script
// whose global is that page's window. Without a layout it mounts itself as it does in a browser,
// on a maze picked by Math.random, which always answers the job's `random` (0.25 by default), so
// a load deals the same maze every run. With a layout it loads as a module instead, and the
// driver mounts it on that drawn layout.
// stdin: {"page": {tree, script, location}, "jobs": [job, ...]}; stdout: {"results": [...]}.
//   job: {storage: {key: value}, layout?: [row, ...], random?: number, reduceMotion?: bool,
//         actions: [action, ...]} -> {results: [one per action], storage}
//   actions:
//     ["look"]                   what the page shows (see look below)
//     ["key", key, {metaKey}?]   keydown on the body -> {prevented}
//     ["tap", label]             hold, then lift, on the pad key with that aria-label
//                                -> {prevented}: whether the pointerdown was
//     ["hold", label]            a finger comes down on that pad key: pointerdown -> {prevented}
//     ["lift", label]            it comes up: the mouse click a browser sends after that pointerdown
//     ["press", label]           a click with no pointer behind it, as Enter or Space on a focused pad key
//     ["button"]                 a mouse click on the overlay's button
//     ["swipe", dx, dy]          pointerdown on the maze, a move by (dx, dy) px, pointerup
//                                -> {prevented}: whether the move was
//     ["frames", n, gap?]        run at most n animation frames, gap ms apart (16 by default) -> {ran}
//     ["pointer", type, selector, dx, dy, id]
//                                one pointer event on the element matching selector, at (dx, dy) px
//                                from where swipes start -> {prevented}
//     ["until", text, n, key]    run frames until the overlay says text, pressing key whenever the
//                                game stops to wait for a move; throws after n frames -> {ran}
//     ["hide"]                   the tab goes to the background
//     ["blur"]                   the window loses focus
//     ["place", selector, top, bottom]
//                                lay the one element matching selector out at those viewport
//                                offsets; the window is 800 px tall
var fs = require('fs');
var vm = require('vm');
var path = require('path');
var dom = require(path.join(__dirname, 'fake_dom.js'));

function all(page, selector) {
  return page.doc.body.querySelectorAll(selector);
}

function one(page, selector) {
  var found = all(page, selector);
  if (found.length !== 1) throw new Error(found.length + ' elements match ' + selector);
  return found[0];
}

function padKey(page, label) {
  var keys = all(page, '.maze-key').filter(function (k) { return k.getAttribute('aria-label') === label; });
  if (keys.length !== 1) throw new Error(keys.length + ' pad keys are labelled ' + label);
  return keys[0];
}

function said(page) {
  return one(page, '.maze-overlay').hidden ? null : one(page, '.maze-msg').textContent;
}

function look(page) {
  var root = one(page, '[data-maze]');
  var button = one(page, '.maze-button');
  return {
    hidden: root.hidden,
    cls: root.getAttribute('class'),
    parent: root.parentNode.getAttribute('class'),
    hud: all(page, '.maze-stat').map(function (s) { return s.textContent; }),
    board: one(page, 'canvas').getAttribute('aria-label'),
    role: one(page, 'canvas').getAttribute('role'),
    live: one(page, '.maze-msg').getAttribute('aria-live'),
    said: said(page),
    msgWrites: one(page, '.maze-msg')._.writes,
    button: one(page, '.maze-overlay').hidden || button.hidden ? null : button.textContent,
    keys: all(page, '.maze-key').map(function (k) { return [k.textContent, k.getAttribute('aria-label')]; }),
    running: page.pendingFrames() > 0,
    scrolls: page.doc._.scrolls,
    scrolledWith: page.doc._.scrolledWith,
    stored: JSON.parse(JSON.stringify(page.stored))
  };
}

var ACTIONS = {
  look: look,
  key: function (page, key, modifiers) {
    return { prevented: dom.fire(page.doc.body, 'keydown', Object.assign({ key: key }, modifiers || {})).prevented };
  },
  tap: function (page, label) {
    var down = ACTIONS.hold(page, label);
    ACTIONS.lift(page, label);
    return down;
  },
  hold: function (page, label) {
    return { prevented: dom.fire(padKey(page, label), 'pointerdown', {}).prevented };
  },
  lift: function (page, label) {
    dom.fire(padKey(page, label), 'click', { detail: 1 });
    return {};
  },
  press: function (page, label) {
    dom.fire(padKey(page, label), 'click', { detail: 0 });
    return {};
  },
  button: function (page) {
    dom.fire(one(page, '.maze-button'), 'click', { detail: 1 });
    return {};
  },
  swipe: function (page, dx, dy) {
    var canvas = one(page, 'canvas');
    dom.fire(canvas, 'pointerdown', { clientX: 100, clientY: 100, pointerId: 7 });
    var move = dom.fire(canvas, 'pointermove', { clientX: 100 + dx, clientY: 100 + dy, pointerId: 7 });
    dom.fire(canvas, 'pointerup', { pointerId: 7 });
    return { prevented: move.prevented };
  },
  pointer: function (page, type, selector, dx, dy, id) {
    return { prevented: dom.fire(one(page, selector), type, { clientX: 100 + dx, clientY: 100 + dy, pointerId: id }).prevented };
  },
  frames: function (page, n, gap) {
    return { ran: page.runFrames(n, gap) };
  },
  until: function (page, text, n, key) {
    for (var ran = 0; ran < n; ran++) {
      if (said(page) === text) return { ran: ran };
      if (!page.pendingFrames()) dom.fire(page.doc.body, 'keydown', { key: key });
      page.runFrames(1);
    }
    throw new Error('the overlay did not say ' + JSON.stringify(text) + ' within ' + n + ' frames');
  },
  hide: function (page) {
    page.doc._.hidden = true;
    dom.fire(page.doc, 'visibilitychange', {});
    return {};
  },
  blur: function (page) {
    page.emit('blur');
    return {};
  },
  place: function (page, selector, top, bottom) {
    one(page, selector)._.rect = { top: top, bottom: bottom, left: 0, right: 400 };
    return {};
  }
};

function load(spec, storage, job) {
  var doc = dom.createDocument();
  dom.build(doc, doc.body, spec.tree);
  var w = dom.createWindow({
    storage: dom.createStorage(storage), location: spec.location, document: doc, reduceMotion: !!job.reduceMotion
  });
  var win = w.window;
  var context = vm.createContext({
    window: win, document: doc, location: win.location,
    requestAnimationFrame: win.requestAnimationFrame, cancelAnimationFrame: win.cancelAnimationFrame
  });
  if (job.layout) context.module = { exports: {} };
  vm.runInContext('Math.random = function () { return ' + JSON.stringify(job.random || 0.25) + '; };', context);
  vm.runInContext(fs.readFileSync(spec.script, 'utf8'), context, { filename: spec.script });
  if (job.layout) {
    var data = JSON.parse(doc.getElementById('maze-data').textContent);
    context.module.exports.mount(doc.querySelector('[data-maze]'), data, { layout: job.layout });
  }
  return { doc: doc, stored: storage, emit: w.emit, pendingFrames: w.pendingFrames, runFrames: w.runFrames };
}

function runJob(spec, job) {
  var storage = JSON.parse(JSON.stringify(job.storage || {}));
  var page = load(spec, storage, job);
  var results = job.actions.map(function (a) {
    if (!Object.prototype.hasOwnProperty.call(ACTIONS, a[0])) throw new Error('unknown action ' + a[0]);
    return ACTIONS[a[0]].apply(null, [page].concat(a.slice(1)));
  });
  return { results: results, storage: storage };
}

var input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ results: input.jobs.map(function (job) { return runJob(input.page, job); }) }));
