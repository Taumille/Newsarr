#!/usr/bin/env node
/*
 * Workaround for the broken system npm on this machine.
 *
 * Symptoms: `npm install` (and even `npm cache verify`) fails with
 *   "Class extends value undefined is not a constructor or null".
 *
 * Cause: the system npm ships a stale `minipass@3.3.6` nested under
 * `node_modules/minipass-sized/node_modules/`. It shadows the `minipass@7`
 * that `minipass-sized` expects. `minipass@3` exports the class as
 * `module.exports`, while the compiled consumer reads `.Minipass` -> undefined.
 *
 * /usr/lib is not writable, so instead of patching system files we pre-seed
 * Node's require cache with the correct hoisted `minipass@7` for that one
 * broken path, then delegate to the real npm CLI.
 *
 * Usage:  node tools/npm.js <npm args...>
 *         (or `./tools/npm <args>` via the sibling shell script)
 */
const path = require('path');
const Module = require('module');

const NPM_ROOT = process.env.NEWSARR_NPM_ROOT || '/usr/lib/node_modules/npm';
const BROKEN = path.join(
  NPM_ROOT,
  'node_modules/minipass-sized/node_modules/minipass/index.js',
);
const GOOD = path.join(NPM_ROOT, 'node_modules/minipass');

try {
  const good = require(GOOD);
  if (good && good.Minipass) {
    const resolved = require.resolve(BROKEN);
    const fake = new Module(resolved, null);
    fake.filename = resolved;
    fake.path = path.dirname(resolved);
    fake.paths = Module._nodeModulePaths(fake.path);
    fake.loaded = true;
    fake.exports = good;
    Module._cache[resolved] = fake;
  }
} catch (err) {
  console.error('npm workaround: could not load hoisted minipass:', err.message);
  console.error('If your npm is healthy, just use `npm` directly.');
  process.exit(1);
}

require(path.join(NPM_ROOT, 'bin/npm-cli.js'));
