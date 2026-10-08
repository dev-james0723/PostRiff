/**
 * Lane C — component registry, per-journey groups, prompts and the generated asset manifest (C01, D-A30, D-A38).
 * The drift check (`generate-openui-assets.mjs --check`) runs separately in CI; this test checks the registry rules and
 * that the committed manifest still describes exactly the current specs when it exists.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { createLoader, WEB } = require('./agent-ui-library-loader.cjs');

const loader = createLoader();
const registry = loader.load('src/features/agent/generative-ui/library-registry.ts');
const specs = loader.load('src/features/agent/generative-ui/component-specs.ts');
const contracts = loader.load('src/lib/agent-runtime/ui-contracts.ts');
const prompts = loader.load('src/features/agent/generative-ui/core/prompt-text.ts');
const langCore = loader.requireWeb('@openuidev/lang-core');

const sha = (text) => crypto.createHash('sha256').update(text, 'utf8').digest('hex');

test('the registry is structurally sound (names, groups, root, reserved words)', () => {
  assert.deepEqual(registry.registryProblems(), []);
  for (const name of specs.RESERVED_NAMES) {
    assert.ok(!registry.LIBRARY_DEFINITIONS.consumer.specs.some((s) => s.name === name), name);
  }
});

test('every journey maps to one library; J09 alone is founder and read-only', () => {
  for (const journey of contracts.JOURNEYS) {
    const entry = registry.JOURNEY_LIBRARIES[journey];
    assert.equal(entry.library, journey === 'J09' ? 'founder' : 'consumer', journey);
    assert.ok(entry.groups.includes('layout') && entry.groups.includes('data'), journey);
    const components = registry.groupComponents(entry.library, entry.groups);
    assert.ok(components.includes('RafiiRoot'), journey);
    if (journey === 'J09') {
      assert.ok(!components.includes('ActionButton') && !components.includes('Form'), 'founder has no write controls');
    }
  }
});

test('positional props keep required props first (the parser maps arguments by key order)', () => {
  for (const spec of registry.LIBRARY_DEFINITIONS.consumer.specs) {
    let optionalSeen = false;
    for (const [prop, schema] of Object.entries(spec.props.shape)) {
      const optional = schema.safeParse(undefined).success;
      if (optional) optionalSeen = true;
      else assert.ok(!optionalSeen, `${spec.name}.${prop} is required after an optional prop`);
    }
  }
});

test('the spec library and its JSON Schema agree; the hash is stable and covers the contract version', () => {
  const library = registry.createSpecLibrary('consumer');
  const schema = library.toJSONSchema();
  for (const spec of registry.LIBRARY_DEFINITIONS.consumer.specs) assert.ok(schema.$defs[spec.name], spec.name);
  const first = sha(registry.libraryHashInput(library.toSpec()));
  const second = sha(registry.libraryHashInput(registry.createSpecLibrary('consumer').toSpec()));
  assert.equal(first, second);
  assert.ok(registry.libraryHashInput(library.toSpec()).endsWith(`\n${contracts.CONTRACT_VERSION}`));
});

test('journey prompts are grounded: no mock-data text, no Mutation section, Rafii rules present', () => {
  for (const journey of ['J01', 'J06', 'J09']) {
    const entry = registry.JOURNEY_LIBRARIES[journey];
    const library = registry.createSpecLibrary(entry.library);
    const allowed = new Set(registry.groupComponents(entry.library, entry.groups));
    const text = langCore.generateSystemPrompt({
      library: registry.subsetSpec(library.toSpec(), allowed),
      promptOptions: {
        toolCalls: false,
        bindings: true,
        preamble: prompts.PRESENTER_PREAMBLE,
        additionalRules: prompts.rulesFor(entry.library),
      },
    });
    assert.ok(!/mock data/i.test(text), journey);
    assert.ok(!/## Mutation/.test(text), journey);
    assert.ok(text.includes('RafiiRoot'), journey);
    if (entry.library === 'founder') {
      for (const name of ['ActionButton', 'Form', 'AssetPreview']) {
        assert.ok(!new RegExp(`\\b${name}\\(`).test(text), `${journey} prompt mentions ${name}`);
      }
    } else {
      assert.ok(/\bActionButton\(/.test(text), journey);
    }
  }
});

test('every core example is valid openui-lang for the consumer library', () => {
  const library = registry.createSpecLibrary('consumer');
  const parser = langCore.createParser(library.toJSONSchema(), 'RafiiRoot');
  prompts.CORE_EXAMPLES.forEach((source, index) => {
    const result = parser.parse(source);
    assert.ok(result.root && result.root.typeName === 'RafiiRoot', `example ${index}`);
    assert.deepEqual(result.meta.errors, [], `example ${index}`);
    assert.deepEqual(result.meta.unresolved, [], `example ${index}`);
    assert.equal(result.mutationStatements.length, 0);
  });
});

test('the committed asset manifest matches the specs (when generated)', (t) => {
  const file = path.join(WEB, '..', 'src', 'postriff_phase2', 'agent_runtime_v2', 'generated', 'openui-assets.json');
  if (!fs.existsSync(file)) return t.skip('assets not generated yet');
  const assets = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(assets.contractVersion, contracts.CONTRACT_VERSION);
  for (const name of ['consumer', 'founder']) {
    const library = registry.createSpecLibrary(name);
    assert.equal(assets.libraries[name].libraryHash, sha(registry.libraryHashInput(library.toSpec())), name);
    assert.equal(assets.libraries[name].root, 'RafiiRoot');
    assert.deepEqual(assets.libraries[name].components, registry.LIBRARY_DEFINITIONS[name].specs.map((s) => s.name));
  }
  for (const journey of contracts.JOURNEYS) {
    assert.deepEqual(assets.journeys[journey].groups, [...registry.JOURNEY_LIBRARIES[journey].groups]);
    for (const mode of ['generate', 'patch']) {
      const entry = assets.prompts[`${assets.journeys[journey].library}:${journey}:${mode}`];
      assert.ok(entry, `${journey}:${mode}`);
      const text = fs.readFileSync(path.join(path.dirname(file), entry.file), 'utf8');
      assert.equal(sha(text), entry.promptHash);
    }
  }
  const web = path.join(WEB, 'src', 'features', 'agent', 'generative-ui', 'generated', 'openui-assets.json');
  assert.equal(fs.readFileSync(web, 'utf8'), fs.readFileSync(file, 'utf8'), 'browser copy equals the Python copy');
});

test('only core/openui.ts imports @openuidev/react-lang and every Renderer opts out of observability (D-A3)', () => {
  const root = path.join(WEB, 'src');
  const offenders = [];
  const renderers = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(ts|tsx|mts|js|jsx)$/.test(entry.name)) {
        const text = fs.readFileSync(full, 'utf8');
        const rel = path.relative(root, full).split(path.sep).join('/');
        if (/from\s+['"]@openuidev\/react-lang['"]|import\(\s*['"]@openuidev\/react-lang['"]\s*\)|require\(\s*['"]@openuidev\/react-lang['"]\s*\)/.test(text) && rel !== 'features/agent/generative-ui/core/openui.ts') offenders.push(rel);
        const code = text.split('\n').filter((line) => !/^\s*(\*|\/\/|\/\*)/.test(line)).join('\n');
        if (/<Renderer[\s>]/.test(code)) renderers.push({ rel, ok: /publishObservability=\{false\}/.test(code) });
      }
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
  assert.ok(renderers.length >= 1);
  for (const r of renderers) assert.ok(r.ok, `${r.rel} renders OpenUI without publishObservability={false}`);
  const facade = fs.readFileSync(path.join(root, 'features/agent/generative-ui/core/openui.ts'), 'utf8');
  assert.ok(facade.indexOf("import './openui-optout'") < facade.indexOf('@openuidev/react-lang'), 'devtools opt-out is imported first');
});
