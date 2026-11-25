'use strict';

// Driver for tests/test_to_top_dom.py. A page's ui-text island and its back-to-top link go into a
// fresh tests/fake_dom.js document, and assets/site.js runs as a classic script whose globals are
// that page's window, as it does in a browser. The window is 800px tall.
// stdin: {"tree": [node, ...], "script": path, "start": px, "loadDock": null | dock, "steps": [step, ...]}
// stdout: {"shown": [bool, ...]}
//   start: where the page already is when site.js runs, as after a reload far down it
//   loadDock: a dock built after site.js has run and before DOMContentLoaded, as git-game.js builds it
//   step: {"scrollY": px, "event": "scroll" | "resize", "dock": null | dock}
//   dock: {"top", "bottom", "position"} of the git game's .gg-dock form, built the first time.
//   The first answer is for the loaded page, then one per step.
var fs = require('fs');
var vm = require('vm');
var path = require('path');
var dom = require(path.join(__dirname, 'fake_dom.js'));

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function (chunk) { input += chunk; });
process.stdin.on('end', function () {
  var request = JSON.parse(input);
  var doc = dom.createDocument();
  request.tree.forEach(function (node) { dom.build(doc, doc.body, node); });
  var w = dom.createWindow({ storage: dom.createStorage({}), location: { origin: 'https://example.test', pathname: '/talks/' } });
  var context = vm.createContext({
    window: w.window, document: doc, navigator: { clipboard: undefined },
    requestAnimationFrame: w.window.requestAnimationFrame, cancelAnimationFrame: w.window.cancelAnimationFrame
  });
  w.setScrollY(request.start);
  vm.runInContext(fs.readFileSync(request.script, 'utf8'), context, { filename: request.script });

  function place(where) {
    var dock = doc.querySelector('.gg-dock');
    if (!dock) {
      dock = doc.createElement('form');
      dock.setAttribute('class', 'gg-dock');
      doc.body.appendChild(dock);
    }
    dock._.rect = { top: where.top, bottom: where.bottom, left: 0, right: 0 };
    dock._.computed = { position: where.position };
  }

  if (request.loadDock) place(request.loadDock);
  dom.fire(doc, 'DOMContentLoaded', {});
  w.flushFrames();
  var link = doc.querySelector('.to-top');
  var shown = [link.classList.contains('is-shown')];
  request.steps.forEach(function (step) {
    if (step.dock) place(step.dock);
    w.setScrollY(step.scrollY);
    w.emit(step.event || 'scroll');
    w.flushFrames();
    shown.push(link.classList.contains('is-shown'));
  });
  process.stdout.write(JSON.stringify({ shown: shown }));
});
