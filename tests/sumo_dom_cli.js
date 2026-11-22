'use strict';

// Driver for tests/test_sumo_dom.py. The sumo page's ui-text island and its .sumo-live block go into
// a fresh tests/fake_dom.js document, and assets/site.js runs as a classic script whose globals are
// that page's window, as it does in a browser. The clock is fixed at `now`, and fetch is a stub that
// answers each URL with its body in `responses` and rejects a URL it has no body for.
// stdin: {"tree": [node, ...], "script": path, "now": ms since the epoch, "responses": {url: body},
//         "fail": null | "reject" | an HTTP status}
//   fail: "reject" makes every fetch reject as a network error would; a status answers every
//   fetch with it.
// stdout: {"at_once": look, "settled": look, "requests": [url, ...]}
var fs = require('fs');
var vm = require('vm');
var path = require('path');
var dom = require(path.join(__dirname, 'fake_dom.js'));

function cell(node) {
  var rec = node.querySelector('.rec');
  var all = node.textContent;
  return rec ? all.slice(0, all.length - rec.textContent.length) + ' ' + rec.textContent : all;
}

function head(table) {
  return table.querySelectorAll('thead th').map(function (th) { return [th.textContent, th.getAttribute('scope')]; });
}

function look(box) {
  var status = box.querySelector('.sumo-status');
  var caption = box.querySelector('table.banzuke caption');
  var note = box.querySelector('.sumo-note');
  var leaders = box.querySelectorAll('table.leaders');
  return {
    order: box.children.map(function (c) { return c.className; }),
    status: status.hidden ? null : status.textContent,
    lists: box.querySelectorAll('dl').length,
    facts: box.querySelectorAll('dl div').map(function (row) {
      return [row.querySelector('dt').textContent, row.querySelector('dd').textContent];
    }),
    leaders: leaders.map(function (t) {
      return {
        caption: t.querySelector('caption').textContent,
        head: head(t),
        rows: t.querySelectorAll('tbody tr').map(function (tr) { return tr.children.map(function (c) { return c.textContent; }); }),
        row_heads: t.querySelectorAll('tbody th').map(function (th) { return th.getAttribute('scope'); })
      };
    }),
    caption: caption ? caption.textContent : null,
    head: box.querySelectorAll('table.banzuke').map(head)[0] || [],
    rows: box.querySelectorAll('table.banzuke tbody tr').map(function (tr) { return tr.children.map(cell); }),
    row_heads: box.querySelectorAll('table.banzuke tbody th').map(function (th) { return th.getAttribute('scope'); }),
    note: note ? note.textContent : null
  };
}

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function (chunk) { input += chunk; });
process.stdin.on('end', async function () {
  var request = JSON.parse(input);
  var doc = dom.createDocument();
  request.tree.forEach(function (node) { dom.build(doc, doc.body, node); });
  var w = dom.createWindow({ storage: dom.createStorage({}), location: { origin: 'https://example.test', pathname: '/sumo/' } });
  var requests = [];
  function fetch(url) {
    requests.push(url);
    if (request.fail === 'reject') return Promise.reject(new TypeError('Failed to fetch'));
    if (request.fail) return Promise.resolve({ ok: false, status: request.fail, json: function () { return Promise.resolve({}); } });
    if (!Object.prototype.hasOwnProperty.call(request.responses, url)) throw new Error('no response for ' + url);
    var body = request.responses[url];
    return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(body); } });
  }
  var context = vm.createContext({
    window: w.window, document: doc, navigator: { clipboard: undefined }, fetch: fetch,
    requestAnimationFrame: w.window.requestAnimationFrame, cancelAnimationFrame: w.window.cancelAnimationFrame
  });
  vm.runInContext('Date.now = function () { return ' + Number(request.now) + '; };', context);
  vm.runInContext(fs.readFileSync(request.script, 'utf8'), context, { filename: request.script });
  w.flushFrames();
  var box = doc.querySelector('.sumo-live');
  var atOnce = look(box);
  for (var i = 0; i < 50; i++) await new Promise(function (resolve) { setImmediate(resolve); });
  process.stdout.write(JSON.stringify({ at_once: atOnce, settled: look(box), requests: requests }));
});
