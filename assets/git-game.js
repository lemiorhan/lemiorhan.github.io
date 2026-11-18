(function () {
  'use strict';

  var MAX_STARS = 3;
  var STAR_MARGIN = 2;
  var STORE_KEY = 'git-game';
  var HISTORY_MAX = 60;
  var OUTPUT_MAX = 300;
  var MOVE_MS = 420;
  var TAP = 44;
  var FLAG_GAP = 6;
  var META = ['help', 'hint', 'undo', 'restart', 'levels', 'clear'];
  var NAMING = { branch: true, checkout: true, switch: true, tag: true };

  function fill(template, values) {
    return String(template).replace(/\{(\w+)\}/g, function (match, key) {
      return key in values ? String(values[key]) : match;
    });
  }

  function has(map, key) {
    return Object.prototype.hasOwnProperty.call(map, key);
  }

  function starsFor(count, par) {
    if (count <= par) return 3;
    return count <= par + STAR_MARGIN ? 2 : 1;
  }

  function goalOf(E, level) {
    var repo = E.fromCommands(level.setup);
    level.solution.forEach(function (line) {
      var r = repo.run(E.resolve(line, repo.state()));
      if (!r.ok) throw new Error('level ' + level.id + ': ' + line + ': ' + r.output.join(' / '));
    });
    return repo.state();
  }

  // `storage` returns the Storage object; it can be missing or throw on any
  // access (private mode, blocked site data), and the game plays the same then.
  function loadProgress(storage) {
    try {
      var raw = storage().getItem(STORE_KEY);
      var saved = raw ? JSON.parse(raw) : null;
      if (saved && typeof saved.solved === 'object' && saved.solved) return saved;
    } catch (e) {}
    return { solved: {}, level: 0 };
  }

  function saveProgress(storage, progress) {
    try { storage().setItem(STORE_KEY, JSON.stringify(progress)); } catch (e) {}
  }

  function recordSolve(progress, id, stars, used) {
    var rec = has(progress.solved, id) ? progress.solved[id] : null;
    progress.solved[id] = {
      stars: Math.max(stars, rec ? rec.stars : 0),
      best: Math.min(used, rec ? rec.best : Infinity)
    };
  }

  function startLevel(progress, total) {
    var n = progress.level;
    return typeof n === 'number' && n % 1 === 0 && n >= 0 && n < total ? n : 0;
  }

  function totals(ui, levels, solved) {
    var t = { solved: 0, total: levels.length, commands: 0, par: 0, stars: 0, max: levels.length * MAX_STARS };
    levels.forEach(function (lv) {
      if (!has(solved, lv.id)) return;
      var rec = solved[lv.id];
      t.solved++;
      t.commands += rec.best;
      t.par += lv.par;
      t.stars += rec.stars;
    });
    var floor = levels.length;
    var span = Math.max(1, t.max - floor);
    var at = Math.max(0, Math.min(1, (t.stars - floor) / span));
    t.rank = ui.ranks[Math.round(at * (ui.ranks.length - 1))];
    return t;
  }

  function resultText(ui, t, url) {
    return fill(ui.result, { solved: t.solved, total: t.total, commands: t.commands, par: t.par, stars: t.stars, max: t.max, rank: t.rank, url: url });
  }

  function sentences(E, ui, before, after) {
    return E.diff(before, after).map(function (d) {
      if (d.type === 'commit') return fill(ui.say_commit, { hash: d.hash });
      if (d.type === 'head') {
        return d.to.type === 'branch' ? fill(ui.say_head_branch, { name: d.to.name }) : fill(ui.say_head_detached, { hash: d.to.hash });
      }
      var what = d.kind === 'tag' ? 'tag' : 'branch';
      var key = d.from === null ? '_new' : (d.to === null ? '_deleted' : '_moved');
      return fill(ui['say_' + what + key], { name: d.name, from: d.from, to: d.to });
    }).join(' ');
  }

  // One level being played: the score counts git commands that changed the
  // graph, and undo restores the graph without refunding the count.
  function createPlay(E, ui, level, goal) {
    var repo = E.fromCommands(level.setup);
    var setup = repo.state();
    var undoStack = [];
    var play = { repo: repo, used: 0, solved: false };

    play.onGoal = function () { return E.matches(repo.state(), goal); };

    function git(text) {
      var before = repo.state();
      var snapshot = repo.snapshot();
      var r = repo.run(text);
      var step = { kind: 'git', text: text, ok: r.ok, output: r.output, changed: r.changed, solvedNow: false, hint: null };
      if (r.changed) {
        undoStack.push({ snapshot: snapshot, line: text });
        play.used++;
      }
      var said = r.changed ? sentences(E, ui, before, repo.state()) : '';
      if (!r.ok) said = (r.output[0] || '') + (said ? ' ' + said : '');
      else if (!said) said = ui.say_nothing;
      if (r.changed && !play.solved) {
        if (play.onGoal()) {
          play.solved = true;
          step.solvedNow = true;
          step.stars = starsFor(play.used, level.par);
          said += ' ' + fill(ui.say_solved, { stars: fill(ui.stars_label, { n: step.stars, max: MAX_STARS }) });
        } else {
          step.hint = shapeHint(E, ui, setup, goal, repo.state());
          if (step.hint) said += ' ' + step.hint;
        }
      }
      step.said = said;
      return step;
    }

    function undo(text) {
      if (!undoStack.length) return { kind: 'undo', text: text, ok: false, note: ui.nothing_to_undo, said: ui.nothing_to_undo };
      var top = undoStack.pop();
      var before = repo.state();
      repo.restore(top.snapshot);
      var note = fill(ui.undone, { line: top.line });
      return { kind: 'undo', text: text, ok: true, note: note, said: note + ' ' + sentences(E, ui, before, repo.state()) };
    }

    play.submit = function (raw) {
      var text = String(raw).trim();
      if (!text) return null;
      var words = text.split(/\s+/);
      if (words.length === 1 && META.indexOf(words[0]) >= 0) {
        return words[0] === 'undo' ? undo(text) : { kind: 'meta', text: text, word: words[0] };
      }
      return git(text);
    };

    return play;
  }

  function createHistory(max) {
    var items = [];
    var at = 0;
    var draft = '';
    return {
      push: function (text) {
        if (items[items.length - 1] !== text) items.push(text);
        if (items.length > max) items.shift();
        at = items.length;
        draft = '';
      },
      up: function (current) {
        if (!items.length) return null;
        if (at === items.length) draft = current;
        at = Math.max(0, at - 1);
        return items[at];
      },
      down: function () {
        if (at >= items.length) return null;
        at++;
        return at === items.length ? draft : items[at];
      }
    };
  }

  function builderChips(ui, goal, state, value) {
    var words = String(value).trim().split(/\s+/);
    var cmd = words[0] === 'git' && words[1] && has(ui.builder, words[1]) ? words[1] : null;
    var chips = { cmd: cmd, options: [], names: [] };
    if (!cmd) return chips;
    chips.options = ui.builder[cmd].filter(function (opt) { return words.indexOf(opt) < 0; });
    if (NAMING[cmd]) {
      chips.names = Object.keys(goal.branches).filter(function (n) { return !has(state.branches, n); })
        .concat(Object.keys(goal.tags).filter(function (n) { return !has(state.tags, n); }))
        .filter(function (n) { return words.indexOf(n) < 0; });
    }
    return chips;
  }

  function complete(E, ui, state, value, caret) {
    var v = String(value);
    var at = typeof caret === 'number' ? caret : v.length;
    var before = v.slice(0, at);
    var word = /(\S*)$/.exec(before)[1];
    var tokens = before.slice(0, at - word.length).trim().split(/\s+/).filter(Boolean);
    var pool;
    if (!tokens.length) {
      if (!word) return null;
      pool = ['git'].concat(META);
    } else if (tokens[0] !== 'git') {
      return null;
    } else if (tokens.length === 1) {
      pool = E.COMMANDS;
    } else if (word.charAt(0) === '-') {
      pool = has(ui.builder, tokens[1]) ? ui.builder[tokens[1]] : [];
    } else {
      pool = Object.keys(state.branches).concat(Object.keys(state.tags), ['HEAD']);
      if (/^[0-9a-f]+$/.test(word)) pool = pool.concat(Object.keys(state.commits));
    }
    var hits = pool.filter(function (c, i) { return c.indexOf(word) === 0 && pool.indexOf(c) === i; });
    if (!hits.length) return null;
    var tail = v.slice(at);
    var head = before.slice(0, at - word.length);
    if (hits.length === 1) {
      var spaced = /^\s/.test(tail);
      head += hits[0] + (spaced ? '' : ' ');
      return { value: head + tail, caret: head.length + (spaced ? 1 : 0) };
    }
    var fillTo = hits[0];
    hits.forEach(function (h) {
      var i = 0;
      while (i < fillTo.length && fillTo[i] === h[i]) i++;
      fillTo = fillTo.slice(0, i);
    });
    if (fillTo.length <= word.length) return { list: hits };
    head += fillTo;
    return { value: head + tail, caret: head.length };
  }

  // A second Tab on the same line and caret is not used. It counts as a repeat
  // only while the list it would print is still the terminal's last line
  // (`shown`).
  function createCompleter(E, ui) {
    var listed = null;
    return {
      press: function (state, value, caret, shown) {
        var c = complete(E, ui, state, value, caret);
        if (!c || !c.list) return c;
        var line = c.list.join('  ');
        var key = JSON.stringify([value, caret]);
        if (key === listed && shown === line) return null;
        listed = key;
        return { line: line };
      }
    };
  }

  // Lanes are assigned once per level and extended for new commits, so that the
  // player sees a command move pointers and add nodes, not redraw the graph.

  function seqOf(s, h) { return s.commits[h].seq; }

  function initialLanes(s) {
    var lanes = {};
    var ranges = [];
    var reach = {};
    Object.keys(s.commits).forEach(function (h) {
      s.commits[h].parents.forEach(function (p, i) {
        if (i > 0) reach[p] = Math.max(reach[p] || 0, s.commits[h].seq);
      });
    });
    var tips = [];
    if (has(s.branches, 'main')) tips.push(s.branches.main);
    Object.keys(s.branches).sort().forEach(function (n) { tips.push(s.branches[n]); });
    Object.keys(s.tags).sort().forEach(function (n) { tips.push(s.tags[n]); });
    if (s.head.type === 'detached') tips.push(s.head.hash);
    Object.keys(s.commits).sort(function (a, b) { return seqOf(s, b) - seqOf(s, a); }).forEach(function (h) { tips.push(h); });
    tips.forEach(function (t) {
      if (has(lanes, t)) return;
      var chain = [];
      var h = t;
      while (h && !has(lanes, h)) {
        chain.push(h);
        lanes[h] = -1;
        h = s.commits[h].parents[0];
      }
      var lo = h ? seqOf(s, h) : 0;
      var hi = chain.reduce(function (m, c) { return Math.max(m, seqOf(s, c), reach[c] || 0); }, 0);
      var lane = 0;
      while ((ranges[lane] || []).some(function (r) { return lo < r[1] && r[0] < hi; })) lane++;
      chain.forEach(function (c) { lanes[c] = lane; });
      (ranges[lane] = ranges[lane] || []).push([lo, hi]);
    });
    return lanes;
  }

  function assignLanes(lanes, s) {
    var present = Object.keys(s.commits).filter(function (h) { return has(lanes, h); });
    Object.keys(s.commits).filter(function (h) { return !has(lanes, h); })
      .sort(function (a, b) { return seqOf(s, a) - seqOf(s, b); })
      .forEach(function (h) {
        var parent = s.commits[h].parents[0];
        var floor = parent ? seqOf(s, parent) : 0;
        function free(lane) {
          return !present.some(function (o) {
            if (lanes[o] === lane && seqOf(s, o) > floor) return true;
            return seqOf(s, o) > floor && s.commits[o].parents.some(function (p, i) {
              return i > 0 && lanes[p] === lane;
            });
          });
        }
        var lane = parent && has(lanes, parent) && free(lanes[parent]) ? lanes[parent] : 0;
        while (!free(lane)) lane++;
        lanes[h] = lane;
        present.push(h);
      });
    return lanes;
  }

  var SIZES = {
    live: { row: 40, lane: 22, r: 6.5, pad: 24, hash: 13, flag: 11.5, msg: 14, flagH: 20 },
    liveNarrow: { row: 44, lane: 20, r: 6.5, pad: 20, hash: 13, flag: 11.5, msg: 14, flagH: 22 },
    goal: { row: 32, lane: 17, r: 5, pad: 18, hash: 12, flag: 11, msg: 13, flagH: 18 }
  };
  var MONO = 0.62;
  var PROSE = 0.5;

  function goalText(E, ui, goal, c) {
    var m = /^(amend|revert)\(base:([0-9a-f]+)\)$|^base:([0-9a-f]+)$/.exec(c.cls || '');
    if (c.cls === 'base:' + c.hash) return null;
    if (c.cls === 'merge') return ui.goal_merge;
    if (m && m[3] && goal.commits[m[3]]) return fill(ui.goal_copy, { message: E.firstLine(goal.commits[m[3]].message) });
    if (m && m[1] === 'amend' && goal.commits[m[2]]) return fill(ui.goal_amend, { message: E.firstLine(goal.commits[m[2]].message) });
    if (m && m[1] === 'revert' && goal.commits[m[2]]) return fill(ui.goal_revert, { message: E.firstLine(goal.commits[m[2]].message) });
    if (/^revert\(/.test(c.cls)) return ui.goal_revert_some;
    return ui.goal_new;
  }

  function kindOf(c) {
    return /^amend\(/.test(c.cls) ? 'amend'
      : /^revert\(/.test(c.cls) ? 'revert'
      : c.cls === 'base:' + c.hash ? 'keep'
      : /^base:/.test(c.cls) ? 'copy'
      : c.cls === 'merge' ? 'merge'
      : 'new';
  }

  function shapeHint(E, ui, setup, goal, state) {
    var pick = (E.identityDiff(state, goal) || []).filter(function (d) { return !has(setup.commits, d.hash); })[0];
    if (!pick) return null;
    var c = goal.commits[pick.goal];
    var mine = state.commits[pick.hash];
    var kind = kindOf(c);
    var how = {
      amend: ui.shape_how_amend, revert: ui.shape_how_revert, keep: ui.shape_how_keep,
      copy: ui.shape_how_copy, merge: ui.shape_how_merge, 'new': ui.shape_how_new
    }[kind];
    return fill(kindOf(mine) === kind ? ui.shape_wrong_commit : ui.shape_right, {
      commit: E.firstLine(mine.message),
      want: goalText(E, ui, goal, c) || fill(ui.goal_keep, { message: E.firstLine(c.message) }),
      how: how
    });
  }

  function flagsOf(ui, s) {
    var out = {};
    function add(hash, flag) { (out[hash] = out[hash] || []).push(flag); }
    var current = s.head.type === 'branch' ? s.head.name : null;
    if (s.head.type === 'detached') add(s.head.hash, { key: 'HEAD', text: ui.flag_head, kind: 'head', insert: 'HEAD' });
    if (current && has(s.branches, current)) {
      add(s.branches[current], { key: 'b:' + current, text: fill(ui.flag_current, { name: current }), kind: 'current', insert: current });
    }
    Object.keys(s.tags).sort().forEach(function (n) {
      add(s.tags[n], { key: 't:' + n, text: fill(ui.flag_tag, { name: n }), kind: 'tag', insert: n });
    });
    Object.keys(s.branches).sort().forEach(function (n) {
      if (n !== current) add(s.branches[n], { key: 'b:' + n, text: n, kind: 'branch', insert: n });
    });
    return out;
  }

  // A pill is narrower and shorter than a fingertip, so each flag owns a slot
  // at least TAP wide and a full row tall; its invisible hit rect fills it.
  function layout(E, ui, s, lanes, kind, width, narrow) {
    var z = kind === 'goal' ? SIZES.goal : (narrow ? SIZES.liveNarrow : SIZES.live);
    var reach = {};
    E.reachable(s).forEach(function (h) { reach[h] = true; });
    var hashes = Object.keys(s.commits).filter(function (h) { return kind !== 'goal' || reach[h]; })
      .sort(function (a, b) { return seqOf(s, b) - seqOf(s, a); });
    var used = [];
    hashes.forEach(function (h) { if (used.indexOf(lanes[h]) < 0) used.push(lanes[h]); });
    used.sort(function (a, b) { return a - b; });
    var flags = flagsOf(ui, s);
    var head = s.head.type === 'detached' ? s.head.hash : s.branches[s.head.name];
    var textX = z.pad + Math.max(0, used.length - 1) * z.lane + z.r + 12;
    var hashW = 7 * MONO * z.hash;
    var widest = 0;
    var rows = hashes.map(function (h) {
      var c = s.commits[h];
      var label = kind === 'goal' ? goalText(E, ui, s, c) : null;
      var x = textX + hashW + 10;
      var fl = (flags[h] || []).map(function (f) {
        var w = f.text.length * MONO * z.flag + 14;
        var slot = Math.max(w + FLAG_GAP, TAP);
        var placed = {
          key: f.key, text: f.text, kind: f.kind, insert: f.insert, w: w, x: x,
          hit: { x: -FLAG_GAP / 2, y: -z.row / 2, w: slot, h: z.row }
        };
        x += slot;
        return placed;
      });
      widest = Math.max(widest, x - textX);
      return {
        hash: h, lane: used.indexOf(lanes[h]), flags: fl, msgX: x + 2,
        message: label === null ? E.firstLine(c.message) : label, anonymous: label !== null,
        lost: !reach[h], head: h === head, root: !c.parents.length, parents: c.parents
      };
    });
    var w = Math.max(width || 0, textX + widest + 60);
    var lineH = Math.round(z.msg * 1.3);
    var y = z.pad;
    rows.forEach(function (r) {
      r.x = z.pad + r.lane * z.lane;
      r.tx = textX;
      var room = Math.floor((w - r.msgX - z.pad) / (PROSE * z.msg));
      r.wrap = r.message.length > room;
      if (r.wrap) {
        r.msgX = textX;
        room = Math.floor((w - textX - z.pad) / (PROSE * z.msg));
      }
      r.shown = room < 4 ? '' : (r.message.length > room ? r.message.slice(0, room - 1) + '…' : r.message);
      r.msgY = r.wrap ? lineH : 0;
      r.h = z.row + r.msgY;
      r.y = y + z.row / 2;
      y += r.h;
    });
    return { z: z, rows: rows, width: w, height: y + z.pad, flags: flags };
  }

  function describe(E, ui, s, onlyReachable) {
    var parts = [];
    var reach = E.reachable(s);
    function named(h) {
      if (!onlyReachable) return h;
      return s.commits[h].cls === 'base:' + h ? h : goalText(E, ui, s, s.commits[h]);
    }
    Object.keys(s.branches).sort().forEach(function (n) { parts.push(fill(ui.sr_ref, { name: n, hash: named(s.branches[n]) })); });
    Object.keys(s.tags).sort().forEach(function (n) { parts.push(fill(ui.sr_ref, { name: n, hash: named(s.tags[n]) })); });
    parts.push(s.head.type === 'branch'
      ? fill(ui.sr_head_branch, { name: s.head.name })
      : fill(ui.sr_head_detached, { hash: named(s.head.hash) }));
    var total = Object.keys(s.commits).length;
    parts.push(fill(ui.sr_commits, { commits: onlyReachable ? reach.length : total, lost: onlyReachable ? 0 : total - reach.length }));
    return parts.join('. ') + '.';
  }

  var GitGame = {
    MAX_STARS: MAX_STARS,
    STAR_MARGIN: STAR_MARGIN,
    starsFor: starsFor,
    goalOf: goalOf,
    loadProgress: loadProgress,
    saveProgress: saveProgress,
    recordSolve: recordSolve,
    startLevel: startLevel,
    totals: totals,
    resultText: resultText,
    sentences: sentences,
    createPlay: createPlay,
    createHistory: createHistory,
    builderChips: builderChips,
    complete: complete,
    createCompleter: createCompleter,
    initialLanes: initialLanes,
    layout: layout
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = GitGame;
  else mount();

  function mount() {
    var mountEl = document.querySelector('[data-git-game]');
    var island = document.getElementById('git-game-data');
    var E = window.GitEngine;
    if (!mountEl || !island || !E) return;

    var data = JSON.parse(island.textContent);
    var ui = data.ui;
    var levels = data.levels;

    var NS = 'http://www.w3.org/2000/svg';
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    var narrow = window.matchMedia('(max-width: 40rem)');
    var storage = function () { return window.localStorage; };

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function svgEl(tag, attrs, parent) {
      var node = document.createElementNS(NS, tag);
      Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
      if (parent) parent.appendChild(node);
      return node;
    }

    function button(cls, text, onClick) {
      var b = el('button', cls, text);
      b.type = 'button';
      if (onClick) b.addEventListener('click', onClick);
      return b;
    }

    function starText(n) {
      var out = '';
      for (var i = 0; i < MAX_STARS; i++) out += i < n ? ui.star : ui.star_empty;
      return out;
    }

    function commands(n) {
      return fill(n === 1 ? ui.command_one : ui.command_many, { n: n });
    }

    // Graph view: an SVG that draws a state as `git log --graph --all`, newest
    // first, and animates nodes, edges and pointer flags between two states.

    function View(frame, kind) {
      this.frame = frame;
      this.kind = kind;
      this.svg = svgEl('svg', { class: 'gg-svg', focusable: 'false' }, frame);
      this.edgeLayer = svgEl('g', { class: 'gg-edges' }, this.svg);
      this.rowLayer = svgEl('g', { class: 'gg-rows' }, this.svg);
      this.flagLayer = svgEl('g', { class: 'gg-flags' }, this.svg);
      this.items = {};
      this.flags = {};
      this.edges = [];
      this.frameId = 0;
      this.active = null;
    }

    View.prototype.reset = function () {
      cancelAnimationFrame(this.frameId);
      this.rowLayer.textContent = '';
      this.flagLayer.textContent = '';
      this.edgeLayer.textContent = '';
      this.items = {};
      this.flags = {};
      this.edges = [];
    };

    function edgePath(c, p, first, row) {
      if (Math.abs(c.x - p.x) < 0.5) return 'M' + c.x + ' ' + c.y + 'V' + p.y;
      var k = Math.max(4, Math.min(row * 0.9, p.y - c.y));
      if (first) {
        return 'M' + c.x + ' ' + c.y + 'V' + (p.y - k) + 'C' + c.x + ' ' + (p.y - k / 2) + ' ' + p.x + ' ' + (p.y - k / 2) + ' ' + p.x + ' ' + p.y;
      }
      return 'M' + c.x + ' ' + c.y + 'C' + c.x + ' ' + (c.y + k / 2) + ' ' + p.x + ' ' + (c.y + k / 2) + ' ' + p.x + ' ' + (c.y + k) + 'V' + p.y;
    }

    View.prototype.draw = function (s, lanes, animate) {
      var view = this;
      var live = this.kind === 'live';
      cancelAnimationFrame(this.frameId);
      var width = this.frame.clientWidth || (liveView && liveView.frame.clientWidth) || 320;
      var L = layout(E, ui, s, lanes, this.kind, width, narrow.matches);
      var z = L.z;
      this.svg.setAttribute('width', L.width);
      this.svg.setAttribute('height', L.height);
      this.svg.setAttribute('viewBox', '0 0 ' + L.width + ' ' + L.height);
      this.svg.style.setProperty('--hash', z.hash + 'px');
      this.svg.style.setProperty('--flag', z.flag + 'px');
      this.svg.style.setProperty('--msg', z.msg + 'px');

      var seen = {};
      var seenFlags = {};
      var focusables = [];
      L.rows.forEach(function (r) {
        seen[r.hash] = true;
        var it = view.items[r.hash];
        var fresh = !it;
        if (fresh) {
          it = view.items[r.hash] = { g: svgEl('g', { class: 'gg-row' }, view.rowLayer) };
          if (live) {
            it.hit = svgEl('rect', { class: 'gg-hit' }, it.g);
            it.g.setAttribute('role', 'button');
            it.g.setAttribute('data-insert', r.hash);
            it.tip = svgEl('title', {}, it.g);
          }
          it.dot = svgEl('g', { class: 'gg-dot' }, it.g);
          it.circle = svgEl('circle', { class: 'gg-node', cx: 0, cy: 0 }, it.dot);
          it.hashText = svgEl('text', { class: 'gg-hash', 'dominant-baseline': 'central' }, it.g);
          it.msgText = svgEl('text', { class: 'gg-msg', 'dominant-baseline': 'central' }, it.g);
          if (animate) it.circle.classList.add('is-new');
        }
        it.g.setAttribute('class', 'gg-row' + (r.lost ? ' is-lost' : '') + (r.head ? ' is-head' : ''));
        it.circle.setAttribute('r', r.head ? z.r + 1 : z.r);
        it.circle.setAttribute('class', 'gg-node ' + (r.lane === 0 ? 'gg-l0' : 'gg-l1') + (r.root ? ' is-root' : '') +
          (fresh && animate ? ' is-new' : ''));
        it.hashText.textContent = r.anonymous ? ui.goal_hash : r.hash;
        it.msgText.textContent = r.shown;
        it.msgText.setAttribute('y', r.msgY);
        if (live) {
          var label = fill(ui.commit_label, { hash: r.hash, message: r.message, lost: r.lost ? ui.commit_lost : '' });
          it.g.setAttribute('aria-label', label);
          it.tip.textContent = r.message;
          it.hit.setAttribute('x', 0);
          it.hit.setAttribute('y', -z.row / 2);
          it.hit.setAttribute('width', L.width);
          it.hit.setAttribute('height', r.h);
          focusables.push(it.g);
        }
        it.from = it.cur || { x: r.x, y: r.y, tx: r.tx, mx: r.msgX };
        it.to = { x: r.x, y: r.y, tx: r.tx, mx: r.msgX };

        r.flags.forEach(function (f) {
          seenFlags[f.key] = true;
          var fg = view.flags[f.key];
          if (!fg) {
            fg = view.flags[f.key] = { g: svgEl('g', {}, view.flagLayer) };
            if (live) fg.hit = svgEl('rect', { class: 'gg-hit' }, fg.g);
            fg.rect = svgEl('rect', { class: 'gg-pill' }, fg.g);
            fg.text = svgEl('text', { 'dominant-baseline': 'central' }, fg.g);
            if (live) fg.g.setAttribute('role', 'button');
            if (animate) fg.g.classList.add('is-new');
          }
          fg.g.setAttribute('class', 'gg-flag gg-flag-' + f.kind + (fg.g.classList.contains('is-new') ? ' is-new' : ''));
          fg.rect.setAttribute('x', 0);
          fg.rect.setAttribute('y', -z.flagH / 2);
          fg.rect.setAttribute('width', f.w);
          fg.rect.setAttribute('height', z.flagH);
          fg.rect.setAttribute('rx', f.kind === 'tag' ? 3 : z.flagH / 2);
          fg.text.setAttribute('x', 7);
          fg.text.textContent = f.text;
          if (live) {
            fg.hit.setAttribute('x', f.hit.x);
            fg.hit.setAttribute('y', f.hit.y);
            fg.hit.setAttribute('width', f.hit.w);
            fg.hit.setAttribute('height', f.hit.h);
            fg.g.setAttribute('data-insert', f.insert);
            fg.g.setAttribute('aria-label', fill(ui.flag_label, { name: f.text }));
            focusables.push(fg.g);
          }
          fg.from = fg.cur || { x: f.x, y: r.y };
          fg.to = { x: f.x, y: r.y };
        });
      });
      Object.keys(this.items).forEach(function (h) {
        if (!seen[h]) { view.rowLayer.removeChild(view.items[h].g); delete view.items[h]; }
      });
      Object.keys(this.flags).forEach(function (k) {
        if (!seenFlags[k]) { view.flagLayer.removeChild(view.flags[k].g); delete view.flags[k]; }
      });

      this.edgeLayer.textContent = '';
      this.edges = [];
      L.rows.forEach(function (r) {
        r.parents.forEach(function (p, i) {
          if (!view.items[p]) return;
          var lane = i === 0 ? r.lane : L.rows.filter(function (o) { return o.hash === p; })[0].lane;
          var path = svgEl('path', { class: 'gg-edge ' + (lane === 0 ? 'gg-l0' : 'gg-l1') + (r.lost ? ' is-lost' : '') }, view.edgeLayer);
          view.edges.push({ el: path, child: r.hash, parent: p, first: i === 0 });
        });
      });

      if (live) this.rove(focusables);

      function frame(t) {
        var e = 1 - Math.pow(1 - t, 3);
        Object.keys(view.items).forEach(function (h) {
          var it = view.items[h];
          var c = {};
          ['x', 'y', 'tx', 'mx'].forEach(function (k) { c[k] = it.from[k] + (it.to[k] - it.from[k]) * e; });
          it.cur = c;
          it.g.setAttribute('transform', 'translate(0 ' + c.y.toFixed(2) + ')');
          it.dot.setAttribute('transform', 'translate(' + c.x.toFixed(2) + ' 0)');
          it.hashText.setAttribute('x', c.tx.toFixed(2));
          it.msgText.setAttribute('x', c.mx.toFixed(2));
        });
        Object.keys(view.flags).forEach(function (k) {
          var fg = view.flags[k];
          var c = { x: fg.from.x + (fg.to.x - fg.from.x) * e, y: fg.from.y + (fg.to.y - fg.from.y) * e };
          fg.cur = c;
          fg.g.setAttribute('transform', 'translate(' + c.x.toFixed(2) + ' ' + c.y.toFixed(2) + ')');
        });
        view.edges.forEach(function (ed) {
          ed.el.setAttribute('d', edgePath(view.items[ed.child].cur, view.items[ed.parent].cur, ed.first, z.row));
        });
      }

      if (!animate || reduceMotion.matches) {
        frame(1);
        return;
      }
      var start = null;
      function step(now) {
        if (start === null) start = now;
        var t = Math.min(1, (now - start) / MOVE_MS);
        frame(t);
        if (t < 1) view.frameId = requestAnimationFrame(step);
      }
      frame(0);
      this.frameId = requestAnimationFrame(step);
    };

    // One tab stop for the whole graph; arrow keys walk commits and their flags.
    View.prototype.rove = function (list) {
      var keep = list.indexOf(this.active);
      if (keep < 0) keep = 0;
      list.forEach(function (node, i) { node.setAttribute('tabindex', i === keep ? '0' : '-1'); });
      this.focusables = list;
      this.active = list[keep] || null;
    };

    View.prototype.move = function (delta) {
      var list = this.focusables || [];
      var i = list.indexOf(document.activeElement);
      if (i < 0) return;
      var next = list[Math.max(0, Math.min(list.length - 1, i + delta))];
      list.forEach(function (node) { node.setAttribute('tabindex', node === next ? '0' : '-1'); });
      this.active = next;
      next.focus();
    };

    var progress = loadProgress(storage);
    var slidesLink = mountEl.querySelector('.gg-fallback a');
    var slides = slidesLink ? { href: slidesLink.getAttribute('href'), text: slidesLink.textContent } : null;

    mountEl.textContent = '';
    mountEl.classList.add('is-live');

    var strip = el('nav', 'gg-strip');
    strip.setAttribute('aria-label', ui.levels);
    var stripList = el('ol');
    strip.appendChild(stripList);
    var stripButtons = levels.map(function (lv, i) {
      var li = el('li');
      var b = button('gg-lv', String(i + 1), function () { loadLevel(i); });
      li.appendChild(b);
      stripList.appendChild(li);
      return b;
    });

    var board = el('div', 'gg-board');

    var brief = el('div', 'gg-brief');
    var count = el('p', 'gg-count');
    var title = el('h3', 'gg-title');
    var story = el('p', 'gg-story');
    var task = el('p', 'gg-task');
    var teaches = el('p', 'gg-teaches');
    var score = el('dl', 'gg-score');
    function scoreItem(label) {
      var wrap = el('div');
      wrap.appendChild(el('dt', '', label));
      var dd = el('dd');
      wrap.appendChild(dd);
      score.appendChild(wrap);
      return dd;
    }
    var scoreCount = scoreItem(ui.commands);
    var scorePar = scoreItem(ui.par);
    [count, title, story, task, teaches].forEach(function (n) { brief.appendChild(n); });
    var briefSide = el('div', 'gg-brief-side');
    briefSide.appendChild(score);
    brief.appendChild(briefSide);

    var stage = el('div', 'gg-stage');
    function pane(cls, label) {
      var p = el('div', 'gg-pane ' + cls);
      var head = el('div', 'gg-pane-head');
      var name = el('p', 'gg-pane-name', label);
      head.appendChild(name);
      p.appendChild(head);
      var frame = el('div', 'gg-frame');
      p.appendChild(frame);
      stage.appendChild(p);
      return { pane: p, head: head, frame: frame };
    }
    var livePane = pane('gg-pane-live', ui.your_graph);
    var goalPane = pane('gg-pane-goal', ui.goal);
    var goalToggle = button('gg-toggle', ui.show_goal, function () {
      var on = goalToggle.getAttribute('aria-pressed') !== 'true';
      goalToggle.setAttribute('aria-pressed', String(on));
      stage.classList.toggle('is-goal', on);
      drawGoal();
    });
    goalToggle.setAttribute('aria-pressed', 'false');
    stage.insertBefore(goalToggle, stage.firstChild);
    var liveDesc = el('p', 'sr-only');
    liveDesc.id = 'gg-live-desc';
    livePane.pane.appendChild(liveDesc);

    var liveView = new View(livePane.frame, 'live');
    var goalView = new View(goalPane.frame, 'goal');
    liveView.svg.setAttribute('role', 'group');
    liveView.svg.setAttribute('aria-label', ui.your_graph);
    liveView.svg.setAttribute('aria-describedby', liveDesc.id);
    goalView.svg.setAttribute('role', 'img');

    var card = el('div', 'gg-card');
    card.hidden = true;
    card.setAttribute('tabindex', '-1');

    var term = el('div', 'gg-term');
    var termHead = el('div', 'gg-term-head');
    termHead.appendChild(el('p', 'gg-pane-name', ui.terminal));
    var tools = el('div', 'gg-tools');
    [['hint', ui.hint], ['undo', ui.undo], ['restart', ui.restart]].forEach(function (t) {
      tools.appendChild(button('gg-tool', t[1], function () { submit(t[0]); }));
    });
    termHead.appendChild(tools);
    term.appendChild(termHead);
    var out = el('div', 'gg-out');
    term.appendChild(out);
    var more = button('gg-more', ui.more_output, function () {
      var open = !term.classList.contains('is-open');
      term.classList.toggle('is-open', open);
      more.textContent = open ? ui.less_output : ui.more_output;
      more.setAttribute('aria-expanded', String(open));
      out.scrollTop = out.scrollHeight;
    });
    more.setAttribute('aria-expanded', 'false');
    term.appendChild(more);

    var dock = el('form', 'gg-dock');
    dock.setAttribute('autocomplete', 'off');
    var line = el('div', 'gg-line');
    var prompt = el('label', 'gg-prompt');
    prompt.setAttribute('for', 'gg-input');
    var dollar = el('span', '', '$');
    dollar.setAttribute('aria-hidden', 'true');
    prompt.appendChild(dollar);
    prompt.appendChild(el('span', 'sr-only', ui.prompt));
    var input = el('input', 'gg-input');
    input.id = 'gg-input';
    input.type = 'text';
    input.placeholder = ui.placeholder;
    ['autocapitalize', 'autocorrect', 'autocomplete'].forEach(function (a) { input.setAttribute(a, 'off'); });
    input.setAttribute('spellcheck', 'false');
    input.setAttribute('enterkeyhint', 'go');
    var erase = button('gg-erase', '', eraseWord);
    erase.setAttribute('aria-label', ui.erase);
    erase.title = ui.erase;
    var eraseIcon = svgEl('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' }, erase);
    svgEl('path', { d: 'M9 5h11v14H9l-6-7z M13 9l5 6 M18 9l-5 6' }, eraseIcon);
    var run = el('button', 'gg-run', ui.run);
    run.type = 'submit';
    var dockNext = button('gg-run gg-dock-next', ui.next, function () { loadLevel(cur + 1); });
    line.appendChild(prompt);
    line.appendChild(input);
    line.appendChild(erase);
    line.appendChild(run);
    line.appendChild(dockNext);
    dock.appendChild(line);
    var cmdChips = el('div', 'gg-chips gg-cmds');
    cmdChips.setAttribute('role', 'group');
    cmdChips.setAttribute('aria-label', ui.builder_label);
    Object.keys(ui.builder).forEach(function (cmd) {
      var b = button('gg-chip', cmd, function () {
        input.value = 'git ' + cmd + ' ';
        syncBuilder();
      });
      b.dataset.cmd = cmd;
      cmdChips.appendChild(b);
    });
    var optChips = el('div', 'gg-chips gg-opts');
    optChips.setAttribute('role', 'group');
    optChips.setAttribute('aria-label', ui.options_label);
    dock.appendChild(cmdChips);
    dock.appendChild(optChips);

    var live = el('p', 'sr-only');
    live.setAttribute('aria-live', 'polite');

    board.appendChild(brief);
    board.appendChild(stage);
    board.appendChild(card);
    board.appendChild(term);
    board.appendChild(dock);
    mountEl.appendChild(strip);
    mountEl.appendChild(board);
    mountEl.appendChild(live);

    var cur = 0;
    var level = null;
    var play = null;
    var goal = null;
    var lanes = null;
    var goalLanes = null;
    var history = createHistory(HISTORY_MAX);
    var completer = createCompleter(E, ui);
    var greeted = false;
    var goals = {};

    function goalFor(i) {
      if (!goals[i]) {
        var state = goalOf(E, levels[i]);
        goals[i] = { state: state, lanes: assignLanes(initialLanes(E.fromCommands(levels[i].setup).state()), state) };
      }
      return goals[i];
    }

    function loadLevel(i, quiet) {
      cur = i;
      level = levels[i];
      var g = goalFor(i);
      goal = g.state;
      goalLanes = g.lanes;
      play = createPlay(E, ui, level, goal);
      lanes = initialLanes(play.repo.state());
      dock.classList.remove('is-solved');
      progress.level = i;
      saveProgress(storage, progress);

      count.textContent = fill(ui.level_of, { n: i + 1, total: levels.length });
      title.textContent = level.title;
      story.textContent = level.story;
      task.textContent = level.task;
      teaches.textContent = '';
      teaches.appendChild(el('span', 'gg-teaches-label', ui.teaches));
      level.teaches.forEach(function (t) { teaches.appendChild(el('code', 'gg-tag', t)); });
      scorePar.textContent = String(level.par);
      updateScore();
      updateStrip();
      card.hidden = true;
      card.textContent = '';
      out.textContent = '';
      print([fill(ui.welcome, { n: i + 1, title: level.title })], 'note');
      if (!greeted) {
        print([ui.welcome_help], 'note');
        greeted = true;
      }
      liveView.reset();
      goalView.reset();
      drawLive(false);
      drawGoal();
      input.value = '';
      syncBuilder();
      if (!quiet) mountEl.scrollIntoView({ block: 'start', behavior: reduceMotion.matches ? 'auto' : 'smooth' });
    }

    function updateScore() {
      scoreCount.textContent = String(play.used);
    }

    function updateStrip() {
      stripButtons.forEach(function (b, i) {
        var lv = levels[i];
        var rec = progress.solved[lv.id];
        b.classList.toggle('is-solved', !!rec);
        b.dataset.stars = rec ? String(rec.stars) : '0';
        if (i === cur) b.setAttribute('aria-current', 'step');
        else b.removeAttribute('aria-current');
        b.setAttribute('aria-label', rec
          ? fill(ui.level_button_solved, { n: i + 1, title: lv.title, stars: fill(ui.stars_label, { n: rec.stars, max: MAX_STARS }) })
          : fill(ui.level_button, { n: i + 1, title: lv.title }));
      });
    }

    function drawLive(animate) {
      var s = play.repo.state();
      assignLanes(lanes, s);
      liveView.draw(s, lanes, animate);
      liveDesc.textContent = describe(E, ui, s, false);
    }

    function drawGoal() {
      goalView.draw(goal, goalLanes, false);
      goalView.svg.setAttribute('aria-label', ui.goal + ': ' + describe(E, ui, goal, true));
    }

    function print(lines, kind) {
      lines.forEach(function (text) {
        var p = el('p', 'gg-o gg-o-' + kind, text);
        out.appendChild(p);
      });
      while (out.childNodes.length > OUTPUT_MAX) out.removeChild(out.firstChild);
      out.scrollTop = out.scrollHeight;
    }

    function announce(text) {
      live.textContent = text;
    }

    function submit(raw) {
      var step = play.submit(raw);
      if (!step) return;
      history.push(step.text);
      print([step.text], 'cmd');
      if (step.kind === 'meta') {
        meta(step.word);
      } else if (step.kind === 'undo') {
        print([step.note], 'note');
        announce(step.said);
        if (step.ok) {
          drawLive(true);
          syncDock();
        }
      } else {
        if (step.output.length) print(step.output, step.ok ? 'out' : 'err');
        if (step.hint) print([step.hint], 'note');
        if (step.changed) {
          updateScore();
          drawLive(true);
        }
        if (step.solvedNow) solved(step.stars);
        else if (step.changed) syncDock();
        announce(step.said);
      }
    }

    function meta(word) {
      if (word === 'help') {
        print(ui.help, 'out');
        announce(ui.help[0]);
      } else if (word === 'hint') {
        print([level.hint], 'note');
        announce(level.hint);
      } else if (word === 'restart') {
        var n = cur + 1;
        loadLevel(cur, true);
        print([fill(ui.restarted, { n: n })], 'note');
        announce(fill(ui.restarted, { n: n }));
      } else if (word === 'levels') {
        print(levels.map(function (lv, i) {
          var rec = progress.solved[lv.id];
          return fill(ui.levels_line, { n: i + 1, title: lv.title, stars: starText(rec ? rec.stars : 0) });
        }), 'out');
        announce(ui.levels);
      } else if (word === 'clear') {
        out.textContent = '';
      }
    }

    // The dock offers Next in Run's place only while the graph still matches;
    // a player who moves on after solving needs Run back.
    function syncDock() {
      dock.classList.toggle('is-solved', play.solved && cur < levels.length - 1 && play.onGoal());
    }

    function solved(stars) {
      recordSolve(progress, level.id, stars, play.used);
      saveProgress(storage, progress);
      updateStrip();
      showCard(stars);
    }

    function starRow(n, cls) {
      var row = el('p', cls);
      row.setAttribute('role', 'img');
      row.setAttribute('aria-label', fill(ui.stars_label, { n: n, max: MAX_STARS }));
      for (var i = 0; i < MAX_STARS; i++) {
        var s = svgEl('svg', { viewBox: '0 0 24 24', class: 'gg-star' + (i < n ? ' is-on' : ''), 'aria-hidden': 'true', focusable: 'false' }, row);
        s.style.setProperty('--i', String(i));
        svgEl('path', { d: 'M12 2.6l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.5l-5.9 3.1 1.2-6.5L2.5 9.5l6.6-.9z' }, s);
      }
      return row;
    }

    function showCard(stars) {
      card.textContent = '';
      var head = el('div', 'gg-card-head');
      head.appendChild(starRow(stars, 'gg-stars'));
      var words = el('div', 'gg-card-words');
      words.appendChild(el('p', 'gg-card-title', ui.solved));
      words.appendChild(el('p', 'gg-card-score', fill(ui.score_line, { commands: commands(play.used), par: level.par })));
      head.appendChild(words);
      card.appendChild(head);
      card.appendChild(el('p', 'gg-fact', level.fact.text));
      var link = el('a', 'gg-fact-link', has(ui.fact_links, level.fact.link) ? ui.fact_links[level.fact.link] : ui.fact_more);
      link.href = level.fact.link;
      card.appendChild(link);
      var actions = el('div', 'gg-card-actions');
      var focusTarget;
      if (cur < levels.length - 1) {
        focusTarget = button('gg-next', ui.next, function () { loadLevel(cur + 1); });
        actions.appendChild(focusTarget);
      }
      card.appendChild(actions);
      if (cur === levels.length - 1) {
        card.appendChild(summary());
        focusTarget = card;
      }
      card.hidden = false;
      card.classList.remove('is-in');
      void card.offsetWidth;
      card.classList.add('is-in');
      syncDock();
      // On a phone the dock carries Next in the thumb zone; moving focus there
      // would only scroll the page under the player's thumb.
      if (narrow.matches) card.scrollIntoView({ block: 'nearest', behavior: reduceMotion.matches ? 'auto' : 'smooth' });
      else focusTarget.focus();
    }

    function summary() {
      var t = totals(ui, levels, progress.solved);
      var box = el('div', 'gg-summary');
      box.appendChild(el('h4', 'gg-summary-title', ui.finish));
      box.appendChild(el('p', 'gg-rank', t.rank));
      var dl = el('dl', 'gg-summary-list');
      [[ui.summary_levels, fill(ui.of, { n: t.solved, total: t.total })],
        [ui.summary_commands, String(t.commands)],
        [ui.summary_par, String(t.par)],
        [ui.summary_stars, fill(ui.of, { n: t.stars, total: t.max })]].forEach(function (pair) {
        var d = el('div');
        d.appendChild(el('dt', '', pair[0]));
        d.appendChild(el('dd', '', pair[1]));
        dl.appendChild(d);
      });
      box.appendChild(dl);
      var text = resultText(ui, t, location.origin + location.pathname + '#play');
      var result = el('p', 'gg-result', text);
      result.id = 'gg-result';
      box.appendChild(result);
      var actions = el('div', 'gg-card-actions');
      var status = el('p', 'gg-copy-status');
      status.setAttribute('aria-live', 'polite');
      var copy = button('gg-next', ui.copy_result, function () {
        var done = function () { status.textContent = ui.copied; };
        var failed = function () { status.textContent = ui.copy_failed; };
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, failed);
          else failed();
        } catch (e) { failed(); }
      });
      actions.appendChild(copy);
      actions.appendChild(button('gg-tool', ui.again, function () { loadLevel(0); }));
      box.appendChild(actions);
      box.appendChild(status);
      var links = el('p', 'gg-links');
      if (slides) {
        var a = el('a', 'gg-link', slides.text);
        a.href = slides.href;
        links.appendChild(a);
      }
      var talks = el('a', 'gg-link', ui.talks_link);
      talks.href = ui.talks_url;
      links.appendChild(talks);
      box.appendChild(links);
      return box;
    }

    function insertToken(token, focus) {
      var v = input.value;
      var focused = document.activeElement === input;
      var at = focused && input.selectionStart !== null ? input.selectionStart : v.length;
      var end = focused && input.selectionEnd !== null ? input.selectionEnd : v.length;
      var head = v.slice(0, at);
      var tail = v.slice(end);
      if (!head) head = 'git ';
      if (!/\s$/.test(head)) head += ' ';
      var add = token + (/^\s/.test(tail) ? '' : ' ');
      input.value = head + add + tail;
      var caret = head.length + add.length;
      if (focus || focused) {
        input.focus();
        input.setSelectionRange(caret, caret);
      } else {
        input.scrollLeft = input.scrollWidth;
      }
      syncBuilder();
    }

    function eraseWord() {
      input.value = input.value.replace(/\S+\s*$/, '');
      if (input.value === 'git ') input.value = '';
      syncBuilder();
    }

    function syncBuilder() {
      var chips = builderChips(ui, goal, play.repo.state(), input.value);
      Array.prototype.forEach.call(cmdChips.children, function (b) {
        b.setAttribute('aria-pressed', String(b.dataset.cmd === chips.cmd));
      });
      optChips.textContent = '';
      chips.options.forEach(function (opt) {
        optChips.appendChild(button('gg-chip gg-chip-opt', opt, function () { insertToken(opt); }));
      });
      chips.names.forEach(function (n) {
        optChips.appendChild(button('gg-chip gg-chip-name', n, function () { insertToken(n); }));
      });
      optChips.hidden = !optChips.children.length;
    }

    function completeInput() {
      var shown = out.lastChild ? out.lastChild.textContent : null;
      var c = completer.press(play.repo.state(), input.value, input.selectionStart, shown);
      if (!c) return false;
      if (c.line) {
        print([c.line], 'out');
      } else {
        input.value = c.value;
        input.setSelectionRange(c.caret, c.caret);
        syncBuilder();
      }
      return true;
    }

    input.addEventListener('keydown', function (event) {
      var recalled = null;
      if (event.key === 'Tab' && !event.shiftKey && !event.altKey && !event.metaKey && !event.ctrlKey) {
        if (completeInput()) event.preventDefault();
        return;
      }
      if (event.key === 'ArrowUp') recalled = history.up(input.value);
      else if (event.key === 'ArrowDown') recalled = history.down();
      if (recalled === null) return;
      event.preventDefault();
      input.value = recalled;
      syncBuilder();
    });
    input.addEventListener('input', syncBuilder);

    dock.addEventListener('submit', function (event) {
      event.preventDefault();
      var text = input.value;
      input.value = '';
      submit(text);
      syncBuilder();
    });

    // A tap that focused the input would open the on-screen keyboard over the
    // graph; a mouse click should leave the focus where it was.
    [liveView.svg, dock].forEach(function (zone) {
      zone.addEventListener('pointerdown', function (event) {
        if (event.target.closest('button, [data-insert]') && document.activeElement === input) event.preventDefault();
      });
    });
    liveView.svg.addEventListener('pointerdown', function (event) {
      if (event.target.closest('[data-insert]')) event.preventDefault();
    });
    liveView.svg.addEventListener('click', function (event) {
      var target = event.target.closest('[data-insert]');
      if (target) insertToken(target.getAttribute('data-insert'));
    });
    liveView.svg.addEventListener('keydown', function (event) {
      var target = event.target.closest('[data-insert]');
      if (!target) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        insertToken(target.getAttribute('data-insert'), true);
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
        event.preventDefault();
        liveView.move(1);
      } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
        event.preventDefault();
        liveView.move(-1);
      }
    });
    liveView.svg.addEventListener('focusin', function (event) {
      var target = event.target.closest('[data-insert]');
      if (target) liveView.active = target;
    });

    var lastWidth = 0;
    function onResize() {
      var w = livePane.frame.clientWidth + 'x' + narrow.matches;
      if (w === lastWidth) return;
      lastWidth = w;
      drawLive(false);
      drawGoal();
    }
    if ('ResizeObserver' in window) new ResizeObserver(onResize).observe(stage);
    else window.addEventListener('resize', onResize);

    loadLevel(startLevel(progress, levels.length), true);
  }
})();
