const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

/**
 * Founder slice 8.D web (CONTRACTS §8.D): Operations, Support and Advanced data health. Loads the pure adapters in
 * `features/founder/operations/ops-model.ts` exactly as the pages see them (TypeScript transpiled in place, relative
 * imports resolved to sibling sources) and checks: every page query asks only for its metric's catalog dimensions (a
 * 4xx from a page query is a bug), server rows are read by `dimensions.window`/their own dimensions and never turned into
 * 0, the swimlane geometry stays inside its track, and the views keep the guarantees the browser gate relies on.
 */
const ROOT = path.join(__dirname, '..', '..');
const SRC = path.join(__dirname, '..', 'src');
const cache = new Map();

function load(relative) {
  const file = path.join(SRC, relative);
  if (cache.has(file)) return cache.get(file);
  const source = fs.readFileSync(file, 'utf8');
  const { outputText } = ts.transpileModule(source, { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  cache.set(file, mod.exports);
  const localRequire = (specifier) => {
    if (specifier.startsWith('.')) {
      const resolved = path.resolve(path.dirname(file), specifier);
      const candidate = ['.ts', '.tsx', '/index.ts', '/index.tsx'].map((ext) => resolved + ext).find((name) => fs.existsSync(name));
      if (candidate) return load(path.relative(SRC, candidate));
    }
    return require(specifier);
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  cache.set(file, mod.exports);
  return mod.exports;
}

const ops = load('features/founder/operations/ops-model.ts');
const read = (relative) => fs.readFileSync(path.join(SRC, relative), 'utf8');

/** The catalog the server validates against: metrics.json, then every metrics.d extension (an activated row governs its id). */
function catalog() {
  const pack = path.join(ROOT, 'src/rafii_control/pack/catalogs');
  const rows = JSON.parse(fs.readFileSync(path.join(pack, 'metrics.json'), 'utf8'));
  const extensions = fs.readdirSync(path.join(pack, 'metrics.d')).filter((name) => name.endsWith('.json')).toSorted();
  for (const name of extensions) rows.push(...JSON.parse(fs.readFileSync(path.join(pack, 'metrics.d', name), 'utf8')));
  const byId = new Map();
  for (const row of rows) {
    const current = byId.get(row.id);
    if (!current || current.status !== 'activated_v1') byId.set(row.id, row);
  }
  return byId;
}

const INTERVAL = { start: '2026-09-24T00:00:00Z', end: '2026-10-01T00:00:00Z', timeZone: 'UTC' };
function row(metricId, dimensions, value, extra = {}) {
  return { metricId, definitionVersion: 'v1', interval: INTERVAL, dimensions, value, unit: 'count', dataState: 'measured', coverage: null, sourceWatermark: null, ...extra };
}

test('every page query asks only for its metric catalog dimensions, at most three, without a comparison', () => {
  const metrics = catalog();
  for (const [key, spec] of Object.entries(ops.OPS_QUERIES)) {
    const entry = metrics.get(spec.id);
    assert.ok(entry, `${key}: ${spec.id} is in the catalog`);
    assert.equal(entry.status, 'activated_v1', `${key}: ${spec.id} is activated`);
    assert.ok(spec.groupBy.length <= 3, `${key}: the schema allows three dimensions`);
    for (const dimension of spec.groupBy) assert.ok(entry.allowed_dimensions.includes(dimension), `${key}: ${spec.id} allows ${dimension}`);
    assert.ok(!('comparison' in spec), `${key}: no comparison (refused with a window grouping)`);
  }
  // publish_outcomes groups by platform (its real dimension); provider belongs to publish_by_provider only.
  assert.deepEqual(ops.OPS_QUERIES.publishOutcomes.groupBy, ['platform', 'status']);
  assert.deepEqual(ops.opsSpec('apiErrors', '7d'), { id: 'api_error_rate', period: '7d', groupBy: ['route'] });
  const spec = ops.opsSpec('apiErrors', '7d');
  spec.groupBy.push('x');
  assert.deepEqual(ops.OPS_QUERIES.apiErrors.groupBy, ['route'], 'opsSpec hands out a copy');
});

test('the views send every metric query through opsSpec, so the catalog check above covers them all', () => {
  for (const file of ['features/founder/operations/operations-view.tsx', 'features/founder/support/support-view.tsx', 'features/founder/advanced/data-health.tsx']) {
    const source = read(file);
    const calls = [...source.matchAll(/use(?:Tile)?Metric\((.*?)\);/g)].map((match) => match[1]);
    assert.ok(calls.length > 0, file);
    for (const argument of calls) assert.match(argument, /^opsSpec\('[a-zA-Z]+', (?:PERIOD|'[a-z0-9]+')\)$/, `${file}: ${argument}`);
    // The kit adapters filter on interval.start, which every server row carries; these pages use ops-model instead.
    assert.doesNotMatch(source, /wholeIntervalRows|categoriesFromRows|seriesFromRows/, file);
  }
});

test('a row the server did not measure is never a number, and never 0', () => {
  assert.equal(ops.shownValue(row('x', {}, 0)), 0, 'a measured zero is a real zero');
  assert.equal(ops.shownValue(row('x', {}, 5, { dataState: 'partial' })), 5);
  assert.equal(ops.shownValue(row('x', {}, 5, { dataState: 'unavailable' })), null);
  assert.equal(ops.shownValue(row('x', {}, null, { dataState: 'not_applicable' })), null);
  assert.equal(ops.shownValue(null), null);
  for (const format of [ops.formatCount, ops.formatMs, ops.formatBurn, ops.formatRatio, ops.formatAge]) {
    assert.equal(format(null), 'Unavailable');
    assert.equal(format(undefined), 'Unavailable');
    assert.equal(format(Number.NaN), 'Unavailable');
  }
  assert.equal(ops.formatMs(145.04), '145 ms');
  assert.equal(ops.formatMs(1500), '1.5 s');
  assert.equal(ops.formatMs(30000, true), '≥ 30 s');
  assert.equal(ops.formatBurn(14.4), '14.4×');
  assert.equal(ops.formatRatio(0.015), '1.5%');
  assert.equal(ops.formatAge(3 * 86400 + 43200), '3.5 d');
});

test('dimension items keep the server order and labels, and age bands sort in their natural order', () => {
  const rows = [row('support_aging', { age_band: 'over_30d' }, 1), row('support_aging', { age_band: 'under_1d' }, 4), row('support_aging', { age_band: '3d_to_7d' }, null, { dataState: 'unavailable' })];
  const bands = ops.ageBandItems(rows);
  assert.deepEqual(bands.map((item) => [item.label, item.value]), [['Under 1 day', 4], ['3–7 days', null], ['Over 30 days', 1]]);
  const kinds = ops.byDimension([row('support_aging', { kind: 'deletion' }, 2), row('support_aging', {}, 9)], 'kind', ops.REQUEST_KIND_LABELS);
  assert.deepEqual(kinds.map((item) => [item.label, item.value]), [['Account deletion', 2]]);
});

test('API health joins the error-rate row and the p50/p95 rows of each route, never averaging them', () => {
  const errors = [row('api_error_rate', { route: 'GET /api/health' }, 0.02, { unit: 'ratio', measures: { requests: 100, serverErrors: 2, clientErrors: 0 } }),
                  row('api_error_rate', { route: 'POST /api/workspaces/:id/actions' }, 0, { unit: 'ratio', measures: { requests: 5, serverErrors: 0, clientErrors: 1 }, dataState: 'partial', reason: 'collecting_since' })];
  const latency = [row('api_latency', { route: 'GET /api/health', percentile: 'p50' }, 9.6, { unit: 'milliseconds' }),
                   row('api_latency', { route: 'GET /api/health', percentile: 'p95' }, 30000, { unit: 'milliseconds', measures: { requests: 100, openEnded: true } }),
                   row('api_latency', { route: 'GET /api/cron/worker', percentile: 'p95' }, 4000, { unit: 'milliseconds' })];
  const routes = ops.routeHealth(errors, latency);
  assert.deepEqual(routes.map((route) => [route.route, route.requests, route.errorRate, route.p50, route.p95, route.p95OpenEnded]), [
    ['GET /api/health', 100, 0.02, 9.6, 30000, true],
    ['POST /api/workspaces/:id/actions', 5, 0, null, null, false],
    ['GET /api/cron/worker', null, null, null, 4000, false]
  ]);
  assert.equal(routes[1].errorRow.reason, 'collecting_since');
});

test('SLO burn shows the server verdicts per pair and the proposed-SLO label', () => {
  const label = 'proposed SLO, not approved';
  const measures = (alerting, threshold) => ({ alerting, threshold, label, basis: 'proposed_slo' });
  const rows = [
    row('slo_burn', { slo: 'api_availability', burn_window: '6h' }, 1, { unit: 'multiple', measures: { ...measures(false, 6), total: 7200, bad: 36 } }),
    row('slo_burn', { slo: 'api_availability', burn_window: '5m' }, 20, { unit: 'multiple', measures: { ...measures(true, 14.4), total: 100, bad: 10 } }),
    row('slo_burn', { slo: 'api_availability', burn_window: '1h' }, 20, { unit: 'multiple', measures: { ...measures(true, 14.4), total: 1200, bad: 120 } }),
    row('slo_burn', { slo: 'api_availability', burn_window: '30m' }, null, { unit: 'multiple', dataState: 'not_applicable', reason: 'no_events', measures: measures(false, 6) }),
    row('slo_burn', { slo: 'publish_success' }, null, { unit: 'multiple', dataState: 'unavailable', reason: 'not_instrumented' })
  ];
  const [api, publish] = ops.burnBySlo(rows);
  assert.deepEqual(api.windows.map((window) => [window.window, window.value]), [['5m', 20], ['30m', null], ['1h', 20], ['6h', 1]]);
  assert.deepEqual(api.pairs, [{ pair: '1h/5m', threshold: 14.4, alerting: true }, { pair: '6h/30m', threshold: 6, alerting: false }]);
  assert.equal(api.sloLabel, label);
  assert.equal(api.label, 'API availability');
  assert.equal(publish.unavailable.reason, 'not_instrumented');
  assert.deepEqual(publish.windows, []);
});

test('queue counters group by their queue with labels; peaks are row values, the latest a measure', () => {
  const rows = [row('queue_health', { counter: 'sms.backlogOver10m', queue: 'sms' }, 2, { measures: { latest: 0, latestAt: '2026-09-30T12:00:00+00:00', snapshots: 1440 } }),
                row('queue_health', { counter: 'queueDelayed', queue: 'publishing' }, 4, { measures: { latest: 1, latestAt: '2026-09-30T12:00:00+00:00', snapshots: 1440 } }),
                row('queue_health', { counter: 'mystery', queue: 'other' }, null, { dataState: 'unavailable' })];
  const groups = ops.queueGroups(rows);
  assert.deepEqual(groups.map((group) => group.queue), ['publishing', 'sms', 'other']);
  assert.deepEqual(groups[0].counters.map((counter) => [counter.label, counter.peak, counter.latest]), [['Publications overdue in the queue', 4, 1]]);
  assert.equal(groups[2].counters[0].peak, null);
});

test('the connection matrix pivots provider × capability and names the worst state of each cell', () => {
  const rows = [row('connection_health', { provider: 'linkedin', capability: 'publish', state: 'ok' }, 3),
                row('connection_health', { provider: 'linkedin', capability: 'publish', state: 'expiring' }, 1),
                row('connection_health', { provider: 'linkedin', capability: 'identity', state: 'ok' }, 4),
                row('connection_health', { provider: 'bluesky', capability: 'identity', state: 'blocked' }, 1),
                row('connection_health', { provider: 'x', capability: 'webhooks', state: 'ok' }, null, { dataState: 'unavailable' }),
                row('connection_health', { provider: 'x', capability: 'identity', state: 'weird' }, 1)];
  const matrix = ops.connectionMatrix(rows);
  assert.deepEqual(matrix.providers, ['bluesky', 'linkedin']);
  assert.deepEqual(matrix.capabilities, ['identity', 'publish']);
  assert.deepEqual(matrix.cells[ops.cellKey('linkedin', 'publish')], { provider: 'linkedin', capability: 'publish', counts: { ok: 3, expiring: 1 }, worst: 'expiring' });
  assert.equal(matrix.cells[ops.cellKey('bluesky', 'identity')].worst, 'blocked');
  assert.equal(matrix.cells[ops.cellKey('x', 'webhooks')], undefined, 'an unmeasured row is not drawn as 0 connections');
});

test('swimlanes lay out Live and Demo episodes by detector inside the 7-day track', () => {
  const now = Date.parse('2026-10-01T12:00:00Z');
  const day = 86_400_000;
  const live = [
    { id: 'a', detector: 'cost_anomaly', scope: 'global', severity: 'critical', state: 'open', openedAt: (now - day) / 1000, version: 2 },
    { id: 'b', detector: 'cost_anomaly', scope: 'global', severity: 'warning', state: 'resolved', openedAt: (now - 3 * day) / 1000, resolvedAt: (now - 2 * day) / 1000, version: 3 },
    { id: 'old', detector: 'source_silence', scope: 'database', severity: 'warning', state: 'resolved', openedAt: (now - 20 * day) / 1000, resolvedAt: (now - 10 * day) / 1000 },
    { id: 'long', detector: 'publish_failure_rate', scope: 'global', severity: 'warning', state: 'open', openedAt: (now - 30 * day) / 1000 }
  ];
  const demo = [{ id: 'incident-demo-outage-1', title: 'Simulated publishing outage', severity: 'warning', state: 'open', detectorFamily: 'demo_publishing_outage', observedAt: '2026-10-01T11:00:00Z', timeline: [{ id: 't', type: 'opened', at: '2026-10-01T11:00:00Z' }] }];
  const lanes = ops.swimlanes([...live, ...demo], now);
  assert.deepEqual(lanes.map((lane) => [lane.detector, lane.label, lane.episodes.map((episode) => episode.id)]), [
    ['publish_failure_rate', 'Publishing failures', ['long']],
    ['cost_anomaly', 'AI cost anomaly', ['b', 'a']],
    ['demo_publishing_outage', 'Publishing (Demo)', ['incident-demo-outage-1']]
  ]);
  const [longLane, costLane] = lanes;
  assert.deepEqual([longLane.episodes[0].left, longLane.episodes[0].width], [0, 100], 'an episode older than the window starts at its edge');
  const [resolved, open] = costLane.episodes;
  assert.ok(Math.abs(resolved.left - (4 / 7) * 100) < 1e-9 && Math.abs(resolved.width - (1 / 7) * 100) < 1e-9);
  assert.equal(open.open, true);
  assert.ok(Math.abs(open.left + open.width - 100) < 1e-9, 'an open episode reaches now');
  for (const lane of lanes) for (const episode of lane.episodes) assert.ok(episode.left >= 0 && episode.width > 0 && episode.left + episode.width <= 100 + 1e-9, episode.id);
  assert.equal(ops.swimlaneTicks(now).length, 8);
  assert.deepEqual(ops.swimlanes([], now), []);
});

test('incident timelines read Live `kind` and Demo `type` events and add the lifecycle stamps', () => {
  const live = { id: 'a', detector: 'cost_anomaly', state: 'acknowledged', openedAt: 1790000000, acknowledgedAt: 1790000300, timeline: [{ id: 'e', kind: 'escalated', at: 1790000100, body: { severity: 'critical' } }] };
  assert.deepEqual(ops.timelineEvents(live).map((event) => event.kind), ['opened', 'escalated', 'acknowledged']);
  const demo = { id: 'd', state: 'open', observedAt: '2026-10-01T11:00:00Z', timeline: [{ id: 't', type: 'opened', at: '2026-10-01T11:00:00Z' }, { id: 'u', type: 'notified', at: '2026-10-01T11:01:00Z' }] };
  assert.deepEqual(ops.timelineEvents(demo).map((event) => event.kind), ['opened', 'notified']);
  assert.equal(ops.detectorOf(demo), 'other');
  assert.equal(ops.detectorOf({ id: 'x', detectorFamily: 'demo_cost_anomaly' }), 'demo_cost_anomaly');
});

test('source health lists every probed source with its last good read, and the D7 ticket source is reported, not zero', () => {
  const sources = ops.sourceViews([
    row('source_health', { source: 'cron', state: 'measured', reason: 'qualified' }, 42, { unit: 'seconds', sourceWatermark: '2026-10-01T11:59:18Z', reason: 'qualified' }),
    row('source_health', { source: 'stripe_webhooks', state: 'not_applicable', reason: 'not_configured' }, null, { unit: 'seconds', dataState: 'not_applicable', reason: 'not_configured' }),
    row('source_health', { source: 'email_provider', state: 'unavailable', reason: null }, null, { unit: 'seconds', dataState: 'unavailable', reason: 'no_probe_recorded' })
  ]);
  assert.deepEqual(sources.map((source) => [source.label, source.state, source.lastGoodAt, source.ageSeconds, source.reason]), [
    ['Founder cron heartbeat', 'measured', '2026-10-01T11:59:18Z', 42, 'qualified'],
    ['Stripe webhooks', 'not_applicable', null, null, 'not_configured'],
    ['Email provider (Resend)', 'unavailable', null, null, 'no_probe_recorded']
  ]);
  assert.equal(ops.sourceTone('unavailable'), 'danger');
  const support = [row('support_aging', { source: 'data_requests' }, 3, { measures: { oldestSeconds: 90000, ticketSource: 'not_collected' } }),
                   row('support_aging', { source: 'support_tickets' }, null, { dataState: 'unavailable', reason: 'not_collected', measures: { decision: 'D7' } })];
  assert.deepEqual(ops.ticketSource(support), { collected: false, reason: 'not_collected', decision: 'D7' });
  assert.equal(ops.ticketSource([]), null);
  assert.equal(ops.measure(ops.openRequestsRow(support), 'oldestSeconds'), 90000);
  assert.equal(ops.openRequestsRow([row('support_aging', {}, 3)]).value, 3);
});

test('the pages keep the browser-gate guarantees: Ack only in Live, scrollers relative, Demo states honest', () => {
  const view = read('features/founder/operations/operations-view.tsx');
  assert.match(view, /ackable=\{live\}/, 'IncidentList gets Ack only in Live');
  const incidents = read('features/founder/operations/incidents.tsx');
  assert.match(incidents, /\{ackable && incident\.state === 'open'/);
  assert.doesNotMatch(incidents, /<button[^>]*style=/, 'swimlane bars are pictures, not tiny targets');
  const panels = read('features/founder/operations/panels.tsx');
  const tables = [...panels.matchAll(/<SimpleTable(?:<[A-Za-z]+>)?\s+className='([^']*)'/g)].map((match) => match[1]);
  assert.ok(tables.length >= 5 && tables.every((cls) => cls.split(' ').includes('relative')), 'every table scroller is relative, so its sr-only caption cannot widen the page');
  assert.match(panels, /className='rafii-quiet relative overflow-x-auto/, 'the matrix scrolls inside a relative box');
  const support = read('features/founder/support/support-view.tsx');
  assert.match(support, /Ticket source not chosen \(D7\)/);
  const advanced = read('features/founder/advanced/advanced-view.tsx');
  assert.match(advanced, /<DataHealth \/>/);
});

/* ---------- Advanced: Actions and Engineering (the coordinator's 8.D follow-up) ---------- */

const eng = load('features/founder/advanced/engineering-model.ts');

test('the engineering state is intelligence.engineering_state: exact SHA, manifest count, attested, success', () => {
  const sha = 'a'.repeat(40);
  const rows = [{ kind: 'check', exact_sha: sha, attested: true, required: true, conclusion: 'success', state: 'checks_passed' }];
  assert.equal(eng.engineeringState(rows, sha, 1), 'checks_passed');
  // The same cases as tests/control/test_intelligence.py.
  for (const change of [{ conclusion: 'skipped' }, { attested: false }, { exact_sha: 'b'.repeat(40) }, { failure_class: 'infrastructure', conclusion: 'failure' }]) {
    assert.equal(eng.engineeringState([{ ...rows[0], ...change }], sha, 1), 'suspected');
  }
  assert.equal(eng.engineeringState(rows, sha, 2), 'suspected');
  assert.equal(eng.engineeringState(rows, sha, 0), 'suspected');
  assert.equal(eng.engineeringState(rows, sha), 'suspected', 'no manifest count, no green');
  assert.equal(eng.engineeringState(rows, 'main', 1), 'suspected', 'a branch name is never a SHA');
  assert.equal(eng.engineeringState(rows, sha.toUpperCase(), 1), 'suspected');
});

function snapshot(requiredCount, exactSha) {
  return { id: 's1', exactSha, provenance: 'admitted_operational', observedAt: '2026-10-01T10:08:00Z', qualification: { requiredCount } };
}

test('the overall verdict judges the newest exact SHA against its manifest and says why it is not green', () => {
  const sha = 'c'.repeat(40);
  const older = 'd'.repeat(40);
  const check = (id, at, extra = {}) => ({ id, kind: 'check', provider: 'github', external_id: `run-${id}`, exact_sha: sha, state: 'suspected', conclusion: 'success', failure_class: null, attested: true, required: true, observed_at: at, ...extra });
  const rows = [
    check('a', '2026-10-01T10:00:00Z'),
    check('b', '2026-10-01T10:05:00Z'),
    check('old', '2026-09-30T09:00:00Z', { exact_sha: older, conclusion: 'failure' }),
    check('optional', '2026-10-01T10:06:00Z', { required: false, conclusion: 'failure' }),
    { ...check('deploy', '2026-10-01T10:07:00Z'), kind: 'deployment', provider: 'vercel' }
  ];
  const manifest = (requiredCount, exactSha = sha) => snapshot(requiredCount, exactSha);
  const passed = eng.engineeringVerdict(rows, [manifest(2)]);
  assert.deepEqual([passed.state, passed.reason, passed.sha, passed.required, passed.observed], ['checks_passed', 'all_green', sha, 2, 2]);
  assert.match(eng.verdictText(passed), /^All 2 required checks on ccccccc are attested green/);
  const verdicts = [passed];
  for (const [snapshots, reason] of [[[manifest(3)], 'count_mismatch'], [[manifest(2, older)], 'manifest_missing'], [[], 'manifest_missing'], [[manifest(0)], 'manifest_missing'], [null, 'manifest_unavailable']]) {
    const verdict = eng.engineeringVerdict(rows, snapshots);
    assert.deepEqual([verdict.state, verdict.reason], ['suspected', reason]);
    verdicts.push(verdict);
  }
  const unattested = eng.engineeringVerdict([check('a', '2026-10-01T10:00:00Z', { attested: false }), check('b', '2026-10-01T10:05:00Z')], [manifest(2)]);
  assert.deepEqual([unattested.state, unattested.reason, unattested.unattested], ['suspected', 'unattested', 1]);
  const red = eng.engineeringVerdict([check('a', '2026-10-01T10:00:00Z', { conclusion: 'skipped' }), check('b', '2026-10-01T10:05:00Z')], [manifest(2)]);
  assert.deepEqual([red.state, red.reason, red.notGreen], ['suspected', 'not_green', 1]);
  const noSha = eng.engineeringVerdict([check('n', '2026-10-01T11:00:00Z', { exact_sha: null }), ...rows], [manifest(2)]);
  assert.equal(noSha.reason, 'no_exact_sha', 'the newest required check without a SHA is never skipped over');
  const newer = eng.engineeringVerdict([...rows, check('late', '2026-10-01T12:00:00Z', { exact_sha: older })], [manifest(2)]);
  assert.deepEqual([newer.sha, newer.reason], [older, 'manifest_missing'], 'the newest SHA is judged, not the greenest');
  const none = eng.engineeringVerdict(rows.slice(3), [manifest(2)]);
  assert.deepEqual([none.state, none.reason], ['suspected', 'no_required_checks']);
  verdicts.push(unattested, red, noSha, newer, none);
  for (const verdict of verdicts) {
    assert.equal(verdict.state === 'checks_passed', verdict.reason === 'all_green', 'only all_green is checks_passed');
    assert.doesNotMatch(eng.verdictText(verdict), /\b(undefined|NaN|null)\b/);
  }
  assert.equal(eng.verdictText(eng.engineeringVerdict([check('a', '2026-10-01T10:00:00Z')], [manifest(1)])), 'The 1 required check on ccccccc is attested green, as its manifest requires.');
  assert.deepEqual([eng.shortSha(sha), eng.shortSha('main'), eng.shortSha(null)], ['ccccccc', null, null]);
  assert.equal(eng.shortRef('x'.repeat(40)).length, 28);
});

test('Advanced keeps the nav tab order, shows the founder action log, and the engineering tab only reads', () => {
  const advanced = read('features/founder/advanced/advanced-view.tsx');
  const tabs = [...advanced.match(/const TABS = \[([\s\S]*?)\] as const;/)[1].matchAll(/\['([a-z-]+)', '[^']+'\]/g)].map((match) => match[1]);
  assert.deepEqual(tabs, ['audit', 'receipts', 'data-health', 'actions', 'engineering']);
  const navTabs = read('config/founder-nav.ts').match(/advanced: \{[^\n]*tabs: \[([^\]]*)\]/)[1].split(',').map((tab) => tab.trim().replace(/'/g, ''));
  assert.deepEqual(tabs, navTabs, "the tabs are the nav's, in its order");
  assert.match(advanced, /import \{ FounderActionsLog \} from '@\/features\/founder\/actions';/);
  assert.match(advanced, /<TabsContent value='actions'[\s\S]*?<FounderActionsLog \/>[\s\S]*?<\/TabsContent>/);
  assert.match(advanced, /<TabsContent value='engineering'[\s\S]*?<EngineeringChecks \/>[\s\S]*?<\/TabsContent>/);
  assert.match(advanced, /<div className='scrollbar-hide relative -mx-1 overflow-x-auto px-1'>\s*<TabsList/, 'five tabs scroll inside a relative box at 390px');
  const engineering = read('features/founder/advanced/engineering.tsx');
  for (const source of [advanced, engineering]) {
    const tables = [...source.matchAll(/<SimpleTable(?:<[A-Za-z]+>)?\s+className='([^']*)'/g)].map((match) => match[1]);
    assert.ok(tables.length >= 1 && tables.every((cls) => cls.split(' ').includes('relative')), 'table scrollers are relative');
  }
  const hooks = read('features/founder/advanced/hooks.ts');
  assert.match(hooks, /return scope\.ready && scope\.mode === 'live' && scope\.capabilities\.includes\('engineering\.read'\);/, 'Demo and operators without engineering.read never ask');
  assert.equal(hooks.match(/enabled: allowed,/g).length, 2);
  assert.deepEqual([...hooks.matchAll(/founderFetch<\w+>\('([^']+)'/g)].map((match) => match[1]), ['/engineering', '/engineering/checks'], 'two plain GETs');
  for (const source of [hooks, engineering]) assert.doesNotMatch(source, /method:|body:|useMutation|<Button|onClick/, 'read-only: no dispatch, re-run or code action');
  assert.match(engineering, /emptyTitle='No attested CI evidence ingested yet'/);
  assert.match(engineering, /if \(scope\.mode === 'demo'\)/);
  assert.match(engineering, /!scope\.capabilities\.includes\('engineering\.read'\)/);
});
