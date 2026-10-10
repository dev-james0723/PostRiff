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

// --- D-A52: a generated view's statements must all be reachable from root (run 3: J08-a / J08-edit unexplained_deletion×5) ---
const { statementsOf, unreachableStatements } = loader.load('src/lib/agent-runtime/ui-parser/validate.ts');
const ORPHANED = [
  'root = RafiiRoot([table], "Recent drafts")',
  '$platform = "all"',
  'drafts = Query("drafts_list", {platform: $platform}, null)',
  'table = ToolBoundTable(drafts, [{field: "title", label: "Draft"}], null, null, "drafts")',
  'summary = Query("analytics_summary", {}, null)',
  'reach = Metric(summary, "totals.reach", "Reach", "number")',
  'note = Text("Nobody lists this.", "muted")',
].join('\n');
const errorsOf = (result, code) => result.errors.filter((e) => e.startsWith(`${code}:`)).sort();

test('generate: a statement root never reaches is rejected as unreachable_statement, never stored or pruned (D-A52)', () => {
  assert.deepEqual(unreachableStatements(statementsOf(ORPHANED)), ['summary', 'reach', 'note']);
  const result = validate(ORPHANED);
  assert.equal(result.accepted, false);
  assert.equal(result.canonicalSource, null, 'a view with orphans is not stored in any form');
  assert.deepEqual(errorsOf(result, 'unreachable_statement'), ['unreachable_statement:note', 'unreachable_statement:reach', 'unreachable_statement:summary']);
  assert.ok(!result.errors.some((e) => e.includes('$platform')), '$state statements are kept, as the merge keeps them');
  // Wired into root's tree, the same statements are accepted unchanged.
  const wired = ORPHANED.replace('root = RafiiRoot([table], "Recent drafts")', 'root = RafiiRoot([table, reach, note], "Recent drafts")');
  const accepted = validate(wired);
  assert.equal(accepted.accepted, true, JSON.stringify(accepted.errors));
  assert.equal(accepted.canonicalSource, wired);
  assert.equal(validate(GOOD).canonicalSource, GOOD);
  // An orphan that also breaks another rule reports both.
  const denied = validate(`${ORPHANED}\nextra = Query("billing_export", {}, null)`);
  assert.ok(hasCode(denied, 'query_binding_denied') && errorsOf(denied, 'unreachable_statement').includes('unreachable_statement:extra'), JSON.stringify(denied.errors));
});

test('generate: run 3 J08-a shape — a Query as a root child plus an unreachable layout is rejected, not stored (D-A52)', () => {
  // Role A read production (artifact 6c61c1c1, revision 1): root listed the Query itself and the intended layout (5 statements)
  // was unreachable; those 5 were the J08-edit unexplained_deletion×5. Both are now first-pass failures that go to the repair.
  const j08 = [
    'root = RafiiRoot([automations], "Automations")',
    '$automationStatus = null',
    'automations = Query("automations_list", {status: $automationStatus}, null)',
    'finalView = Stack([listSection])',
    'listSection = Section("Automations", [filters, automationList])',
    'automationList = AutomationList(automations)',
    'filters = Stack([statusFilter], "horizontal")',
    'statusFilter = Select("status", "Status", [{value: "active", label: "Active"}, {value: "paused", label: "Paused"}], $automationStatus)',
  ].join('\n');
  const result = validate(j08, { policy: policy({ readBindings: ['automations_list'] }) });
  assert.equal(result.accepted, false);
  assert.deepEqual(errorsOf(result, 'query_as_child'), ['query_as_child:automations']);
  assert.deepEqual(errorsOf(result, 'unreachable_statement'), ['automationList', 'filters', 'finalView', 'listSection', 'statusFilter']
    .map((id) => `unreachable_statement:${id}`));
  // The repaired program (root lists the layout, the Query feeds AutomationList) is accepted.
  const repaired = j08.replace('root = RafiiRoot([automations], "Automations")', 'root = RafiiRoot([finalView], "Automations")');
  const ok = validate(repaired, { policy: policy({ readBindings: ['automations_list'] }) });
  assert.equal(ok.accepted, true, JSON.stringify(ok.errors));
});

