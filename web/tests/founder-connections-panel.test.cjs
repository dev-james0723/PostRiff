const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

/**
 * Founder Settings → "Connections needing attention" (PR #150, Rafii API connections A29-A31). Renders the real panel
 * (TypeScript/TSX transpiled in place) with its data hooks replaced by fixtures, and checks each state an operator can
 * see: loading, inaccessible (403), error, empty, degraded and populated. Unknown counts never read as 0, stale or
 * unreadable sources never read as healthy, and the query asks only for the read-only route in the session's mode.
 */
const SRC = path.join(__dirname, '..', 'src');
const PANEL = 'features/founder/settings/connections-attention-panel.tsx';

const harness = { query: null, options: null, scope: null, fetches: [] };
const stubs = {
  '@tanstack/react-query': { useQuery: (options) => { harness.options = options; return harness.query; } },
  '@/components/rafii': {
    StateMessage: ({ kind, title, description, action }) => React.createElement('div', { 'data-state': kind }, title, ' — ', description, action ?? null)
  },
  '@/lib/founder/api': { founderFetch: (route, init) => { harness.fetches.push({ route, init }); return Promise.resolve({ data: { ok: true } }); } },
  '../customers/kit/api': {
    useFounderScope: () => harness.scope,
    failureOf: (error) => ({ message: error?.message ?? 'failed', code: error?.code, status: typeof error?.status === 'number' ? error.status : undefined })
  },
  '../customers/kit/page-frame': {
    Panel: ({ title, description, children }) => React.createElement('section', { 'data-panel': title }, React.createElement('p', null, description), children),
    RetryAction: () => React.createElement('button', { type: 'button' }, 'Try again')
  }
};

function load(relative) {
  const file = path.join(SRC, relative);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
  });
  const mod = { exports: {} };
  const localRequire = (specifier) => {
    if (Object.hasOwn(stubs, specifier)) return stubs[specifier];
    assert.ok(!specifier.startsWith('.') && !specifier.startsWith('@/'), `unexpected panel import ${specifier}`);
    return require(specifier);
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}

const panel = load(PANEL);

const fresh = { freshness: 'fresh', coverage: 'complete', observedAt: '2026-10-09T23:00:00Z', lastCheckedAt: '2026-10-09T23:00:00Z', reason: null };
const unknownFreshness = { freshness: 'unknown', coverage: 'complete', observedAt: null, lastCheckedAt: null, reason: 'missing_timestamp' };
const count = (value, countState) => ({ value, countState });
const UNKNOWN = count(null, 'unknown');
const registry = [
  { provider: 'youtube', appRef: 'youtube', environment: 'production', readiness: 'check_required', launchScope: true,
    requirements: [{ kind: 'brand_verification', standing: 'check_required', blockers: ['no_decision_recorded'], freshness: unknownFreshness }] },
  { provider: 'google', appRef: 'rafii-sign-in', environment: 'production', readiness: 'check_required', launchScope: false,
    requirements: [{ kind: 'domain_ownership', standing: 'check_required', blockers: ['no_decision_recorded'], freshness: unknownFreshness }] }
];
const connected = { connectionHealth: { state: 'connected', freshness: fresh }, incidents: { state: 'connected' } };

function item(overrides = {}) {
  return {
    id: 'att_1', priority: 'P2', category: 'reconnect_required', state: 'open', title: 'Connections need new consent for the current client',
    summary: '3 youtube connection(s) in 2 workspace(s) report client binding missing.', launchBlocker: false,
    affected: { users: UNKNOWN, tenants: count(2, 'exact'), connections: count(3, 'exact'), jobs: UNKNOWN },
    owner: { lane: 'connections', label: 'Unassigned — coordinator action required' },
    nextAction: { label: 'Ask the account holder to reconnect.', requiresHuman: true }, freshness: fresh, ...overrides
  };
}

function render({ query, ready = true, mode = 'live' }) {
  harness.query = { isPending: false, isError: false, error: null, data: undefined, refetch: () => {}, ...query };
  harness.scope = { mode, environment: 'production', ready, key: (...parts) => ['founder', mode, 'production', ...parts] };
  return renderToStaticMarkup(React.createElement(panel.ConnectionsAttentionPanel));
}

