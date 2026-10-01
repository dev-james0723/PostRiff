const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

/**
 * Pure helpers behind the founder domain pages (features/founder/*): period maths, formatting, metric adapters,
 * the records query body, risk rules and saved views. TypeScript sources are transpiled in place; a relative
 * import inside them resolves to the sibling .ts so the modules load exactly as the pages see them.
 */
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

const period = load('features/founder/customers/kit/period.ts');
const format = load('features/founder/customers/kit/format.ts');
const metric = load('features/founder/customers/kit/metric.ts');
const records = load('features/founder/customers/kit/records.ts');
const risk = load('features/founder/customers/risk-flags.ts');
const views = load('features/founder/customers/query.ts');
const sharedFormat = load('features/founder/shared/format.ts');
const attention = load('lib/founder/attention.ts');
const tabs = load('features/founder/customers/kit/tab-ids.ts');
const nav = load('config/founder-nav.ts');

const NOW = new Date('2026-10-01T15:30:00Z');

test('periods are half-open UTC intervals ending now, with the viewer zone attached', () => {
  const week = period.periodInterval('7d', NOW, 'Asia/Hong_Kong');
  assert.equal(week.start, '2026-09-24T00:00:00.000Z');
  assert.equal(week.end, NOW.toISOString());
  assert.equal(week.timeZone, 'Asia/Hong_Kong');
  assert.equal(period.periodInterval('mtd', NOW, 'UTC').start, '2026-10-01T00:00:00.000Z');
  assert.equal(period.periodInterval('6m', NOW, 'UTC').start, '2026-05-01T00:00:00.000Z');
  assert.equal(period.periodDays('90d', NOW), 91);
  assert.ok(period.isPeriodKey('30d'));
  assert.ok(!period.isPeriodKey('1y'));
});

test('an unreported metric value is a word, never 0', () => {
  assert.equal(format.metricValue({ value: null, unit: 'count', dataState: 'measured' }), 'Unavailable');
  assert.equal(format.metricValue({ value: 12, unit: 'count', dataState: 'unavailable' }), 'Unavailable');
  assert.equal(format.metricValue({ value: 0, unit: 'count', dataState: 'measured' }), '0');
  assert.equal(format.metricValue({ value: 2900, unit: 'currency_minor', currency: 'USD', dataState: 'measured' }), '$29.00');
  assert.equal(format.metricValue({ value: 1_234_500, unit: 'usd_micro', dataState: 'measured' }), '$1.23');
  assert.equal(format.metricValue({ value: 0.125, unit: 'ratio', dataState: 'measured' }), '12.5%');
  assert.equal(format.minutesToClock(1320), '22:00');
  assert.equal(format.clockToMinutes('08:05'), 485);
  assert.equal(format.clockToMinutes('25:00'), null);
});

test('server timestamps are read as ISO strings or epoch seconds, never compared as text', () => {
  // founder_incidents / founder_schedules write `extract(epoch …)` floats; metrics and follow-ups write ISO 8601.
  assert.equal(format.timeValue(1790000000), Date.parse('2026-09-21T14:13:20Z'));
  assert.equal(format.timeValue(1790000000.5), Date.parse('2026-09-21T14:13:20.500Z'));
  assert.equal(format.timeValue('2026-09-21T14:13:20Z'), Date.parse('2026-09-21T14:13:20Z'));
  assert.equal(format.timeValue(Date.parse('2026-09-21T14:13:20Z')), Date.parse('2026-09-21T14:13:20Z'));
  for (const bad of [null, undefined, '', 'tomorrow', 0, -5, Number.NaN, {}]) assert.equal(format.timeValue(bad), null, String(bad));
  assert.equal(format.whenDateTime(1790000000), format.whenDateTime('2026-09-21T14:13:20Z'));
  assert.equal(format.whenDateTime(0), 'Not recorded');
  assert.equal(format.whenDate(1790000000), format.whenDate('2026-09-21T14:13:20Z'));
});

test('series pivot keeps gaps as null and counts measured buckets per series', () => {
  const rows = [
    { metricId: 'ai_cost_by_feature', definitionVersion: 'v1', interval: { start: '2026-09-29T00:00:00Z', end: '2026-09-30T00:00:00Z' }, dimensions: { feature: 'draft' }, value: 100, unit: 'usd_micro', dataState: 'measured' },
    { metricId: 'ai_cost_by_feature', definitionVersion: 'v1', interval: { start: '2026-09-29T00:00:00Z', end: '2026-09-30T00:00:00Z' }, dimensions: { feature: 'publish' }, value: null, unit: 'usd_micro', dataState: 'unavailable' },
    { metricId: 'ai_cost_by_feature', definitionVersion: 'v1', interval: { start: '2026-09-30T00:00:00Z', end: '2026-10-01T00:00:00Z' }, dimensions: { feature: 'draft' }, value: 50, unit: 'usd_micro', dataState: 'measured' }
  ];
  const series = metric.seriesFromRows(rows, 'feature');
  assert.deepEqual(series.series.map((s) => [s.label, s.measured]), [['draft', 2], ['publish', 0]]);
  assert.equal(series.points.length, 2);
  assert.equal(series.points[0].s1, null);
  assert.equal(series.points[0].s0, 100);
  assert.equal(series.dataState, 'partial');
});

