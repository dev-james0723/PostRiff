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
      const ids = shape.actionId.options ?? [];
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
