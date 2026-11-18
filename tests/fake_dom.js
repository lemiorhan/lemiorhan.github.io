'use strict';

// A DOM double for tests/git_game_dom_cli.js, written by hand for what assets/git-game.js
// uses. There is no layout: every box measures 0. Reading, writing or calling anything this
// file does not define throws, and so do selectors, media queries, event types and namespaces
// it does not know, so page code that needs more DOM fails the smoke test instead of running
// on `undefined`. An exception in a listener reaches the caller.

var SVG_NS = 'http://www.w3.org/2000/svg';
var EVENTS = { click: 'mouse', pointerdown: 'mouse', keydown: 'key', input: 'plain', submit: 'plain', focusin: 'plain' };
var FOCUSABLE = { a: true, button: true, input: true };

function has(map, key) {
  return Object.prototype.hasOwnProperty.call(map, key);
}

function setterOf(target, key) {
  for (var o = target; o; o = Object.getPrototypeOf(o)) {
    var d = Object.getOwnPropertyDescriptor(o, key);
    if (d) return d.set || null;
  }
  return null;
}

function strict(target, name) {
  return new Proxy(target, {
    get: function (t, key, receiver) {
      if (typeof key === 'symbol' || key in t) return Reflect.get(t, key, receiver);
      throw new Error('fake DOM: ' + name + ' has no ' + key);
    },
    set: function (t, key, value, receiver) {
      if (typeof key === 'symbol' || !setterOf(t, key)) throw new Error('fake DOM: cannot set ' + name + '.' + String(key));
      return Reflect.set(t, key, value, receiver);
    }
  });
}

function isElement(node) {
  return !!node && has(node._, 'tag');
}

// tags: the HTML elements that have `member`, or null for every HTML element.
function only(node, tags, member) {
  if (node._.svg || (tags && tags.indexOf(node._.tag) < 0)) throw new Error('fake DOM: <' + node._.tag + '> has no ' + member);
}

