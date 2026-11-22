'use strict';

// Driver for tests/test_archive_dom.py. The talks page's ui-text island and its archive, map
// included, go into a fresh tests/fake_dom.js document, and assets/site.js runs as a classic script
// whose globals are that page's window, as it does in a browser.
// stdin: {"tree": [node, ...], "script": path, "actions": [action, ...]}; stdout: {"results": [...]}
//   actions:
//     ["look"]                 what the archive shows (see look below)
//     ["click", selector, i]   a click on the i-th element that matches selector
var fs = require('fs');
var vm = require('vm');
var path = require('path');
var dom = require(path.join(__dirname, 'fake_dom.js'));

function look(doc, scrolls) {
  var archive = doc.querySelector('.archive');
  function pressed(selector, key) {
    return archive.querySelectorAll(selector).filter(function (b) {
      return b.getAttribute('aria-pressed') === 'true';
    }).map(function (b) { return b.getAttribute(key); });
  }
  return {
    status: archive.querySelector('.filter-status').textContent,
    mapStatus: archive.querySelector('.tmap-status').textContent,
    cloudHidden: archive.querySelector('.themes').hidden,
    tagsHidden: archive.querySelectorAll('.ev-themes').map(function (tags) { return tags.hidden; }),
    emptyHidden: archive.querySelector('.empty-note').hidden,
    years: archive.querySelectorAll('section.year').filter(function (s) { return !s.hidden; }).map(function (s) { return s.id; }),
    events: archive.querySelectorAll('.ev').filter(function (ev) { return !ev.hidden; }).map(function (ev) {
      return {
        year: ev.closest('section.year').id,
        name: ev.querySelector('.ev-name').textContent,
        talks: ev.querySelectorAll('.ev-talks > li').map(function (li) { return !li.hidden; })
      };
    }),
    themes: pressed('button[data-theme]', 'data-theme'),
    media: pressed('.filters button', 'data-filter'),
    barHidden: archive.querySelector('.filter-bar').hidden,
    university: archive.querySelector('button[data-university]').getAttribute('aria-pressed'),
    scrolls: scrolls
  };
}

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
  vm.runInContext(fs.readFileSync(request.script, 'utf8'), context, { filename: request.script });
  w.flushFrames();
  var results = request.actions.map(function (a) {
    if (a[0] === 'look') return look(doc, w.scrolls());
    if (a[0] !== 'click') throw new Error('unknown action ' + a[0]);
    var target = doc.querySelectorAll(a[1])[a[2] || 0];
    if (!target) throw new Error('nothing matches ' + a[1] + ' at ' + (a[2] || 0));
    dom.fire(target, 'click', {});
    w.flushFrames();
    return {};
  });
  process.stdout.write(JSON.stringify({ results: results }));
});
