/**
 * J10 interactive tools: NumberField, Slider, Toggle and Readout, the local-only validator policy and reactive readouts.
 *
 * Proves, with the real trusted validator and the real OpenUI 0.3.2 evaluation path (no jsdom, no network, no model):
 *   - the J10 journey examples are accepted local-only, and a J10 program with a Query, @Run or ActionButton is refused;
 *   - a Readout re-evaluates its expression when a bound $variable changes: moving the Slider (through the very setter
 *     `useStateField` hands the component) changes the Readout, with zero fetches and no tool provider at all;
 *   - NaN / Infinity / null / objects show "—" with an accessible label, never "NaN";
 *   - the primitives render inside a generated message with no invalid props.
 *
 *   node --test web/tests/agent-ui-tools.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createLoader, WEB } = require('./agent-ui-library-loader.cjs');

const loader = createLoader();
const React = loader.requireWeb('react');
const { renderToStaticMarkup } = loader.requireWeb('react-dom/server');
const langCore = loader.requireWeb('@openuidev/lang-core');
const parser = loader.load('src/lib/agent-runtime/ui-parser/index.ts');
const contracts = loader.load('src/lib/agent-runtime/ui-contracts.ts');
const registry = loader.load('src/features/agent/generative-ui/library-registry.ts');
const specs = loader.load('src/features/agent/generative-ui/component-specs.ts');
const locale = loader.load('src/features/agent/generative-ui/core/locale.tsx');
const tool = loader.load('src/features/agent/generative-ui/components/primitives/tool.tsx');
const { CONSUMER_LIBRARY } = loader.load('src/features/agent/generative-ui/library.tsx');
const { RafiiGenerativeMessage } = loader.load('src/features/agent/generative-ui/renderer.tsx');

const EXAMPLES = path.join(WEB, '..', 'src', 'postriff_phase2', 'agent_runtime_v2', 'generated', 'journey-examples');
const read = (file) => fs.readFileSync(path.join(EXAMPLES, file), 'utf8').trim();
const consumer = parser.validatorLibrary('consumer');
const J10 = registry.JOURNEY_LIBRARIES.J10;
const TOOL_COMPONENTS = registry.groupComponents('consumer', J10.groups);
const scope = { workspaceId: 'w', artifactId: '6c1f2f3e-1111-4222-8333-944455556666', attemptId: 't' };
const en = locale.createGenUiLocale({ locale: 'en', timeZone: 'UTC' });

function validateTool(source, overrides = {}) {
  return parser.validateAndMergeUi({
    v: 'v1',
    contractVersion: contracts.CONTRACT_VERSION,
    mode: 'generate',
    baseSource: null,
    candidateSource: source,
    libraryHash: consumer.libraryHash,
    policy: { rootName: 'RafiiRoot', allowedComponents: TOOL_COMPONENTS, readBindings: [], actionIds: [], localOnly: true, ...overrides },
    scope,
  });
}

// --- contracts ---------------------------------------------------------------------------------------------------------
test('the tool primitives are specs with bindable values, required props first, and a renderer each', () => {
  const byName = Object.fromEntries(registry.LIBRARY_DEFINITIONS.consumer.specs.map((s) => [s.name, s]));
  assert.deepEqual(Object.keys(byName.NumberField.props.shape), ['name', 'label', 'value', 'min', 'max', 'step', 'unit']);
  assert.deepEqual(Object.keys(byName.Slider.props.shape), ['name', 'label', 'min', 'max', 'value', 'step', 'unit']);
  assert.deepEqual(Object.keys(byName.Toggle.props.shape), ['name', 'label', 'value']);
  assert.deepEqual(Object.keys(byName.Readout.props.shape), ['label', 'value', 'format', 'unit', 'currency']);
  for (const name of ['NumberField', 'Slider', 'Toggle']) {
    assert.ok(langCore.isReactiveSchema(byName[name].props.shape.value), `${name}.value is a $binding`);
    assert.equal(byName[name].fieldNameProp, 'name');
  }
  assert.ok(!langCore.isReactiveSchema(byName.Readout.props.shape.value), 'a Readout only displays');
  for (const name of ['NumberField', 'Slider', 'Toggle', 'Readout']) {
    assert.equal(byName[name].rules, undefined, `${name} has no query/action rule`);
    assert.ok(Object.prototype.hasOwnProperty.call(loader.load('src/features/agent/generative-ui/components/primitives/index.ts').PRIMITIVE_RENDERERS, name));
  }
  const schema = registry.createSpecLibrary('consumer').toJSONSchema();
  for (const name of ['NumberField', 'Slider', 'Toggle', 'Readout']) assert.ok(schema.$defs[name], name);
  assert.ok(specs.TOOL_CORE_GROUP_IDS.every((g) => J10.groups.includes(g)));
});

// --- local-only validation ---------------------------------------------------------------------------------------------
test('every J10 example and the J10 edit are accepted local-only', () => {
  for (const file of ['J10-bill-splitter.openui', 'J10-unit-converter.openui', 'J10-savings-what-if.openui']) {
    const result = validateTool(read(file));
    assert.deepEqual(result.errors, [], file);
    assert.equal(result.accepted, true, file);
    assert.deepEqual(result.queryNames, [], file);
    assert.deepEqual(result.actionIds, [], file);
    for (const c of result.componentNames) assert.ok(TOOL_COMPONENTS.includes(c), `${file} uses ${c}`);
  }
  const base = validateTool(read('J10-bill-splitter.openui'));
  const patched = parser.validateAndMergeUi({
    v: 'v1',
    contractVersion: contracts.CONTRACT_VERSION,
    mode: 'patch',
    baseSource: base.canonicalSource,
    baseSourceHash: parser.sha256Hex(base.canonicalSource),
    candidateSource: read('edits/J10-add-tip-per-person.patch.openui'),
    libraryHash: consumer.libraryHash,
    policy: { rootName: 'RafiiRoot', allowedComponents: TOOL_COMPONENTS, readBindings: [], actionIds: [], localOnly: true },
    scope,
  });
  assert.deepEqual(patched.errors, []);
  assert.deepEqual(patched.removedStatementIds, []);
  assert.ok(patched.stateNames.includes('$bill') && patched.stateNames.includes('$tip'));
});

test('a J10 program with a Query, @Run or a registered action is refused, whatever the component list allows', () => {
  const everything = registry.LIBRARY_DEFINITIONS.consumer.specs.map((s) => s.name);
  const withQuery = validateTool('root = RafiiRoot([t])\nrows = Query("drafts_list", {}, null)\nt = ToolBoundTable(rows, [{field: "title", label: "T"}])', {
    allowedComponents: everything,
  });
  assert.equal(withQuery.accepted, false);
  assert.ok(withQuery.errors.some((e) => e.startsWith('local_only_query:')), withQuery.errors.join(','));
  const withAction = validateTool('root = RafiiRoot([a])\na = ActionButton("draft_rewrite")', { allowedComponents: everything });
  assert.equal(withAction.accepted, false);
  assert.ok(withAction.errors.some((e) => e.startsWith('local_only_action:')), withAction.errors.join(','));
  const withRun = validateTool('root = RafiiRoot([b])\n$n = 1\nb = Button("Refresh", Action([@Run(n)]))\nn = Text("x")');
  assert.equal(withRun.accepted, false);
  assert.ok(withRun.errors.some((e) => e.startsWith('local_only_run:')), withRun.errors.join(','));
  // A local-only policy can never carry bindings or action ids.
  assert.deepEqual(validateTool(read('J10-bill-splitter.openui'), { readBindings: ['drafts_list'] }).errors, ['bad_request']);
  assert.deepEqual(validateTool(read('J10-bill-splitter.openui'), { actionIds: ['draft_rewrite'] }).errors, ['bad_request']);
  assert.deepEqual(validateTool(read('J10-bill-splitter.openui'), { localOnly: 'yes' }).errors, ['bad_request']);
  // Local @Set / @Reset / @ToAssistant buttons stay allowed.
  const local = validateTool('root = RafiiRoot([b, r])\n$n = 2\nb = Button("Reset", Action([@Reset($n)]))\nr = Readout("Double", $n * 2)');
  assert.deepEqual(local.errors, []);
});

// --- reactive readouts -------------------------------------------------------------------------------------------------
function findElement(node, statementId) {
  if (!node || typeof node !== 'object') return null;
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findElement(item, statementId);
      if (found) return found;
    }
    return null;
  }
  if (node.type === 'element' && node.statementId === statementId) return node;
  for (const value of Object.values(node.type === 'element' ? node.props ?? {} : node)) {
    const found = findElement(value, statementId);
    if (found) return found;
  }
  return null;
}

/** The Renderer's evaluation path (react-lang 0.3.2): store + evaluateElementProps over the parsed tree, keyed on the store. */
function toolHarness(source) {
  const accepted = validateTool(source);
  assert.equal(accepted.accepted, true, accepted.errors.join(','));
  const parsed = langCore.createParser(CONSUMER_LIBRARY.toJSONSchema(), 'RafiiRoot').parse(accepted.canonicalSource);
  const store = langCore.createStore();
  store.initialize(parsed.stateDeclarations ?? {}, {});
  const unwrap = (value) => (value && typeof value === 'object' && 'value' in value && 'componentType' in value ? value.value : value);
  const ctx = { getState: (name) => unwrap(store.get(name)), resolveRef: () => undefined };
  let renders = 0;
  store.subscribe(() => {
    renders += 1;
  });
  const evaluate = () => langCore.evaluateElementProps(parsed.root, { ctx, library: CONSUMER_LIBRARY, store, errors: [] });
  const field = (statementId, name) => {
    const el = findElement(evaluate(), statementId);
    assert.ok(el, statementId);
    // The exact call `useStateField(name, props.value)` makes inside NumberField / Slider / Toggle.
    return langCore.resolveStateField(name, el.props.value, store, ctx, () => undefined, () => {
      throw new Error('a bound tool input never writes a form field');
    });
  };
  const readout = (statementId) => findElement(evaluate(), statementId).props.value;
  return { store, field, readout, renders: () => renders };
}

