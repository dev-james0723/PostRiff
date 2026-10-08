/**
 * Lane C — RafiiGenerativeMessage and the primitives through the real OpenUI 0.3.2 Renderer, server-rendered with
 * react-dom/server (the repo's node --test pattern: no jsdom). Covers C01/C02/C07 rendering, G06/G12 isolation and the
 * evidence hooks lane G locates ([data-rafii-generated][data-artifact-id][data-generation-state]).
 * Effects do not run in server rendering, so these tests also show that rendering alone makes no request.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { createLoader } = require('./agent-ui-library-loader.cjs');

const loader = createLoader();
const React = loader.requireWeb('react');
const { renderToStaticMarkup } = loader.requireWeb('react-dom/server');
const parser = loader.load('src/lib/agent-runtime/ui-parser/index.ts');
const contracts = loader.load('src/lib/agent-runtime/ui-contracts.ts');
const registry = loader.load('src/features/agent/generative-ui/library-registry.ts');
const { RafiiGenerativeMessage, supportedLibraryHashes } = loader.load('src/features/agent/generative-ui/renderer.tsx');
const library = loader.load('src/features/agent/generative-ui/library.tsx');
const founderLibrary = loader.load('src/features/agent/generative-ui/founder-library.tsx');
const build = loader.load('src/features/agent/generative-ui/core/build-library.tsx');

const ARTIFACT_ID = '6c1f2f3e-1111-4222-8333-944455556666';
const consumer = parser.validatorLibrary('consumer');

function canonical(source, reads = ['drafts_list'], actions = ['draft_rewrite']) {
  const result = parser.validateAndMergeUi({
    v: 'v1',
    contractVersion: contracts.CONTRACT_VERSION,
    mode: 'generate',
    baseSource: null,
    candidateSource: source,
    libraryHash: consumer.libraryHash,
    policy: { rootName: 'RafiiRoot', allowedComponents: registry.LIBRARY_DEFINITIONS.consumer.specs.map((s) => s.name), readBindings: reads, actionIds: actions },
    scope: { workspaceId: 'w', artifactId: ARTIFACT_ID, attemptId: 't' },
  });
  assert.equal(result.accepted, true, JSON.stringify(result.errors));
  return result;
}

function artifact(overrides = {}) {
  return {
    contractVersion: 'rafii-genui/1',
    artifactId: ARTIFACT_ID,
    conversationId: '6c1f2f3e-1111-4222-8333-000000000001',
    messageId: '6c1f2f3e-1111-4222-8333-000000000002',
    runId: '6c1f2f3e-1111-4222-8333-000000000003',
    revision: 1,
    generationAttemptId: '6c1f2f3e-1111-4222-8333-000000000004',
    generationState: 'ready',
    validationState: 'accepted',
    language: 'openui-lang',
    languageVersion: '0.3.2',
    libraryVersion: 'rafii-components/1.0.0',
    libraryHash: consumer.libraryHash,
    promptHash: 'p',
    sourceHash: null,
    canonicalSource: null,
    fallbackText: 'Here are your drafts.',
    manifestId: 'm1',
    bindingVersion: 1,
    safeState: {},
    stateRevision: 0,
    createdAt: '2026-10-08T12:00:00Z',
    updatedAt: '2026-10-08T12:00:00Z',
    asOf: null,
    ...overrides,
  };
}

let fetches = 0;
const transport = {
  base: '/api/workspaces/w1/agent/ui',
  scope: 'workspace',
  scopeKey: 'user-1:w1',
  fetch: async () => {
    fetches += 1;
    throw new Error('no network in render tests');
  },
};
const manifest = {
  manifestId: 'm1',
  bindingVersion: 1,
  journeyIds: ['J01'],
  componentGroups: ['layout', 'data'],
  queries: [{ name: 'drafts_list', description: 'Drafts', argsSchema: {}, refreshMinSeconds: null, pageSize: 50 }],
  actions: [{ actionId: 'draft_rewrite', label: 'Rewrite with Rafii', effect: 'CREATE_DRAFT', requiresConfirmation: true, inputSchema: {}, summary: null }],
  expiresAt: null,
};

function render(props) {
  return renderToStaticMarkup(
    React.createElement(RafiiGenerativeMessage, {
      surface: 'chat',
      transport,
      manifest,
      onContinue: () => {
        throw new Error('render must not send follow-ups');
      },
      nativeResult: React.createElement('p', { 'data-native': '' }, 'Native answer stays.'),
      ...props,
    }),
  );
}

const KITCHEN = [
  'root = RafiiRoot([s, g, sec, card, tabs, acc, txt, link, empty, loading, err, table, chart, metric, tl, cmp, task, pick, form, btn, act], "All parts")',
  '$v = "first"',
  '$picked = []',
  '$range = null',
  'rows = Query("drafts_list", {}, null)',
  's = Stack([Text("one"), Text("two")], "horizontal", "sm")',
  'g = Grid([Text("g1"), Text("g2")], 2)',
  'sec = Section("Section title", [Text("in section")], "desc")',
  'card = Card([Text("in card")], "Card title", "card desc", "muted")',
  'tabs = Tabs([TabItem("First", [Text("tab one")], "first"), TabItem("Second", [Text("tab two")], "second")], $v)',
  'acc = Accordion([AccordionItem("More", [Text("hidden detail")], true)])',
  'txt = Text("<img src=x onerror=alert(1)> heading", "heading")',
  'link = EvidenceLink("Library", "/app/library", "Rafii", "2026-10-08")',
  'empty = EmptyState("Nothing yet", "Try later")',
  'loading = LoadingState("Loading drafts")',
  'err = ErrorState("Could not load", "Try again")',
  'table = ToolBoundTable(rows, [{field: "title", label: "Draft"}], null, "Drafts", "drafts")',
  'chart = ToolBoundChart(rows, "line", "day", [{field: "reach", label: "Reach"}], "Reach", null, "drafts")',
  'metric = Metric(rows, "totals.reach", "Reach", "number")',
  'tl = Timeline(rows, "createdAt", "title", "status", null, "drafts")',
  'cmp = Comparison(rows, "title", [{field: "body", label: "Text"}], "ref", $picked, "drafts")',
  'task = TaskStatus(rows, "title", "status")',
  'pick = SelectionList(rows, "title", $picked, "ref", null, 2, "Pick", "drafts")',
  'form = Form("brief", [TextField("goal", "Goal", null, "Your goal", false, {required: true}), Select("platform", "Platform", [{value: "a", label: "A"}]), DateRange("range", "Period", $range)])',
  'btn = Button("Refresh", Action([@Run(rows)]), "secondary")',
  'act = ActionButton("draft_rewrite", "brief", {draftIds: $picked})',
].join('\n');

test('every spec in both libraries has a renderer', () => {
  assert.deepEqual(build.missingRenderers('consumer', library.CONSUMER_RENDERERS), []);
  assert.deepEqual(build.missingRenderers('founder', founderLibrary.FOUNDER_RENDERERS), []);
  assert.ok(supportedLibraryHashes('consumer').includes(consumer.libraryHash), 'generated assets match the current consumer library');
});

function capture(fn) {
  const errors = [];
  const original = console.error;
  console.error = (...args) => errors.push(args.map((a) => (a && a.stack) || String(a)).join(' ').slice(0, 600));
  try {
    return { value: fn(), errors };
  } finally {
    console.error = original;
  }
}

test('an accepted view renders every primitive inside the generated frame, after the native answer', () => {
  const result = canonical(KITCHEN);
  const { value: html, errors } = capture(() => render({ artifact: artifact({ canonicalSource: result.canonicalSource, sourceHash: result.sourceHash }) }));
  const markers = [...html.matchAll(/data-genui(?:-invalid|-missing)?="[^"]*"/g)].map((m) => m[0]);
  const openui = loader.load('src/features/agent/generative-ui/core/openui.ts');
  const parsed = openui.createParser(library.CONSUMER_LIBRARY.toJSONSchema(), 'RafiiRoot').parse(result.canonicalSource);
  const rootKids = (parsed.root?.props?.children ?? []).map((c) => (c && c.typeName) || String(c));
  const why = () =>
    `\nmarkers: ${markers.join(' ')}\nreact-library parse: children=${rootKids.join(',')} errors=${JSON.stringify(parsed.meta.errors).slice(0, 800)} unresolved=${parsed.meta.unresolved}\nconsole.error: ${errors.slice(0, 3).join('\n')}`;
  assert.ok(html.indexOf('data-native') < html.indexOf('data-rafii-generated'), 'native answer first');
  assert.match(html, new RegExp(`data-rafii-generated="" data-artifact-id="${ARTIFACT_ID}" data-generation-state="ready"`));
  for (const name of ['RafiiRoot', 'Stack', 'Grid', 'Section', 'Card', 'Tabs', 'AccordionItem', 'Text', 'EvidenceLink', 'EmptyState', 'LoadingState', 'ErrorState',
    'ToolBoundTable', 'ToolBoundChart', 'Metric', 'Timeline', 'Comparison', 'TaskStatus', 'SelectionList', 'Form', 'TextField', 'Select', 'DateRange', 'Button', 'ActionButton']) {
    assert.ok(html.includes(`data-genui="${name}"`), `${name} rendered${why()}`);
  }
  assert.ok(!html.includes('data-genui-invalid'), `no component rejected its props${why()}`);
  assert.ok(!html.includes('data-genui-missing'), 'no missing renderer');
  assert.ok(html.includes('tab one') && html.includes('in card') && html.includes('hidden detail'));
  // Text is text: no HTML injection from generated strings.
  assert.ok(!html.includes('<img src=x'));
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt; heading'));
  // Reads have not run (no provider during server render): bound components wait; nothing was fetched.
  assert.equal(fetches, 0);
});

test('stable statement ids key children (inserting a statement does not remount siblings)', () => {
  const result = canonical('root = RafiiRoot([a, b])\na = Text("first")\nb = TextField("name", "Name")');
  const html = render({ artifact: artifact({ canonicalSource: result.canonicalSource }) });
  assert.match(html, /data-genui="Text" data-statement-id="a"/);
  assert.match(html, /data-genui="TextField" data-statement-id="b"/);
});

test('while streaming, literal data typed into a bound component is never shown and actions are off', () => {
  const source = [
    'root = RafiiRoot([t, act])',
    't = ToolBoundTable({state: "available", data: [{title: "FAKE ROW 123"}], asOf: null, sourceRefs: [], revision: null, nextCursor: null, coverage: {known: null, total: null, note: null}, warnings: []}, [{field: "title", label: "T"}])',
    'act = ActionButton("draft_rewrite")',
  ].join('\n');
  const html = render({
    artifact: artifact({ generationState: 'streaming', validationState: 'pending', revision: 0 }),
    render: { mode: 'preview', artifact: null, source, accepted: false },
  });
  assert.ok(!html.includes('FAKE ROW 123'));
  assert.match(html, /data-generation-state="streaming"/);
  assert.match(html, /aria-busy="true"/);
  // No write control is offered for an unaccepted revision (the action label never appears as an enabled button).
  assert.ok(!html.includes('Rewrite with Rafii'));
});

test('an artifact from an unsupported library version shows its stored fallback without generating', () => {
  const html = render({ artifact: artifact({ libraryHash: 'f'.repeat(64), canonicalSource: 'root = RafiiRoot([])' }) });
  assert.ok(html.includes('earlier version'));
  assert.ok(!html.includes('data-genui="RafiiRoot"'));
});

test('a failed presentation keeps the native answer and names the failure', () => {
  const html = render({ artifact: artifact({ generationState: 'failed', validationState: 'rejected', revision: 0 }) });
  assert.ok(html.includes('Native answer stays.'));
  assert.match(html, /data-generation-state="failed"/);
  assert.ok(html.includes('couldn’t be shown'));
  assert.ok(!html.includes('data-genui="RafiiRoot"'));
});

test('oversized streaming source is stopped by the watchdog before parsing', () => {
  const huge = `root = RafiiRoot([t])\nt = Text("${'x'.repeat(contracts.BOUNDS.sourceBytes + 10)}")`;
  const html = render({ artifact: artifact({ generationState: 'streaming', validationState: 'pending', revision: 0 }), render: { mode: 'preview', artifact: null, source: huge, accepted: false } });
  assert.ok(html.includes('too large'));
  assert.ok(!html.includes('data-genui="Text"'));
});

test('browser voice mounts no visual view (speaks the native summary only)', () => {
  const result = canonical('root = RafiiRoot([t])\nt = Text("hello")');
  const html = render({ surface: 'browser_voice', artifact: artifact({ canonicalSource: result.canonicalSource }) });
  assert.equal(html, '<p data-native="">Native answer stays.</p>');
});

test('unsafe links render as text; in-app links stay in the app', () => {
  const result = parser.validateAndMergeUi({
    v: 'v1', contractVersion: contracts.CONTRACT_VERSION, mode: 'generate', baseSource: null,
    candidateSource: 'root = RafiiRoot([a])\na = EvidenceLink("Library", "/app/library")', libraryHash: consumer.libraryHash,
    policy: { rootName: 'RafiiRoot', allowedComponents: ['RafiiRoot', 'EvidenceLink'], readBindings: [], actionIds: [] },
    scope: { workspaceId: 'w', artifactId: ARTIFACT_ID, attemptId: 't' },
  });
  const html = render({ artifact: artifact({ canonicalSource: result.canonicalSource }) });
  assert.ok(html.includes('href="/app/library"'));
  // A stored source is still data: an unsafe href in it is not rendered as a link.
  const tampered = render({ artifact: artifact({ canonicalSource: 'root = RafiiRoot([a])\na = EvidenceLink("Bad", "javascript:alert(1)")', sourceHash: crypto.createHash('sha256').update('x').digest('hex') }) });
  assert.ok(!tampered.includes('javascript:'));
});
