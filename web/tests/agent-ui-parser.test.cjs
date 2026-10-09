/**
 * Lane C — trusted OpenUI validator/merge (D-A11, D-A42, 02-CONTRACTS §7) against the pinned @openuidev/lang-core 0.3.2.
 * Pure parsing and policy only: these tests also prove nothing is fetched or executed while validating.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { createLoader } = require('./agent-ui-library-loader.cjs');

const loader = createLoader();
const parser = loader.load('src/lib/agent-runtime/ui-parser/index.ts');
const contracts = loader.load('src/lib/agent-runtime/ui-contracts.ts');
const registry = loader.load('src/features/agent/generative-ui/library-registry.ts');

const sha = (text) => crypto.createHash('sha256').update(text, 'utf8').digest('hex');
const consumer = parser.validatorLibrary('consumer');
const founder = parser.validatorLibrary('founder');

const READS = ['drafts_list', 'analytics_summary', 'analytics_trend'];
const ACTIONS = ['draft_rewrite'];
function policy(overrides = {}) {
  return {
    rootName: 'RafiiRoot',
    allowedComponents: registry.LIBRARY_DEFINITIONS.consumer.specs.map((s) => s.name),
    readBindings: READS,
    actionIds: ACTIONS,
    founder: false,
    ...overrides,
  };
}
function request(candidateSource, overrides = {}) {
  return {
    v: 'v1',
    contractVersion: contracts.CONTRACT_VERSION,
    mode: 'generate',
    baseSource: null,
    candidateSource,
    libraryHash: consumer.libraryHash,
    policy: policy(),
    scope: { workspaceId: 'w', artifactId: 'a', attemptId: 't' },
    ...overrides,
  };
}
const validate = (source, overrides) => parser.validateAndMergeUi(request(source, overrides));
const codes = (result) => result.errors.map((e) => e.split(':')[0]);
const hasCode = (result, code) => codes(result).includes(code);

const GOOD = [
  'root = RafiiRoot([heading, controls, table, actions], "Recent drafts")',
  'heading = Text("Pick two drafts to compare.", "muted")',
  '$platform = "all"',
  '$picked = []',
  'drafts = Query("drafts_list", {platform: $platform}, null)',
  'controls = Form("filters", [platform])',
  'platform = Select("platform", "Platform", [{value: "all", label: "All"}, {value: "threads", label: "Threads"}], $platform)',
  'table = ToolBoundTable(drafts, [{field: "title", label: "Draft"}, {field: "platform", label: "Platform"}], null, null, "drafts")',
  'actions = ActionButton("draft_rewrite", null, {draftIds: $picked})',
].join('\n');

test('a grounded view is accepted with canonical source, hash and declared names', () => {
  const result = validate(GOOD);
  assert.equal(result.accepted, true, JSON.stringify(result.errors));
  assert.equal(result.sourceHash, sha(result.canonicalSource));
  assert.equal(result.libraryHash, consumer.libraryHash);
  assert.deepEqual(result.queryNames, ['drafts_list']);
  assert.deepEqual(result.actionIds, ['draft_rewrite']);
  assert.ok(result.componentNames.includes('ToolBoundTable'));
  assert.ok(result.statementCount >= 8);
  // D-A42: declared reactive state and form names (the only persistable keys).
  assert.deepEqual(result.stateNames, ['$picked', '$platform']);
  assert.deepEqual(result.formNames, ['filters']);
});

test('comments and code fences are stripped from the canonical source', () => {
  const fenced = '```openui\n// a note\n' + GOOD + '\n```';
  const result = validate(fenced);
  assert.equal(result.accepted, true, JSON.stringify(result.errors));
  assert.ok(!result.canonicalSource.includes('```'));
  assert.ok(!result.canonicalSource.includes('a note'));
});

test('unknown component, missing root and wrong root type are rejected', () => {
  assert.ok(hasCode(validate('root = RafiiRoot([x])\nx = Hologram("hi")'), 'unknown_component'));
  assert.ok(hasCode(validate('x = Text("no root here")'), 'root_invalid'));
  assert.ok(hasCode(validate('root = Card([t])\nt = Text("wrong root")'), 'root_invalid'));
});

test('fragmented source (stream cut mid-statement) is never accepted', () => {
  const cut = GOOD.slice(0, GOOD.indexOf('[{field: "title"') + 12);
  const result = validate(cut);
  assert.equal(result.accepted, false);
  assert.ok(hasCode(result, 'incomplete') || hasCode(result, 'unresolved_ref'), JSON.stringify(result.errors));
});

test('library hash mismatch and contract drift are rejected before parsing', () => {
  assert.ok(hasCode(validate(GOOD, { libraryHash: 'f'.repeat(64) }), 'library_unsupported'));
  assert.ok(hasCode(validate(GOOD, { policy: policy({ rootName: 'Stack' }) }), 'root_invalid'));
  assert.ok(hasCode(validate(GOOD, { mode: 'rewrite' }), 'bad_request'));
});

test('Mutation is forbidden in every position (D-A12)', () => {
  const source = [
    'root = RafiiRoot([b])',
    'm = Mutation("schedule_apply", {})',
    'b = Button("Go", Action([@Run(m)]))',
  ].join('\n');
  assert.ok(hasCode(validate(source), 'mutation_forbidden'));
});

test('Query names must be literal read bindings; a write name or computed name is denied', () => {
  const write = 'root = RafiiRoot([t])\nw = Query("draft_rewrite", {}, null)\nt = ToolBoundTable(w, [{field: "a", label: "A"}])';
  assert.ok(hasCode(validate(write), 'query_binding_denied'));
  const computed = 'root = RafiiRoot([t])\nw = Query("drafts" + "_list", {}, null)\nt = ToolBoundTable(w, [{field: "a", label: "A"}])';
  assert.ok(hasCode(validate(computed), 'query_binding_denied'));
  const proto = 'root = RafiiRoot([t])\nw = Query("constructor", {}, null)\nt = ToolBoundTable(w, [{field: "a", label: "A"}])';
  assert.ok(hasCode(validate(proto), 'query_binding_denied'));
});

test('Query defaults must be null and refresh must be a literal of at least 30 seconds', () => {
  const base = (args) => `root = RafiiRoot([m])\ns = Query("analytics_summary", {}, ${args})\nm = Metric(s, "reach", "Reach")`;
  assert.ok(hasCode(validate(base('{reach: 0}')), 'query_defaults_forbidden'));
  assert.ok(hasCode(validate(base('null, 0.5')), 'refresh_invalid'));
  assert.ok(hasCode(validate(base('null, $fast')), 'refresh_invalid'));
  assert.equal(validate(base('null, 30')).accepted, true);
  assert.equal(validate(base('null')).accepted, true);
});

test('Query arguments are literals or $variables only (no query-to-query dependency)', () => {
  const source = [
    'root = RafiiRoot([m])',
    'a = Query("analytics_summary", {}, null)',
    'b = Query("analytics_trend", {range: a.data.range}, null)',
    'm = Metric(b, "reach", "Reach")',
  ].join('\n');
  assert.ok(hasCode(validate(source), 'query_args_shape'));
});

test('a library_search Query with the literal ids a Manager turn found (suggestedInputs, D-A51) passes the argument-shape rule', () => {
  const source = [
    'root = RafiiRoot([browser], "Found in your Library")',
    '$selectedAssets = []',
    `results = Query("library_search", {ids: ["${'a'.repeat(32)}", "${'b'.repeat(32)}"]}, null)`,
    'browser = LibraryBrowser(results, $selectedAssets)',
  ].join('\n');
  const result = validate(source, { policy: policy({ readBindings: [...READS, 'library_search'] }) });
  assert.equal(hasCode(result, 'query_args_shape'), false, result.errors.join(', '));
  assert.equal(result.accepted, true, result.errors.join(', '));
});

test('components outside the journey policy and unknown action ids are denied', () => {
  const allowed = policy({ allowedComponents: ['RafiiRoot', 'Text'] });
  assert.ok(hasCode(validate(GOOD, { policy: allowed }), 'component_denied'));
  const action = GOOD.replace('ActionButton("draft_rewrite"', 'ActionButton("schedule_apply"');
  assert.ok(hasCode(validate(action), 'action_denied'));
  const computed = GOOD.replace('ActionButton("draft_rewrite"', 'ActionButton("draft_" + "rewrite"');
  assert.ok(hasCode(validate(computed), 'action_id_not_literal'));
});

test('facts come from bound data: literal table data and external literal links are rejected', () => {
  const literal = 'root = RafiiRoot([t])\nt = ToolBoundTable({state: "available", data: [{a: 1}]}, [{field: "a", label: "A"}])';
  assert.ok(hasCode(validate(literal), 'source_not_query'));
  const external = 'root = RafiiRoot([l])\nl = EvidenceLink("Source", "https://example.com/x")';
  assert.ok(hasCode(validate(external), 'href_not_allowed'));
  const script = 'root = RafiiRoot([l])\nl = EvidenceLink("Source", "javascript:alert(1)")';
  assert.ok(hasCode(validate(script), 'href_not_allowed'));
  const inApp = 'root = RafiiRoot([l])\nl = EvidenceLink("Library", "/app/library")';
  assert.equal(validate(inApp).accepted, true);
});

test('bounds: source size, patch size, statements, nesting and tree depth', () => {
  const big = `root = RafiiRoot([t])\nt = Text("${'x'.repeat(contracts.BOUNDS.sourceBytes)}")`;
  assert.ok(hasCode(validate(big), 'source_too_large'));
  const many = ['root = RafiiRoot([s0])'];
  for (let i = 0; i < contracts.BOUNDS.statements + 5; i++) many.push(`s${i} = Text("n${i}")`);
  assert.ok(hasCode(validate(many.join('\n')), 'bounds_statements'));
  const brackets = `root = RafiiRoot([t])\nt = Text(${'('.repeat(80)}"x"${')'.repeat(80)})`;
  assert.ok(hasCode(validate(brackets), 'nesting_too_deep'));
  const deep = ['root = RafiiRoot([s0])'];
  for (let i = 0; i < 30; i++) deep.push(`s${i} = Stack([s${i + 1}])`);
  deep.push('s30 = Text("bottom")');
  assert.ok(hasCode(validate(deep.join('\n')), 'bounds_depth'));
  const patch = `t = Text("${'y'.repeat(contracts.BOUNDS.patchBytes)}")`;
  const accepted = validate(GOOD);
  assert.ok(hasCode(validate(patch, { mode: 'patch', baseSource: accepted.canonicalSource }), 'source_too_large'));
});

test('duplicate statement ids are rejected in generate mode', () => {
  assert.ok(hasCode(validate(`${GOOD}\nheading = Text("again")`), 'duplicate_statement'));
});

test('Form names must be literal identifiers (they become persisted state keys)', () => {
  const source = 'root = RafiiRoot([f])\nf = Form("my form!", [t])\nt = TextField("note", "Note")';
  assert.ok(hasCode(validate(source), 'form_name_invalid'));
});

test('patch: replace and append are merged onto the exact base and keep unaffected statements', () => {
  const base = validate(GOOD).canonicalSource;
  const patchSource = [
    'heading = Text("Compare the drafts you picked.", "muted")',
    'root = RafiiRoot([heading, controls, table, chart, actions], "Recent drafts")',
    'trend = Query("analytics_trend", {platform: $platform}, null)',
    'chart = ToolBoundChart(trend, "line", "day", [{field: "reach", label: "Reach"}], "Reach by day")',
  ].join('\n');
  const result = validate(patchSource, { mode: 'patch', baseSource: base, baseSourceHash: sha(base) });
  assert.equal(result.accepted, true, JSON.stringify(result.errors));
  assert.ok(result.canonicalSource.includes('ToolBoundTable(drafts'));
  assert.ok(result.canonicalSource.includes('ToolBoundChart(trend'));
  assert.ok(result.replacedStatementIds.includes('heading'));
  assert.deepEqual(result.removedStatementIds, []);
  assert.deepEqual(result.queryNames.sort(), ['analytics_trend', 'drafts_list']);
  // The person's selections and filters keep their names, so their state survives (D-A42 names unchanged).
  assert.deepEqual(result.stateNames, ['$picked', '$platform']);
});

test('patch: a stale base hash is a revision conflict and a missing base is rejected', () => {
  const base = validate(GOOD).canonicalSource;
  const patchSource = 'heading = Text("x")';
  assert.ok(hasCode(validate(patchSource, { mode: 'patch', baseSource: base, baseSourceHash: sha(`${base} `) }), 'revision_conflict'));
  assert.ok(hasCode(validate(patchSource, { mode: 'patch', baseSource: null }), 'missing_base'));
});

test('patch: a malformed right-hand side never silently deletes a statement', () => {
  const base = validate(GOOD).canonicalSource;
  const result = validate('table = )', { mode: 'patch', baseSource: base });
  assert.equal(result.accepted, false);
  assert.ok(result.errors.some((e) => e.startsWith('unexplained_deletion:table')) || hasCode(result, 'unresolved_ref'), JSON.stringify(result.errors));
});

test('patch: explicit null deletion and re-declared parents are explained deletions', () => {
  const base = validate(GOOD).canonicalSource;
  const explicit = validate('heading = null\nroot = RafiiRoot([controls, table, actions], "Recent drafts")', {
    mode: 'patch',
    baseSource: base,
  });
  assert.equal(explicit.accepted, true, JSON.stringify(explicit.errors));
  assert.ok(explicit.removedStatementIds.includes('heading'));
  const parent = validate('root = RafiiRoot([controls, table], "Recent drafts")', { mode: 'patch', baseSource: base });
  assert.equal(parent.accepted, true, JSON.stringify(parent.errors));
  assert.ok(parent.removedStatementIds.includes('actions'));
});

test('patch: an edit cannot expand query or action scope beyond the manifest', () => {
  const base = validate(GOOD).canonicalSource;
  const result = validate('extra = Query("billing_export", {}, null)\nroot = RafiiRoot([heading, controls, table, actions, x])\nx = ToolBoundTable(extra, [{field: "a", label: "A"}])', {
    mode: 'patch',
    baseSource: base,
  });
  assert.ok(hasCode(result, 'query_binding_denied'));
});

test('founder library is separate: no actions or forms, its own hash, consumer components only by name', () => {
  assert.notEqual(founder.libraryHash, consumer.libraryHash);
  assert.ok(!registry.LIBRARY_DEFINITIONS.founder.specs.some((s) => s.name === 'ActionButton' || s.name === 'Form'));
  const source = 'root = RafiiRoot([b])\nb = ActionButton("draft_rewrite")';
  const result = parser.validateAndMergeUi(
    request(source, {
      libraryHash: founder.libraryHash,
      policy: policy({ founder: true, allowedComponents: registry.LIBRARY_DEFINITIONS.founder.specs.map((s) => s.name) }),
    }),
  );
  assert.equal(result.accepted, false);
  assert.ok(hasCode(result, 'unknown_component') || hasCode(result, 'unknown-component'), JSON.stringify(result.errors));
  // A consumer hash never validates against the founder library.
  assert.ok(hasCode(parser.validateAndMergeUi(request(GOOD, { policy: policy({ founder: true }) })), 'library_unsupported'));
});

test('errors are stable codes: no source text, bounded count', () => {
  const secret = 'PRIVATE-DRAFT-TEXT-123';
  const source = `root = RafiiRoot([a, b])\na = Text("${secret}", "nope-variant")\nb = Hologram("${secret}")`;
  const result = validate(source);
  assert.equal(result.accepted, false);
  assert.ok(result.errors.length <= 20);
  for (const error of result.errors) assert.ok(!error.includes(secret), error);
});

test('validation performs no network or tool execution', () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('network is not allowed in the validator');
  };
  try {
    validate(GOOD);
    validate('root = RafiiRoot([t])\nw = Query("draft_rewrite", {}, null)\nt = ToolBoundTable(w, [{field: "a", label: "A"}])');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(calls, 0);
});
