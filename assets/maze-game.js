(function (global) {
  'use strict';

  var DIRS = {
    up: { dx: 0, dy: -1 },
    left: { dx: -1, dy: 0 },
    down: { dx: 0, dy: 1 },
    right: { dx: 1, dy: 0 }
  };
  var ORDER = ['up', 'left', 'down', 'right'];
  var OPPOSITE = { up: 'down', down: 'up', left: 'right', right: 'left' };

  // Cells, not tiles: a board of COLS x ROWS cells is (2 COLS + 1) x (2 ROWS + 1) tiles. COLS is odd
  // so the middle column is its own mirror image.
  var COLS = 9;
  var ROWS = 10;
  var LIVES = 3;
  var POINTS = { dot: 10, power: 50, squash: 100 };
  var PLAYER_SPEED = 7.5;
  var HIT = 0.55;
  // Collisions are checked once a tick. HEAD and a bug closing head-on, at PLAYER_SPEED plus the
  // cap on g.bugSpeed, must close by less than 2 * HIT in one TICK, or they can pass through each
  // other unseen.
  var TICK = 1 / 120;
  var DYING = 1.2;
  var CLEARED = 1.6;
  var RESPAWN = 3;
  var LOOPS = 0.12;

  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function pick(rand, list) {
    return list[Math.floor(rand() * list.length)];
  }

  // A layout is an array of equal-length strings: # wall, . commit, o test, P start, B bug home.
  function generate(rand) {
    var w = 2 * COLS + 1, h = 2 * ROWS + 1, mid = (COLS - 1) / 2;
    var open = [];
    for (var i = 0; i < w * h; i++) open.push(false);
    function at(x, y) { return open[y * w + x]; }
    function carve(x, y) { open[y * w + x] = true; open[y * w + w - 1 - x] = true; }
    function inside(c) { return c[0] >= 0 && c[1] >= 0 && c[0] < COLS && c[1] < ROWS; }
    function around(c) {
      return ORDER.map(function (d) { return [c[0] + DIRS[d].dx, c[1] + DIRS[d].dy]; }).filter(inside);
    }
    function exits(c) {
      return around(c).filter(function (n) { return at(c[0] + n[0] + 1, c[1] + n[1] + 1); }).length;
    }

    // A spanning tree over the left half and its mirror image: each half is connected and both
    // contain the middle column, so the whole board is.
    var seen = {};
    var stack = [[mid, ROWS - 1]];
    seen[mid + ',' + (ROWS - 1)] = true;
    carve(2 * mid + 1, 2 * ROWS - 1);
    while (stack.length) {
      var top = stack[stack.length - 1];
      var next = around(top).filter(function (c) { return c[0] <= mid && !seen[c[0] + ',' + c[1]]; });
      if (!next.length) {
        stack.pop();
        continue;
      }
      var c = pick(rand, next);
      seen[c[0] + ',' + c[1]] = true;
      carve(2 * c[0] + 1, 2 * c[1] + 1);
      carve(top[0] + c[0] + 1, top[1] + c[1] + 1);
      stack.push(c);
    }

    for (var y = 1; y < h - 1; y++) {
      for (var x = 1; x <= (w - 1) / 2; x++) {
        if ((x + y) % 2 === 1 && !at(x, y) && rand() < LOOPS) carve(x, y);
      }
    }

    // Opening a wall only adds exits, so one pass leaves no dead end behind.
    for (var cy = 0; cy < ROWS; cy++) {
      for (var cx = 0; cx <= mid; cx++) {
        var cell = [cx, cy];
        if (exits(cell) > 1) continue;
        var shut = around(cell).filter(function (n) { return !at(cx + n[0] + 1, cy + n[1] + 1); });
        var dead = shut.filter(function (n) { return exits(n) === 1; });
        var n = pick(rand, dead.length ? dead : shut);
        carve(cx + n[0] + 1, cy + n[1] + 1);
      }
    }

    var mark = {};
    function put(c, ch) { mark[(2 * c[1] + 1) * w + 2 * c[0] + 1] = ch; }
    put([mid, ROWS - 1], 'P');
    [[mid, 0], [0, 0], [COLS - 1, 0], [mid, 2]].forEach(function (c) { put(c, 'B'); });
    var side = Math.floor(ROWS / 2) - 1;
    [[0, ROWS - 1], [COLS - 1, ROWS - 1], [0, side], [COLS - 1, side]].forEach(function (c) { put(c, 'o'); });

    var rows = [];
    for (var ry = 0; ry < h; ry++) {
      var row = '';
      for (var rx = 0; rx < w; rx++) row += at(rx, ry) ? (mark[ry * w + rx] || '.') : '#';
      rows.push(row);
    }
    return rows;
  }

  function passable(g, x, y) {
    return x >= 0 && y >= 0 && x < g.w && y < g.h && !g.wall[y * g.w + x];
  }

  function canGo(g, e, dir) {
    return passable(g, e.x + DIRS[dir].dx, e.y + DIRS[dir].dy);
  }

  function where(e) {
    var d = e.dir ? DIRS[e.dir] : { dx: 0, dy: 0 };
    return { x: e.x + d.dx * e.t, y: e.y + d.dy * e.t };
  }

  function create(opts) {
    opts = opts || {};
    var g = { rand: rng(opts.seed || 0), fixed: opts.layout || null, score: 0, lives: LIVES };
    level(g, 1);
    return g;
  }

  function restart(g) {
    g.score = 0;
    g.lives = LIVES;
    level(g, 1);
  }

  function level(g, n) {
    var layout = g.fixed || generate(g.rand);
    var homes = [];
    g.level = n;
    g.layout = layout;
    g.h = layout.length;
    g.w = layout[0].length;
    g.wall = [];
    g.items = [];
    g.left = 0;
    for (var y = 0; y < g.h; y++) {
      for (var x = 0; x < g.w; x++) {
        var ch = layout[y][x];
        g.wall.push(ch === '#');
        g.items.push(ch === '.' ? 'dot' : ch === 'o' ? 'power' : null);
        if (ch === '.' || ch === 'o') g.left++;
        if (ch === 'P') g.start = { x: x, y: y };
        if (ch === 'B') homes.push({ x: x, y: y });
      }
    }
    var hunt = Math.min(0.85, 0.55 + 0.08 * (n - 1));
    g.bugs = homes.slice(0, Math.min(2 + n, homes.length)).map(function (home, i) {
      return { home: home, aggression: Math.max(0.2, hunt - 0.15 * i) };
    });
    g.bugSpeed = Math.min(5.6 + 0.35 * (n - 1), 7.2);
    g.scaredSpeed = 3.6;
    g.powerTime = Math.max(3, 7 - 0.6 * (n - 1));
    g.release = Math.max(0.8, 2.5 - 0.25 * (n - 1));
    reset(g);
  }

  function reset(g) {
    g.mode = 'ready';
    g.player = { x: g.start.x, y: g.start.y, dir: null, t: 0, want: null, face: 'up' };
    g.power = 0;
    g.chain = 0;
    g.field = null;
    g.bugs.forEach(function (b, i) {
      b.x = b.home.x;
      b.y = b.home.y;
      b.dir = null;
      b.t = 0;
      b.scared = false;
      b.gone = false;
      b.wait = i * g.release;
    });
  }

  function go(g) {
    if (g.mode === 'ready') g.mode = 'playing';
  }

  function steer(g, dir) {
    if (!DIRS[dir] || (g.mode !== 'ready' && g.mode !== 'playing')) return;
    go(g);
    var p = g.player;
    p.want = dir;
    if (p.dir && dir === OPPOSITE[p.dir] && p.t > 0) {
      p.x += DIRS[p.dir].dx;
      p.y += DIRS[p.dir].dy;
      p.t = 1 - p.t;
      p.dir = dir;
      p.face = dir;
    } else if (p.dir && p.t === 0 && canGo(g, p, dir)) {
      // move() picks the next direction on arrival, so a player resting on a tile centre already
      // has one; without this the turn would wait a whole tile.
      p.dir = dir;
      p.face = dir;
    }
  }

  function step(g, dt) {
    var events = [];
    while (dt > 1e-9) {
      var h = Math.min(dt, TICK);
      tick(g, h, events);
      dt -= h;
    }
    return events;
  }

  function tick(g, h, events) {
    if (g.mode === 'dying' || g.mode === 'cleared') {
      g.timer -= h;
      if (g.timer > 0) return;
      if (g.mode === 'cleared') {
        level(g, g.level + 1);
        events.push({ type: 'level', level: g.level });
      } else {
        reset(g);
      }
      return;
    }
    if (g.mode !== 'playing') return;
    if (g.power > 0) {
      g.power -= h;
      if (g.power <= 0) {
        g.power = 0;
        g.bugs.forEach(function (b) { b.scared = false; });
      }
    }
    var p = g.player;
    move(g, p, PLAYER_SPEED * h, function () { return steerPlayer(g, p); }, function () { arrive(g, events); });
    if (g.mode !== 'playing') return;
    g.bugs.forEach(function (b) {
      if (b.wait > 0) {
        b.wait -= h;
        if (b.wait <= 0) b.gone = false;
        return;
      }
      move(g, b, (b.scared ? g.scaredSpeed : g.bugSpeed) * h, function () { return steerBug(g, b); });
    });
    collide(g, events);
  }

  function move(g, e, dist, choose, arrived) {
    while (dist > 1e-9) {
      if (!e.dir) {
        e.dir = choose();
        if (!e.dir) return;
      }
      var room = 1 - e.t;
      if (dist < room) {
        e.t += dist;
        return;
      }
      dist -= room;
      e.x += DIRS[e.dir].dx;
      e.y += DIRS[e.dir].dy;
      e.t = 0;
      if (arrived) {
        arrived();
        if (g.mode !== 'playing') return;
      }
      e.dir = choose();
    }
  }

  function steerPlayer(g, p) {
    var d = p.want && canGo(g, p, p.want) ? p.want : p.dir && canGo(g, p, p.dir) ? p.dir : null;
    if (d) p.face = d;
    return d;
  }

  function arrive(g, events) {
    var p = g.player, i = p.y * g.w + p.x, item = g.items[i];
    if (!item) return;
    g.items[i] = null;
    g.left--;
    g.score += POINTS[item];
    events.push({ type: item, x: p.x, y: p.y });
    if (item === 'power') {
      g.power = g.powerTime;
      g.chain = 0;
      g.bugs.forEach(function (b) { if (b.wait <= 0) b.scared = true; });
    }
    if (g.left === 0) {
      g.mode = 'cleared';
      g.timer = CLEARED;
      events.push({ type: 'cleared' });
    }
  }

  // Breadth-first distances from the player's tile, so bugs follow corridors, not straight lines.
  function distances(g) {
    var p = g.player, x = p.x, y = p.y;
    if (p.dir && p.t >= 0.5) {
      x += DIRS[p.dir].dx;
      y += DIRS[p.dir].dy;
    }
    var from = y * g.w + x;
    if (g.field && g.fieldFrom === from) return g.field;
    var far = g.w * g.h, field = [];
    for (var i = 0; i < far; i++) field.push(far);
    field[from] = 0;
    var queue = [from];
    for (var q = 0; q < queue.length; q++) {
      var at = queue[q], cx = at % g.w, cy = (at - cx) / g.w;
      for (var k = 0; k < ORDER.length; k++) {
        var nx = cx + DIRS[ORDER[k]].dx, ny = cy + DIRS[ORDER[k]].dy, j = ny * g.w + nx;
        if (passable(g, nx, ny) && field[j] === far) {
          field[j] = field[at] + 1;
          queue.push(j);
        }
      }
    }
    g.field = field;
    g.fieldFrom = from;
    return field;
  }

  function steerBug(g, b) {
    var ways = ORDER.filter(function (d) { return d !== OPPOSITE[b.dir] && canGo(g, b, d); });
    if (!ways.length) ways = ORDER.filter(function (d) { return canGo(g, b, d); });
    if (ways.length < 2) return ways[0] || null;
    var field = distances(g);
    function gap(d) { return field[(b.y + DIRS[d].dy) * g.w + b.x + DIRS[d].dx]; }
    function nearest(sign) {
      return ways.reduce(function (best, d) { return sign * gap(d) < sign * gap(best) ? d : best; });
    }
    var roll = g.rand();
    if (b.scared) return roll < 0.8 ? nearest(-1) : pick(g.rand, ways);
    return roll < b.aggression ? nearest(1) : pick(g.rand, ways);
  }

  function collide(g, events) {
    var p = where(g.player);
    for (var i = 0; i < g.bugs.length; i++) {
      var b = g.bugs[i];
      if (b.wait > 0) continue;
      var q = where(b);
      if (Math.hypot(p.x - q.x, p.y - q.y) >= HIT) continue;
      if (b.scared) {
        g.chain++;
        var points = POINTS.squash * g.chain;
        g.score += points;
        events.push({ type: 'squash', points: points, x: q.x, y: q.y });
        b.scared = false;
        b.gone = true;
        b.wait = RESPAWN;
        b.x = b.home.x;
        b.y = b.home.y;
        b.dir = null;
        b.t = 0;
        continue;
      }
      g.lives--;
      events.push({ type: 'caught' });
      if (g.lives === 0) {
        g.mode = 'over';
        events.push({ type: 'over' });
      } else {
        g.mode = 'dying';
        g.timer = DYING;
      }
      return;
    }
  }

  var MazeGame = { create: create, restart: restart, steer: steer, step: step, where: where, mount: mount };

  var KEYS = {
    ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
    w: 'up', a: 'left', s: 'down', d: 'right', W: 'up', A: 'left', S: 'down', D: 'right'
  };
  var SWIPE = 18;
  var BEST = 'maze-best';

  // `opts` goes to create: tests pass a drawn layout, the page leaves it out for a random maze.
  function mount(root, data, opts) {
    var ui = data.ui;
    var win = global, doc = global.document;
    var calm = win.matchMedia('(prefers-reduced-motion: reduce)');
    var scheme = win.matchMedia('(prefers-color-scheme: dark)');

    function el(tag, cls, text) {
      var n = doc.createElement(tag);
      if (cls) n.className = cls;
      if (text != null) n.textContent = text;
      return n;
    }

    var play = el('div', 'maze-play');
    var hud = el('p', 'maze-hud');
    function stat(label) {
      var s = el('span', 'maze-stat', label + ' ');
      var v = el('b');
      s.appendChild(v);
      hud.appendChild(s);
      return v;
    }
    var scoreOut = stat(ui.score), bestOut = stat(ui.best), levelOut = stat(ui.level), livesOut = stat(ui.lives);
    var board = el('div', 'maze-board');
    var canvas = el('canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', ui.board);
    var overlay = el('div', 'maze-overlay');
    var msg = el('p', 'maze-msg');
    msg.setAttribute('aria-live', 'polite');
    var button = el('button', 'maze-button');
    button.type = 'button';
    overlay.appendChild(msg);
    overlay.appendChild(button);
    board.appendChild(canvas);
    board.appendChild(overlay);
    var pad = el('div', 'maze-pad');
    [['left', ui.left, '←'], ['up', ui.up, '↑'], ['down', ui.down, '↓'], ['right', ui.right, '→']].forEach(function (k) {
      var b = el('button', 'maze-key', k[2]);
      b.type = 'button';
      b.setAttribute('aria-label', k[1]);
      b.addEventListener('pointerdown', function (e) {
        e.preventDefault();
        input(k[0]);
      });
      b.addEventListener('click', function (e) {
        if (e.detail === 0) input(k[0]);
      });
      pad.appendChild(b);
    });
    play.appendChild(hud);
    play.appendChild(board);
    play.appendChild(pad);
    root.appendChild(play);
    root.hidden = false;
    if (root.parentNode && root.parentNode.classList) root.parentNode.classList.add('has-maze');

    var g = create(opts || { seed: (Math.random() * 4294967296) >>> 0 });
    var ctx = canvas.getContext('2d');
    var started = false, paused = false, note = null, raf = 0, last = 0;
    var best = readBest(), popups = [], colors = {}, walls = null, tile = 0, dpr = 1;
    board.style.setProperty('aspect-ratio', g.w + ' / ' + g.h);

    function readBest() {
      try {
        return parseInt(win.localStorage.getItem(BEST), 10) || 0;
      } catch (e) {
        return 0;
      }
    }

    function saveBest() {
      try {
        win.localStorage.setItem(BEST, String(best));
      } catch (e) {}
    }

    function readColors() {
      var s = win.getComputedStyle(doc.documentElement);
      function v(name) { return s.getPropertyValue(name).trim(); }
      colors = {
        board: v('--paper-2'), wall: v('--maze-wall'), dot: v('--ink-soft'), head: v('--accent'),
        bug: v('--maze-bug'), scared: v('--maze-scared'), pass: v('--maze-pass'), ink: v('--ink')
      };
      walls = null;
    }

    function resize() {
      var w = board.clientWidth;
      if (w) {
        dpr = Math.min(win.devicePixelRatio || 1, 3);
        tile = w / g.w;
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(tile * g.h * dpr);
        walls = null;
      }
      render();
    }

    function isWall(x, y) {
      return x >= 0 && y >= 0 && x < g.w && y < g.h && g.wall[y * g.w + x];
    }

    function wallLayer() {
      var layer = doc.createElement('canvas');
      layer.width = canvas.width;
      layer.height = canvas.height;
      var c = layer.getContext('2d');
      c.setTransform(dpr * tile, 0, 0, dpr * tile, 0, 0);
      c.strokeStyle = colors.wall;
      c.lineWidth = 0.3;
      c.lineCap = 'round';
      c.beginPath();
      for (var y = 0; y < g.h; y++) {
        for (var x = 0; x < g.w; x++) {
          if (!isWall(x, y)) continue;
          var cx = x + 0.5, cy = y + 0.5;
          if (isWall(x + 1, y)) { c.moveTo(cx, cy); c.lineTo(cx + 1, cy); }
          if (isWall(x, y + 1)) { c.moveTo(cx, cy); c.lineTo(cx, cy + 1); }
          if (!isWall(x + 1, y) && !isWall(x, y + 1) && !isWall(x - 1, y) && !isWall(x, y - 1)) {
            c.moveTo(cx, cy);
            c.lineTo(cx + 0.01, cy);
          }
        }
      }
      c.stroke();
      return layer;
    }

    function drawTest(x, y, s) {
      ctx.fillStyle = colors.pass;
      ctx.beginPath();
      ctx.arc(x, y, 0.32 * s, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = colors.board;
      ctx.lineWidth = 0.09;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(x - 0.14 * s, y + 0.01 * s);
      ctx.lineTo(x - 0.04 * s, y + 0.11 * s);
      ctx.lineTo(x + 0.15 * s, y - 0.1 * s);
      ctx.stroke();
    }

    function drawBug(b, now, still) {
      if (b.gone) return;
      var q = where(b), d = DIRS[b.dir || 'down'];
      var blink = b.scared && g.power < 1.5 && !still && Math.floor(now / 160) % 2 === 1;
      var color = b.scared && !blink ? colors.scared : colors.bug;
      var wiggle = still || b.wait > 0 ? 0 : Math.sin(now / 55 + b.home.x) * 0.07;
      ctx.save();
      ctx.globalAlpha = b.wait > 0 ? 0.35 : 1;
      ctx.translate(q.x + 0.5, q.y + 0.5);
      ctx.rotate(Math.atan2(d.dy, d.dx) + Math.PI / 2);
      ctx.strokeStyle = color;
      ctx.lineWidth = 0.06;
      ctx.lineCap = 'round';
      ctx.beginPath();
      [-0.1, 0.05, 0.2].forEach(function (ly, k) {
        var sway = k % 2 ? -wiggle : wiggle;
        ctx.moveTo(-0.15, ly);
        ctx.lineTo(-0.36, ly - 0.07 + sway);
        ctx.moveTo(0.15, ly);
        ctx.lineTo(0.36, ly - 0.07 - sway);
      });
      ctx.moveTo(-0.05, -0.32);
      ctx.lineTo(-0.15, -0.44);
      ctx.moveTo(0.05, -0.32);
      ctx.lineTo(0.15, -0.44);
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.ellipse(0, 0.06, 0.2, 0.27, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(0, -0.25, 0.11, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = colors.board;
      ctx.lineWidth = 0.035;
      ctx.beginPath();
      ctx.moveTo(0, -0.16);
      ctx.lineTo(0, 0.31);
      ctx.stroke();
      ctx.restore();
    }

    function drawHead() {
      if (g.mode === 'over') return;
      var p = where(g.player), d = DIRS[g.player.face];
      var s = g.mode === 'dying' ? Math.max(0, g.timer / DYING) : 1;
      if (!s) return;
      ctx.save();
      ctx.translate(p.x + 0.5, p.y + 0.5);
      ctx.scale(s, s);
      ctx.fillStyle = colors.head;
      ctx.beginPath();
      ctx.arc(0, 0, 0.4, 0, Math.PI * 2);
      ctx.fill();
      ctx.rotate(Math.atan2(d.dy, d.dx));
      ctx.strokeStyle = colors.board;
      ctx.lineWidth = 0.1;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(-0.07, -0.16);
      ctx.lineTo(0.11, 0);
      ctx.lineTo(-0.07, 0.16);
      ctx.stroke();
      ctx.restore();
    }

    function draw(now) {
      if (!tile || !ctx) return;
      var still = calm.matches;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!walls) walls = wallLayer();
      ctx.drawImage(walls, 0, 0);
      ctx.setTransform(dpr * tile, 0, 0, dpr * tile, 0, 0);
      ctx.strokeStyle = colors.dot;
      ctx.lineWidth = 0.07;
      ctx.beginPath();
      for (var i = 0; i < g.items.length; i++) {
        if (g.items[i] !== 'dot') continue;
        var x = i % g.w + 0.5, y = Math.floor(i / g.w) + 0.5;
        ctx.moveTo(x + 0.12, y);
        ctx.arc(x, y, 0.12, 0, Math.PI * 2);
      }
      ctx.stroke();
      var pulse = still ? 1 : 1 + 0.08 * Math.sin(now / 170);
      for (var j = 0; j < g.items.length; j++) {
        if (g.items[j] === 'power') drawTest(j % g.w + 0.5, Math.floor(j / g.w) + 0.5, pulse);
      }
      g.bugs.forEach(function (b) { drawBug(b, now, still); });
      drawHead();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = colors.ink;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.font = '700 ' + Math.max(11, Math.round(tile * 0.7)) + 'px ui-monospace, SFMono-Regular, Menlo, monospace';
      popups = popups.filter(function (u) { return u.until > now; });
      popups.forEach(function (u) {
        var rise = still ? 0 : (1 - (u.until - now) / 900) * 0.8;
        ctx.fillText(u.text, (u.x + 0.5) * tile, (u.y + 0.5 - rise) * tile);
      });
    }

    function render(now) {
      if (now === undefined) now = win.performance.now();
      if (g.score > best) {
        best = g.score;
        saveBest();
      }
      scoreOut.textContent = String(g.score);
      bestOut.textContent = String(best);
      levelOut.textContent = String(g.level);
      livesOut.textContent = String(g.lives);
      var text = null, label = null;
      if (paused) {
        text = ui.paused;
        label = ui.resume;
      } else if (g.mode === 'over') {
        text = ui.over;
        label = ui.again;
      } else if (g.mode === 'cleared') {
        text = ui.cleared;
      } else if (g.mode === 'ready') {
        text = started ? note : ui.start;
        label = started ? null : ui.play;
      }
      overlay.hidden = !text;
      if (msg.textContent !== (text || '')) msg.textContent = text || '';
      button.hidden = !label;
      button.textContent = label || '';
      draw(now);
    }

    function running() {
      return !paused && (g.mode === 'playing' || g.mode === 'dying' || g.mode === 'cleared');
    }

    function frame(now) {
      raf = 0;
      if (!running()) {
        last = 0;
        render(now);
        return;
      }
      var dt = last ? Math.min((now - last) / 1000, 0.05) : 0;
      last = now;
      step(g, dt).forEach(function (e) {
        if (e.type === 'squash') popups.push({ x: e.x, y: e.y, text: '+' + e.points, until: now + 900 });
        if (e.type === 'caught') note = ui.caught;
        if (e.type === 'level') {
          note = ui.next;
          walls = null;
        }
      });
      render(now);
      if (running()) raf = win.requestAnimationFrame(frame);
      else last = 0;
    }

    function kick() {
      render();
      if (running() && !raf) {
        last = 0;
        raf = win.requestAnimationFrame(frame);
      }
    }

    function begin() {
      if (started) return;
      started = true;
      root.classList.add('is-on');
      var r = play.getBoundingClientRect();
      if (r.top < 0 || r.bottom > win.innerHeight) {
        play.scrollIntoView({ block: 'nearest', behavior: calm.matches ? 'auto' : 'smooth' });
      }
    }

    function input(dir) {
      begin();
      paused = false;
      steer(g, dir);
      kick();
    }

    function pause() {
      if (!running()) return;
      paused = true;
      if (raf) win.cancelAnimationFrame(raf);
      raf = 0;
      last = 0;
      render();
    }

    button.addEventListener('click', function () {
      if (paused) {
        paused = false;
      } else {
        if (g.mode === 'over') restart(g);
        begin();
        walls = null;
        go(g);
      }
      kick();
    });

    doc.addEventListener('keydown', function (e) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      var dir = KEYS[e.key];
      if (!dir) {
        if ((e.key === 'p' || e.key === 'P' || e.key === 'Escape') && started && g.mode !== 'over') {
          e.preventDefault();
          if (paused) {
            paused = false;
            kick();
          } else {
            pause();
          }
        }
        return;
      }
      if (g.mode === 'over') return;
      if (!started) {
        var r = board.getBoundingClientRect();
        if (r.bottom <= 0 || r.top >= win.innerHeight) return;
      }
      e.preventDefault();
      input(dir);
    });

    var anchor = null;
    board.addEventListener('pointerdown', function (e) {
      if (e.target !== canvas) return;
      anchor = { x: e.clientX, y: e.clientY, id: e.pointerId };
    });
    board.addEventListener('pointermove', function (e) {
      if (!anchor || e.pointerId !== anchor.id) return;
      var dx = e.clientX - anchor.x, dy = e.clientY - anchor.y, sideways = Math.abs(dx) > Math.abs(dy);
      if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE) return;
      // Before the game starts an up or down drag scrolls the page (the board's touch-action), and
      // a quick flick can pass SWIPE before the browser cancels it.
      if (!started && !sideways) return;
      e.preventDefault();
      anchor.x = e.clientX;
      anchor.y = e.clientY;
      input(sideways ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up'));
    });
    ['pointerup', 'pointercancel'].forEach(function (type) {
      board.addEventListener(type, function () { anchor = null; });
    });

    doc.addEventListener('visibilitychange', function () {
      if (doc.hidden) pause();
    });
    win.addEventListener('blur', pause);
    function retheme() {
      readColors();
      render();
    }
    if ('addEventListener' in scheme) scheme.addEventListener('change', retheme);
    if ('ResizeObserver' in win) new win.ResizeObserver(resize).observe(board);
    else win.addEventListener('resize', resize);

    readColors();
    resize();
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = MazeGame;
    return;
  }
  var root = global.document && global.document.querySelector('[data-maze]');
  var island = root && global.document.getElementById('maze-data');
  if (island) mount(root, JSON.parse(island.textContent));
})(typeof window !== 'undefined' ? window : this);