test('a Query is data, never a child: as an element of any component list it is query_as_child, as a source it is fine (D-A52)', () => {
  // react-lang 0.3.2 renderDeep returns null for a plain object, so a Query result listed as a child renders nothing.
  const view = (body) => validate(`root = RafiiRoot([box])\nrows = Query("drafts_list", {}, null)\n${body}`);
  for (const body of ['box = Stack([rows])', 'box = Card([Text("x"), rows], "Drafts")', 'box = Section("Drafts", [rows])',
    'box = Tabs([TabItem("All", [rows])])', 'kids = [rows]\nbox = Stack(kids)']) {
    const result = view(body);
    assert.deepEqual(errorsOf(result, 'query_as_child'), ['query_as_child:rows'], `${body}: ${JSON.stringify(result.errors)}`);
  }
  assert.ok(hasCode(validate('root = RafiiRoot([rows])\nrows = Query("drafts_list", {}, null)'), 'query_as_child'));
  const fine = view('box = Stack([ToolBoundTable(rows, [{field: "title", label: "Draft"}], null, null, "drafts"), Text("x")])');
  assert.equal(fine.accepted, true, JSON.stringify(fine.errors));
  // Patch mode applies the same rule to the merged program.
  const base = validate(GOOD).canonicalSource;
  assert.ok(hasCode(validate('root = RafiiRoot([heading, controls, table, actions, drafts], "Recent drafts")', { mode: 'patch', baseSource: base }), 'query_as_child'));
});

test('query children cannot hide behind value aliases, nested lists, conditionals or value-returning builtins', () => {
  const prefix = 'root = RafiiRoot([box])\nrows = Query("drafts_list", {}, null)\n';
  for (const body of [
    'alias = rows\nbox = Stack([alias])',
    'alias = rows\nother = alias\nbox = Stack([other])',
    'kids = [rows]\nother = kids\nbox = Stack(other)',
    'box = Stack([[rows]])',
    'box = Stack([true ? rows : Text("Empty")])',
    'box = Stack([false ? Text("Empty") : rows])',
    'choice = true ? [Text("Empty")] : [rows]\nbox = Stack(choice)',
    'box = Stack([@First([rows])])',
    'box = Stack([@Last([rows])])',
    'box = Stack([@Each([1], "item", rows)])',
  ]) {
    const result = validate(prefix + body);
    assert.equal(result.accepted, false, body);
    assert.deepEqual(errorsOf(result, 'query_as_child'), ['query_as_child:rows'], `${body}: ${JSON.stringify(result.errors)}`);
  }
});

test('rendered queries cannot escape through logical operators, container selectors or Each bindings', () => {
  const prefix = 'root = RafiiRoot([box])\nrows = Query("drafts_list", {}, null)\n';
  for (const body of [
    'box = Stack([true && rows])',
    'box = Stack([false || rows])',
    'box = Stack([rows || Text("Empty")])',
    'box = Stack([[rows][0]])',
    'box = Stack([[rows]["non-numeric-index"]])',
    'items = [rows]\nbox = Stack([items[0]])',
    'holder = {child: rows}\nbox = Stack([holder.child])',
    'holder = {child: rows}\nbox = Stack([holder["child"]])',
    'box = Stack([@First([{child: rows}]).child])',
    'box = Stack([@Each([rows], "item", item)])',
    'box = Stack([@Each([rows], item, item)])',
    'box = Stack([@Each([{child: rows}], "item", item.child)])',
    'box = Stack([@Each([rows], "item", Card([item]))])',
    'box = Stack([@Each([[rows]], "group", @Each(group, "item", item))])',
    'box = Stack([@Each([rows], "item", item)[0]])',
    'box = Stack([@Filter([rows], "state", "!=", "empty")])',
    'box = Stack([@Sort([rows], "state")[0]])',
    'box = Stack([ToolBoundTable(rows, [{field: "title", label: "Draft"}]).props.source])',
    '$child = rows\nbox = Stack([$child])',
  ]) {
    const result = validate(prefix + body);
    assert.equal(result.accepted, false, body);
    assert.deepEqual(errorsOf(result, 'query_as_child'), ['query_as_child:rows'], `${body}: ${JSON.stringify(result.errors)}`);
  }
});

