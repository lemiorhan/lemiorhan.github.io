'use strict';

// Driver for tests/test_maze_game.py. stdin: {"jobs": [job, ...]}; stdout: {"results": [...]}.
//   {op: "maze", seed}                     -> {layout}: the maze a new game starts on
//   {op: "play", layout?, seed?, actions}  -> {looks: [look, ...], events: [type, ...]}
//     actions: ["steer", dir] | ["step", seconds] | ["look"] | ["restart"]
//              ["only", x, y]  keep the commit or test at (x, y) and remove every other one
var path = require('path');
var MazeGame = require(path.join(__dirname, '..', 'assets', 'maze-game.js'));

function look(g) {
  var p = MazeGame.where(g.player);
  return {
    mode: g.mode, score: g.score, lives: g.lives, level: g.level, left: g.left, layout: g.layout,
    player: { x: g.player.x, y: g.player.y, t: g.player.t, dir: g.player.dir, px: p.x, py: p.y },
    bugs: g.bugs.map(function (b) {
      var q = MazeGame.where(b);
      return { px: q.x, py: q.y, gone: b.gone, scared: b.scared, waiting: b.wait > 0 };
    })
  };
}

function play(job) {
  var g = MazeGame.create({ seed: job.seed, layout: job.layout });
  var looks = [], events = [];
  job.actions.forEach(function (a) {
    if (a[0] === 'steer') MazeGame.steer(g, a[1]);
    else if (a[0] === 'step') events = events.concat(MazeGame.step(g, a[1]).map(function (e) { return e.type; }));
    else if (a[0] === 'look') looks.push(look(g));
    else if (a[0] === 'restart') MazeGame.restart(g);
    else if (a[0] === 'only') {
      var keep = a[2] * g.w + a[1];
      g.items = g.items.map(function (item, i) { return i === keep ? item : null; });
      g.left = g.items[keep] ? 1 : 0;
    } else throw new Error('unknown action ' + a[0]);
  });
  return { looks: looks, events: events };
}

var input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
var results = input.jobs.map(function (job) {
  if (job.op === 'maze') return { layout: MazeGame.create({ seed: job.seed }).layout };
  if (job.op === 'play') return play(job);
  throw new Error('unknown op ' + job.op);
});
process.stdout.write(JSON.stringify({ results: results }));
