const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

/**
 * The Revenue page (features/founder/revenue, CONTRACTS §8.A): the pure adapters behind the MRR bridge, day series,
 * forecast and route queries, plus static guards that every metric query on the page uses only the catalog's
 * allowed dimensions (a 4xx from a page query is a bug) and that the tabs are exactly founder-nav's revenue tabs.
 */
const SRC = path.join(__dirname, '..', 'src');
const PACK = path.resolve(__dirname, '../../src/rafii_control/pack/catalogs');
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

const rows = load('features/founder/revenue/rows.ts');
const types = load('features/founder/revenue/types.ts');
const INTERVAL = { start: '2026-09-01T00:00:00Z', end: '2026-10-01T00:00:00Z', timeZone: 'America/Indiana/Indianapolis' };

function row(metricId, dimensions, value, extra = {}) {
  return { metricId, definitionVersion: 'v1', interval: INTERVAL, dimensions, value, unit: 'currency_minor', currency: dimensions.currency ?? 'USD', dataState: value === null ? 'unavailable' : 'measured', coverage: { known: 1, unknown: 0, numerator: null, denominator: null }, ...extra };
}

function catalog() {
  const all = JSON.parse(fs.readFileSync(path.join(PACK, 'metrics.json'), 'utf8'));
  for (const name of fs.readdirSync(path.join(PACK, 'metrics.d')).filter((file) => file.endsWith('.json')).toSorted()) all.push(...JSON.parse(fs.readFileSync(path.join(PACK, 'metrics.d', name), 'utf8')));
  const byId = new Map();
  for (const entry of all) if (!byId.has(entry.id) || entry.status === 'activated_v1') byId.set(entry.id, entry);
  return byId;
}

test('day series pivot on dimensions.window; a missing day is a gap, never a zero', () => {
  const input = [
    row('cash_collected', { currency: 'USD', payment_type: 'top_up', window: '2026-09-02' }, 500),
    row('cash_collected', { currency: 'USD', payment_type: 'subscription_invoice', window: '2026-09-01' }, 2900),
    row('cash_collected', { currency: 'USD', payment_type: 'top_up', window: '2026-09-01' }, null),
    row('cash_collected', { currency: 'EUR', payment_type: 'top_up', window: '2026-09-01' }, 999),
    row('cash_collected', { currency: 'USD', payment_type: 'top_up' }, 7000)
  ];
  const series = rows.windowSeries(input, 'payment_type', 'USD');
  assert.deepEqual(series.points.map((point) => point.t), ['2026-09-01', '2026-09-02']);
  const top = series.series.find((entry) => entry.label === 'top_up');
  const invoice = series.series.find((entry) => entry.label === 'subscription_invoice');
  assert.equal(series.points[0][top.key], null, 'an unmeasured bucket stays null');
  assert.equal(series.points[0][invoice.key], 2900);
  assert.equal(series.points[1][invoice.key], undefined, 'no row for that day: nothing drawn');
  assert.equal(series.currency, 'USD');
  assert.ok(!series.points.some((point) => Object.values(point).includes(999)), 'another currency is never mixed in');
  assert.deepEqual(rows.currenciesOf(input), ['USD', 'EUR']);
});

test('category items keep whole-interval rows only and unmeasured values as null', () => {
  const input = [row('mrr', { currency: 'USD', plan: 'Studio' }, 14900), row('mrr', { currency: 'USD', plan: 'Starter' }, null), row('mrr', { currency: 'USD', plan: 'Studio', window: '2026-09-01' }, 1)];
  const items = rows.categoryItems(input, 'plan', 'USD');
  assert.deepEqual(items.map((item) => [item.label, item.value]), [['Studio', 14900], ['Starter', null]]);
  assert.deepEqual(rows.rowsWith(input, ['plan', 'window']).map((entry) => entry.value), [1]);
});

test('the MRR bridge places floating bars from server values and reconciles', () => {
  const values = { opening: 23600, new: 5900, expansion: 3000, reactivation: 0, contraction: 0, churn: -14900, closing: 17600 };
  const input = Object.entries(values).map(([movement, value]) => row('mrr_movements', { currency: 'USD', movement }, value, { coverage: { known: 2, unknown: 0, numerator: null, denominator: null } }));
  const { bars, complete, reconciles } = rows.bridgeBars(input, 'USD');
  assert.deepEqual(bars.map((bar) => bar.step), [...types.BRIDGE_STEPS]);
  assert.deepEqual(bars.map((bar) => [bar.base, bar.size, bar.direction]), [[0, 23600, 'total'], [23600, 5900, 'up'], [29500, 3000, 'up'], [32500, 0, 'up'], [32500, 0, 'up'], [17600, 14900, 'down'], [0, 17600, 'total']]);
  assert.deepEqual(bars.map((bar) => bar.value), Object.values(values), 'labels are the server values');
  assert.equal(complete, true);
  assert.equal(reconciles, true);
  assert.equal(bars[1].customers, 2);
  const missing = rows.bridgeBars(input.filter((entry) => entry.dimensions.movement !== 'churn'), 'USD');
  assert.equal(missing.complete, false, 'no bridge is drawn from incomplete steps');
  const wrong = rows.bridgeBars(input.map((entry) => (entry.dimensions.movement === 'closing' ? { ...entry, value: 1 } : entry)), 'USD');
  assert.equal(wrong.reconciles, false);
  assert.equal(rows.isMovement('churn'), true);
  assert.equal(rows.isMovement('opening'), false);
});

