/**
 * Lane E — journey components plug into lane C's registry correctly, and every journey example and edit case is valid
 * for the REAL trusted validator (lane C's validateAndMergeUi, official @openuidev/lang-core parser) under the journey's
 * own policy (its component groups, its read bindings, its action ids). Edit cases merge in patch mode on the canonical
 * base, remove only what the case says, and keep the selection/filter/form state statements.
 *
 *   node --test web/tests/agent-ui-journeys/catalog.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { REPO, createLoader } = require('./_load.cjs');

const loader = createLoader();
const registry = loader.load('src/features/agent/generative-ui/library-registry.ts');
const primitives = loader.load('src/features/agent/generative-ui/component-specs.ts');
const journeySpecs = loader.load('src/features/agent/generative-ui/components/journeys/specs.ts');
const contracts = loader.load('src/lib/agent-runtime/ui-contracts.ts');
const parser = loader.load('src/lib/agent-runtime/ui-parser/index.ts');
const { statementsOf } = loader.load('src/lib/agent-runtime/ui-parser/validate.ts');

const EXAMPLES = path.join(REPO, 'src/postriff_phase2/agent_runtime_v2/generated/journey-examples');
const catalog = JSON.parse(fs.readFileSync(path.join(EXAMPLES, 'journeys.json'), 'utf8'));
const scope = { workspaceId: '11111111-1111-4111-8111-111111111111', artifactId: '22222222-2222-4222-8222-222222222222', attemptId: '33333333-3333-4333-8333-333333333333' };

function policyFor(journey) {
  const entry = catalog.journeys[journey];
  const lib = registry.JOURNEY_LIBRARIES[journey];
  return {
    library: lib.library,
    policy: {
      rootName: 'RafiiRoot',
      allowedComponents: registry.groupComponents(lib.library, lib.groups),
      readBindings: entry.bindings,
      actionIds: entry.actions,
      founder: lib.library === 'founder',
    },
  };
}

function validate(journey, mode, candidateSource, baseSource = null) {
  const { library, policy } = policyFor(journey);
  const request = {
    v: 'v1',
    contractVersion: contracts.CONTRACT_VERSION,
    mode,
    baseSource,
    candidateSource,
    libraryHash: parser.validatorLibrary(library).libraryHash,
    policy,
    scope,
  };
  if (baseSource !== null) request.baseSourceHash = parser.sha256Hex(baseSource);
  return parser.validateAndMergeUi(request);
}

const read = (file) => fs.readFileSync(path.join(EXAMPLES, file), 'utf8').trim();

test('C’s seam serves E’s journey module, and the merged registry is sound', () => {
  const seam = loader.load('src/features/agent/generative-ui/core/journey-module.ts');
  assert.equal(seam.JOURNEYS_MODULE, journeySpecs.JOURNEY_SPEC_MODULE);
  assert.deepEqual(registry.registryProblems(), []);
  const primitiveNames = new Set(primitives.PRIMITIVE_SPECS.map((s) => s.name));
  for (const spec of [...journeySpecs.CONSUMER_JOURNEY_SPECS, ...journeySpecs.FOUNDER_JOURNEY_SPECS]) {
    assert.ok(!primitiveNames.has(spec.name), `${spec.name} collides with a primitive`);
    assert.ok(!primitives.RESERVED_NAMES.includes(spec.name), `${spec.name} is reserved`);
  }
});

test('every bound data prop is a direct Query reference and every action prop names fixed server action ids', () => {
  for (const spec of [...journeySpecs.CONSUMER_JOURNEY_SPECS, ...journeySpecs.FOUNDER_JOURNEY_SPECS]) {
    const shape = spec.props.shape;
    if ('data' in shape) assert.equal(spec.rules?.data, 'query', `${spec.name}.data`);
    if ('actionId' in shape) {
      assert.equal(spec.rules?.actionId, 'action-id', `${spec.name}.actionId`);
      let schema = shape.actionId;
      while (schema && !schema.options && typeof schema.unwrap === 'function') schema = schema.unwrap(); // optional/nullable controls
      const ids = schema?.options ?? [];
      assert.ok(ids.length >= 1, `${spec.name}.actionId is an enum of server ids`);
      const offered = Object.values(catalog.journeys).filter((j) => j.components.includes(spec.name)).flatMap((j) => j.actions);
      for (const id of ids) assert.ok(offered.includes(id), `${spec.name} names ${id}, which no journey using it offers`);
    }
  }
});

test('the journey index agrees with the specs: groups, components and libraries', () => {
  for (const [journey, entry] of Object.entries(catalog.journeys)) {
    assert.ok(contracts.JOURNEYS.includes(journey), journey);
    assert.deepEqual([...journeySpecs.JOURNEY_GROUPS[journey]], entry.groups, `${journey} groups`);
    assert.equal(registry.JOURNEY_LIBRARIES[journey].library, entry.library, `${journey} library`);
    const allowed = new Set(registry.groupComponents(entry.library, registry.JOURNEY_LIBRARIES[journey].groups));
    for (const name of entry.components) assert.ok(allowed.has(name), `${journey} prompt includes ${name}`);
    const own = new Set(
      entry.groups.flatMap((g) => (journeySpecs.CONSUMER_JOURNEY_GROUPS.concat(journeySpecs.FOUNDER_JOURNEY_GROUPS).find((x) => x.id === g) ?? { components: [] }).components),
    );
    assert.deepEqual([...own].sort(), [...entry.components].sort(), `${journey} components = its journey groups`);
  }
});

test('every journey example is accepted by the trusted validator under its journey policy', () => {
  for (const [journey, entry] of Object.entries(catalog.journeys)) {
    assert.ok(entry.examples.length >= 1, `${journey} has examples`);
    for (const example of entry.examples) {
      const result = validate(journey, 'generate', read(example.file));
      assert.deepEqual(result.errors, [], `${example.file}`);
      assert.equal(result.accepted, true, example.file);
      for (const q of result.queryNames) assert.ok(entry.bindings.includes(q), `${example.file} queries ${q}`);
      for (const a of result.actionIds) assert.ok(entry.actions.includes(a), `${example.file} uses ${a}`);
      for (const c of result.componentNames) assert.ok(registry.groupComponents(entry.library, registry.JOURNEY_LIBRARIES[journey].groups).includes(c), `${example.file} uses ${c}`);
    }
  }
  // Every example file on disk is indexed (the asset generator feeds all of them into prompts).
  const indexed = new Set(Object.values(catalog.journeys).flatMap((j) => j.examples.map((e) => e.file)));
  for (const name of fs.readdirSync(EXAMPLES).filter((n) => /^J0[1-9]-.*\.openui$/.test(n))) assert.ok(indexed.has(name), `${name} is indexed`);
});

test('each journey edit case patches its base: only intended removals, state statements kept, no new authority', () => {
  for (const [journey, entry] of Object.entries(catalog.journeys)) {
    const edit = entry.editCase;
    assert.ok(edit, `${journey} has an explicit edit case`);
    const base = validate(journey, 'generate', read(edit.base));
    assert.equal(base.accepted, true, `${edit.base}`);
    const patched = validate(journey, 'patch', read(edit.patch), base.canonicalSource);
    assert.deepEqual(patched.errors, [], edit.patch);
    assert.equal(patched.accepted, true, edit.patch);
    assert.deepEqual([...(patched.removedStatementIds ?? [])].sort(), [...edit.removes].sort(), `${edit.id} removes`);
    const ids = new Set(statementsOf(patched.canonicalSource).map((st) => st.id));
    for (const keep of edit.preserves) assert.ok(ids.has(keep), `${edit.id} keeps ${keep}`);
    for (const name of base.stateNames) assert.ok(patched.stateNames.includes(name), `${edit.id} keeps state ${name}`);
    for (const q of patched.queryNames) assert.ok(entry.bindings.includes(q), `${edit.id} queries ${q}`);
    for (const a of patched.actionIds) assert.ok(base.actionIds.includes(a) || entry.actions.includes(a), `${edit.id} action ${a}`);
    const added = patched.queryNames.filter((q) => !base.queryNames.includes(q));
    assert.deepEqual(added.sort(), [...edit.addsBindings].sort(), `${edit.id} adds bindings`);
    assert.notEqual(patched.sourceHash, base.sourceHash, `${edit.id} changes the view`);
  }
});

test('a stale base hash is a conflict, not a merge', () => {
  const [journey, entry] = Object.entries(catalog.journeys)[0];
  const base = validate(journey, 'generate', read(entry.editCase.base));
  const { library, policy } = policyFor(journey);
  const result = parser.validateAndMergeUi({
    v: 'v1',
    contractVersion: contracts.CONTRACT_VERSION,
    mode: 'patch',
    baseSource: base.canonicalSource,
    baseSourceHash: 'f'.repeat(64),
    candidateSource: read(entry.editCase.patch),
    libraryHash: parser.validatorLibrary(library).libraryHash,
    policy,
    scope,
  });
  assert.equal(result.accepted, false);
  assert.ok(result.errors.length > 0);
});

test('an example that names a binding outside its journey is refused (no borrowed authority)', () => {
  const result = validate('J02', 'generate', read('J01-drafts-studio.openui'));
  assert.equal(result.accepted, false);
});

// --- every Query argument of every example and edit matches lane D's argument schema (fixtures/d-catalog.json) ---------
const dCatalog = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'd-catalog.json'), 'utf8'));
const langCore = require(require.resolve('@openuidev/lang-core', { paths: [require('./_load.cjs').WEB] }));

function literal(node) {
  if (!node) return { kind: 'none' };
  if (node.k === 'Str') return { kind: 'value', value: node.v };
  if (node.k === 'Num') return { kind: 'value', value: node.v };
  if (node.k === 'Bool') return { kind: 'value', value: node.v };
  if (node.k === 'Null') return { kind: 'value', value: null };
  if (node.k === 'Arr') return { kind: 'value', value: (node.els ?? []).map((e) => literal(e).value) };
  return { kind: 'expression' };
}

function checkValue(spec, value, where) {
  if (value === null) return;
  const types = Array.isArray(spec.type) ? spec.type : [spec.type];
  if (typeof value === 'string') {
    assert.ok(types.includes('string'), `${where} is a string`);
    if (spec.enum) assert.ok(spec.enum.includes(value), `${where}="${value}" is one of ${spec.enum.join('|')}`);
    if (spec.maxLength) assert.ok(value.length <= spec.maxLength, `${where} length`);
    if (spec.pattern) assert.ok(new RegExp(spec.pattern).test(value), `${where}="${value}" matches ${spec.pattern}`);
    if (spec.format === 'date') assert.match(value, /^\d{4}-\d{2}-\d{2}$/, where);
  } else if (Array.isArray(value)) {
    assert.ok(types.includes('array'), `${where} is an array`);
    assert.ok(value.length <= spec.maxItems, `${where} has at most ${spec.maxItems} items`);
    for (const item of value) checkValue(spec.items ?? { type: 'string', maxLength: 120 }, item, `${where}[]`);
  } else if (typeof value === 'number') {
    assert.ok(types.includes('integer') || types.includes('number'), `${where} is a number`);
  }
}

test('every Query in every example and edit names a D binding with arguments D accepts', () => {
  const sources = [];
  for (const entry of Object.values(catalog.journeys)) {
    for (const example of entry.examples) sources.push({ entry, file: example.file });
    sources.push({ entry, file: entry.editCase.patch });
  }
  let queries = 0;
  for (const { entry, file } of sources) {
    const library = registry.createSpecLibrary(entry.library);
    const parsed = langCore.createParser(library.toJSONSchema(), 'RafiiRoot').parse(read(file));
    for (const q of parsed.queryStatements) {
      const name = literal(q.toolAST).value;
      const binding = dCatalog.queries[name];
      assert.ok(binding, `${file}: ${name} is a D binding`);
      const props = binding.argsSchema.properties;
      const given = new Map((q.argsAST?.entries ?? []).map(([k, v]) => [k, v]));
      for (const [key, node] of given) {
        if (key === 'cursor') continue; // reserved page position (lifted into UiQueryV1.cursor by the query bridge)
        assert.ok(Object.prototype.hasOwnProperty.call(props, key), `${file}: ${name} accepts ${key}`);
        const value = literal(node);
        if (value.kind === 'value') checkValue(props[key], value.value, `${file}: ${name}.${key}`);
      }
      for (const key of binding.argsSchema.required ?? []) assert.ok(given.has(key), `${file}: ${name} needs ${key}`);
      queries += 1;
    }
  }
  assert.ok(queries >= 30, `${queries} queries checked`);
});