var COMPOUND = /^([a-z][a-z0-9-]*)?((?:\.[\w-]+|#[\w-]+|\[[\w-]+(?:="[^"]*")?\])*)$/i;

function compile(selector) {
  return String(selector).split(',').map(function (part) {
    return part.trim().split(/\s+/).map(function (text) {
      var m = COMPOUND.exec(text);
      if (!text || !m) throw new Error('fake DOM: unsupported selector ' + JSON.stringify(String(selector)));
      var c = { tag: m[1] ? m[1].toLowerCase() : null, classes: [], ids: [], attrs: [] };
      m[2].replace(/\.([\w-]+)|#([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g, function (all, cls, id, attr, value) {
        if (cls) c.classes.push(cls);
        else if (id) c.ids.push(id);
        else c.attrs.push([attr, value]);
        return all;
      });
      return c;
    });
  });
}

function matchesCompound(node, c) {
  if (c.tag && node._.tag.toLowerCase() !== c.tag) return false;
  var classes = (node._.attrs['class'] || '').split(/\s+/);
  return c.classes.every(function (n) { return classes.indexOf(n) >= 0; }) &&
    c.ids.every(function (id) { return node._.attrs.id === id; }) &&
    c.attrs.every(function (a) { return has(node._.attrs, a[0]) && (a[1] === undefined || node._.attrs[a[0]] === a[1]); });
}

function matches(node, compiled) {
  return compiled.some(function (chain) {
    if (!matchesCompound(node, chain[chain.length - 1])) return false;
    var i = chain.length - 2;
    for (var up = node._.parent; up && i >= 0; up = up._.parent) {
      if (matchesCompound(up, chain[i])) i--;
    }
    return i < 0;
  });
}

function descendants(node, out) {
  node._.children.forEach(function (c) {
    if (!isElement(c)) return;
    out.push(c);
    descendants(c, out);
  });
  return out;
}

function detach(node) {
  var parent = node._.parent;
  if (parent) parent._.children.splice(parent._.children.indexOf(node), 1);
  node._.parent = null;
}

class FakeNode {
  constructor(doc) {
    this._ = { doc: doc, parent: null };
  }

  get parentNode() { return this._.parent; }
}

class Text extends FakeNode {
  constructor(doc, data) {
    super(doc);
    this._.data = String(data);
  }

  get textContent() { return this._.data; }
  set textContent(value) { this._.data = String(value); }
}

class Element extends FakeNode {
  constructor(doc, tag, svg) {
    super(doc);
    Object.assign(this._, { tag: tag, svg: svg, attrs: {}, children: [], listeners: {}, style: {}, scrollTop: 0, scrollLeft: 0 });
  }

  get childNodes() { return this._.children.slice(); }
  get children() { return this._.children.filter(isElement); }
  get firstChild() { return this._.children[0] || null; }
  get lastChild() { return this._.children[this._.children.length - 1] || null; }

  appendChild(child) {
    detach(child);
    child._.parent = this;
    this._.children.push(child);
    return child;
  }

  insertBefore(child, ref) {
    if (ref === null) return this.appendChild(child);
    if (this._.children.indexOf(ref) < 0) throw new Error('fake DOM: insertBefore with a node that is not a child');
    detach(child);
    child._.parent = this;
    this._.children.splice(this._.children.indexOf(ref), 0, child);
    return child;
  }

  removeChild(child) {
    if (this._.children.indexOf(child) < 0) throw new Error('fake DOM: removeChild with a node that is not a child');
    detach(child);
    return child;
  }

  get textContent() {
    return this._.children.map(function (c) { return c.textContent; }).join('');
  }

  set textContent(value) {
    this._.children.slice().forEach(detach);
    if (String(value) !== '') this.appendChild(text(this._.doc, value));
  }

  setAttribute(name, value) { this._.attrs[name] = String(value); }
  getAttribute(name) { return has(this._.attrs, name) ? this._.attrs[name] : null; }
  removeAttribute(name) { delete this._.attrs[name]; }

  get className() { only(this, null, 'className'); return this.getAttribute('class') || ''; }
  set className(value) { only(this, null, 'className'); this.setAttribute('class', value); }
  get id() { return this.getAttribute('id') || ''; }
  set id(value) { this.setAttribute('id', value); }
  get hidden() { only(this, null, 'hidden'); return this.getAttribute('hidden') !== null; }
  set hidden(value) {
    only(this, null, 'hidden');
    if (value) this.setAttribute('hidden', '');
    else this.removeAttribute('hidden');
  }
  get title() { only(this, null, 'title'); return this.getAttribute('title') || ''; }
  set title(value) { only(this, null, 'title'); this.setAttribute('title', value); }
  get type() { only(this, ['button', 'input'], 'type'); return this.getAttribute('type') || ''; }
  set type(value) { only(this, ['button', 'input'], 'type'); this.setAttribute('type', value); }
  get placeholder() { only(this, ['input'], 'placeholder'); return this.getAttribute('placeholder') || ''; }
  set placeholder(value) { only(this, ['input'], 'placeholder'); this.setAttribute('placeholder', value); }
  get href() { throw new Error('fake DOM: <' + this._.tag + '>.href would be a resolved URL; read getAttribute("href")'); }
  set href(value) { only(this, ['a'], 'href'); this.setAttribute('href', value); }

  get classList() {
    var node = this;
    function names() { return (node.getAttribute('class') || '').split(/\s+/).filter(Boolean); }
    function add(name) { var n = names(); if (n.indexOf(name) < 0) node.setAttribute('class', n.concat([name]).join(' ')); }
    function remove(name) { node.setAttribute('class', names().filter(function (n) { return n !== name; }).join(' ')); }
    return strict({
      add: function (name) { add(name); },
      remove: function (name) { remove(name); },
      contains: function (name) { return names().indexOf(name) >= 0; },
      toggle: function (name, force) {
        var on = force === undefined ? names().indexOf(name) < 0 : !!force;
        if (on) add(name);
        else remove(name);
        return on;
      }
    }, 'classList');
  }

  get dataset() {
    var node = this;
    function attr(key) {
      if (typeof key !== 'string') throw new Error('fake DOM: dataset has no ' + String(key));
      return 'data-' + key.replace(/[A-Z]/g, function (c) { return '-' + c.toLowerCase(); });
    }
    return new Proxy({}, {
      get: function (t, key) { var v = node.getAttribute(attr(key)); return v === null ? undefined : v; },
      set: function (t, key, value) { node.setAttribute(attr(key), value); return true; }
    });
  }

  get style() {
    var props = this._.style;
    return strict({ setProperty: function (name, value) { props[name] = String(value); } }, 'style');
  }

  addEventListener(type, listener) {
    if (arguments.length > 2) throw new Error('fake DOM: addEventListener options are not supported');
    if (!has(EVENTS, type)) throw new Error('fake DOM: no ' + type + ' events');
    (this._.listeners[type] = this._.listeners[type] || []).push(listener);
  }

  closest(selector) {
    var compiled = compile(selector);
    for (var node = this; node; node = node._.parent) {
      if (matches(node, compiled)) return node;
    }
    return null;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    var compiled = compile(selector);
    return descendants(this, []).filter(function (n) { return matches(n, compiled); });
  }

  focus() {
    var tag = this._.tag;
    var focusable = this.getAttribute('tabindex') !== null || (has(FOCUSABLE, tag) && (tag !== 'a' || this.getAttribute('href') !== null));
    if (!focusable) throw new Error('fake DOM: <' + tag + '> cannot take focus');
    if (this._.doc._.active === this) return;
    this._.doc._.active = this;
    fire(this, 'focusin', {});
  }

  scrollIntoView() { this._.doc._.scrolls++; }

  get scrollTop() { return this._.scrollTop; }
  set scrollTop(value) { this._.scrollTop = Number(value); }
  get scrollLeft() { return this._.scrollLeft; }
  set scrollLeft(value) { this._.scrollLeft = Number(value); }
  get scrollHeight() { return 0; }
  get scrollWidth() { return 0; }
  get clientWidth() { return 0; }
  get offsetWidth() { return 0; }

  get value() { only(this, ['input'], 'value'); return this._.value || ''; }
  set value(v) {
    only(this, ['input'], 'value');
    this._.value = String(v);
    this._.selStart = this._.selEnd = this._.value.length;
  }
  get selectionStart() { only(this, ['input'], 'selectionStart'); return this._.selStart || 0; }
  get selectionEnd() { only(this, ['input'], 'selectionEnd'); return this._.selEnd || 0; }
  setSelectionRange(start, end) {
    only(this, ['input'], 'setSelectionRange');
    var length = this.value.length;
    this._.selStart = Math.min(start, length);
    this._.selEnd = Math.min(end, length);
  }
}

function text(doc, data) {
  return strict(new Text(doc, data), '#text');
}

function element(doc, tag, svg) {
  return strict(new Element(doc, tag, svg), '<' + tag + '>');
}

class Document {
  constructor() {
    this._ = { active: null, body: null, handled: 0, scrolls: 0 };
  }

  get body() { return this._.body; }
  get activeElement() { return this._.active || this._.body; }

  createElement(tag) { return element(this, String(tag).toLowerCase(), false); }

  createElementNS(ns, tag) {
    if (ns !== SVG_NS) throw new Error('fake DOM: unsupported namespace ' + ns);
    return element(this, String(tag), true);
  }

  getElementById(id) {
    return descendants(this._.body, []).filter(function (n) { return n._.attrs.id === id; })[0] || null;
  }

  querySelector(selector) { return this._.body.querySelector(selector); }
}

function createDocument() {
  var raw = new Document();
  var doc = strict(raw, 'document');
  raw._.body = element(doc, 'body', false);
  return doc;
}

// Dispatches an event that bubbles from `target` up its ancestors, the way every event the game
// listens for does, and returns whether a listener prevented the default and how many ran.
function fire(target, type, init) {
  if (!has(EVENTS, type)) throw new Error('fake DOM: no ' + type + ' events');
  var prevented = false;
  var raw = {
    get type() { return type; },
    get target() { return target; },
    get defaultPrevented() { return prevented; },
    preventDefault: function () { prevented = true; }
  };
  if (EVENTS[type] !== 'plain') {
    ['shiftKey', 'altKey', 'metaKey', 'ctrlKey'].forEach(function (k) {
      Object.defineProperty(raw, k, { get: function () { return !!init[k]; }, enumerable: true });
    });
  }
  if (EVENTS[type] === 'key') Object.defineProperty(raw, 'key', { get: function () { return init.key; }, enumerable: true });
  var event = strict(raw, type + ' event');
  var handled = 0;
  for (var node = target; node; node = node._.parent) {
    (node._.listeners[type] || []).slice().forEach(function (listener) {
      listener.call(node, event);
      handled++;
    });
  }
  target._.doc._.handled += handled;
  return { prevented: prevented, handled: handled };
}

// options: {narrow, reduceMotion, storage, location: {origin, pathname}}.
function createWindow(options) {
  var media = { '(max-width: 40rem)': !!options.narrow, '(prefers-reduced-motion: reduce)': !!options.reduceMotion };
  var frames = [];
  var lastFrame = 0;
  var clock = 0;
  var engine;
  var resize = [];
  var location = strict({ origin: options.location.origin, pathname: options.location.pathname }, 'location');
  var raw = {
    get GitEngine() { return engine; },
    set GitEngine(value) { engine = value; },
    get localStorage() { return options.storage; },
    get location() { return location; },
    matchMedia: function (query) {
      if (!has(media, query)) throw new Error('fake DOM: unsupported media query ' + query);
      return strict({ get matches() { return media[query]; } }, 'MediaQueryList');
    },
    requestAnimationFrame: function (callback) {
      frames.push({ id: ++lastFrame, callback: callback });
      return lastFrame;
    },
    cancelAnimationFrame: function (id) {
      frames = frames.filter(function (f) { return f.id !== id; });
    },
    addEventListener: function (type, listener) {
      if (arguments.length > 2 || type !== 'resize') throw new Error('fake DOM: window has no ' + type + ' events');
      resize.push(listener);
    }
  };
  return {
    window: strict(raw, 'window'),
    flushFrames: function () {
      for (var round = 0; frames.length; round++) {
        if (round > 1000) throw new Error('fake DOM: animation frames never stop');
        clock += 16;
        var due = frames;
        frames = [];
        due.forEach(function (f) { f.callback(clock); });
      }
    }
  };
}

function createStorage(map) {
  return strict({
    getItem: function (key) { return has(map, key) ? map[key] : null; },
    setItem: function (key, value) { map[key] = String(value); }
  }, 'localStorage');
}

// tree: {tag, attrs: [[name, value]], children} with text nodes as strings.
function build(doc, parent, tree) {
  if (typeof tree === 'string') {
    parent.appendChild(text(doc, tree));
    return;
  }
  var node = doc.createElement(tree.tag);
  tree.attrs.forEach(function (a) { node.setAttribute(a[0], a[1]); });
  parent.appendChild(node);
  tree.children.forEach(function (c) { build(doc, node, c); });
}

module.exports = { createDocument: createDocument, createWindow: createWindow, createStorage: createStorage, build: build, fire: fire };
