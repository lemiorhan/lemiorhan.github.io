(function () {
  'use strict';

  var root = document.documentElement;
  var darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
  var ui = JSON.parse(document.getElementById('ui-text').textContent);

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (match, key) {
      return key in values ? String(values[key]) : match;
    });
  }

  function currentTheme() {
    return root.dataset.theme || (darkQuery.matches ? 'dark' : 'light');
  }

  function syncThemeColor() {
    if (!root.dataset.theme) return;
    var paper = getComputedStyle(root).getPropertyValue('--paper').trim();
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) {
      m.setAttribute('content', paper);
    });
  }

  function setupThemeToggle() {
    var btn = document.querySelector('.theme-toggle');
    if (!btn) return;
    function label() {
      var text = currentTheme() === 'dark' ? ui.theme_to_light : ui.theme_to_dark;
      btn.setAttribute('aria-label', text);
      btn.title = text;
    }
    btn.addEventListener('click', function () {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      try { localStorage.setItem('theme', next); } catch (e) {}
      label();
      syncThemeColor();
    });
    darkQuery.addEventListener('change', label);
    label();
    syncThemeColor();
    btn.hidden = false;
  }

  function setupEmail() {
    document.querySelectorAll('.mail-link').forEach(function (a) {
      var address = a.dataset.user + '@' + a.dataset.domain;
      a.href = 'mailto:' + address;
      a.textContent = address;
    });
  }

  function setupCopy() {
    if (!navigator.clipboard) return;
    document.querySelectorAll('[data-copy]').forEach(function (btn) {
      var source = document.getElementById(btn.dataset.copy);
      if (!source) return;
      var idle = btn.textContent;
      var timer;
      btn.setAttribute('aria-live', 'polite');
      btn.addEventListener('click', function () {
        var text = source.textContent.trim().replace(/\s+/g, ' ');
        navigator.clipboard.writeText(text).then(function () {
          btn.textContent = ui.copied;
        }, function () {
          btn.textContent = ui.copy_failed;
        }).then(function () {
          clearTimeout(timer);
          timer = setTimeout(function () { btn.textContent = idle; }, 2500);
        });
      });
      btn.hidden = false;
    });
  }

  // Draws the career list as a `git log --graph`: one main lane, and side
  // lanes for the positions that left Sony and merged back into it.
  function setupGraph() {
    var log = document.querySelector('.log');
    if (!log || !('ResizeObserver' in window)) return;

    var NS = 'http://www.w3.org/2000/svg';
    var DURATION = 1600;
    var items = Array.prototype.slice.call(log.children).filter(function (el) {
      return el.tagName === 'LI';
    });
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'graph');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    log.insertBefore(svg, log.firstChild);
    log.classList.add('has-graph');

    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var phase = reduceMotion || !('IntersectionObserver' in window) ? 'done' : 'primed';
    var state;
    var lastSize = '';

    function centerOf(li) {
      var node = li.querySelector('.node');
      return {
        x: node.offsetLeft + node.offsetWidth / 2,
        y: li.offsetTop + node.offsetTop + node.offsetHeight / 2,
        lane: li.dataset.lane === '1' ? 1 : 0
      };
    }

    function branchPath(child, first, last, parent) {
      var x0 = child.x;
      var x1 = first.x;
      var out = Math.min(14, (first.y - child.y) / 3);
      var back = Math.min(14, (parent.y - last.y) / 3);
      return 'M' + x0 + ' ' + child.y +
        'C' + x0 + ' ' + (child.y + out) + ' ' + x1 + ' ' + (child.y + out) + ' ' + x1 + ' ' + (child.y + 2 * out) +
        'L' + x1 + ' ' + (parent.y - 2 * back) +
        'C' + x1 + ' ' + (parent.y - back) + ' ' + x0 + ' ' + (parent.y - back) + ' ' + x0 + ' ' + parent.y;
    }

    function draw() {
      var points = items.map(centerOf);
      var main = points.filter(function (p) { return p.lane === 0; });
      var top = main[0];
      var bottom = main[main.length - 1];
      var paths = [{ lane: 0, start: top.y, end: bottom.y, d: 'M' + top.x + ' ' + top.y + 'V' + bottom.y }];

      for (var i = 0; i < points.length; i++) {
        if (points[i].lane !== 1) continue;
        var first = i;
        while (i + 1 < points.length && points[i + 1].lane === 1) i++;
        var child = points[first - 1];
        var parent = points[i + 1];
        if (!child || !parent) continue;
        paths.push({ lane: 1, start: child.y, end: parent.y, d: branchPath(child, points[first], points[i], parent) });
      }

      svg.textContent = '';
      paths.forEach(function (p) {
        p.el = document.createElementNS(NS, 'path');
        p.el.setAttribute('d', p.d);
        p.el.setAttribute('class', 'lane-' + p.lane);
        svg.appendChild(p.el);
      });

      state = { points: points, paths: paths, top: top.y, span: Math.max(1, bottom.y - top.y) };
      if (phase === 'primed') hidePaths();
    }

    function hidePaths() {
      log.classList.add('is-drawing');
      state.paths.forEach(function (p) {
        var length = p.el.getTotalLength();
        p.el.style.strokeDasharray = length + ' ' + length;
        p.el.style.strokeDashoffset = String(length);
      });
    }

    function timeAt(y) {
      return Math.round((y - state.top) / state.span * DURATION);
    }

    function play() {
      if (phase !== 'primed') return;
      phase = 'playing';
      items.forEach(function (li, i) {
        li.querySelector('.node').style.transitionDelay = timeAt(state.points[i].y) + 'ms';
      });
      log.getBoundingClientRect();
      requestAnimationFrame(function () {
        log.classList.add('go');
        state.paths.forEach(function (p) {
          var delay = timeAt(p.start);
          var duration = Math.max(200, timeAt(p.end) - delay);
          p.el.style.transition = 'stroke-dashoffset ' + duration + 'ms linear ' + delay + 'ms';
          p.el.style.strokeDashoffset = '0';
        });
      });
      setTimeout(finish, DURATION + 400);
    }

    function finish() {
      if (phase === 'done') return;
      phase = 'done';
      log.classList.remove('is-drawing', 'go');
      items.forEach(function (li) {
        li.querySelector('.node').style.transitionDelay = '';
      });
      draw();
    }

    draw();

    new ResizeObserver(function () {
      var size = log.offsetWidth + 'x' + log.offsetHeight;
      if (size === lastSize) return;
      lastSize = size;
      if (phase === 'playing') finish();
      else draw();
    }).observe(log);

    if (phase === 'primed') {
      var io = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) {
          io.disconnect();
          play();
        }
      }, { rootMargin: '0px 0px -15% 0px' });
      io.observe(log);
      window.addEventListener('beforeprint', finish);
    }
  }

  function setupArchive() {
    var archive = document.querySelector('.archive');
    if (!archive) return;

    var sections = Array.prototype.slice.call(archive.querySelectorAll('section.year'));
    var strip = archive.querySelector('.years');
    var mini = buildMiniStrip(strip);
    var filters = archive.querySelector('.filters');
    var buttons = Array.prototype.slice.call(filters.querySelectorAll('button'));
    var status = archive.querySelector('.filter-status');
    var empty = archive.querySelector('.empty-note');
    var total = archive.querySelectorAll('.ev').length;

    var state = { media: 'all', country: '', region: '' };

    function plural(n) { return fill(n === 1 ? ui.event_one : ui.event_many, { n: n }); }

    function matches(ev) {
      if (state.media !== 'all' && !ev.hasAttribute('data-' + state.media)) return false;
      if (state.country && ev.dataset.country !== state.country) return false;
      return !state.region || ev.dataset.region === state.region;
    }

    function apply() {
      var counts = sections.map(function (section) {
        var shown = 0;
        section.querySelectorAll('.ev').forEach(function (ev) {
          var match = matches(ev);
          ev.hidden = !match;
          if (match) shown++;
        });
        section.hidden = shown === 0;
        return shown;
      });
      var max = Math.max.apply(null, counts.concat(1));
      var visible = 0;

      sections.forEach(function (section, i) {
        var n = counts[i];
        visible += n;
        var label = fill(ui.year_label, { year: section.id.slice(1), events: plural(n) });
        yearLinks(section.id).forEach(function (link) {
          link.style.setProperty('--h', String(n / max));
          link.setAttribute('aria-label', label);
          link.title = label;
          if (n) {
            link.removeAttribute('aria-disabled');
            link.removeAttribute('tabindex');
          } else {
            link.setAttribute('aria-disabled', 'true');
            link.tabIndex = -1;
          }
        });
      });

      buttons.forEach(function (b) {
        b.setAttribute('aria-pressed', String(b.dataset.filter === state.media));
      });
      empty.hidden = visible > 0;
      return visible;
    }

    function refresh() {
      var visible = apply();
      status.textContent = showPlaceCount(visible) || (visible === total
        ? fill(ui.showing_all, { events: plural(total) })
        : fill(ui.showing_some, { visible: visible, events: plural(total) }));
      queue();
    }

    function yearLinks(id) {
      return [strip, mini.strip].map(function (s) {
        return s.querySelector('a[href="#' + id + '"]');
      }).filter(Boolean);
    }

    var header = document.querySelector('.site-header');
    var current = null;
    var queued = false;

    function onScroll() {
      queued = false;
      var top = Math.max(0, header ? header.getBoundingClientRect().bottom : 0);
      var shown = strip.getBoundingClientRect().bottom < top;
      mini.nav.style.top = top + 'px';
      mini.nav.classList.toggle('is-shown', shown);

      var line = top + (shown ? mini.nav.offsetHeight : 0) + 96;
      var active = null;
      sections.forEach(function (section) {
        if (!section.hidden && section.getBoundingClientRect().top <= line) active = section;
      });
      if (active && active.getBoundingClientRect().bottom <= line) active = null;
      var id = active && shown ? active.id : null;
      if (id === current) return;
      if (current) yearLinks(current).forEach(function (a) { a.removeAttribute('aria-current'); });
      if (id) yearLinks(id).forEach(function (a) { a.setAttribute('aria-current', 'location'); });
      current = id;
    }

    function queue() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(onScroll);
    }

    var showPlaceCount = setupTalkMap(archive, function (country, region) {
      state.country = country;
      state.region = region;
      refresh();
    }, plural);

    buttons.forEach(function (b) {
      b.addEventListener('click', function () {
        state.media = b.dataset.filter;
        refresh();
      });
    });

    refresh();
    strip.classList.add('has-bars');
    mini.strip.classList.add('has-bars');
    filters.hidden = false;
    window.addEventListener('scroll', queue, { passive: true });
    window.addEventListener('resize', queue);
    onScroll();
  }

  // The talks map is a second way into the year archive: choosing a country,
  // province or city filters the archive to it and zooms the map to its country.
  // Returns the function that shows how many events the filter left in that
  // place and returns the same text, '' when no place is chosen, so that the
  // filter status can announce it.
  function setupTalkMap(archive, select, plural) {
    var map = archive.querySelector('.tmap');
    if (!map) return function () { return ''; };

    var svg = map.querySelector('.tmap-svg');
    var controls = map.querySelector('.tmap-controls');
    var back = map.querySelector('.tmap-back');
    var status = map.querySelector('.tmap-status');
    var chips = Array.prototype.slice.call(controls.querySelectorAll('button'));
    var subs = Array.prototype.slice.call(controls.querySelectorAll('.chips-sub'));
    var circles = Array.prototype.slice.call(svg.querySelectorAll('circle'));
    var base = svg.viewBox.baseVal;
    var home = [base.x, base.y, base.width, base.height];
    var aspect = home[2] / home[3];
    var dot = circles.length ? circles[0].r.baseVal.value / home[2] : 0;
    var view = home.slice();
    var frame = 0;
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var current = { country: '', region: '' };

    function setView(v) {
      view = v;
      svg.setAttribute('viewBox', v.map(function (n) { return n.toFixed(1); }).join(' '));
      var r = (v[2] * dot).toFixed(2);
      circles.forEach(function (c) { c.setAttribute('r', r); });
    }

    function boxOf(country) {
      var els = svg.querySelectorAll('.tmap-countries [data-country="' + country + '"], circle[data-country="' + country + '"]');
      var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      els.forEach(function (el) {
        var b = el.getBBox();
        x0 = Math.min(x0, b.x);
        y0 = Math.min(y0, b.y);
        x1 = Math.max(x1, b.x + b.width);
        y1 = Math.max(y1, b.y + b.height);
      });
      if (!els.length) return home;
      var w = Math.max((x1 - x0) * 1.35, home[2] * 0.2);
      var h = Math.max((y1 - y0) * 1.35, w / aspect);
      w = Math.max(w, h * aspect);
      // build.py leaves out the countries outside the home view, so a zoom never leaves it.
      if (w > home[2] || h > home[3]) return home;
      var x = Math.min(Math.max((x0 + x1 - w) / 2, home[0]), home[0] + home[2] - w);
      var y = Math.min(Math.max((y0 + y1 - h) / 2, home[1]), home[1] + home[3] - h);
      return [x, y, w, h];
    }

    function zoomTo(target) {
      cancelAnimationFrame(frame);
      if (reduceMotion) {
        setView(target);
        return;
      }
      var from = view.slice();
      var start = null;
      function step(now) {
        if (start === null) start = now;
        var t = Math.min(1, (now - start) / 650);
        var e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        setView(from.map(function (a, i) { return a + (target[i] - a) * e; }));
        if (t < 1) frame = requestAnimationFrame(step);
      }
      frame = requestAnimationFrame(step);
    }

    function choose(country, region) {
      if (!subs.some(function (group) { return group.dataset.for === country; })) region = '';
      current = { country: country, region: region };
      var zoomed = country === 'online' ? '' : country;
      chips.forEach(function (b) {
        var on = 'region' in b.dataset ? b.dataset.region === region : b.dataset.country === country;
        b.setAttribute('aria-pressed', String(on));
      });
      subs.forEach(function (group) { group.hidden = group.dataset.for !== country; });
      svg.querySelectorAll('.is-selected').forEach(function (el) { el.classList.remove('is-selected'); });
      if (zoomed) {
        var picked = region
          ? '[data-region="' + region + '"]'
          : '.tmap-countries [data-country="' + country + '"], .tmap-provinces[data-for="' + country + '"]';
        svg.querySelectorAll(picked).forEach(function (el) { el.classList.add('is-selected'); });
      }
      back.hidden = !zoomed;
      zoomTo(zoomed ? boxOf(zoomed) : home);
      select(country, region);
    }

    svg.addEventListener('click', function (event) {
      var el = event.target.closest('[data-country]');
      if (!el) return;
      var region = el.dataset.region || '';
      if (region && region === current.region) region = '';
      if (el.dataset.country === current.country && region === current.region) return;
      choose(el.dataset.country, region);
    });

    chips.forEach(function (b) {
      b.addEventListener('click', function () {
        var region = b.dataset.region || '';
        if (region && region === current.region) region = '';
        choose(b.dataset.country, region);
      });
    });

    back.addEventListener('click', function () { choose('', ''); });

    controls.hidden = false;
    map.classList.add('is-live');

    return function (visible) {
      var said = '';
      if (current.country) {
        var chip = chips.filter(function (b) {
          return b.getAttribute('aria-pressed') === 'true' && (!current.region || 'region' in b.dataset);
        })[0];
        said = fill(ui.place_status, { events: plural(visible), place: chip.dataset.label });
      }
      status.textContent = said;
      return said;
    };
  }

  function buildMiniStrip(strip) {
    var nav = document.createElement('nav');
    nav.className = 'years-mini';
    nav.setAttribute('aria-label', ui.jump_to_year);
    var wrap = document.createElement('div');
    wrap.className = 'wrap';
    var copy = strip.cloneNode(true);
    wrap.appendChild(copy);
    nav.appendChild(wrap);
    document.body.appendChild(nav);
    return { nav: nav, strip: copy };
  }

  function setupLightbox() {
    var links = Array.prototype.slice.call(document.querySelectorAll('a[data-lightbox]'));
    if (!links.length || typeof HTMLDialogElement !== 'function') return;

    var dialog = document.createElement('dialog');
    dialog.className = 'lightbox';
    dialog.setAttribute('aria-label', ui.photo_viewer);
    var figure = document.createElement('figure');
    var img = document.createElement('img');
    var caption = document.createElement('figcaption');
    figure.appendChild(img);
    figure.appendChild(caption);
    dialog.appendChild(figure);

    function button(cls, label, onClick) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = cls;
      b.setAttribute('aria-label', label);
      b.addEventListener('click', onClick);
      dialog.appendChild(b);
      return b;
    }
    var close = button('lb-close', ui.close, function () { dialog.close(); });
    var prev = button('lb-prev', ui.previous_photo, function () { step(-1); });
    var next = button('lb-next', ui.next_photo, function () { step(1); });
    document.body.appendChild(dialog);

    var current = null;
    var opener = null;

    function visible() {
      return links.filter(function (a) { return a.offsetParent !== null; });
    }

    function show(link) {
      current = link;
      var thumb = link.querySelector('img');
      img.src = link.href;
      img.alt = thumb ? thumb.alt : '';
      caption.textContent = link.dataset.caption || '';
      if (link.dataset.captionLang) caption.setAttribute('lang', link.dataset.captionLang);
      else caption.removeAttribute('lang');
      var many = visible().length > 1;
      prev.hidden = !many;
      next.hidden = !many;
    }

    function step(delta) {
      var list = visible();
      var i = list.indexOf(current);
      if (i < 0 || list.length < 2) return;
      show(list[(i + delta + list.length) % list.length]);
    }

    links.forEach(function (link) {
      link.addEventListener('click', function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        opener = link;
        show(link);
        root.classList.add('lightbox-open');
        dialog.showModal();
        close.focus();
      });
    });

    dialog.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowLeft') step(-1);
      if (event.key === 'ArrowRight') step(1);
    });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog || event.target === figure) dialog.close();
    });
    dialog.addEventListener('close', function () {
      root.classList.remove('lightbox-open');
      img.removeAttribute('src');
      if (opener) opener.focus();
    });
  }

  setupThemeToggle();
  setupEmail();
  setupCopy();
  setupGraph();
  setupArchive();
  setupLightbox();
})();