test('moving the Slider re-evaluates the Readout: no network, no tool provider, no model call', () => {
  const originalFetch = global.fetch;
  let fetches = 0;
  global.fetch = async () => {
    fetches += 1;
    throw new Error('no network in a tool');
  };
  try {
    const h = toolHarness(read('J10-bill-splitter.openui'));
    assert.equal(h.readout('total'), 138);
    assert.equal(h.readout('each'), 34.5);
    const tip = h.field('tip', 'tip');
    assert.equal(tip.isReactive, true, 'the Slider is two-way bound to $tip');
    assert.equal(tip.value, 15);
    tip.setValue(20);
    assert.equal(h.store.get('$tip'), 20);
    assert.ok(h.renders() >= 1, 'the store notified its subscribers (the Renderer re-renders on its snapshot)');
    assert.equal(h.readout('total'), 144);
    assert.equal(h.readout('each'), 36);
    h.field('bill', 'bill').setValue(121);
    assert.equal(Math.round(h.readout('each') * 1000) / 1000, 36.3);
    const roundUp = h.field('roundUp', 'roundUp');
    assert.equal(roundUp.value, false);
    roundUp.setValue(true);
    assert.equal(h.readout('each'), 37, 'the Toggle switches the ternary to @Ceil');
    h.field('people', 'people').setValue(0);
    assert.equal(h.readout('each'), null, 'a guarded division by zero is null, shown as a dash');
    assert.equal(tool.readoutText(h.readout('each'), { format: 'currency' }, en), null);
    assert.equal(fetches, 0);
  } finally {
    global.fetch = originalFetch;
  }
});