test('query conditions, scalar expressions and lexically scoped component children stay valid', () => {
  const prefix = 'root = RafiiRoot([table, box])\nrows = Query("drafts_list", {}, null)\n'
    + 'table = ToolBoundTable(rows, [{field: "title", label: "Draft"}])\n';
  for (const body of [
    'box = Stack([rows && Text("Loaded")])',
    'box = Stack([@Count(rows.data.rows) > 0 && Text("Drafts")])',
    'box = Stack([Text(@Count(rows.data.rows) > 0 ? "Drafts" : "Empty")])',
    'box = Stack([Text(rows.data.title || "Empty")])',
    'box = Stack([rows.data.title])',
    'box = Stack([@Each(rows.data.rows, "row", Card([Text(row.title)]))])',
    'box = Stack([@Each(["Visible"], "rows", Card([rows]))])',
    'box = Stack([@Each(["Visible"], rows, Card([rows]))])',
    'box = Stack([@Each([["Visible"]], "item", @Each(item, "item", Card([item])))])',
    'holder = {ignored: rows, child: Text("Visible")}\nbox = Stack([holder.child])',
    'items = [rows, Text("Visible")]\nbox = Stack([items[1]])',
    'box = Stack([[{length: rows}].length])',
  ]) {
    const result = validate(prefix + body);
    assert.equal(result.accepted, true, `${body}: ${JSON.stringify(result.errors)}`);
  }
});

test('child alias cycles and excessive depth fail closed; valid component data sources still pass', () => {
  const cycle = validate('root = RafiiRoot([first])\nfirst = second\nsecond = first');
  assert.equal(cycle.accepted, false);
  assert.ok(hasCode(cycle, 'unresolved_ref'), JSON.stringify(cycle.errors));
  const aliases = Array.from({ length: 40 }, (_, i) => `a${i} = ${i === 39 ? 'Text("Visible")' : `a${i + 1}`}`);
  const deep = validate(['root = RafiiRoot([a0])', ...aliases].join('\n'));
  assert.equal(deep.accepted, false);
  assert.ok(hasCode(deep, 'bounds_depth'), JSON.stringify(deep.errors));
  const data = validate([
    'root = RafiiRoot([alias, conditional, items])',
    'rows = Query("drafts_list", {}, null)',
    'table = ToolBoundTable(rows, [{field: "title", label: "Draft"}], null, null, "drafts")',
    'alias = table',
    'conditional = @Count(rows.data.rows) > 0 ? table : Text("No drafts")',
    'items = @Each(rows.data.rows, "row", Text(row.title))',
  ].join('\n'));
  assert.equal(data.accepted, true, JSON.stringify(data.errors));
  assert.deepEqual(errorsOf(data, 'query_as_child'), []);
});

test('patch: orphans in a stored base are unexplained deletions on any edit; the deletion guard is unchanged (D-A52)', () => {
  // Views stored before this rule may still hold orphans. lang-core's merge garbage-collects them, and the guard cannot explain
  // a removal no parent made, so the edit (or its repair) must remove each one on purpose.
  const edit = 'drafts = Query("drafts_list", {platform: "threads"}, null)';
  const raw = validate(edit, { mode: 'patch', baseSource: ORPHANED });
  assert.equal(raw.accepted, false);
  assert.deepEqual(errorsOf(raw, 'unexplained_deletion'), ['unexplained_deletion:note', 'unexplained_deletion:reach', 'unexplained_deletion:summary']);
  const explicit = validate(`${edit}\nsummary = null\nreach = null\nnote = null`, { mode: 'patch', baseSource: ORPHANED });
  assert.equal(explicit.accepted, true, JSON.stringify(explicit.errors));
  assert.ok(explicit.canonicalSource.includes('{platform: "threads"}'));
  // A base accepted under the rule has no orphans, so the same edit is accepted first time.
  const clean = validate(edit, { mode: 'patch', baseSource: validate(GOOD).canonicalSource });
  assert.equal(clean.accepted, true, JSON.stringify(clean.errors));
  assert.deepEqual(clean.removedStatementIds, []);
});

