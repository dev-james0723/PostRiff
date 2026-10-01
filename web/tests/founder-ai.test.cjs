const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

/**
 * The AI & API cost page (CONTRACTS §8.B): the pure adapters that turn `POST /metrics/query` rows into its charts and
 * tables, and a static check that every metric query the page sends stays inside the catalog's allowed dimensions
 * (a 4xx from a page query fails the browser gate). Rows here look like the server's: every row carries the query
 * interval and a daily bucket is `dimensions.window`.
 */
const SRC = path.join(__dirname, '..', 'src');
const PAGE = path.join(SRC, 'features/founder/ai-cost');
const CATALOGS = path.resolve(__dirname, '../../src/rafii_control/pack/catalogs');

function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  const { outputText } = ts.transpileModule(source, { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const ai = load(path.join(PAGE, 'adapters.ts'));

const INTERVAL = { start: '2026-09-01T04:00:00Z', end: '2026-10-01T04:00:00Z', timeZone: 'America/New_York' };
function row(metricId, dimensions, value, extra = {}) {
  return { metricId, definitionVersion: 'v1', interval: INTERVAL, dimensions, value, unit: 'count', dataState: 'measured', ...extra };
}

test('buckets are keyed by dimensions.window although every row carries the query interval', () => {
  const rows = [
    row('ai_cost_by_feature', { window: '2026-09-29', feature: 'writer' }, 100, { unit: 'usd_micro', currency: 'USD' }),
    row('ai_cost_by_feature', { window: '2026-09-28', feature: 'image' }, 40, { unit: 'usd_micro', currency: 'USD' }),
    row('ai_cost_by_feature', { window: '2026-09-29', feature: 'image' }, null, { unit: 'usd_micro', dataState: 'unavailable' }),
    row('ai_cost_by_feature', { feature: 'writer' }, 999, { unit: 'usd_micro' })
  ];
  assert.deepEqual(ai.wholeRows(rows).map((item) => item.value), [999]);
  const series = ai.windowSeries(rows, { dimension: 'feature' });
  assert.deepEqual(series.points.map((point) => point.t), ['2026-09-28', '2026-09-29'], 'one point per local day, in date order');
  assert.deepEqual(series.series.map((item) => [item.label, item.measured]), [['writer', 1], ['image', 1]]);
  assert.deepEqual(series.points[0], { t: '2026-09-28', s0: null, s1: 40 }, 'a bucket without a row is a gap, never 0');
  assert.deepEqual(series.points[1], { t: '2026-09-29', s0: 100, s1: null }, 'an unavailable bucket stays null');
  assert.equal(series.unit, 'usd_micro');
  assert.equal(series.dataState, 'partial');
});

test('tokens stack in the four PRD types and an unreported type is not a zero', () => {
  const rows = [
    row('ai_tokens', { window: '2026-09-30', token_type: 'reasoning' }, 30, { unit: 'tokens' }),
    row('ai_tokens', { window: '2026-09-30', token_type: 'output' }, 200, { unit: 'tokens' }),
    row('ai_tokens', { window: '2026-09-30', token_type: 'input' }, 900, { unit: 'tokens' }),
    row('ai_tokens', { window: '2026-09-30', token_type: 'cached' }, null, { unit: 'tokens', dataState: 'unavailable', reason: 'tokens_not_reported' })
  ];
  const series = ai.tokenSeries(rows);
  assert.deepEqual(series.series.map((item) => item.label), ['Input', 'Cached input', 'Output', 'Reasoning']);
  assert.deepEqual(series.points, [{ t: '2026-09-30', s0: 900, s1: null, s2: 200, s3: 30 }]);
  assert.equal(series.series[1].measured, 0);
});

test('latency p50 / p95 come from each row as the server computed them, never averaged; n is shown', () => {
  const day = (window, p50, p95, n, extra = {}) => row('ai_latency', { window }, p95, { unit: 'milliseconds', sampleCount: n, measures: { p50Ms: p50, p95Ms: p95 }, ...extra });
  const daily = [day('2026-09-30', 800, 2400, 120), day('2026-09-29', 500, 1900, 12, { reason: 'small_sample' }), day('2026-09-28', null, null, 0, { dataState: 'unavailable', reason: 'not_instrumented' })];
  const series = ai.latencySeries(daily);
  assert.deepEqual(series.points, [
    { t: '2026-09-28', s0: null, s1: null },
    { t: '2026-09-29', s0: 500, s1: 1900 },
    { t: '2026-09-30', s0: 800, s1: 2400 }
  ]);
  assert.equal(series.unit, 'ms');
  assert.deepEqual(ai.smallSampleDays(daily), ['2026-09-29'], 'an unavailable day is not a small sample');

  const byModel = [
    row('ai_latency', { model: 'openai/gpt-5.1' }, 2100, { unit: 'milliseconds', sampleCount: 340, measures: { p50Ms: 700, p95Ms: 2100 } }),
    row('ai_latency', { model: 'openai/gpt-5.1-mini' }, 900, { unit: 'milliseconds', sampleCount: 18, dataState: 'partial', reason: 'collecting_since', measures: { p50Ms: 300, p95Ms: 900 } })
  ];
  const table = ai.latencyTable(byModel, 'model');
  assert.deepEqual(table.map((item) => [item.label, item.p50, item.p95, item.n, item.small]), [
    ['openai/gpt-5.1', 700, 2100, 340, false],
    ['openai/gpt-5.1-mini', 300, 900, 18, true]
  ], 'n under 30 is a small sample even when the row carries another reason');
});

test('routes per model join three server answers without browser arithmetic', () => {
  const calls = [
    row('ai_calls', { model: 'openai/gpt-5.1', route: 'primary' }, 90),
    row('ai_calls', { model: 'openai/gpt-5.1', route: 'fallback' }, 10),
    row('ai_calls', { model: 'google/gemini-3-flash', route: 'fallback' }, 4)
  ];
  const rates = [
    row('ai_fallback_retry_rate', { model: 'openai/gpt-5.1' }, 0.15, { unit: 'ratio', coverage: { known: 100, unknown: 0, numerator: 15, denominator: 100 }, measures: { fallbackAttempts: 10, retryAttempts: 7, fallbackRate: 0.1, retryRate: 0.07 } }),
    row('ai_fallback_retry_rate', { model: 'google/gemini-3-flash' }, 1, { unit: 'ratio', coverage: { numerator: 4, denominator: 4 }, measures: { fallbackAttempts: 4, retryAttempts: 0 } })
  ];
  const costs = [row('ai_cost_per_call', { model: 'openai/gpt-5.1' }, 4200, { unit: 'usd_micro', dataState: 'partial', reason: 'cost_unknown_attempts' })];
  const routes = ai.modelRoutes(calls, rates, costs);
  assert.deepEqual(
    routes.map((item) => [item.model, item.attempts, item.primary, item.noPrimary, item.fallback, item.retries, item.retryShare, item.costPerAttempt, item.dataState]),
    [
      ['openai/gpt-5.1', 100, 90, false, 10, 7, 0.15, 4200, 'partial'],
      ['google/gemini-3-flash', 4, null, true, 4, 0, 1, null, 'measured']
    ]
  );
  assert.deepEqual(ai.modelRoutes([], [row('ai_fallback_retry_rate', {}, null, { dataState: 'unavailable', reason: 'not_instrumented' })], []), [], 'nothing collected → no rows to draw');
});

test('coverage: ledger money beside the unknown estimate, attempts by cost basis', () => {
  assert.deepEqual(ai.ledgerCoverage(row('ai_cost_actual', {}, 1_250_000, { unit: 'usd_micro', measures: { unknownEstimateUsdMicro: 40_000 } })), { known: 1_250_000, unknown: 40_000 });
  assert.equal(ai.ledgerCoverage(row('ai_cost_actual', {}, null, { dataState: 'unavailable' })), null, 'unavailable is not a zero bar');
  assert.equal(ai.ledgerCoverage(null), null);

  const basis = [row('ai_calls', { cost_basis: 'reported' }, 70), row('ai_calls', { cost_basis: 'price_table' }, 25)];
  assert.deepEqual(ai.attemptCoverage(basis), { known: 70, estimated: 25, unknown: 0 }, 'a basis with no group in a measured answer had no attempts');
  assert.equal(ai.attemptCoverage([row('ai_calls', {}, null, { dataState: 'unavailable', reason: 'demo_not_simulated' })]), null);
});

test('cost per useful outcome names its basis and never turns zero outcomes into a zero cost', () => {
  const rows = [
    row('cost_per_useful_outcome', { outcome_proxy: 'time_back' }, 52_000, { unit: 'usd_micro', measures: { costUsdMicro: 2_600_000, outcomes: 50, basis: 'time_back_accepted_outcomes' } }),
    row('cost_per_useful_outcome', { outcome_proxy: 'learning_events' }, null, { unit: 'usd_micro', dataState: 'not_applicable', reason: 'zero_denominator', measures: { costUsdMicro: 2_600_000, outcomes: 0, basis: 'learning_approvals_publishes' } })
  ];
  assert.deepEqual(ai.outcomeTable(rows).map((item) => [item.proxy, item.cost, item.outcomes, item.perOutcome, item.reason]), [
    ['Time Back accepted outcomes', 2_600_000, 50, 52_000, null],
    ['Learning approvals and publishes', 2_600_000, 0, null, 'zero_denominator']
  ]);
  const unavailable = ai.outcomeTable([row('cost_per_useful_outcome', { plan: null }, null, { dataState: 'unavailable', reason: 'source_not_configured', measures: { basis: 'time_back_accepted_outcomes' } })]);
  assert.deepEqual(unavailable.map((item) => [item.plan, item.cost, item.outcomes]), [[null, null, null]]);
});

function forecastMeasures(kind) {
  return { basis: 'scenario', method: 'ols_trailing_56d_daily_actuals_v1', kind, budgetStopUsdMicro: 50_000_000, budgetWarnUsdMicro: 40_000_000, budgetStatus: 'ok' };
}

test('forecast: actual days solid, the scenario dashed from the last actual value, budget from the server', () => {
  const measures = forecastMeasures;
  const rows = [
    row('ai_cost_forecast', { window: '2026-10-03' }, 3_900_000, { unit: 'usd_micro', measures: measures('projection') }),
    row('ai_cost_forecast', { window: '2026-10-01' }, 1_000_000, { unit: 'usd_micro', measures: measures('actual') }),
    row('ai_cost_forecast', { window: '2026-10-02' }, 2_400_000, { unit: 'usd_micro', measures: measures('projection') })
  ];
  const view = ai.forecastView(rows);
  assert.deepEqual(view.points, [
    { t: '2026-10-01', actual: 1_000_000, projection: 1_000_000 },
    { t: '2026-10-02', actual: null, projection: 2_400_000 },
    { t: '2026-10-03', actual: null, projection: 3_900_000 }
  ]);
  assert.deepEqual(view.budget, { stop: 50_000_000, warn: 40_000_000, status: 'ok' });
  assert.equal(ai.forecastView([row('ai_cost_forecast', { window: null }, null, { dataState: 'unavailable', reason: 'insufficient_history' })]), null);

  const short = ai.forecastHeadline(row('ai_cost_forecast', {}, null, { unit: 'usd_micro', dataState: 'unavailable', reason: 'insufficient_history', history: { availableDays: 12, requiredDays: 56 }, measures: { basis: 'scenario' } }));
  assert.equal(short.insufficient, true);
  assert.equal(short.total, null);
  assert.deepEqual(short.history, { availableDays: 12, requiredDays: 56 });
  const full = ai.forecastHeadline(row('ai_cost_forecast', {}, 31_000_000, { unit: 'usd_micro', measures: { ...measures(undefined), mtdActualUsdMicro: 1_000_000, slopeUsdMicroPerDay: 1_000_000.5, monthStart: '2026-10-01', monthEnd: '2026-11-01' } }));
  assert.deepEqual([full.total, full.mtd, full.slope, full.monthStart, full.budget.stop, full.insufficient], [31_000_000, 1_000_000, 1_000_000.5, '2026-10-01', 50_000_000, false]);
});

test('a queue row reconciles its own reservation; Demo ids that are not UUIDs cannot start one', () => {
  const workspaceId = '7b0b2f5e-8f1a-4c39-9d43-2a8f9a1c0b11';
  const reservationId = '3c5a9e71-0d2b-4f6e-8a19-6b7c2d4e5f80';
  assert.deepEqual(ai.queueTarget({ id: 'u1', kind: 'settle', workspaceId, reservationId, estimatedUsdMicro: 1200, provider: 'vercel-ai-gateway', model: 'openai/gpt-5.1', at: '2026-09-30T12:00:00Z' }), {
    workspaceId,
    reservationId,
    estimatedUsdMicro: 1200,
    provider: 'vercel-ai-gateway',
    model: 'openai/gpt-5.1',
    at: '2026-09-30T12:00:00Z'
  });
  assert.equal(ai.queueTarget({ id: reservationId, kind: 'reserve', workspaceId }).reservationId, reservationId, 'the reserve row is the reservation');
  assert.equal(ai.queueTarget({ id: reservationId, kind: 'settle', workspaceId }).reservationId, null, 'a settle row without its reservation id');
  const demo = ai.queueTarget({ id: 'demo-usage-4', kind: 'reserve', workspaceId: 'demo-ws-2', reservationId: 'demo-res-4' });
  assert.deepEqual([demo.workspaceId, demo.reservationId, demo.estimatedUsdMicro], [null, null, null]);
});

test('every query the page sends stays inside the catalog (allowed dimensions, no comparison over window)', () => {
  const catalog = new Map();
  const files = [path.join(CATALOGS, 'metrics.json'), ...fs.readdirSync(path.join(CATALOGS, 'metrics.d')).filter((name) => name.endsWith('.json')).map((name) => path.join(CATALOGS, 'metrics.d', name))];
  for (const file of files) for (const entry of JSON.parse(fs.readFileSync(file, 'utf8'))) catalog.set(entry.id, entry);
  const source = fs.readFileSync(path.join(PAGE, 'ai-cost-view.tsx'), 'utf8');
  const calls = [...source.matchAll(/use(Tile)?Metric\(\{([^}]*)\}\)/g)];
  assert.ok(calls.length >= 20, `found ${calls.length} metric queries`);
  for (const [, tile, body] of calls) {
    const id = /id:\s*'([a-z0-9_]+)'/.exec(body)?.[1];
    const entry = catalog.get(id);
    assert.ok(entry, `${id} is in the catalog`);
    assert.match(entry.status, /^activated/, `${id} is activated`);
    const groupBy = [...(/groupBy:\s*\[([^\]]*)\]/.exec(body)?.[1] ?? '').matchAll(/'([a-z_]+)'/g)].map((match) => match[1]);
    for (const dimension of groupBy) assert.ok(entry.allowed_dimensions.includes(dimension), `${id} allows ${dimension}`);
    const compared = Boolean(tile) || /comparison:\s*'(?!none)/.test(body);
    assert.ok(!(compared && groupBy.includes('window')), `${id}: a comparison never groups by window`);
  }
  const ids = new Set(calls.map(([, , body]) => /id:\s*'([a-z0-9_]+)'/.exec(body)[1]));
  for (const id of ['ai_calls', 'ai_tokens', 'ai_latency', 'ai_fallback_retry_rate', 'ai_cost_per_call', 'cost_per_useful_outcome', 'ai_cost_forecast']) assert.ok(ids.has(id), `the page shows ${id}`);
});

test('every ai-cost tab id has an anchor on the page', () => {
  const source = fs.readFileSync(path.join(PAGE, 'ai-cost-view.tsx'), 'utf8');
  const anchors = [...source.matchAll(/<TabAnchor section='ai-cost' tab='([a-z-]+)'/g)].map((match) => match[1]);
  const nav = fs.readFileSync(path.join(SRC, 'config/founder-nav.ts'), 'utf8');
  const tabs = /'ai-cost':\s*\{[^}]*tabs:\s*\[([^\]]*)\]/.exec(nav)[1].match(/'([a-z-]+)'/g).map((value) => value.slice(1, -1));
  assert.deepEqual(anchors.toSorted(), tabs.toSorted());
});
