const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { selectSources, assertSourceSafe, assertArtifactSafe } = require('../../scripts/consumer_ready_artifact_inputs.cjs');
const root = path.resolve(__dirname, '../..');
const modules = process.env.VERCEL_BUILDER_MODULES || path.join(root, '.codex/consumer-ready/vercel/node_modules');

test('private review evidence is rejected in source and function archives', () => {
  assert.throws(() => assertSourceSafe(['api/index.py', '.superpowers/sdd/private.json']));
  assert.throws(() => assertArtifactSafe(['api/index.py', '.superpowers/sdd/private.json']));
  assert.throws(() => assertArtifactSafe(['api/index.py', '_vendor/package/.superpowers/private.json']));
});

test('runtime data and upstream package tests remain permitted', () => {
  assertSourceSafe(['api/index.py', 'src/postriff_phase2/locale_catalogue.json', 'skills/postriff-voice/SKILL.md']);
  assertArtifactSafe(['api/index.py', '_vendor/jsonschema/tests/test_validators.py']);
  assert.throws(() => assertArtifactSafe(['_vendor/package/.env.local']));
  assert.throws(() => assertSourceSafe(['docs/operator-private.md']));
});

test('pinned Vercel input selection excludes the actual private ledger', {
  skip: fs.existsSync(path.join(modules, 'vercel/package.json')) ? false : 'pinned local builder modules are installed at the artifact stage',
}, async () => {
  assert.equal(require(path.join(modules, 'vercel/package.json')).version, '59.23.2');
  assert.equal(require(path.join(modules, '@vercel/python/package.json')).version, '14.2.0');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rafii-upload-inputs-'));
  try {
    fs.copyFileSync(path.join(root, '.vercelignore'), path.join(tmp, '.vercelignore'));
    for (const name of ['api/index.py', 'src/postriff_phase2/locale_catalogue.json', 'skills/postriff-voice/SKILL.md',
      '.superpowers/sdd/private.json', '.codex/private.json', '.token-pilot/state.json']) {
      const file = path.join(tmp, name);
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, 'synthetic local fixture');
    }
    fs.mkdirSync(path.join(tmp, 'web'), { recursive: true });
    // A deliberately absent target proves selection never follows the dependency link.
    fs.symlinkSync(path.join(tmp, 'absent-dependency-target'), path.join(tmp, 'web/node_modules'), 'dir');
    const selected = await selectSources(tmp, modules);
    assert.deepEqual(selected.sort(), ['api/index.py', 'skills/postriff-voice/SKILL.md', 'src/postriff_phase2/locale_catalogue.json']);
    fs.symlinkSync(path.join(tmp, '.superpowers/sdd/private.json'), path.join(tmp, 'api/unreviewed.py'));
    await assert.rejects(selectSources(tmp, modules), /Unreviewed symlink/);
  } finally {
    fs.rmSync(tmp, { recursive: true });
  }
});
