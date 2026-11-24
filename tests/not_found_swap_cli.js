'use strict';

// Driver for tests/test_not_found_swap.py: runs the language swap script of 404.html on a stub of the few DOM
// members it may use, and reports which language's text <main> holds afterwards, and <html lang> and the title.
// stdin: {"script", "pathname", "lang", "title", "templates": [{"lang", "title"}]}; stdout: {"main", "lang", "title"}.
var input = JSON.parse(require('fs').readFileSync(0, 'utf8'));

function only(want, got) {
  if (got !== want) throw new Error('the stub knows the selector ' + JSON.stringify(want) + ', not ' + JSON.stringify(got));
}

var main = { shows: input.lang, replaceChildren: function (content) { this.shows = content.lang; } };
var templates = input.templates.map(function (t) {
  return { dataset: { lang: t.lang, title: t.title }, content: { lang: t.lang } };
});
var document = {
  title: input.title,
  documentElement: { lang: input.lang },
  querySelectorAll: function (selector) { only('template[data-lang]', selector); return templates; },
  querySelector: function (selector) { only('main', selector); return main; }
};
new Function('document', 'location', input.script)(document, { pathname: input.pathname });
process.stdout.write(JSON.stringify({ main: main.shows, lang: document.documentElement.lang, title: document.title }));