test('forecast points keep the measured line and the scenario apart, by day', () => {
  const actual = [row('mrr', { currency: 'USD', window: '2026-09-30' }, 5900), row('mrr', { currency: 'USD', window: '2026-10-01' }, null)];
  const scenario = [row('mrr_forecast', { currency: 'USD', window: '2026-10-02' }, 6000), row('mrr_forecast', { currency: 'EUR', window: '2026-10-02' }, 10)];
  assert.deepEqual(rows.forecastPoints(actual, scenario, 'USD'), [
    { t: '2026-09-30', actual: 5900, scenario: null },
    { t: '2026-10-01', actual: null, scenario: null },
    { t: '2026-10-02', actual: null, scenario: 6000 }
  ]);
});

test('honest notes for history and reasons', () => {
  assert.equal(rows.historyNote({ reason: 'insufficient_history', history: { availableDays: 12, requiredDays: 30 } }), 'Needs 30 days of billing events; 12 so far.');
  assert.equal(rows.historyNote({ reason: 'not_instrumented', history: null }), null);
  assert.match(rows.reasonText('not_instrumented'), /Stripe is not live/);
  assert.match(rows.reasonText('demo_not_simulated'), /Demo dataset/);
  assert.equal(rows.reasonText(undefined), null);
});

test('route queries: Live sends the exact interval, Demo sends the period anchored at its dataset', () => {
  const live = new URLSearchParams(rows.routeSearch('live', '30d', INTERVAL, { movement: 'churn', status: null }).slice(1));
  assert.deepEqual(Object.fromEntries(live), { mode: 'live', start: INTERVAL.start, end: INTERVAL.end, movement: 'churn' });
  const demo = new URLSearchParams(rows.routeSearch('demo', '90d', INTERVAL, { status: 'open' }).slice(1));
  assert.deepEqual(Object.fromEntries(demo), { mode: 'demo', period: '90d', status: 'open' });
});

test('dunning lists only invoices still owed; the reminder is a draft over ids', () => {
  const invoices = ['paid', 'open', 'void', 'uncollectible', 'draft'].map((status, index) => ({ invoiceId: `in_${index}`, status }));
  assert.deepEqual(rows.dunningRows(invoices).map((invoice) => invoice.status), ['open', 'uncollectible']);
  const prompt = rows.draftReminderPrompt({ invoiceId: 'in_123', status: 'open' });
  assert.match(prompt, /founder_draft_message/);
  assert.match(prompt, /do not send anything/);
  assert.match(prompt, /in_123/);
  assert.equal(rows.shortId('0123456789abcdef0123'), '01234567…0123');
});

function pageSources() {
  const folder = path.join(SRC, 'features/founder/revenue');
  return fs.readdirSync(folder).filter((name) => /\.(ts|tsx)$/.test(name)).map((name) => fs.readFileSync(path.join(folder, name), 'utf8')).join('\n');
}

test('every metric query on the page uses only catalog-allowed dimensions and groups native currencies by currency', () => {
  const byId = catalog();
  const source = pageSources();
  const calls = [...source.matchAll(/use(?:Tile)?Metric\(\{\s*id:\s*'([a-z_]+)'([^}]*)\}/g)];
  assert.ok(calls.length >= 12, `expected the page's metric queries, found ${calls.length}`);
  for (const [, id, rest] of calls) {
    const entry = byId.get(id);
    assert.ok(entry && entry.status === 'activated_v1', `${id} is an activated catalog metric`);
    const groupBy = /groupBy:\s*\[([^\]]*)\]/.exec(rest);
    const dims = groupBy ? [...groupBy[1].matchAll(/'([a-z_]+)'/g)].map((match) => match[1]) : [];
    for (const dim of dims) assert.ok(entry.allowed_dimensions.includes(dim), `${id} does not allow ${dim}`);
    if (entry.currency_policy === 'native_currency_separate') assert.ok(dims.includes('currency'), `${id} must group by currency on this page`);
  }
  const forecast = /metricIds:\s*\['mrr_forecast'\][^}]*groupBy:\s*\[([^\]]*)\]/.exec(source);
  assert.ok(forecast, 'the forecast query is present');
  const forecastDims = [...forecast[1].matchAll(/'([a-z_]+)'/g)].map((match) => match[1]);
  assert.deepEqual(forecastDims, ['currency', 'window']);
  for (const dim of forecastDims) assert.ok(byId.get('mrr_forecast').allowed_dimensions.includes(dim));
});

test('the page tabs are exactly the revenue tabs in founder-nav, and nothing renders a zero for a missing value', () => {
  const nav = fs.readFileSync(path.join(SRC, 'config/founder-nav.ts'), 'utf8');
  const tabs = /revenue:\s*\{[^}]*tabs:\s*\[([^\]]*)\]/.exec(nav);
  const expected = [...tabs[1].matchAll(/'([a-z-]+)'/g)].map((match) => match[1]);
  const view = fs.readFileSync(path.join(SRC, 'features/founder/revenue/revenue-view.tsx'), 'utf8');
  const block = view.slice(view.indexOf('const TABS'), view.indexOf('];', view.indexOf('const TABS')));
  const listed = [...block.matchAll(/\{ id: '([a-z-]+)', label:/g)].map((match) => match[1]);
  assert.deepEqual(listed, expected);
  for (const id of expected) assert.match(view, new RegExp(`TabsContent value='${id}'`));
  assert.doesNotMatch(pageSources(), /\.value \?\? 0|value: 0\b/, 'an unavailable value is never shown as 0');
});
