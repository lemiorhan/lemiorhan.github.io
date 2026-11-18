'use strict';

// Driver for tests/test_git_game.py, and for the identityDiff tests in tests/test_git_engine.py.
// stdin: {"jobs": [job, ...]}; stdout: {"results": [result, ...]}.
//   {op: "exports"}                                      -> {names}
//   {op: "stars", cases: [[count, par], ...]}            -> {stars: [n, ...], margin, max}
//   {op: "goal", level}                                  -> {ok, state} | {ok: false, error}
//   {op: "play", ui, level, steps}                       -> {steps: [step + {used, solved, onGoal, state}]}
//      A {Message} token in a step becomes that commit's hash first, as a player reads it off the graph.
//   {op: "chips", ui, level, steps, values}              -> {chips: [builderChips(...) per value]}
//   {op: "progress", storage, initial, solves, level, ui, levels}
//      storage: memory | absent | missing | getter-throws | methods-throw
//   {op: "totals", ui, levels, solved}                   -> totals
//   {op: "result", ui, totals, url}                      -> {text}
//   {op: "sentences", ui, before, after}                 -> {text}
//   {op: "complete", ui, setup, cases: [[value, caret]]} -> {state, results}
//   {op: "completer", ui, setup, events}                 -> {results}
//      events: ["tab", value, caret, shown] presses Tab on one completer; ["run", line] changes the graph between presses.
//   {op: "history", max, ops: [[name, arg], ...]}        -> {results}
//   {op: "layout", ui, setup, kind, width, narrow}       -> layout
//   {op: "identity", setup, goal, attempt}               -> {ok, matches, diff, goal, attempt} | {ok: false, error}
//      goal and attempt are lines run after setup, and come back as the states they build.
var path = require('path');
var GitEngine = require(path.join(__dirname, '..', 'assets', 'git-engine.js'));
var GitGame = require(path.join(__dirname, '..', 'assets', 'git-game.js'));

function has(map, key) {
  return Object.prototype.hasOwnProperty.call(map, key);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function playThrough(job) {
  var goal = GitGame.goalOf(GitEngine, job.level);
  var play = GitGame.createPlay(GitEngine, job.ui, job.level, goal);
  var steps = (job.steps || []).map(function (raw) {
    var step = play.submit(GitEngine.resolve(raw, play.repo.state()));
    var seen = step ? clone(step) : { kind: null };
    seen.used = play.used;
    seen.solved = play.solved;
    seen.onGoal = play.onGoal();
    seen.state = play.repo.state();
    return seen;
  });
  return { goal: goal, play: play, steps: steps };
}

function build(setup, lines, label) {
  var repo = GitEngine.fromCommands(setup);
  lines.forEach(function (raw, i) {
    var r = repo.run(GitEngine.resolve(raw, repo.state()));
    if (!r.ok) throw new Error(label + ' line ' + (i + 1) + ' ' + JSON.stringify(raw) + ' failed: ' + r.output.join(' / '));
  });
  return repo.state();
}

function identityJob(job) {
  try {
    var goal = build(job.setup, job.goal, 'goal');
    var attempt = build(job.setup, job.attempt, 'attempt');
    return {
      ok: true, matches: GitEngine.matches(attempt, goal), diff: GitEngine.identityDiff(attempt, goal),
      goal: goal, attempt: attempt
    };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

function storageOf(kind, initial) {
  var map = clone(initial || {});
  var memory = {
    getItem: function (k) { return has(map, k) ? map[k] : null; },
    setItem: function (k, v) { map[k] = String(v); }
  };
  var refuse = function () { throw new Error('storage refused'); };
  var thunks = {
    memory: function () { return memory; },
    absent: undefined,
    missing: function () { return undefined; },
    'getter-throws': refuse,
    'methods-throw': function () { return { getItem: refuse, setItem: refuse }; }
  };
  if (!has(thunks, kind)) throw new Error('unknown storage ' + kind);
  return { thunk: thunks[kind], map: map };
}

function progressJob(job) {
  var store = storageOf(job.storage, job.initial);
  var progress = GitGame.loadProgress(store.thunk);
  var loaded = clone(progress);
  var start = GitGame.startLevel(progress, job.levels.length);
  (job.solves || []).forEach(function (s) {
    GitGame.recordSolve(progress, s[0], s[1], s[2]);
    GitGame.saveProgress(store.thunk, progress);
  });
  if (has(job, 'level')) {
    progress.level = job.level;
    GitGame.saveProgress(store.thunk, progress);
  }
  return {
    loaded: loaded,
    start: start,
    progress: progress,
    stored: store.map,
    reloaded: GitGame.loadProgress(store.thunk),
    totals: GitGame.totals(job.ui, job.levels, progress.solved)
  };
}

var ops = {
  exports: function () { return { names: Object.keys(GitGame).sort() }; },
  stars: function (job) {
    return {
      stars: job.cases.map(function (c) { return GitGame.starsFor(c[0], c[1]); }),
      margin: GitGame.STAR_MARGIN,
      max: GitGame.MAX_STARS
    };
  },
  goal: function (job) {
    try {
      return { ok: true, state: GitGame.goalOf(GitEngine, job.level) };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  },
  play: function (job) { return { steps: playThrough(job).steps }; },
  chips: function (job) {
    var p = playThrough(job);
    return {
      chips: job.values.map(function (v) { return GitGame.builderChips(job.ui, p.goal, p.play.repo.state(), v); })
    };
  },
  progress: progressJob,
  totals: function (job) { return GitGame.totals(job.ui, job.levels, job.solved); },
  result: function (job) { return { text: GitGame.resultText(job.ui, job.totals, job.url) }; },
  sentences: function (job) { return { text: GitGame.sentences(GitEngine, job.ui, job.before, job.after) }; },
  complete: function (job) {
    var state = GitEngine.fromCommands(job.setup).state();
    return {
      state: state,
      results: job.cases.map(function (c) { return GitGame.complete(GitEngine, job.ui, state, c[0], c[1]); })
    };
  },
  completer: function (job) {
    var repo = GitEngine.fromCommands(job.setup);
    var completer = GitGame.createCompleter(GitEngine, job.ui);
    return {
      results: job.events.map(function (e) {
        if (e[0] === 'run') return repo.run(e[1]).ok;
        if (e[0] !== 'tab') throw new Error('unknown completer event ' + e[0]);
        return completer.press(repo.state(), e[1], e[2], e[3]);
      })
    };
  },
  history: function (job) {
    var h = GitGame.createHistory(job.max);
    return {
      results: job.ops.map(function (o) {
        var r = h[o[0]](o[1]);
        return r === undefined ? null : r;
      })
    };
  },
  layout: function (job) {
    var state = GitEngine.fromCommands(job.setup).state();
    var lanes = GitGame.initialLanes(state);
    return GitGame.layout(GitEngine, job.ui, state, lanes, job.kind, job.width, job.narrow);
  },
  identity: identityJob
};

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function (chunk) { input += chunk; });
process.stdin.on('end', function () {
  var jobs = JSON.parse(input).jobs;
  var results = jobs.map(function (job) {
    if (!has(ops, job.op)) throw new Error('unknown op ' + job.op);
    return ops[job.op](job);
  });
  process.stdout.write(JSON.stringify({ results: results }));
});
