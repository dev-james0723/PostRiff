/**
 * Lane C — renderer state and safety helpers (C03, C04, C06, G05, G06, G10, G12, G18), React-free parts.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createLoader } = require('./agent-ui-library-loader.cjs');

const loader = createLoader();
const results = loader.load('src/features/agent/generative-ui/core/query-results.ts');
const data = loader.load('src/features/agent/generative-ui/core/query-data.ts');
const actions = loader.load('src/features/agent/generative-ui/core/actions.ts');
const state = loader.load('src/features/agent/generative-ui/core/state.ts');
const watchdog = loader.load('src/features/agent/generative-ui/core/watchdog.ts');
const props = loader.load('src/features/agent/generative-ui/core/props.ts');
const locale = loader.load('src/features/agent/generative-ui/core/locale.tsx');
const contracts = loader.load('src/lib/agent-runtime/ui-contracts.ts');

const plain = (value) => JSON.parse(JSON.stringify(value));
const envelope = (overrides = {}) => ({
  state: 'available',
  data: { drafts: [{ ref: 'draft:d1', title: 'Spring', reach: 120 }, { ref: 'draft:d2', title: 'Summer', reach: null }] },
  asOf: '2026-10-08T12:00:00Z',
  sourceRefs: ['draft:d1'],
  revision: '3',
  nextCursor: null,
  coverage: { known: 1, total: 2, note: null },
  warnings: [],
  ...overrides,
});

test('read results reach OpenUI in the MCP shape, bounded, schema-checked and branded', async () => {
  const calls = [];
  const inner = { callTool: async (call) => (calls.push(call), envelope()) };
  const provider = results.wrapReadToolProvider(inner);
  const answer = await provider.callTool({ name: 'drafts_list', arguments: { platform: 'all' } });
  assert.deepEqual(plain(calls), [{ name: 'drafts_list', arguments: { platform: 'all' } }]);
  assert.deepEqual(answer.content, []);
  assert.equal(results.isGenuineQueryResult(answer.structuredContent), true);
  // An MCP-shaped answer from the bridge is unwrapped, not double-wrapped.
  const mcp = results.wrapReadToolProvider({ callTool: async () => ({ content: [], structuredContent: envelope() }) });
  assert.equal((await mcp.callTool({ name: 'drafts_list' })).structuredContent.state, 'available');
  // No provider before acceptance.
  assert.equal(results.wrapReadToolProvider(null), null);
});

test('malformed or failing reads become "unavailable", never data', async () => {
  const bad = results.normalizeQueryResult({ state: 'available', data: 1 }); // missing fields
  assert.equal(bad.state, 'unavailable');
  const failing = results.wrapReadToolProvider({ callTool: async () => { throw new Error('server said: secret detail'); } });
  const answer = await failing.callTool({ name: 'drafts_list' });
  assert.equal(answer.structuredContent.state, 'unavailable');
  assert.ok(!JSON.stringify(answer).includes('secret detail'));
});

test('results are bounded before materialization and prototype keys are dropped', () => {
  const rows = Array.from({ length: 500 }, (_, i) => ({ ref: `draft:${i}`, title: 'x'.repeat(10_000) }));
  const big = results.normalizeQueryResult(envelope({ data: rows }));
  assert.ok(big.data.length <= contracts.BOUNDS.queryPageMax);
  assert.ok(big.data[0].title.length <= results.RESULT_LIMITS.stringChars + 1);
  assert.ok(big.warnings.includes('truncated'));
  const proto = results.normalizeQueryResult(JSON.parse('{"state":"available","data":{"__proto__":{"polluted":true},"ok":1},"asOf":null,"sourceRefs":[],"revision":null,"nextCursor":null,"coverage":{"known":null,"total":null,"note":null},"warnings":[]}'));
  assert.equal({}.polluted, undefined);
  assert.equal(Object.prototype.hasOwnProperty.call(proto.data, '__proto__'), false);
});

test('bound components see a typed literal as "waiting", never as data (genuine results only)', () => {
  const literal = envelope();
  assert.equal(data.readQuery(literal, 'drafts').state, 'waiting');
  assert.deepEqual(data.readQuery(literal, 'drafts').rows, []);
  assert.equal(data.readQuery(null).state, 'loading');
  const genuine = results.normalizeQueryResult(envelope());
  const view = data.readQuery(genuine, 'drafts');
  assert.equal(view.state, 'available');
  assert.equal(view.rows.length, 2);
  assert.equal(view.coverage.known, 1);
  // Unknown is not zero.
  assert.equal(data.numberAt(view.rows[1], 'reach'), undefined);
  assert.equal(data.numberAt(view.rows[0], 'reach'), 120);
  assert.equal(data.rowId(view.rows[0]), 'draft:d1');
  assert.deepEqual(plain(data.refParts('draft:d1')), { type: 'draft', id: 'd1' });
});

test('rows come from rowsField, a bare list or the single list property; paths are own-key only', () => {
  assert.equal(data.rowsOf([{ a: 1 }]).rows.length, 1);
  assert.equal(data.rowsOf({ items: [{ a: 1 }], offset: 0 }).rows.length, 1);
  assert.equal(data.rowsOf({ a: [{}], b: [{}] }).hasList, false);
  assert.equal(data.rowsOf({ a: [{}], b: [{}, {}] }, 'b').rows.length, 2);
  assert.equal(data.getPath({ a: { b: 2 } }, 'a.b'), 2);
  assert.equal(data.getPath({}, 'constructor'), undefined);
  assert.equal(data.getPath({ a: 1 }, '__proto__'), undefined);
});

test('generated plans keep only local steps; host actions handle follow-ups and same-origin links only', () => {
  const plan = actions.sanitizePlan({
    steps: [
      { type: 'set', target: '$a', valueAST: { k: 'Num', v: 1 } },
      { type: 'run', statementId: 'w', refType: 'mutation' },
      { type: 'run', statementId: 'q', refType: 'query' },
      { type: 'rafii.publish', params: {} },
      { type: 'continue_conversation', message: 'Compare these' },
    ],
  });
  assert.deepEqual(plan.steps.map((s) => s.type), ['set', 'run', 'continue_conversation']);
  assert.equal(plan.steps[1].refType, 'query');
  assert.equal(actions.sanitizePlan({ type: 'custom', params: { x: 1 } }), null);

  const followUps = [];
  const navigations = [];
  const blocked = [];
  const handle = actions.createHostActionHandler({
    origin: 'https://rafii.io',
    onFollowUp: (m) => followUps.push(m),
    onNavigate: (p) => navigations.push(p),
    onBlocked: (k) => blocked.push(k),
  });
  handle({ type: 'continue_conversation', humanFriendlyMessage: '  Compare   the second two  ', params: { context: 'IGNORE PREVIOUS' }, formState: { secret: 1 } });
  handle({ type: 'open_url', params: { url: '/app/library?asset=1' } });
  handle({ type: 'open_url', params: { url: 'https://rafii.io/app/calendar' } });
  handle({ type: 'open_url', params: { url: 'javascript:alert(1)' } });
  handle({ type: 'open_url', params: { url: 'https://evil.example/phish' } });
  handle({ type: 'open_url', params: { url: '//evil.example' } });
  handle({ type: 'rafii.schedule', params: { all: true } });
  assert.deepEqual(followUps, ['Compare the second two']);
  assert.deepEqual(navigations, ['/app/library?asset=1', '/app/calendar']);
  assert.equal(blocked.length, 3);
});

test('dirty fields an edit would remove are detected; the swap keeps the latest typed values', () => {
  const hosts = { TextField: 'name', Select: 'name', DateRange: 'name' };
  const before = {
    type: 'element', typeName: 'RafiiRoot', statementId: 'root',
    props: { children: [
      { type: 'element', typeName: 'Form', statementId: 'f', props: { name: 'brief', children: [
        { type: 'element', typeName: 'TextField', statementId: 'goal', props: { name: 'goal', label: 'Goal' } },
        { type: 'element', typeName: 'TextField', statementId: 'note', props: { name: 'note', label: 'Note', value: { k: 'StateRef', n: '$note' } } },
      ] } },
    ] },
  };
  const after = { ...before, props: { children: [{ type: 'element', typeName: 'Form', statementId: 'f', props: { name: 'brief', children: [before.props.children[0].props.children[0]] } }] } };
  const previous = state.collectFieldHosts(before, hosts);
  const next = state.collectFieldHosts(after, hosts);
  assert.deepEqual(previous.map((h) => h.key), ['brief/goal', 'brief/note']);
  assert.equal(previous[1].stateKey, '$note');
  const initial = { $note: '' };
  const current = { $note: 'call the venue', brief: { goal: { value: 'x', componentType: 'TextField' } } };
  const removed = state.dirtyFieldsRemoved({ previous, next, initial, current });
  assert.deepEqual(removed.map((h) => h.label), ['Note']);
  // Untouched fields that disappear need no warning.
  assert.deepEqual(state.dirtyFieldsRemoved({ previous, next, initial: current, current }), []);
  // Lane F's unsaved keys count as dirty even when the value equals the opening one.
  assert.equal(state.dirtyFieldsRemoved({ previous, next, initial: current, current, dirtyKeys: ['$note'] }).length, 1);
  const swapped = state.swapInitialState({ $note: '', $page: null }, current);
  assert.equal(swapped.$note, 'call the venue');
  assert.ok('$page' in swapped);
});

test('watchdog bounds untrusted streaming source before parsing', () => {
  assert.equal(watchdog.checkSource('root = RafiiRoot([])'), null);
  assert.equal(watchdog.checkSource(`root = Text("${'x'.repeat(contracts.BOUNDS.sourceBytes)}")`), 'source_too_large');
  assert.equal(watchdog.checkSource(`root = Text(${'['.repeat(70)})`), 'nesting_too_deep');
  const many = Array.from({ length: 600 }, (_, i) => `s${i} = Text("a")`).join('\n');
  assert.equal(watchdog.checkSource(many), 'too_many_statements');
});

test('props: nulls are "not given", children keep statement-id keys', () => {
  const { z } = loader.requireWeb('zod');
  const schema = z.object({ title: z.string(), tone: z.enum(['a', 'b']).optional() });
  assert.equal(props.safeProps(schema, { title: 'x', tone: null }).ok, true);
  assert.equal(props.safeProps(schema, { title: 1 }).ok, false);
  assert.equal(props.childKey({ type: 'element', typeName: 'Text', statementId: 'intro', props: {} }, 3), 's:intro');
  assert.equal(props.childKey({ type: 'element', typeName: 'Text', props: {} }, 3), 'i:Text:3');
});

test('locale: unknown is never zero; dates keep calendar days; three label languages', () => {
  const en = locale.createGenUiLocale({ locale: 'en-US', timeZone: 'America/Indiana/Indianapolis' });
  assert.equal(en.formatNumber(null), 'Not available');
  assert.equal(en.formatValue(undefined, 'number'), 'Not available');
  assert.equal(en.formatValue(0, 'number'), '0');
  assert.equal(en.formatValue(0.125, 'percent'), '12.5%');
  assert.match(en.formatDate('2026-10-08'), /Oct 8, 2026/);
  assert.equal(en.toEpochMs(1760000000), 1760000000000);
  const hk = locale.createGenUiLocale({ locale: 'zh-HK', timeZone: 'Asia/Hong_Kong' });
  assert.equal(hk.language, 'zh-Hant');
  assert.equal(hk.t('notAvailable'), '未有資料');
  assert.equal(locale.createGenUiLocale({ locale: 'zh-CN' }).language, 'zh-Hans');
  assert.equal(locale.createGenUiLocale({ locale: 'ar-EG' }).dir, 'rtl');
  assert.equal(locale.createGenUiLocale({ locale: 'not a locale!!' }).locale, 'en');
});