test('the converter and the what-if example compute from their inputs', () => {
  const converter = toolHarness(read('J10-unit-converter.openui'));
  assert.equal(Math.round(converter.readout('result') * 1000) / 1000, 6.214);
  converter.field('pair', 'pair').setValue('c_f');
  converter.field('amount', 'amount').setValue(100);
  assert.equal(converter.readout('result'), 212);
  const whatIf = toolHarness(read('J10-savings-what-if.openui'));
  assert.equal(whatIf.readout('putIn'), 120000);
  whatIf.field('withLump', 'withLump').setValue(true);
  assert.equal(whatIf.readout('putIn'), 130000);
  whatIf.field('rate', 'rate').setValue(0);
  assert.equal(whatIf.readout('total'), 130000, 'no return: the total is what was put in');
});

// --- formatting --------------------------------------------------------------------------------------------------------
test('a value that cannot be computed is a dash with a label, never "NaN"', () => {
  for (const bad of [Number.NaN, Infinity, -Infinity, null, undefined, {}, [], '   ']) {
    assert.equal(tool.readoutText(bad, { format: 'number' }, en), null, String(bad));
    assert.equal(tool.readoutText(bad, { format: 'currency', currency: 'HKD' }, en), null, String(bad));
  }
  const html = renderToStaticMarkup(React.createElement(tool.ReadoutView, { label: 'Each pays', text: tool.readoutText(Number.NaN, {}, en), unavailable: en.t('notComputable') }));
  assert.ok(!html.includes('NaN'));
  assert.match(html, /<output aria-live="polite" aria-atomic="true"/);
  assert.match(html, /<span aria-hidden="true">—<\/span><span class="sr-only">Can’t be calculated with these values<\/span>/);
});