test('a tile from an unavailable answer has no value and carries when collection started', () => {
  const result = { requestId: 'r', queryReceiptId: 'rcpt-1', asOf: NOW.toISOString(), dataState: 'unavailable', rows: [{ metricId: 'mrr', definitionVersion: 'v1', value: null, unit: 'currency_minor', dataState: 'unavailable', reason: 'definition_not_activated', sourceWatermark: '2026-09-20T00:00:00Z', collectingSince: '2026-09-25T00:00:00Z' }] };
  const tile = metric.tileFromResult(result, { id: 'mrr', label: 'MRR', period: '30d' });
  assert.equal(tile.value, null);
  assert.equal(tile.dataState, 'unavailable');
  assert.equal(tile.collectingSince, '2026-09-25T00:00:00Z');
  assert.equal(tile.lastGoodAt, '2026-09-20T00:00:00Z', 'the watermark is the last good read, kept apart');
  assert.equal(tile.receiptId, 'rcpt-1');
  assert.equal(tile.delta, null);
  // A watermark is not an instrumentation start: without collectingSince the tile does not claim one.
  const noStart = metric.tileFromResult({ ...result, rows: [{ ...result.rows[0], collectingSince: undefined }] }, { id: 'mrr', label: 'MRR', period: '30d' });
  assert.equal(noStart.collectingSince, null);
  assert.equal(noStart.lastGoodAt, '2026-09-20T00:00:00Z');
  const measured = metric.tileFromResult({ ...result, rows: [{ metricId: 'mrr', definitionVersion: 'v1', value: 420, unit: 'currency_minor', dataState: 'measured', delta: 20 }] }, { id: 'mrr', label: 'MRR', period: '30d' });
  assert.equal(measured.value, 420);
  assert.equal(measured.delta, 20);
  assert.equal(measured.deltaPeriod, '30d');
});

test('the Live records query sends exactly the five required keys; Demo may refine', () => {
  const input = { collection: 'customers', search: 'maya', status: 'all', page: 2, recordId: '', plan: 'Studio', sort: 'name', direction: 'desc' };
  assert.deepEqual(Object.keys(records.recordsQueryBody('live', input)).toSorted(), ['collection', 'page', 'recordId', 'search', 'status']);
  const demo = records.recordsQueryBody('demo', input);
  assert.equal(demo.plan, 'Studio');
  assert.equal(demo.sort, 'name');
  assert.equal(demo.direction, 'desc');
  assert.equal(records.pageCount(10_000, 50), 200);
  assert.equal(records.pageCount(0, 50), 1);
});

test('risk flags are observed rules on returned fields; at-risk is a labelled hypothesis', () => {
  const workspaces = [
    { id: 'w-1', status: 'past_due', creditsQuota: 1000, creditsUsed: 850, creditsRemaining: 150, lastActiveAt: '2026-08-01T00:00:00Z' },
    { id: 'w-2', status: 'active', creditsQuota: 1000, creditsUsed: 100, creditsRemaining: 900 }
  ];
  const flags = risk.riskFlags({ id: 'c-1', status: 'active', workspaceIds: ['w-1'] }, workspaces, NOW);
  assert.deepEqual(flags.map((flag) => flag.id), ['payment_risk', 'quota_near_limit', 'inactive', 'at_risk']);
  assert.equal(flags.find((flag) => flag.id === 'at_risk').kind, 'hypothesis');
  assert.equal(flags.find((flag) => flag.id === 'quota_near_limit').evidence, '850 of 1,000 credits used');
  // No activity stamp means unknown, which raises nothing.
  assert.deepEqual(risk.riskFlags({ id: 'c-2', status: 'active', workspaceIds: ['w-2'] }, workspaces, NOW), []);
  // Server-computed flags win and pass through.
  const server = risk.riskFlags({ id: 'c-3', riskFlags: [{ id: 'connection_risk', evidence: 'token expired' }] }, workspaces, NOW);
  assert.deepEqual(server.map((flag) => [flag.id, flag.rule, flag.evidence]), [['connection_risk', 'server', 'token expired']]);
});

test('saved views resolve to a server status only when the source reports one', () => {
  const paymentRisk = views.savedView('payment_risk');
  assert.equal(views.serverStatusForView(paymentRisk, ['active', 'past_due', 'grace'], 'all'), 'past_due');
  assert.equal(views.serverStatusForView(paymentRisk, ['active'], 'all'), 'all');
  assert.equal(views.serverStatusForView(views.savedView('quota'), ['active', 'past_due'], 'active'), 'active');
  assert.ok(views.paymentRiskAvailable(['grace']));
  assert.ok(!views.paymentRiskAvailable(['active', 'trialing']));
  assert.deepEqual(views.observedPlans([{ plan: 'Studio' }, { plan: 'Starter' }, { plan: 'Studio' }, {}]), ['Starter', 'Studio']);
});

