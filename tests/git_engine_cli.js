'use strict';

// Driver for tests/gitgraph.py. stdin: {"jobs": [job, ...]}; stdout: {"results": [result, ...]}.
//   {op: "run", lines}                     -> {ok, state} | {ok: false, index, output, before, state}
//   {op: "match", setup, goal, attempt}    -> {ok, matches} | {ok: false, error}
//   {op: "trace", lines}                   -> {steps: [{ok, output, changed, diff}], state, reachable}
//      "#snapshot" and "#restore" lines call repo.snapshot() / repo.restore() instead of run().
//   {op: "resolve", lines, line}           -> {ok, line} | {ok: false, error}
//   {op: "commands"}                       -> {commands}
var path = require('path');
var GitEngine = require(path.join(__dirname, '..', 'assets', 'git-engine.js'));

function run(lines) {
  var repo = GitEngine.createRepo();
  for (var i = 0; i < lines.length; i++) {
    var before = repo.state();
    var line;
    try {
      line = GitEngine.resolve(lines[i], before);
    } catch (e) {
      return { ok: false, index: i, output: [e.message], before: before, state: before };
    }
    var r = repo.run(line);
    if (!r.ok) return { ok: false, index: i, output: r.output, before: before, state: repo.state() };
  }
  return { ok: true, state: repo.state() };
}

function build(setup, lines, label) {
  var repo = GitEngine.fromCommands(setup);
  lines.forEach(function (raw, i) {
    var r = repo.run(GitEngine.resolve(raw, repo.state()));
    if (!r.ok) throw new Error(label + ' line ' + (i + 1) + ' ' + JSON.stringify(raw) + ' failed: ' + r.output.join(' / '));
  });
  return repo.state();
}

function match(job) {
  try {
    var goal = build(job.setup, job.goal, 'goal');
    var attempt = build(job.setup, job.attempt, 'attempt');
    return { ok: true, matches: GitEngine.matches(attempt, goal) };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

function trace(lines) {
  var repo = GitEngine.createRepo();
  var saved = null;
  var steps = lines.map(function (line) {
    var before = repo.state();
    var r;
    if (line === '#snapshot') {
      saved = repo.snapshot();
      r = { ok: true, output: [], changed: false };
    } else if (line === '#restore') {
      repo.restore(saved);
      r = { ok: true, output: [], changed: true };
    } else {
      r = repo.run(line);
    }
    r.diff = GitEngine.diff(before, repo.state());
    return r;
  });
  var state = repo.state();
  return { steps: steps, state: state, reachable: GitEngine.reachable(state) };
}

function resolveJob(job) {
  try {
    return { ok: true, line: GitEngine.resolve(job.line, run(job.lines).state) };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

var ops = {
  run: function (job) { return run(job.lines); },
  match: match,
  trace: function (job) { return trace(job.lines); },
  resolve: resolveJob,
  commands: function () { return { commands: GitEngine.COMMANDS }; }
};

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function (chunk) { input += chunk; });
process.stdin.on('end', function () {
  var jobs = JSON.parse(input).jobs;
  var results = jobs.map(function (job) {
    if (!ops[job.op]) throw new Error('unknown op ' + job.op);
    return ops[job.op](job);
  });
  process.stdout.write(JSON.stringify({ results: results }));
});
