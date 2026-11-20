'use strict';

// Driver for tests/test_contact_dom.py. The contact page's ui-text island and its form go into a
// fresh tests/fake_dom.js document, and assets/site.js runs as a classic script whose globals are
// that page's window, as it does in a browser. Web3Forms is a fetch stub that answers with the reply
// last set, hCaptcha a stub that counts resets and, as the real one does, empties its answer on
// each, and FormData a stub that reads the named fields.
// stdin: {"tree": [node, ...], "script": path, "actions": [action, ...]}; stdout: {"results": [...]}
//   actions:
//     ["look"]                  what the form shows (see look below)
//     ["fill", name, text]      types text into the field of that name
//     ["token", text]           hCaptcha solved: its h-captcha-response field holds text
//     ["reply", kind, body]     how the next fetch ends: "json" with body, "not-json", or "reject"
//     ["submit"]                submits the form; gives whether it was prevented and look() at once
//     ["settle"]                lets every pending promise run
//     ["sent"]                  every request fetch was given: {url, method, headers, body}
var fs = require('fs');
var vm = require('vm');
var path = require('path');
var dom = require(path.join(__dirname, 'fake_dom.js'));

function fields(form) {
  return form.querySelectorAll('input, textarea').filter(function (n) {
    return n.getAttribute('name') && !n.hasAttribute('disabled');
  });
}

function look(form, state) {
  var values = {};
  fields(form).forEach(function (n) { values[n.getAttribute('name')] = n.value; });
  return {
    hidden: form.hidden,
    status: form.querySelector('.form-status').textContent,
    disabled: form.querySelector('.send').disabled,
    values: values,
    resets: state.resets
  };
}

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function (chunk) { input += chunk; });
process.stdin.on('end', async function () {
  var request = JSON.parse(input);
  var doc = dom.createDocument();
  request.tree.forEach(function (node) { dom.build(doc, doc.body, node); });
  var state = { resets: 0, reply: null, sent: [] };
  var w = dom.createWindow({
    storage: dom.createStorage({}), location: { origin: 'https://example.test', pathname: '/contact/' },
    hcaptcha: {
      reset: function () {
        state.resets++;
        var answer = doc.querySelector('textarea[name="h-captcha-response"]');
        if (answer) answer.value = '';
      }
    }
  });
  function fetch(url, options) {
    state.sent.push({ url: url, method: options.method, headers: options.headers, body: JSON.parse(options.body) });
    var reply = state.reply;
    if (!reply) throw new Error('fetch called with no reply set');
    if (reply.kind === 'reject') return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve({
      json: function () {
        return reply.kind === 'json' ? Promise.resolve(reply.body) : Promise.reject(new SyntaxError('Unexpected token'));
      }
    });
  }
  function FormData(form) {
    return fields(form).map(function (n) { return [n.getAttribute('name'), n.value]; });
  }
  var context = vm.createContext({
    window: w.window, document: doc, navigator: { clipboard: undefined }, fetch: fetch, FormData: FormData,
    requestAnimationFrame: w.window.requestAnimationFrame, cancelAnimationFrame: w.window.cancelAnimationFrame
  });
  vm.runInContext(fs.readFileSync(request.script, 'utf8'), context, { filename: request.script });
  w.flushFrames();
  var form = doc.querySelector('.contact-form');
  var results = [];
  for (var i = 0; i < request.actions.length; i++) {
    var a = request.actions[i];
    if (a[0] === 'look') {
      results.push(look(form, state));
    } else if (a[0] === 'fill') {
      var field = form.querySelector('[name="' + a[1] + '"]');
      if (!field) throw new Error('no field named ' + a[1]);
      field.value = a[2];
      results.push({});
    } else if (a[0] === 'token') {
      var box = form.querySelector('.h-captcha');
      var answer = box.querySelector('textarea');
      if (!answer) {
        answer = box.appendChild(doc.createElement('textarea'));
        answer.setAttribute('name', 'h-captcha-response');
      }
      answer.value = a[1];
      results.push({});
    } else if (a[0] === 'reply') {
      state.reply = { kind: a[1], body: a[2] };
      results.push({});
    } else if (a[0] === 'submit') {
      var fired = dom.fire(form, 'submit', {});
      results.push({ prevented: fired.prevented, at_once: look(form, state) });
    } else if (a[0] === 'settle') {
      await new Promise(function (resolve) { setImmediate(resolve); });
      results.push({});
    } else if (a[0] === 'sent') {
      results.push(state.sent);
    } else {
      throw new Error('unknown action ' + a[0]);
    }
  }
  process.stdout.write(JSON.stringify({ results: results }));
});