test('readout formats: number, currency (ISO code or plain), percent ratio, unit, text and yes/no', () => {
  assert.equal(tool.readoutText(1234.5678, {}, en), '1,234.57');
  assert.equal(tool.readoutText(12, { unit: 'kg' }, en), '12 kg');
  assert.equal(tool.readoutText(34.5, { format: 'currency', currency: 'USD' }, en), '$34.50');
  assert.equal(tool.readoutText(34.5, { format: 'currency', currency: 'hkd' }, en), 'HK$34.50');
  assert.equal(tool.readoutText(34.5, { format: 'currency' }, en), '34.50');
  assert.equal(tool.readoutText(34.5, { format: 'currency', currency: 'not a code', unit: 'HKD' }, en), '34.50 HKD');
  assert.equal(tool.readoutText(0.155, { format: 'percent' }, en), '15.5%');
  assert.equal(tool.readoutText('Medium', {}, en), 'Medium');
  assert.equal(tool.readoutText(true, {}, en), 'Yes');
  assert.equal(tool.readoutText(false, {}, locale.createGenUiLocale({ locale: 'zh-HK' })), '否');
  assert.equal(tool.readoutText(0, {}, en), '0', 'zero is a real result, not a dash');
});

test('number inputs accept only finite numbers within their range', () => {
  assert.equal(tool.toFiniteNumber('12.5'), 12.5);
  assert.equal(tool.toFiniteNumber('1e3'), 1000);
  for (const bad of ['', ' ', '12abc', 'NaN', 'Infinity', '--1', null, {}, Number.NaN]) assert.equal(tool.toFiniteNumber(bad), null, String(bad));
  assert.equal(tool.numberProblem(5, 1, 10, en), null);
  assert.equal(tool.numberProblem(0, 1, 10, en), 'Enter a number from 1 to 10');
  assert.equal(tool.numberProblem(-1, 0, undefined, en), 'Enter 0 or more');
  assert.equal(tool.numberProblem(11, undefined, 10, en), 'Enter 10 or less');
  assert.equal(tool.numberProblem(null, 0, 10, en), 'Enter a number');
});

// --- rendering ---------------------------------------------------------------------------------------------------------
test('a J10 view renders its tool primitives with accessible controls and no invalid props', () => {
  const accepted = validateTool(read('J10-bill-splitter.openui'));
  const transport = {
    base: '/api/workspaces/w1/agent/ui',
    scope: 'workspace',
    scopeKey: 'user-1:w1',
    fetch: async () => {
      throw new Error('no network in render tests');
    },
  };
  const html = renderToStaticMarkup(
    React.createElement(RafiiGenerativeMessage, {
      surface: 'panel',
      transport,
      manifest: { manifestId: 'm', bindingVersion: 1, journeyIds: ['J10'], componentGroups: [...J10.groups], queries: [], actions: [], expiresAt: null },
      onContinue: () => {
        throw new Error('render must not send follow-ups');
      },
      nativeResult: React.createElement('p', { 'data-native': '' }, 'Native answer stays.'),
      artifact: {
        contractVersion: 'rafii-genui/1',
        artifactId: scope.artifactId,
        conversationId: '6c1f2f3e-1111-4222-8333-000000000001',
        messageId: '6c1f2f3e-1111-4222-8333-000000000002',
        runId: '6c1f2f3e-1111-4222-8333-000000000003',
        revision: 1,
        generationAttemptId: '6c1f2f3e-1111-4222-8333-000000000004',
        generationState: 'ready',
        validationState: 'accepted',
        language: 'openui-lang',
        languageVersion: '0.3.2',
        libraryVersion: specs.LIBRARY_VERSION,
        libraryHash: consumer.libraryHash,
        promptHash: 'p',
        sourceHash: accepted.sourceHash,
        canonicalSource: accepted.canonicalSource,
        fallbackText: 'Here is your bill splitter.',
        manifestId: 'm',
        bindingVersion: 1,
        safeState: { $bill: 120, $tip: 15, $people: 4, $roundUp: false },
        stateRevision: 0,
        createdAt: '2026-10-15T12:00:00Z',
        updatedAt: '2026-10-15T12:00:00Z',
        asOf: null,
      },
    }),
  );
  for (const name of ['NumberField', 'Slider', 'Toggle', 'Readout', 'Section', 'Grid', 'Text']) assert.ok(html.includes(`data-genui="${name}"`), name);
  assert.ok(!html.includes('data-genui-invalid'), 'no tool primitive rejected its props');
  assert.ok(!html.includes('NaN'));
  assert.match(html, /type="range"/);
  assert.match(html, /role="switch"/);
  assert.match(html, /aria-checked="false"/);
  assert.match(html, /type="number"/);
  assert.match(html, /inputMode="decimal"|inputmode="decimal"/);
});