test('the query reads only the read-only attention route in the session mode, forwards cancellation and waits for the session', async () => {
  render({ query: { isPending: true }, mode: 'demo', ready: false });
  assert.equal(harness.options.enabled, false, 'no request before the Founder session is ready');
  assert.deepEqual(harness.options.queryKey, ['founder', 'demo', 'production', 'connections-attention']);
  const controller = new AbortController();
  harness.fetches.length = 0;
  await harness.options.queryFn({ signal: controller.signal });
  assert.equal(harness.fetches.length, 1);
  assert.equal(harness.fetches[0].route, '/connections/attention?mode=demo');
  assert.equal(harness.fetches[0].init.signal, controller.signal, 'React Query cancellation reaches the request');
  assert.equal(harness.fetches[0].init.method, undefined, 'a GET: the panel never writes');
});

test('loading says so and shows no counts', () => {
  const html = render({ query: { isPending: true } });
  assert.match(html, /Loading connections…/);
  assert.doesNotMatch(html, /Workspaces affected/);
});

test('an operator without control.read sees a permission state, not an error or an empty queue', () => {
  const html = render({ query: { isError: true, error: { status: 403, code: 'SCOPE_DENIED', message: 'Scope denied' } } });
  assert.match(html, /data-state="permission"/);
  assert.match(html, /not available to this operator/);
  assert.doesNotMatch(html, /Try again|No open items|Workspaces affected/);
});

test('a failed read is an error with a retry that never claims health', () => {
  const html = render({ query: { isError: true, error: { status: 503, code: 'SOURCE_UNAVAILABLE', message: 'Control source unavailable' } } });
  assert.match(html, /data-state="error"/);
  assert.match(html, /Nothing has been counted as healthy/);
  assert.match(html, /Try again/);
  assert.doesNotMatch(html, /No open items/);
});

test('an empty queue from fresh, complete sources says exactly that', () => {
  const html = render({ query: { data: { items: [], truncated: false, total: 0, summary: { tenants: count(0, 'exact'), unassigned: 0, launchBlockers: 0 }, registry, sources: connected } } });
  assert.match(html, /No open items from the observed sources\./);
  assert.match(html, /Workspaces affected: 0/);
  assert.match(html, /Connection health: Current/);
  assert.match(html, /Provider approvals \(0 of 2 apps evidenced\)/);
  assert.doesNotMatch(html, /Not readable/);
});

test('degraded sources are named and their impact is unknown, never zero or current', () => {
  const sources = { connectionHealth: { state: 'unavailable', freshness: unknownFreshness }, incidents: { state: 'unavailable' } };
  const stale = item({ id: 'att_2', priority: 'P3', category: 'stale_telemetry', title: 'Connection health is not observed', owner: { lane: 'ops', label: 'Unassigned — coordinator action required' },
    affected: { users: UNKNOWN, tenants: UNKNOWN, connections: UNKNOWN, jobs: UNKNOWN }, freshness: unknownFreshness, nextAction: { label: 'Check the connection health projection.', requiresHuman: true } });
  const html = render({ query: { data: { items: [stale], truncated: false, total: 1, summary: { tenants: UNKNOWN, unassigned: 1, launchBlockers: 0 }, registry, sources } } });
  assert.match(html, /Not readable: connection health \(unavailable\), incidents \(unavailable\)\. Their impact is unknown, not zero\./);
  assert.match(html, /Workspaces affected: unknown/);
  assert.match(html, /Connection health: Check required/);
  assert.match(html, /Workspaces: unknown · Connections: unknown · Jobs: unknown · Users: unknown/);
  assert.doesNotMatch(html, /Workspaces affected: 0|Connection health: Current/);
});

