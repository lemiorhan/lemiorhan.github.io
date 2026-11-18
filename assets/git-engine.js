(function (global) {
  'use strict';

  var SPEC = {
    commit: ['[-m <message>] [--amend]', 'Record a new commit: a new node whose parent is HEAD'],
    branch: ['[<name> [<rev>]] | -d <name> | -D <name>', 'List, create or delete branches, the pointers that move'],
    checkout: ['<branch> | -b <name> [<rev>] | <rev>', 'Move HEAD to a branch, or detach it at a commit'],
    switch: ['<branch> | -c <name> [<rev>]', 'Move HEAD to a branch'],
    merge: ['[--no-ff] <rev>', 'Join another line of history into the current one'],
    rebase: ['[--onto <newbase>] <upstream> [<branch>]', 'Replay commits on top of another base'],
    'cherry-pick': ['<rev>...', 'Copy commits on top of HEAD'],
    reset: ['[--soft | --mixed | --hard] [<rev>]', 'Move the current branch to another commit'],
    revert: ['<rev>', 'Add a commit that undoes an earlier one'],
    tag: ['[<name> [<rev>]] | -d <name>', 'List, create or delete tags, the pointers that never move'],
    log: ['[--oneline] [--all] [<rev>]', 'Show history, newest first'],
    status: ['', 'Show where HEAD is'],
    reflog: ['', 'Show where HEAD has been, newest first'],
    help: ['[<command>]', 'Show the commands this game understands']
  };
  var COMMANDS = Object.keys(SPEC);

  var REAL_BUT_UNSUPPORTED = ['add', 'am', 'apply', 'archive', 'bisect', 'blame', 'bundle', 'clean', 'clone',
    'config', 'describe', 'diff', 'fetch', 'format-patch', 'gc', 'grep', 'init', 'mv', 'notes', 'pull', 'push',
    'range-diff', 'remote', 'restore', 'rm', 'shortlog', 'show', 'sparse-checkout', 'stash', 'submodule', 'worktree'];

  var AUTO_MESSAGE = 'Commit ';

  function GitError(output, keep) {
    this.output = output;
    this.keep = !!keep;
  }

  function fail(output, keep) {
    throw new GitError(typeof output === 'string' ? [output] : output, keep);
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function hash32(str) {
    var h = 0x811c9dc5;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    h ^= h >>> 16;
    h = Math.imul(h, 0x85ebca6b);
    h ^= h >>> 13;
    h = Math.imul(h, 0xc2b2ae35);
    h ^= h >>> 16;
    return h >>> 0;
  }

  function makeHash(message, parents, seq, taken) {
    for (var salt = 0; ; salt++) {
      var hex = ('00000000' + hash32(message + '\u0000' + parents.join(',') + '\u0000' + seq + '\u0000' + salt).toString(16)).slice(-8);
      var hash = hex.slice(0, 7);
      if (!taken[hash]) return hash;
    }
  }

  function firstLine(message) {
    return String(message).split('\n')[0];
  }

  // Phone keyboards curl quotes, so a quote opened by any character of a family closes at the
  // next character of that family, curled or straight. Inside a word ‘ and ’ are apostrophes
  // (Lemi’s), so they open a quote only where a word starts; a straight ' opens anywhere, as in bash.
  var DOUBLE_QUOTES = '"“”';
  var SINGLE_QUOTES = '\'‘’';
  var APOSTROPHES = '‘’';

  function quoteFamily(ch) {
    if (DOUBLE_QUOTES.indexOf(ch) >= 0) return DOUBLE_QUOTES;
    if (SINGLE_QUOTES.indexOf(ch) >= 0) return SINGLE_QUOTES;
    return null;
  }

  function tokenize(line) {
    var out = [];
    var cur = '';
    var inToken = false;
    var quote = null;
    for (var i = 0; i < line.length; i++) {
      var ch = line[i];
      if (quote) {
        if (quote.indexOf(ch) >= 0) quote = null;
        else if (ch === '\\' && quote === DOUBLE_QUOTES && (DOUBLE_QUOTES + '\\').indexOf(line[i + 1]) >= 0) cur += line[++i];
        else cur += ch;
        continue;
      }
      if (quoteFamily(ch) && !(inToken && APOSTROPHES.indexOf(ch) >= 0)) {
        quote = quoteFamily(ch);
        inToken = true;
      } else if (/\s/.test(ch)) {
        if (inToken) out.push(cur);
        cur = '';
        inToken = false;
      } else if (ch === '\\' && i + 1 < line.length) {
        cur += line[++i];
        inToken = true;
      } else {
        cur += ch;
        inToken = true;
      }
    }
    if (quote) return null;
    if (inToken) out.push(cur);
    return out;
  }

  function validRefName(name) {
    if (!name || name === '@' || name === 'HEAD' || name === '__proto__' || name.charAt(0) === '-') return false;
    if (/[\s~^:?*[\\\u0000-\u001f\u007f]/.test(name)) return false;
    if (name.indexOf('..') >= 0 || name.indexOf('@{') >= 0 || name.indexOf('//') >= 0) return false;
    if (/(^|\/)\./.test(name) || /[\/.]$/.test(name) || /\.lock(\/|$)/.test(name) || name.charAt(0) === '/') return false;
    return true;
  }

  function has(map, key) {
    return Object.prototype.hasOwnProperty.call(map, key);
  }

  function headCommit(s) {
    if (s.head.type === 'detached') return s.head.hash;
    return has(s.branches, s.head.name) ? s.branches[s.head.name] : null;
  }

  function ancestors(s, hash) {
    var seen = {};
    var stack = hash ? [hash] : [];
    while (stack.length) {
      var h = stack.pop();
      if (seen[h]) continue;
      seen[h] = true;
      var c = s.commits[h];
      for (var i = 0; i < c.parents.length; i++) stack.push(c.parents[i]);
    }
    return seen;
  }

  function isAncestor(s, a, b) {
    return !!a && !!b && !!ancestors(s, b)[a];
  }

  function mergeBases(s, a, b) {
    var fromA = ancestors(s, a);
    var fromB = ancestors(s, b);
    var common = Object.keys(fromA).filter(function (h) { return fromB[h]; });
    var best = common.filter(function (h) {
      return !common.some(function (o) { return o !== h && isAncestor(s, h, o); });
    });
    return best.sort(function (x, y) { return s.commits[y].seq - s.commits[x].seq; });
  }

  // A patch is "p<seq>" (adds that change) or "-p<seq>" (removes it); a tree maps
  // each change to whether it is there, as the files of a real commit would.
  function invert(patch) {
    return patch.charAt(0) === '-' ? patch.slice(1) : '-' + patch;
  }

  function changes(tree, patch) {
    var adds = patch.charAt(0) !== '-';
    return !!tree[adds ? patch : patch.slice(1)] !== adds;
  }

  function applied(tree, patch) {
    var out = {};
    for (var k in tree) out[k] = tree[k];
    var adds = patch.charAt(0) !== '-';
    out[adds ? patch : patch.slice(1)] = adds;
    return out;
  }

  function threeWay(base, ours, theirs) {
    var out = {};
    [base, ours, theirs].forEach(function (t) { for (var k in t) out[k] = false; });
    Object.keys(out).forEach(function (k) {
      out[k] = !!ours[k] === !!base[k] ? !!theirs[k] : !!ours[k];
    });
    return out;
  }

  // Several merge bases are merged into one virtual base first, as git's ort strategy does.
  function treeOf(s) {
    var trees = {};
    var anc = {};
    function ancestorsOf(h) {
      if (!has(anc, h)) anc[h] = ancestors(s, h);
      return anc[h];
    }
    function node(h) {
      return { anc: ancestorsOf(h), tree: tree(h) };
    }
    function merged(x, y) {
      var common = Object.keys(x.anc).filter(function (h) { return y.anc[h]; });
      var bases = common.filter(function (h) {
        return !common.some(function (o) { return o !== h && ancestorsOf(o)[h]; });
      });
      var base = bases.length ? node(bases[0]) : { anc: {}, tree: {} };
      for (var i = 1; i < bases.length; i++) {
        var next = node(bases[i]);
        var both = {};
        for (var h in base.anc) both[h] = true;
        for (h in next.anc) both[h] = true;
        base = { anc: both, tree: merged(base, next) };
      }
      return threeWay(base.tree, x.tree, y.tree);
    }
    function tree(h) {
      if (!has(trees, h)) {
        var c = s.commits[h];
        trees[h] = c.parents.length > 1 ? merged(node(c.parents[0]), node(c.parents[1]))
          : applied(c.parents.length ? tree(c.parents[0]) : {}, c.patch);
      }
      return trees[h];
    }
    return tree;
  }

  function reachableSet(s) {
    var seen = {};
    var tips = [];
    Object.keys(s.branches).forEach(function (n) { tips.push(s.branches[n]); });
    Object.keys(s.tags).forEach(function (n) { tips.push(s.tags[n]); });
    if (headCommit(s)) tips.push(headCommit(s));
    tips.forEach(function (t) {
      var a = ancestors(s, t);
      for (var h in a) seen[h] = true;
    });
    return seen;
  }

  function bySeq(s, hashes) {
    return hashes.slice().sort(function (x, y) { return s.commits[x].seq - s.commits[y].seq; });
  }

  function addCommit(s, message, parents, patch, cls) {
    var seq = Object.keys(s.commits).length + 1;
    var hash = makeHash(message, parents, seq, s.commits);
    s.commits[hash] = { hash: hash, parents: parents.slice(), message: message, patch: patch, seq: seq, cls: cls };
    return hash;
  }

  function moveHead(s, hash, action) {
    if (s.head.type === 'branch') s.branches[s.head.name] = hash;
    else s.head = { type: 'detached', hash: hash };
    s.reflog.unshift({ hash: hash, action: action });
  }

  function where(s) {
    return s.head.type === 'branch' ? s.head.name : 'detached HEAD';
  }

  function commitLine(s, hash) {
    var c = s.commits[hash];
    return '[' + where(s) + (c.parents.length ? ' ' : ' (root-commit) ') + hash + '] ' + firstLine(c.message);
  }

  function describe(s, hash) {
    return hash + ' ' + firstLine(s.commits[hash].message);
  }

  function lookup(s, rev) {
    var m = /^([^~^]+)((?:[~^]\d*)*)$/.exec(rev || '');
    if (!m) return null;
    var base = m[1];
    var hash;
    if (base === 'HEAD' || base === '@') hash = headCommit(s);
    else if (Object.prototype.hasOwnProperty.call(s.tags, base)) hash = s.tags[base];
    else if (Object.prototype.hasOwnProperty.call(s.branches, base)) hash = s.branches[base];
    else if (/^[0-9a-f]{4,40}$/i.test(base)) {
      var prefix = base.toLowerCase();
      var found = Object.keys(s.commits).filter(function (h) {
        return prefix.length <= h.length ? h.indexOf(prefix) === 0 : false;
      });
      if (found.length > 1) fail(['error: short object ID ' + base + ' is ambiguous', 'fatal: ambiguous argument \'' + rev + '\'']);
      hash = found[0];
    }
    if (!hash) return null;
    var re = /([~^])(\d*)/g;
    var step;
    while ((step = re.exec(m[2]))) {
      var n = step[2] === '' ? 1 : parseInt(step[2], 10);
      if (step[1] === '~') {
        for (var i = 0; i < n && hash; i++) hash = s.commits[hash].parents[0];
      } else if (n > 0) {
        hash = s.commits[hash].parents[n - 1];
      }
      if (!hash) return null;
    }
    return hash;
  }

  function revOrFail(s, rev, message) {
    var hash = lookup(s, rev);
    if (!hash) fail(message || ['fatal: ambiguous argument \'' + rev + '\': unknown revision or path not in the working tree.']);
    return hash;
  }

  function unknownOption(cmd, arg) {
    if (arg === '-') return ['error: \'-\' is not supported in this game: name the branch or commit'];
    if (arg === '--') return ['error: \'--\' is not supported in this game: there are no paths here, only the graph'];
    var what = arg.charAt(1) === '-' ? 'option `' + arg.slice(2) + '\'' : 'switch `' + arg.slice(1) + '\'';
    return ['error: unknown ' + what, 'usage: git ' + cmd + ' ' + SPEC[cmd][0]];
  }

  function decorations(s) {
    var deco = {};
    function add(hash, label) { (deco[hash] = deco[hash] || []).push(label); }
    var current = s.head.type === 'branch' ? s.head.name : null;
    if (s.head.type === 'detached') add(s.head.hash, 'HEAD');
    else if (has(s.branches, current)) add(s.branches[current], 'HEAD -> ' + current);
    Object.keys(s.tags).sort().forEach(function (n) { add(s.tags[n], 'tag: ' + n); });
    Object.keys(s.branches).sort().forEach(function (n) { if (n !== current) add(s.branches[n], n); });
    return deco;
  }

  function decorated(deco, hash) {
    return deco[hash] ? ' (' + deco[hash].join(', ') + ')' : '';
  }

  var handlers = {};

  handlers.commit = function (s, args) {
    var messages = [];
    var amend = false;
    for (var i = 0; i < args.length; i++) {
      var a = args[i];
      if (a === '-m') {
        if (i + 1 >= args.length) fail('error: switch `m\' requires a value');
        messages.push(args[++i]);
      } else if (a === '--amend') amend = true;
      else if (a.charAt(0) === '-') fail(unknownOption('commit', a));
      else fail('error: pathspec \'' + a + '\' did not match any file(s) known to git');
    }
    var message = messages.length ? messages.join('\n\n') : null;
    if (message !== null && message.trim() === '') fail('Aborting commit due to empty commit message.');
    var head = headCommit(s);
    var hash;
    if (amend) {
      if (!head) fail('fatal: You have nothing to amend.');
      var old = s.commits[head];
      if (message === null) message = old.message;
      var fromSetup = old.cls === 'base:' + old.hash;
      hash = addCommit(s, message, old.parents, old.patch, fromSetup ? 'amend(' + old.cls + ')' : old.cls);
      moveHead(s, hash, 'commit (amend): ' + firstLine(message));
      return [commitLine(s, hash)];
    }
    if (message === null) {
      s.autoMessages = (s.autoMessages || 0) + 1;
      message = AUTO_MESSAGE + s.autoMessages;
    }
    var seq = Object.keys(s.commits).length + 1;
    hash = addCommit(s, message, head ? [head] : [], 'p' + seq, 'new');
    moveHead(s, hash, (head ? 'commit: ' : 'commit (initial): ') + firstLine(message));
    return [commitLine(s, hash)];
  };

  function listBranches(s) {
    var out = [];
    if (s.head.type === 'detached') out.push('* (HEAD detached at ' + s.head.hash + ')');
    Object.keys(s.branches).sort().forEach(function (n) {
      out.push((s.head.type === 'branch' && s.head.name === n ? '* ' : '  ') + n);
    });
    return out;
  }

  function createBranch(s, name, rev, verb) {
    if (!validRefName(name)) fail('fatal: \'' + name + '\' is not a valid branch name');
    if (Object.prototype.hasOwnProperty.call(s.branches, name)) fail('fatal: a branch named \'' + name + '\' already exists');
    var target;
    if (rev !== undefined) {
      target = lookup(s, rev);
      if (!target) fail(verb === 'branch'
        ? 'fatal: not a valid object name: \'' + rev + '\''
        : 'fatal: \'' + rev + '\' is not a commit and a branch \'' + name + '\' cannot be created from it');
    } else {
      target = headCommit(s);
      if (!target && verb === 'branch') fail('fatal: not a valid object name: \'' + s.head.name + '\'');
    }
    if (target) s.branches[name] = target;
    return target;
  }

  handlers.branch = function (s, args) {
    if (args.length === 0) return listBranches(s);
    var a = args[0];
    if (a === '-d' || a === '-D') {
      if (args.length < 2) fail('fatal: branch name required');
      if (args.length > 2) fail('fatal: deleting more than one branch at once is not supported in this game');
      var name = args[1];
      if (!Object.prototype.hasOwnProperty.call(s.branches, name)) fail('error: branch \'' + name + '\' not found');
      if (s.head.type === 'branch' && s.head.name === name) {
        fail('error: cannot delete branch \'' + name + '\' used by worktree at \'~/repo\'');
      }
      if (a !== '-D' && !isAncestor(s, s.branches[name], headCommit(s))) {
        fail(['error: the branch \'' + name + '\' is not fully merged',
          'hint: If you are sure you want to delete it, run \'git branch -D ' + name + '\'']);
      }
      var was = s.branches[name];
      delete s.branches[name];
      return ['Deleted branch ' + name + ' (was ' + was + ').'];
    }
    if (a.charAt(0) === '-') fail(unknownOption('branch', a));
    if (args.length > 2) fail('fatal: too many arguments');
    createBranch(s, a, args[1], 'branch');
    return [];
  };

  function orphanWarning(s, oldHash) {
    if (!oldHash || s.head.type !== 'branch' && s.head.hash === oldHash) return [];
    var kept = reachableSet(s);
    var lost = bySeq(s, Object.keys(ancestors(s, oldHash)).filter(function (h) { return !kept[h]; })).reverse();
    if (!lost.length) return [];
    var out = ['Warning: you are leaving ' + lost.length + ' commit' + (lost.length > 1 ? 's' : '') +
      ' behind, not connected to', 'any of your branches:', ''];
    lost.slice(0, 4).forEach(function (h) { out.push('  ' + describe(s, h)); });
    if (lost.length > 4) out.push(' ... and ' + (lost.length - 4) + ' more.');
    out.push('', 'If you want to keep it by creating a new branch, this may be a good time',
      'to do so with:', '', ' git branch <new-branch-name> ' + lost[0], '');
    return out;
  }

  function fromName(s) {
    return s.head.type === 'branch' ? s.head.name : s.head.hash;
  }

  function attach(s, name) {
    if (s.head.type === 'branch' && s.head.name === name) return ['Already on \'' + name + '\''];
    var out = [];
    var wasDetached = s.head.type === 'detached' ? s.head.hash : null;
    var from = fromName(s);
    s.head = { type: 'branch', name: name };
    if (wasDetached && wasDetached !== s.branches[name]) {
      out = orphanWarning(s, wasDetached);
      if (!out.length) out.push('Previous HEAD position was ' + describe(s, wasDetached));
    }
    s.reflog.unshift({ hash: s.branches[name], action: 'checkout: moving from ' + from + ' to ' + name });
    out.push('Switched to branch \'' + name + '\'');
    return out;
  }

  function createAndAttach(s, name, rev, cmd) {
    var target = createBranch(s, name, rev, cmd);
    var from = fromName(s);
    s.head = { type: 'branch', name: name };
    if (target) s.reflog.unshift({ hash: target, action: 'checkout: moving from ' + from + ' to ' + name });
    return ['Switched to a new branch \'' + name + '\''];
  }

  handlers.checkout = function (s, args) {
    if (!args.length) return [];
    var a = args[0];
    if (a === '-b') {
      if (args.length < 2) fail('error: switch `b\' requires a value');
      if (args.length > 3) fail('fatal: too many arguments');
      return createAndAttach(s, args[1], args[2], 'checkout');
    }
    if (a.charAt(0) === '-') fail(unknownOption('checkout', a));
    if (args.length > 1) fail('error: pathspec \'' + args[1] + '\' did not match any file(s) known to git');
    if (Object.prototype.hasOwnProperty.call(s.branches, a)) return attach(s, a);
    if (a === 'HEAD' || a === '@') {
      if (!headCommit(s)) fail('error: pathspec \'' + a + '\' did not match any file(s) known to git');
      return [];
    }
    var target = lookup(s, a);
    if (!target) fail('error: pathspec \'' + a + '\' did not match any file(s) known to git');
    var old = headCommit(s);
    var wasDetached = s.head.type === 'detached';
    var from = fromName(s);
    s.head = { type: 'detached', hash: target };
    s.reflog.unshift({ hash: target, action: 'checkout: moving from ' + from + ' to ' + a });
    var out = [];
    if (wasDetached) {
      out = orphanWarning(s, old);
      if (!out.length && old !== target) out.push('Previous HEAD position was ' + describe(s, old));
    } else {
      out.push('Note: switching to \'' + a + '\'.', '',
        'You are in \'detached HEAD\' state. You can look around and make commits;',
        'they stay on no branch until you create one with git switch -c <name>.', '');
    }
    out.push('HEAD is now at ' + describe(s, target));
    return out;
  };

  handlers.switch = function (s, args) {
    if (!args.length) fail('fatal: missing branch or commit argument');
    var a = args[0];
    if (a === '-c') {
      if (args.length < 2) fail('error: switch `c\' requires a value');
      if (args.length > 3) fail('fatal: too many arguments');
      return createAndAttach(s, args[1], args[2], 'switch');
    }
    if (a.charAt(0) === '-') fail(unknownOption('switch', a));
    if (args.length > 1) fail('fatal: only one reference expected');
    if (Object.prototype.hasOwnProperty.call(s.branches, a)) return attach(s, a);
    if (lookup(s, a)) {
      var kind = Object.prototype.hasOwnProperty.call(s.tags, a) ? 'tag' : 'commit';
      fail(['fatal: a branch is expected, got ' + kind + ' \'' + a + '\'',
        'hint: If you want to detach HEAD at the commit, try again with the --detach option.']);
    }
    fail('fatal: invalid reference: ' + a);
  };

  function mergeMessage(s, rev, target) {
    var into = s.head.type === 'detached' ? ' into HEAD' : (s.head.name === 'main' ? '' : ' into ' + s.head.name);
    var m = /^([^~^]+)(.*)$/.exec(rev);
    var base = m ? m[1] : rev;
    var text;
    if (base !== 'HEAD' && base !== '@' && Object.prototype.hasOwnProperty.call(s.branches, base) &&
        !Object.prototype.hasOwnProperty.call(s.tags, base)) {
      text = 'Merge branch \'' + base + '\'' + (s.branches[base] === target ? '' : ' (early part)');
    } else if (m && m[2] === '' && Object.prototype.hasOwnProperty.call(s.tags, base)) {
      text = 'Merge tag \'' + base + '\'';
    } else {
      text = 'Merge commit \'' + rev + '\'';
    }
    return text + into;
  }

  handlers.merge = function (s, args) {
    var noff = false;
    var revs = [];
    args.forEach(function (a) {
      if (a === '--no-ff') noff = true;
      else if (a.charAt(0) === '-') fail(unknownOption('merge', a));
      else revs.push(a);
    });
    if (!revs.length) fail('fatal: No remote for the current branch.');
    if (revs.length > 1) fail('fatal: merging more than one branch at once is not supported in this game');
    var rev = revs[0];
    var target = lookup(s, rev);
    if (!target) fail('merge: ' + rev + ' - not something we can merge');
    var head = headCommit(s);
    if (!head) {
      moveHead(s, target, 'initial pull');
      return ['Fast-forward'];
    }
    if (isAncestor(s, target, head)) return ['Already up to date.'];
    if (!noff && isAncestor(s, head, target)) {
      moveHead(s, target, 'merge ' + rev + ': Fast-forward');
      return ['Updating ' + head + '..' + target, 'Fast-forward'];
    }
    var hash = addCommit(s, mergeMessage(s, rev, target), [head, target], null, 'merge');
    moveHead(s, hash, 'merge ' + rev + ': Merge made by the \'ort\' strategy.');
    return ['Merge made by the \'ort\' strategy.'];
  };

  function linear(s, from, to) {
    while (to && to !== from) {
      var c = s.commits[to];
      if (!c.parents.length) return true;
      if (c.parents.length > 1) return false;
      to = c.parents[0];
    }
    return true;
  }

  function replayOrder(s, inRange, tip) {
    if (!inRange[tip]) return [];
    var indegree = {};
    Object.keys(inRange).forEach(function (h) { indegree[h] = 1; });
    Object.keys(inRange).forEach(function (h) {
      s.commits[h].parents.forEach(function (p) { if (indegree[p]) indegree[p]++; });
    });
    var stack = [tip];
    var order = [];
    while (stack.length) {
      var h = stack.pop();
      s.commits[h].parents.forEach(function (p) {
        if (indegree[p] && --indegree[p] === 1) stack.push(p);
      });
      indegree[h] = 0;
      order.push(h);
    }
    return order.reverse();
  }

  handlers.rebase = function (s, args) {
    var ontoRev = null;
    var positional = [];
    for (var i = 0; i < args.length; i++) {
      var a = args[i];
      if (a === '--onto') {
        if (i + 1 >= args.length) fail('error: option `onto\' requires a value');
        ontoRev = args[++i];
      } else if (a === '-i' || a === '--interactive') fail('error: interactive rebase is not supported in this game');
      else if (a.charAt(0) === '-') fail(unknownOption('rebase', a));
      else positional.push(a);
    }
    if (!positional.length) fail(['There is no tracking information for the current branch.',
      'Please specify which branch you want to rebase against.']);
    if (positional.length > 2) fail('fatal: too many arguments');
    var upstream = lookup(s, positional[0]);
    if (!upstream) fail('fatal: invalid upstream \'' + positional[0] + '\'');
    var onto = upstream;
    if (ontoRev !== null) {
      onto = lookup(s, ontoRev);
      if (!onto) fail('fatal: Does not point to a valid commit \'' + ontoRev + '\'');
    }
    var branchArg = positional[1];
    if (branchArg !== undefined) {
      if (Object.prototype.hasOwnProperty.call(s.branches, branchArg)) {
        if (!(s.head.type === 'branch' && s.head.name === branchArg)) {
          s.reflog.unshift({ hash: s.branches[branchArg], action: 'checkout: moving from ' + fromName(s) + ' to ' + branchArg });
          s.head = { type: 'branch', name: branchArg };
        }
      } else {
        var detachAt = lookup(s, branchArg);
        if (!detachAt) fail('fatal: no such branch/commit \'' + branchArg + '\'');
        s.reflog.unshift({ hash: detachAt, action: 'checkout: moving from ' + fromName(s) + ' to ' + branchArg });
        s.head = { type: 'detached', hash: detachAt };
      }
    }
    var head = headCommit(s);
    if (!head) fail('fatal: no such branch/commit \'HEAD\'');
    var label = s.head.type === 'branch' ? s.head.name : 'HEAD';
    var refname = s.head.type === 'branch' ? 'refs/heads/' + s.head.name : 'detached HEAD';
    var ontoBases = mergeBases(s, onto, head);
    var branchBase = ontoBases.length === 1 ? ontoBases[0] : null;
    var upstreamBases = mergeBases(s, upstream, head);
    if (branchBase === onto && upstreamBases.length === 1 && upstreamBases[0] === onto && linear(s, onto, head)) {
      return ['Current branch ' + label + ' is up to date.'];
    }
    var fromUpstream = ancestors(s, upstream);
    var fromHead = ancestors(s, head);
    var inRange = {};
    Object.keys(fromHead).forEach(function (h) { if (!fromUpstream[h]) inRange[h] = true; });
    var upstreamPatches = {};
    Object.keys(fromUpstream).forEach(function (h) {
      if (!fromHead[h] && s.commits[h].patch) upstreamPatches[s.commits[h].patch] = true;
    });
    var tree = treeOf(s)(onto);
    var out = [];
    var tip = onto;
    s.reflog.unshift({ hash: onto, action: 'rebase (start): checkout ' + (ontoRev !== null ? ontoRev : positional[0]) });
    replayOrder(s, inRange, head).forEach(function (h) {
      var c = s.commits[h];
      if (c.parents.length > 1) return;
      if (upstreamPatches[c.patch]) {
        out.push('warning: skipped previously applied commit ' + h,
          'hint: use --reapply-cherry-picks to include skipped commits');
        return;
      }
      if (!changes(tree, c.patch)) return;
      tip = c.parents[0] === tip ? h : addCommit(s, c.message, [tip], c.patch, c.cls);
      tree = applied(tree, c.patch);
      s.reflog.unshift({ hash: tip, action: 'rebase (pick): ' + firstLine(c.message) });
    });
    if (s.head.type === 'branch') s.branches[s.head.name] = tip;
    else s.head = { type: 'detached', hash: tip };
    s.reflog.unshift({ hash: tip, action: 'rebase (finish): returning to ' + (s.head.type === 'branch' ? refname : 'HEAD') });
    out.push('Successfully rebased and updated ' + refname + '.');
    return out;
  };

  handlers['cherry-pick'] = function (s, args) {
    var revs = [];
    args.forEach(function (a) {
      if (a.charAt(0) === '-') fail(unknownOption('cherry-pick', a));
      revs.push(a);
    });
    if (!revs.length) fail('fatal: empty commit set passed');
    var targets = revs.map(function (r) { return revOrFail(s, r, 'fatal: bad revision \'' + r + '\''); });
    if (!headCommit(s)) fail('error: cannot cherry-pick onto an unborn branch in this game');
    var out = [];
    targets.forEach(function (t, i) {
      var c = s.commits[t];
      if (c.parents.length > 1) {
        fail(out.concat(['error: commit ' + t + ' is a merge but no -m option was given.', 'fatal: cherry-pick failed']), i > 0);
      }
      if (!changes(treeOf(s)(headCommit(s)), c.patch)) {
        fail(out.concat(['The previous cherry-pick is now empty, possibly due to conflict resolution.',
          'If you wish to skip this commit, use: git cherry-pick --skip']), i > 0);
      }
      var hash = addCommit(s, c.message, [headCommit(s)], c.patch, c.cls);
      moveHead(s, hash, 'cherry-pick: ' + firstLine(c.message));
      out.push(commitLine(s, hash));
    });
    return out;
  };

  handlers.reset = function (s, args) {
    var mode = '--mixed';
    var revs = [];
    args.forEach(function (a) {
      if (a === '--soft' || a === '--mixed' || a === '--hard') mode = a;
      else if (a.charAt(0) === '-') fail(unknownOption('reset', a));
      else revs.push(a);
    });
    if (revs.length > 1) fail('fatal: paths are not part of this game: ' + revs.slice(1).join(' '));
    var rev = revs.length ? revs[0] : 'HEAD';
    var target = revOrFail(s, rev);
    moveHead(s, target, 'reset: moving to ' + rev);
    return mode === '--hard' ? ['HEAD is now at ' + describe(s, target)] : [];
  };

  function revertMessage(message) {
    var subject = firstLine(message);
    var m = /^Revert "(.*)"$/.exec(subject);
    return m ? 'Reapply "' + m[1] + '"' : 'Revert "' + subject + '"';
  }

  handlers.revert = function (s, args) {
    args.forEach(function (a) { if (a.charAt(0) === '-') fail(unknownOption('revert', a)); });
    if (!args.length) fail('fatal: empty commit set passed');
    if (args.length > 1) fail('fatal: reverting more than one commit at once is not supported in this game');
    var t = revOrFail(s, args[0], 'fatal: bad revision \'' + args[0] + '\'');
    var c = s.commits[t];
    var head = headCommit(s);
    if (c.parents.length > 1) fail(['error: commit ' + t + ' is a merge but no -m option was given.', 'fatal: revert failed']);
    var patch = invert(c.patch);
    if (!head || !changes(treeOf(s)(head), patch)) {
      fail([s.head.type === 'branch' ? 'On branch ' + s.head.name : 'HEAD detached at ' + head,
        'nothing to commit, working tree clean']);
    }
    var message = revertMessage(c.message);
    var hash = addCommit(s, message, [head], patch, 'revert(' + c.cls + ')');
    moveHead(s, hash, 'revert: ' + message);
    return [commitLine(s, hash)];
  };

  handlers.tag = function (s, args) {
    if (!args.length) return Object.keys(s.tags).sort();
    var a = args[0];
    if (a === '-d') {
      if (args.length < 2) fail('fatal: tag name required');
      if (args.length > 2) fail('fatal: deleting more than one tag at once is not supported in this game');
      var name = args[1];
      if (!Object.prototype.hasOwnProperty.call(s.tags, name)) fail('error: tag \'' + name + '\' not found.');
      var was = s.tags[name];
      delete s.tags[name];
      return ['Deleted tag \'' + name + '\' (was ' + was + ')'];
    }
    if (a.charAt(0) === '-') fail(unknownOption('tag', a));
    if (args.length > 2) fail('fatal: too many arguments');
    if (!validRefName(a)) fail('fatal: \'' + a + '\' is not a valid tag name.');
    if (Object.prototype.hasOwnProperty.call(s.tags, a)) fail('fatal: tag \'' + a + '\' already exists');
    var rev = args.length > 1 ? args[1] : 'HEAD';
    s.tags[a] = revOrFail(s, rev, 'fatal: Failed to resolve \'' + rev + '\' as a valid ref.');
    return [];
  };

  function noCommitsYet(s) {
    return 'fatal: your current branch \'' + s.head.name + '\' does not have any commits yet';
  }

  handlers.log = function (s, args) {
    var oneline = false;
    var all = false;
    var revs = [];
    args.forEach(function (a) {
      if (a === '--oneline') oneline = true;
      else if (a === '--all') all = true;
      else if (a.charAt(0) === '-') fail(unknownOption('log', a));
      else revs.push(a);
    });
    var tips = revs.map(function (r) { return revOrFail(s, r); });
    if (all) {
      Object.keys(s.branches).forEach(function (n) { tips.push(s.branches[n]); });
      Object.keys(s.tags).forEach(function (n) { tips.push(s.tags[n]); });
      if (headCommit(s)) tips.push(headCommit(s));
    } else if (!revs.length) {
      if (!headCommit(s)) fail(noCommitsYet(s));
      tips.push(headCommit(s));
    }
    var seen = {};
    tips.forEach(function (t) {
      var a = ancestors(s, t);
      for (var h in a) seen[h] = true;
    });
    var deco = decorations(s);
    var out = [];
    bySeq(s, Object.keys(seen)).reverse().forEach(function (h) {
      var c = s.commits[h];
      if (oneline) {
        out.push(h + decorated(deco, h) + ' ' + firstLine(c.message));
        return;
      }
      out.push('commit ' + h + decorated(deco, h));
      if (c.parents.length > 1) out.push('Merge: ' + c.parents.join(' '));
      out.push('');
      String(c.message).split('\n').forEach(function (l) { out.push('    ' + l); });
      out.push('');
    });
    if (!oneline && out.length) out.pop();
    return out;
  };

  handlers.status = function (s, args) {
    if (args.length && args[0].charAt(0) === '-') fail(unknownOption('status', args[0]));
    if (s.head.type === 'detached') return ['HEAD detached at ' + s.head.hash, 'nothing to commit, working tree clean'];
    if (!headCommit(s)) {
      return ['On branch ' + s.head.name, '', 'No commits yet', '',
        'nothing to commit (create/copy files and use "git add" to track)'];
    }
    return ['On branch ' + s.head.name, 'nothing to commit, working tree clean'];
  };

  handlers.reflog = function (s, args) {
    if (args.length && args[0].charAt(0) === '-') fail(unknownOption('reflog', args[0]));
    if (!s.reflog.length) fail(noCommitsYet(s));
    var deco = decorations(s);
    return s.reflog.map(function (e, i) {
      return e.hash + decorated(deco, e.hash) + ' HEAD@{' + i + '}: ' + e.action;
    });
  };

  function help(args) {
    if (args.length && has(SPEC, args[0])) {
      return ['usage: git ' + args[0] + (SPEC[args[0]][0] ? ' ' + SPEC[args[0]][0] : ''), '', '   ' + SPEC[args[0]][1]];
    }
    var width = COMMANDS.reduce(function (w, c) { return Math.max(w, c.length); }, 0) + 3;
    var out = ['These are the git commands this game understands:', ''];
    COMMANDS.forEach(function (c) {
      out.push('   ' + c + new Array(width - c.length + 1).join(' ') + SPEC[c][1]);
    });
    out.push('', 'A revision is a branch or tag name, HEAD (or @), a hash of at least 4 characters,',
      'optionally followed by ~n (n-th first parent) or ^n (n-th parent), e.g. HEAD~2 or main^2.');
    return out;
  }

  function execute(s, line) {
    var raw = String(line === undefined || line === null ? '' : line).trim();
    if (!raw) return [];
    var tokens = tokenize(raw);
    if (!tokens) fail('error: unterminated quote');
    if (tokens[0] !== 'git') fail(tokens[0] + ': command not found');
    if (tokens.length === 1) fail(['usage: git <command> [<args>]', 'Type git help to see the commands this game understands.']);
    var cmd = tokens[1];
    var args = tokens.slice(2);
    if (cmd === 'help' || cmd === '--help' || cmd === '-h') return help(args);
    if (Object.prototype.hasOwnProperty.call(handlers, cmd)) return handlers[cmd](s, args);
    if (REAL_BUT_UNSUPPORTED.indexOf(cmd) >= 0) {
      fail('git ' + cmd + ' is not supported in this game: it is about files or remotes, and here only the graph exists. Type git help.');
    }
    fail('git: \'' + cmd + '\' is not a git command. See \'git help\'.');
  }

  function graphKey(s) {
    function sorted(o) {
      return Object.keys(o).sort().map(function (k) { return k + '=' + o[k]; }).join(',');
    }
    return Object.keys(s.commits).length + '|' + sorted(s.branches) + '|' + sorted(s.tags) + '|' + JSON.stringify(s.head);
  }

  function emptyState() {
    return { commits: {}, branches: {}, tags: {}, head: { type: 'branch', name: 'main' }, reflog: [] };
  }

  function Repo(state) {
    this._s = state ? clone(state) : emptyState();
  }

  Repo.prototype.run = function (line) {
    var work = clone(this._s);
    var before = graphKey(this._s);
    var ok = true;
    var output;
    try {
      output = execute(work, line);
      this._s = work;
    } catch (e) {
      ok = false;
      if (e instanceof GitError) {
        output = e.output;
        if (e.keep) this._s = work;
      } else {
        output = ['fatal: internal error: ' + (e && e.message ? e.message : String(e))];
      }
    }
    return { ok: ok, output: output, changed: graphKey(this._s) !== before };
  };

  Repo.prototype.state = function () { return clone(this._s); };
  Repo.prototype.snapshot = function () { return clone(this._s); };
  Repo.prototype.restore = function (snapshot) { this._s = clone(snapshot); };

  Repo.prototype.markBaseline = function () {
    var commits = this._s.commits;
    Object.keys(commits).forEach(function (h) { commits[h].cls = 'base:' + h; });
  };

  function createRepo() {
    return new Repo();
  }

  function fromCommands(lines) {
    var repo = new Repo();
    (lines || []).forEach(function (line, i) {
      var r = repo.run(line);
      if (!r.ok) throw new Error('setup line ' + (i + 1) + ' failed: ' + line + ': ' + r.output.join(' / '));
    });
    repo.markBaseline();
    return repo;
  }

  function resolve(line, state) {
    return String(line).replace(/\{([^{}]+)\}/g, function (match, message) {
      var found = Object.keys(state.commits).filter(function (h) { return state.commits[h].message === message; });
      if (found.length !== 1) {
        throw new Error((found.length ? found.length + ' commits have' : 'no commit has') + ' the message "' + message + '"');
      }
      return found[0];
    });
  }

  function correspond(state, goal) {
    var memo = {};
    var pairs = [];
    function same(x, y) {
      var key = x + ' ' + y;
      if (Object.prototype.hasOwnProperty.call(memo, key)) return memo[key];
      var cx = state.commits[x];
      var cy = goal.commits[y];
      var result = !!cx && !!cy && cx.parents.length === cy.parents.length &&
        cx.parents.every(function (p, i) { return same(p, cy.parents[i]); });
      memo[key] = result;
      if (result) pairs.push([x, y]);
      return result;
    }
    function sameRefs(a, b) {
      var names = Object.keys(a).sort();
      if (names.join('\n') !== Object.keys(b).sort().join('\n')) return false;
      return names.every(function (n) { return same(a[n], b[n]); });
    }
    // Two structurally equal commits on the player's side must not stand for one goal commit, nor
    // the other way round: every commit reachable from a compared ref pairs with exactly one.
    function oneToOne() {
      var toGoal = {};
      var toState = {};
      return pairs.every(function (p) {
        if (has(toGoal, p[0]) && toGoal[p[0]] !== p[1]) return false;
        if (has(toState, p[1]) && toState[p[1]] !== p[0]) return false;
        toGoal[p[0]] = p[1];
        toState[p[1]] = p[0];
        return true;
      });
    }
    if (!sameRefs(state.branches, goal.branches) || !sameRefs(state.tags, goal.tags)) return null;
    if (state.head.type !== goal.head.type) return null;
    if (state.head.type === 'branch' && state.head.name !== goal.head.name) return null;
    if (state.head.type === 'detached' && !same(state.head.hash, goal.head.hash)) return null;
    return oneToOne() ? pairs : null;
  }

  function identityDiff(state, goal) {
    var pairs = correspond(state, goal);
    if (!pairs) return null;
    return pairs.filter(function (p) { return state.commits[p[0]].cls !== goal.commits[p[1]].cls; })
      .sort(function (a, b) { return goal.commits[a[1]].seq - goal.commits[b[1]].seq; })
      .map(function (p) { return { hash: p[0], goal: p[1] }; });
  }

  function matches(state, goal) {
    var diff = identityDiff(state, goal);
    return diff !== null && diff.length === 0;
  }

  function reachable(state) {
    return bySeq(state, Object.keys(reachableSet(state)));
  }

  function headView(head) {
    return head.type === 'branch' ? { type: 'branch', name: head.name } : { type: 'detached', hash: head.hash };
  }

  function diff(before, after) {
    var changes = [];
    bySeq(after, Object.keys(after.commits).filter(function (h) { return !before.commits[h]; })).forEach(function (h) {
      changes.push({ type: 'commit', hash: h });
    });
    [['branch', 'branches'], ['tag', 'tags']].forEach(function (k) {
      var a = before[k[1]];
      var b = after[k[1]];
      var names = Object.keys(a).concat(Object.keys(b).filter(function (n) { return !has(a, n); })).sort();
      names.forEach(function (n) {
        var from = has(a, n) ? a[n] : null;
        var to = has(b, n) ? b[n] : null;
        if (from !== to) changes.push({ type: 'ref', kind: k[0], name: n, from: from, to: to });
      });
    });
    if (JSON.stringify(headView(before.head)) !== JSON.stringify(headView(after.head))) {
      changes.push({ type: 'head', from: headView(before.head), to: headView(after.head) });
    }
    return changes;
  }

  var GitEngine = {
    createRepo: createRepo,
    fromCommands: fromCommands,
    resolve: resolve,
    matches: matches,
    identityDiff: identityDiff,
    reachable: reachable,
    diff: diff,
    tokenize: tokenize,
    firstLine: firstLine,
    COMMANDS: COMMANDS.slice()
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = GitEngine;
  else global.GitEngine = GitEngine;
})(typeof window !== 'undefined' ? window : this);