test('shared tile formatting knows every server unit and reads a comparison start as a date', () => {
  assert.equal(sharedFormat.formatMetricValue(123456, 'currency_minor', 'USD'), '$1,234.56');
  assert.equal(sharedFormat.formatMetricValue(2_500_000, 'currency_micro', 'USD'), '$2.50');
  assert.equal(sharedFormat.formatMetricValue(1500, 'millicredits'), '1.5 credits');
  assert.equal(sharedFormat.formatMetricValue(90, 'seconds_estimate'), '2 min');
  assert.equal(sharedFormat.formatMetricValue(null, 'currency_minor', 'USD'), 'Unavailable');
  assert.equal(sharedFormat.formatComparisonPeriod('2026-08-31T00:00:00+00:00'), `vs ${sharedFormat.formatDateShort('2026-08-31T00:00:00+00:00')} window`);
  assert.equal(sharedFormat.formatComparisonPeriod('30d'), 'vs 30d');
  assert.equal(sharedFormat.formatComparisonPeriod(null), null);
});

test('attention actions are objects with a kind and a label; an ack is kept only when it names incident and version', () => {
  const item = { id: 'payment_failures_7d', severity: 'warning', title: '3 payment failures', scope: 'billing', count: 3, since: null, href: '/founder/revenue?tab=payments', actions: ['explain', 'open', 'draft_reminder'] };
  const normalised = attention.normalizeAttentionItem(item);
  assert.deepEqual(normalised.actions.map((a) => [a.id, a.kind, a.label, a.href]), [['explain', 'explain', 'Explain', null], ['open', 'open', 'Open', '/founder/revenue?tab=payments'], ['draft_reminder', 'draft_reminder', 'Draft reminder', null]]);
  const incident = { ...item, id: 'incident_i1', href: '/founder/operations?incident=i1', actions: [{ id: 'explain', kind: 'explain', label: 'Explain', href: null }, { id: 'ack', kind: 'ack', label: 'Acknowledge', href: null, incidentId: 'i1', version: 2 }] };
  assert.deepEqual(attention.normalizeAttentionItem(incident).actions.map((a) => a.kind), ['explain', 'ack']);
  assert.deepEqual(attention.normalizeAttentionItem({ ...incident, actions: ['explain', 'acknowledge'] }).actions.map((a) => a.kind), ['explain'], 'a bare acknowledge has no version: never defaulted');
  assert.deepEqual(attention.normalizeAttentionItem({ ...incident, actions: [{ id: 'ack', kind: 'ack', label: 'Acknowledge', incidentId: 'i1', version: null }] }).actions, []);
  assert.deepEqual(attention.normalizeAttentionItem({ ...item, actions: undefined }).actions, []);
});

test('every deep link the server and the nav emit resolves to a tab the page owns', () => {
  const sections = nav.FOUNDER_SECTIONS;
  assert.equal(tabs.resolveTab('data-health', sections.advanced.tabs), 'data-health');
  assert.equal(tabs.resolveTab('sources', sections.advanced.tabs), 'data-health', 'older spelling');
  assert.equal(tabs.resolveTab('evidence', sections.advanced.tabs), 'receipts', '/control/evidence redirect');
  assert.equal(tabs.resolveTab('failures', sections.revenue.tabs), 'payments');
  assert.equal(tabs.resolveTab('mrr', sections.revenue.tabs), 'mrr-bridge');
  assert.equal(tabs.resolveTab('requests', sections.support.tabs), 'inbox');
  assert.equal(tabs.resolveTab('nope', sections.revenue.tabs), null, 'unknown values resolve to nothing, never another tab');
  assert.equal(tabs.resolveTab(null, sections.revenue.tabs), null);
  // The hrefs live_metrics._attention / TILES emit (src/rafii_control/live_metrics.py) and the redirect map all land.
  const served = { revenue: ['payments', 'mrr-bridge', 'cash'], 'ai-cost': ['reconcile', 'budget'], support: ['inbox'], operations: ['health', 'connections'], advanced: ['data-health'], settings: ['contact', 'reports', 'notifications'] };
  for (const [section, ids] of Object.entries(served)) for (const id of ids) assert.equal(tabs.resolveTab(id, sections[section].tabs), id, `${section}?tab=${id}`);
  assert.equal(tabs.tabAnchorId('revenue', 'cash'), 'founder-revenue-cash');
});

test('the section registry names the eight domain pages', () => {
  const sections = load('features/founder/sections.ts');
  assert.deepEqual(Object.keys(sections.SECTIONS), ['customers', 'revenue', 'product', 'ai-cost', 'operations', 'support', 'settings', 'advanced']);
  assert.ok(sections.isFounderSection('ai-cost'));
  assert.ok(!sections.isFounderSection('overview'));
});