test('a populated queue shows priority, blockers, honest counts, owner, next step, truncation and the registry', () => {
  const stalePartial = { freshness: 'stale', coverage: 'partial', observedAt: '2026-10-09T20:00:00Z', lastCheckedAt: '2026-10-09T20:00:00Z', reason: 'stale_after_exceeded' };
  const items = [
    item({ id: 'att_a', priority: 'P1', category: 'publishing', state: 'acknowledged', title: 'Publish failure rate · global',
      affected: { users: UNKNOWN, tenants: UNKNOWN, connections: UNKNOWN, jobs: count(4, 'estimated') }, owner: { lane: 'publishing', label: null },
      nextAction: { label: 'Inspect the exact failed jobs.', requiresHuman: true }, freshness: { ...fresh, freshness: 'not_applicable' } }),
    item({ id: 'att_b', priority: 'P2', category: 'launch_blocker', launchBlocker: true, title: 'youtube approval evidence is incomplete',
      affected: { users: UNKNOWN, tenants: UNKNOWN, connections: UNKNOWN, jobs: UNKNOWN }, freshness: unknownFreshness }),
    item({ id: 'att_c', affected: { users: UNKNOWN, tenants: count(5000, 'lower_bound'), connections: count(5000, 'lower_bound'), jobs: UNKNOWN }, freshness: stalePartial })
  ];
  const sources = { connectionHealth: { state: 'connected', freshness: stalePartial }, incidents: { state: 'connected' } };
  const html = render({ query: { data: { items, truncated: true, total: 7, summary: { tenants: count(5000, 'lower_bound'), unassigned: 2, launchBlockers: 1 }, registry, sources } } });
  assert.match(html, /Workspaces affected: at least 5000 · 1 launch blocker\(s\) · 2 unassigned/);
  assert.match(html, /P1 · Publish failure rate · global · acknowledged/);
  assert.match(html, /P2 · youtube approval evidence is incomplete · Launch blocker/);
  assert.match(html, /Jobs: ~4/);
  assert.match(html, /Workspaces: at least 5000 · Connections: at least 5000/);
  assert.match(html, /Owner: publishing · Episode record/);
  assert.match(html, /Owner: Unassigned — coordinator action required · Check required/);
  assert.match(html, /Next: Ask the account holder to reconnect\. \(needs a person\)/);
  assert.match(html, /Stale · last good/);
  assert.doesNotMatch(html, /Connection health: Current/, 'stale evidence is never current');
  assert.match(html, /Showing the first 3 of 7 items\./);
  assert.match(html, /youtube<\/span> · check required · launch scope/);
  assert.match(html, /brand verification: check required/);
  assert.doesNotMatch(html, /Not readable/);
});

test('count and freshness wording never turns unknown into 0 or partial into complete', () => {
  assert.equal(panel.formatCount(UNKNOWN, 'Users'), 'Users: unknown');
  assert.equal(panel.formatCount({ value: 0, countState: 'unknown' }, 'Users'), 'Users: unknown');
  assert.equal(panel.formatCount(count(3, 'lower_bound'), 'Jobs'), 'Jobs: at least 3');
  assert.equal(panel.formatCount(count(3, 'estimated'), 'Jobs'), 'Jobs: ~3');
  assert.equal(panel.freshnessLabel({ ...fresh, coverage: 'partial' }), 'Current (partial coverage)');
  assert.equal(panel.freshnessLabel(unknownFreshness), 'Check required');
  assert.equal(panel.freshnessLabel({ ...fresh, freshness: 'stale', observedAt: null }), 'Stale');
  assert.deepEqual(panel.degradedSources(connected), []);
  assert.deepEqual(panel.degradedSources({ connectionHealth: { state: 'source_not_configured', freshness: unknownFreshness }, incidents: { state: 'connected' } }),
    ['connection health (source not configured)']);
});

test('Founder Settings mounts the panel', () => {
  const settings = fs.readFileSync(path.join(SRC, 'features/founder/settings/settings-view.tsx'), 'utf8');
  assert.match(settings, /import \{ ConnectionsAttentionPanel \} from '\.\/connections-attention-panel'/);
  assert.match(settings, /<ConnectionsAttentionPanel \/>/);
});
