/** Shared offline guards for source selection and the actual builder output. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const forbidden = /(^|\/)(\.env[^/]*|broker\.key|vendor|\.codex|\.token-pilot|\.superpowers|\.claude|\.agents|\.git|tests|node_modules|\.next[^/]*|.*-broker-.*|james-au-[^/]*)(\/|$)/;
const forbiddenVendored = /(^|\/)(\.env[^/]*|broker\.key|\.codex|\.token-pilot|\.superpowers|\.claude|\.agents|\.git|node_modules|\.next[^/]*|.*-broker-.*)(\/|$)/;

function assertSourceSafe(names) {
  assert.deepEqual(names.filter(name => forbidden.test(name) || name.startsWith('docs/')), []);
}

function assertArtifactSafe(names) {
  // Upstream packages can contain their own tests; private state remains forbidden.
  assert.deepEqual(names.filter(name => name.startsWith('_vendor/')
    ? forbiddenVendored.test(name) : forbidden.test(name)), []);
}

async function selectSources(root, modules) {
  const ignored = await require(path.join(modules, '@vercel/build-utils/dist/get-ignore-filter.js')).default(root);
  const selected = [];
  function walk(dir, rel = '') {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const name = rel + entry.name;
      if (ignored(name + (entry.isDirectory() ? '/' : ''))) continue;
      if (entry.isSymbolicLink()) {
        // Excluded dependency/state directories may be links; never follow them.
        if (ignored(name + '/')) continue;
        throw new Error('Unreviewed symlink in source upload: ' + name);
      }
      if (entry.isDirectory()) walk(path.join(dir, entry.name), name + '/');
      else selected.push(name);
    }
  }
  walk(root);
  assertSourceSafe(selected);
  return selected;
}

module.exports = { selectSources, assertSourceSafe, assertArtifactSafe };