test('query arguments: DateRange member access, a null object and copied hint literals are rejected (D-A52)', () => {
  const view = (args) => validate(`root = RafiiRoot([t])\n$range = null\nrows = Query("drafts_list", ${args}, null)\nt = ToolBoundTable(rows, [{field: "title", label: "Draft"}], null, null, "drafts")`);
  assert.ok(hasCode(view('{start: $range.start, end: $range.end}'), 'query_args_shape'));
  assert.ok(hasCode(view('null'), 'query_args_shape'), 'a null arguments object is rejected');
  for (const args of ['{start: "YYYY-MM-DD"}', '{end: " YYYY-MM-DD "}', '{local: "YYYY-MM-DDTHH:MM"}', '{zone: "Area/City"}', '{draftId: "<id from CONTEXT>"}',
    '{q: "<text>"}', '{ids: ["d1", "<id>"]}', '{filter: {zone: "Area/City"}}']) {
    const result = view(args);
    assert.deepEqual(errorsOf(result, 'query_arg_placeholder'), ['query_arg_placeholder:rows'], `${args}: ${JSON.stringify(result.errors)}`);
  }
  for (const args of ['{start: "2026-10-12", end: "2026-10-18"}', '{zone: "Asia/Hong_Kong"}', '{q: "a < b"}', '{ids: ["d1", "d2"]}', '{}']) {
    assert.equal(view(args).accepted, true, args);
  }
});

test('query hints are rejected through reactive initializers while real state-backed filters remain valid', () => {
  const view = (state, args) => validate([
    'root = RafiiRoot([t])', state,
    `rows = Query("drafts_list", ${args}, null)`,
    't = ToolBoundTable(rows, [{field: "title", label: "Draft"}], null, null, "drafts")',
  ].join('\n'));
  for (const [state, args] of [
    ['$start = "YYYY-MM-DD"', '{start: $start}'],
    ['$zone = "Area/City"', '{zone: $zone}'],
    ['$ids = ["d1", "<id>"]', '{ids: $ids}'],
    ['$filter = {zone: "Area/City"}', '{filter: $filter}'],
    ['$date = "YYYY-MM-DD"\n$start = $date', '{start: $start}'],
  ]) {
    const result = view(state, args);
    assert.equal(result.accepted, false, state);
    assert.deepEqual(errorsOf(result, 'query_arg_placeholder'), ['query_arg_placeholder:rows'], JSON.stringify(result.errors));
  }
  for (const [state, args] of [
    ['$start = "2026-10-12"', '{start: $start}'],
    ['$zone = "Asia/Hong_Kong"', '{zone: $zone}'],
    ['$ids = ["d1", "d2"]', '{ids: $ids}'],
    ['$platform = null', '{platform: $platform}'],
    ['$picked = []', '{ids: $picked}'],
  ]) {
    const result = view(state, args);
    assert.equal(result.accepted, true, `${state}: ${JSON.stringify(result.errors)}`);
  }
  const cycle = view('$first = $second\n$second = $first', '{q: $first}');
  assert.equal(cycle.accepted, false);
  assert.ok(hasCode(cycle, 'query_args_shape'), JSON.stringify(cycle.errors));
});

test('names: one binding read twice takes two distinct Query names; a Query name is never reused for a component (D-A52)', () => {
  const two = [
    'root = RafiiRoot([reach, views])',
    'reachSeriesData = Query("analytics_trend", {metric: "reach"}, null)',
    'viewsSeriesData = Query("analytics_trend", {metric: "views"}, null)',
    'reach = ToolBoundChart(reachSeriesData, "line", "day", [{field: "value", label: "Reach"}], "Reach")',
    'views = ToolBoundChart(viewsSeriesData, "line", "day", [{field: "value", label: "Views"}], "Views")',
  ].join('\n');
  const result = validate(two);
  assert.equal(result.accepted, true, JSON.stringify(result.errors));
  assert.deepEqual(result.queryNames, ['analytics_trend']);
  const reused = two.replace('reach = ToolBoundChart(reachSeriesData', 'reachSeriesData = ToolBoundChart(reachSeriesData').replace('[reach, views]', '[reachSeriesData, views]');
  assert.ok(errorsOf(validate(reused), 'duplicate_statement').includes('duplicate_statement:reachSeriesData'));
});
