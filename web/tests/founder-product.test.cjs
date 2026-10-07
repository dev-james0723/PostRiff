const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

/**
 * Slice 8.C (Product & customers) web adapters: the Product page's funnel, time to value, adoption, retention heatmap,
 * time back by confidence and correlations; the stuck-workspace drill-down; and the Customers risk views and flag
 * chips from GET /customers/risk. TypeScript sources are transpiled in place (as tests/founder-pages.test.cjs does);
 * the catalog and the Python modules are read as text so the page can never ask for a dimension or view the server
 * would refuse with a 4xx.
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

const product = load('features/founder/product/product-data.ts');
const risk = load('features/founder/customers/customer-risk.ts');
const nav = load('config/founder-nav.ts');

const INTERVAL = { start: '2026-09-01T00:00:00.000Z', end: '2026-10-01T15:30:00.000Z', timeZone: 'America/Indiana/Indianapolis' };

function row(metricId, dimensions, value, extra = {}) {
  return { metricId, definitionVersion: 'v1', interval: INTERVAL, dimensions, value, unit: extra.unit ?? 'count', dataState: extra.dataState ?? 'measured', coverage: extra.coverage ?? { known: 0, unknown: 0, numerator: null, denominator: null }, sampleCount: extra.sampleCount ?? 0, reason: extra.reason ?? null, ...extra.more };
}

function catalog() {
  const pack = path.join(ROOT, 'src/rafii_control/pack/catalogs');
  const rows = JSON.parse(fs.readFileSync(path.join(pack, 'metrics.json'), 'utf8'));
  const extra = path.join(pack, 'metrics.d');
  for (const name of fs.readdirSync(extra).filter((file) => file.endsWith('.json')).toSorted()) rows.push(...JSON.parse(fs.readFileSync(path.join(extra, name), 'utf8')));
  const byId = new Map();
  for (const entry of rows) if (!byId.has(entry.id) || entry.status === 'activated_v1') byId.set(entry.id, entry);
  return byId;
}

/* ---------- activation funnel ---------- */

test('funnel steps keep the server order, counts and drop-offs; an unmeasured step stays null, never 0', () => {
  const rows = [
    row('activation_funnel', { step: 'channel_connected' }, 6, { dataState: 'partial', reason: 'transition_proxy', coverage: { known: 10, unknown: 0, numerator: 6, denominator: 10 }, more: { measures: { order: 2, source: 'taxonomy+transition_proxy', proxy: 'audit:channel.connected', rate: 0.6, dropFromPrevious: 0.4, stuckFromPrevious: 4, immature: 3, windowDays: 14 } } }),
    row('activation_funnel', { step: 'workspace_created' }, 10, { coverage: { known: 10, unknown: 0, numerator: 10, denominator: 10 }, more: { measures: { order: 1, source: 'workspace_start', rate: 1, immature: 3, windowDays: 14 } } }),
    row('activation_funnel', { step: 'voice_activated' }, null, { dataState: 'unavailable', reason: 'not_instrumented', coverage: { known: 0, unknown: 10, numerator: null, denominator: null }, more: { measures: { order: 3, source: 'taxonomy', proxy: null, immature: 3 } } }),
    row('activation_funnel', { step: 'draft_created' }, 0, { coverage: { known: 4, unknown: 6, numerator: 0, denominator: 4 }, more: { collectingSince: '2026-09-10T00:00:00Z', measures: { order: 4, source: 'taxonomy', rate: 0, dropFromPrevious: null, stuckFromPrevious: 0 } } })
  ];
  const steps = product.funnelSteps(rows);
  assert.deepEqual(steps.map((step) => step.id), ['workspace_created', 'channel_connected', 'voice_activated', 'draft_created']);
  assert.deepEqual(steps.map((step) => step.label), ['Signed up', 'Connected a channel', 'Set up a voice', 'Created a first draft']);
  const [anchor, channel, voice, draft] = steps;
  assert.equal(anchor.reached, 10);
  assert.equal(anchor.immature, 3);
  assert.equal(channel.reached, 6);
  assert.equal(channel.of, 10);
  assert.equal(channel.rate, 0.6);
  assert.equal(channel.stuck, 4);
  assert.equal(product.sourceLabel(channel.source), 'Product events + proxy');
  assert.deepEqual(channel.interval, INTERVAL, 'the drill-down reuses the exact interval the funnel was asked for');
  assert.equal(voice.reached, null, 'not instrumented is not zero');
  assert.equal(voice.rate, null);
  assert.equal(voice.stuck, null);
  assert.equal(product.reasonText(voice.reason, voice.row), 'Not instrumented yet.');
  assert.equal(draft.reached, 0, 'a measured zero is a real zero');
  assert.equal(draft.unknown, 6);
  assert.ok(product.canDrillStuck(channel));
  assert.ok(!product.canDrillStuck(anchor), 'the anchor has no previous step');
  assert.ok(!product.canDrillStuck(voice));
  assert.ok(!product.canDrillStuck(draft), 'nobody stuck, nothing to open');
  assert.equal(product.points(0.4), '40 pts');
  assert.equal(product.points(null), null);
  assert.equal(product.signedPoints(0.081), '+8.1 pts');
  assert.equal(product.signedPoints(-0.031), '−3.1 pts');
  assert.equal(product.barWidth(1.4), '100%');
  assert.equal(product.barWidth(null), '0%');
});

test('the funnel steps match the server definition', () => {
  const source = fs.readFileSync(path.join(ROOT, 'src/rafii_control/founder_metrics_product.py'), 'utf8');
  const block = source.slice(source.indexOf('STEPS = ('), source.indexOf('# Feature ->'));
  const steps = [...block.matchAll(/\('([a-z_]+)', /g)].map((match) => match[1]);
  assert.deepEqual(steps, [...product.FUNNEL_STEPS]);
  const features = source.slice(source.indexOf('FEATURES = ('), source.indexOf('FEATURE_IDS'));
  for (const [, feature] of features.matchAll(/^\s+\('([a-z_]+)', '[a-z_.]+',/gm)) assert.ok(feature in product.FEATURE_LABEL, `label for ${feature}`);
});

test('the stuck drill-down asks for the funnel interval and only when the operator may read it', () => {
  const pathname = product.stuckPath('live', 'channel_connected', INTERVAL);
  const url = new URL(pathname, 'https://example.test/api/control/v2');
  assert.equal(url.pathname, '/product/funnel/stuck');
  assert.deepEqual(Object.fromEntries(url.searchParams), { mode: 'live', step: 'channel_connected', start: INTERVAL.start, end: INTERVAL.end, timeZone: INTERVAL.timeZone });
  assert.ok(product.canListStuck(['customers.read', 'metrics.query', 'workspaces.read'], 'live'));
  assert.ok(!product.canListStuck(['customers.read', 'metrics.query'], 'live'), 'Live also needs workspaces.read');
  assert.ok(product.canListStuck(['customers.read', 'metrics.query'], 'demo'));
  assert.ok(!product.canListStuck(['customers.read'], 'demo'));
  const answer = { mode: 'live', step: 'channel_connected', previousStep: 'workspace_created', interval: INTERVAL, limit: 200, windowDays: 14, source: 'taxonomy+transition_proxy', rows: [], truncated: false };
  assert.equal(product.verifyStuck(answer, 'live', 'channel_connected'), answer);
  assert.throws(() => product.verifyStuck({ ...answer, mode: 'demo' }, 'live', 'channel_connected'));
  assert.throws(() => product.verifyStuck({ ...answer, step: 'draft_created' }, 'live', 'channel_connected'));
  assert.throws(() => product.verifyStuck({ ...answer, rows: null }, 'live', 'channel_connected'));
  // The route refuses the anchor and unknown steps, so the page never offers them.
  const route = fs.readFileSync(path.join(ROOT, 'src/rafii_control/founder_metrics_product.py'), 'utf8');
  assert.match(route, /if not index:\s+# unknown, or the anchor/);
});

/* ---------- time to value, adoption ---------- */

test('median time to value comes with its n and quartiles; an empty cohort says why', () => {
  const measured = { rows: [row('time_to_value', {}, 7200, { unit: 'seconds', coverage: { known: 12, unknown: 0, numerator: 9, denominator: 12 }, sampleCount: 9, more: { measures: { n: 9, cohort: 12, noFirstValue: 3, immature: 2, p25: 3600, p75: 86400, windowDays: 14 } } })] };
  const ttv = product.timeToValue(measured);
  assert.deepEqual([ttv.median, ttv.n, ttv.cohort, ttv.noFirstValue, ttv.p25, ttv.p75], [7200, 9, 12, 3, 3600, 86400]);
  const empty = product.timeToValue({ rows: [row('time_to_value', {}, null, { unit: 'seconds', dataState: 'not_applicable', reason: 'no_matured_workspaces', more: { measures: { n: 0, cohort: 0, noFirstValue: 0, immature: 4, p25: null, p75: null } } })] });
  assert.equal(empty.median, null);
  assert.equal(empty.p25, null);
  assert.equal(product.reasonText(empty.reason, empty.row), 'No signup in this period is 14 days old yet.');
  const demo = product.timeToValue({ rows: [row('time_to_value', {}, null, { unit: 'seconds', dataState: 'unavailable', reason: 'demo_not_simulated' })] });
  assert.equal(demo.median, null);
  assert.equal(product.reasonText(demo.reason), 'Not simulated in the Demo dataset.');
  assert.equal(product.timeToValue(undefined), null);
});

test('feature adoption keeps the eligible denominator per feature and never invents a share', () => {
  const rows = [
    row('feature_adoption', { feature: 'review' }, 0.25, { unit: 'ratio', dataState: 'partial', reason: 'transition_proxy', coverage: { known: 40, unknown: 0, numerator: 10, denominator: 40 }, more: { measures: { adopters: 10, eligible: 40, source: 'taxonomy+transition_proxy' } } }),
    row('feature_adoption', { feature: 'humanizer' }, null, { unit: 'ratio', dataState: 'unavailable', reason: 'not_instrumented', coverage: { known: 0, unknown: 0, numerator: null, denominator: 40 }, more: { measures: { adopters: 0, eligible: 40 } } }),
    row('feature_adoption', { feature: 'mystery_tool' }, 0.5, { unit: 'ratio', coverage: { known: 40, unknown: 0, numerator: 20, denominator: 40 } })
  ];
  const items = product.adoptionItems(rows);
  assert.deepEqual(items.map((item) => [item.label, item.share, item.adopters, item.eligible]), [['Review and approve', 0.25, 10, 40], ['Humanizer', null, null, 40], ['mystery tool', 0.5, 20, 40]]);
  assert.equal(product.eligibleWorkspaces(items), 40);
  assert.equal(product.eligibleWorkspaces([]), null);
});

/* ---------- retention heatmap ---------- */

test('the retention grid keeps unmatured cells grey with n/d, and an early answer says how much history it needs', () => {
  const rows = [];
  for (const week of [0, 1, 2]) rows.push(row('retention_weekly', { cohort: '2026-08-03', week }, week === 2 ? null : 0.5 - week * 0.1, { unit: 'ratio', dataState: week === 2 ? 'not_applicable' : 'measured', reason: week === 2 ? 'cell_not_matured' : null, coverage: { known: 10, unknown: 0, numerator: week === 2 ? null : 5 - week, denominator: 10 } }));
  rows.push(row('retention_weekly', { cohort: '2026-07-27', week: 0 }, 0, { unit: 'ratio', coverage: { known: 4, unknown: 0, numerator: 0, denominator: 4 } }));
  const grid = product.retentionGrid(rows);
  assert.deepEqual(grid.weeks, [0, 1, 2]);
  assert.deepEqual(grid.cohorts.map((cohort) => [cohort.cohort, cohort.size]), [['2026-08-03', 10], ['2026-07-27', 4]]);
  const [first] = grid.cohorts;
  assert.equal(first.label, 'Aug 3', 'a local date is never shifted by the viewer zone');
  assert.deepEqual(first.cells.map((cell) => [cell.week, cell.share, cell.retained, cell.matured]), [[0, 0.5, 5, true], [1, 0.4, 4, true], [2, null, null, false]]);
  assert.equal(grid.cohorts[1].cells[0].share, 0, 'a measured 0% cell is shown as 0%');
  assert.equal(product.cellOpacity(null), 0);
  assert.equal(product.cellOpacity(0), 0.12);
  assert.equal(product.cellOpacity(1), 1);
  const early = { rows: [row('retention_weekly', {}, null, { unit: 'ratio', dataState: 'unavailable', reason: 'insufficient_history', more: { history: { availableDays: 23, requiredDays: 56 } } })] };
  assert.equal(product.retentionGrid(early.rows).cohorts.length, 0);
  const status = product.statusRow(early, 'cohort');
  assert.equal(status.reason, 'insufficient_history');
  assert.equal(product.reasonText(status.reason, status), 'Needs 56 days of history; 23 available.');
  assert.equal(product.statusRow({ rows }, 'cohort'), null, 'a broken-down answer has no status row');
});

/* ---------- time back ---------- */

test('time back stays three separate confidences in a fixed order and colour; nothing is added together', () => {
  const totals = product.timeBackTotals([
    row('time_back', { confidence: 'estimated' }, 5400, { unit: 'seconds', sampleCount: 12 }),
    row('time_back', { confidence: 'measured' }, 1800, { unit: 'seconds', sampleCount: 3 })
  ]);
  assert.deepEqual(totals.map((item) => [item.confidence, item.seconds, item.tasks]), [['measured', 1800, 3], ['personalized', null, null], ['estimated', 5400, 12]]);
  assert.ok(!totals.some((item) => item.confidence === 'total'));
  assert.deepEqual(product.CONFIDENCES.map(product.confidenceColor), ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)']);
  const series = product.timeBackSeries([
    row('time_back', { confidence: 'estimated', window: '2026-09-02' }, 600, { unit: 'seconds' }),
    row('time_back', { confidence: 'measured', window: '2026-09-01' }, 120, { unit: 'seconds' })
  ]);
  assert.deepEqual(series.series.map((item) => [item.key, item.label, item.measured]), [['s0', 'Measured', 1], ['s1', 'Personalized', 0], ['s2', 'Estimated', 1]]);
  assert.deepEqual(series.points, [{ t: '2026-09-01', s0: 120, s1: null, s2: null }, { t: '2026-09-02', s0: null, s1: null, s2: 600 }]);
  assert.equal(series.unit, 'seconds');
});

test('daily series pivot on the window dimension and keep unmeasured days as gaps', () => {
  const rows = [
    row('publish_outcomes', { status: 'failed', window: '2026-09-02' }, 1),
    row('publish_outcomes', { status: 'verified', window: '2026-09-01' }, 4),
    row('publish_outcomes', { status: 'verified', window: '2026-09-02' }, null, { dataState: 'unavailable' })
  ];
  const series = product.windowSeries(rows, { by: 'status', order: ['verified', 'failed', 'pending'] });
  assert.deepEqual(series.series.map((item) => item.label), ['verified', 'failed'], 'unlisted statuses are not invented');
  assert.deepEqual(series.points, [{ t: '2026-09-01', s0: 4, s1: null }, { t: '2026-09-02', s0: null, s1: 1 }]);
  assert.equal(series.dataState, 'partial');
  const single = product.windowSeries([row('active_workspaces', { window: '2026-09-01' }, 3)], { label: 'Active workspaces' });
  assert.deepEqual(single.series.map((item) => item.label), ['Active workspaces']);
  assert.equal(product.windowSeries([row('active_workspaces', {}, 3)]).points.length, 0, 'rows without a window are not drawn on a time axis');
});

/* ---------- correlations ---------- */

test('retention correlations are a labelled hypothesis; small groups are withheld, not shown as zero', () => {
  const rows = [
    row('retention_correlations', { feature: 'scheduling' }, 0.6, { unit: 'ratio', more: { measures: { basis: 'hypothesis', adopters: 20, adoptersRetained: 12, nonAdopters: 30, nonAdoptersRetained: 9, nonAdopterShare: 0.3, difference: 0.3 } } }),
    row('retention_correlations', { feature: 'campaigns' }, null, { unit: 'ratio', dataState: 'suppressed', reason: 'sample_too_small', more: { measures: { basis: 'hypothesis', adopters: 3, adoptersRetained: 1, nonAdopters: 47, nonAdoptersRetained: 20, minimumGroup: 10 } } })
  ];
  const items = product.correlationItems(rows);
  assert.deepEqual(items.map((item) => [item.label, item.adopterShare, item.nonAdopterShare, item.difference, item.basis]), [['Scheduling', 0.6, 0.3, 0.3, 'hypothesis'], ['Campaigns', null, null, null, 'hypothesis']]);
  assert.equal(items[1].adopters, null, 'a withheld group shows no counts');
  assert.equal(product.reasonText(items[1].reason, items[1].row), 'Too few workspaces: each group needs at least 10.');
  assert.ok(product.isHypothesis({ rows }));
  assert.ok(!product.isHypothesis({ rows: [row('active_workspaces', {}, 1)] }));
});

/* ---------- queries the page sends ---------- */

test('every Product query asks for activated metrics and only their allowed dimensions', () => {
  const metrics = catalog();
  const sources = ['features/founder/product/product-view.tsx'].map((file) => fs.readFileSync(path.join(SRC, file), 'utf8')).join('\n');
  const calls = [...sources.matchAll(/use(?:Tile)?Metric\(\{([^}]*(?:\{[^}]*\}[^}]*)*)\}\)/g)].map((match) => match[1]);
  assert.ok(calls.length >= 10, `found ${calls.length} metric queries`);
  for (const call of calls) {
    const id = /id: '([a-z0-9_]+)'/.exec(call)[1];
    const entry = metrics.get(id);
    assert.ok(entry, `${id} is in the catalog`);
    assert.equal(entry.status, 'activated_v1', `${id} is activated`);
    const groupBy = /groupBy: \[([^\]]*)\]/.exec(call);
    const dims = groupBy ? [...groupBy[1].matchAll(/'([a-z_]+)'/g)].map((match) => match[1]) : [];
    for (const match of call.matchAll(/dimension: '([a-z_]+)'/g)) dims.push(match[1]);
    for (const dim of dims) assert.ok(entry.allowed_dimensions.includes(dim), `${id} allows ${dim}`);
    assert.ok(new Set(dims).size <= 3, 'groupBy holds at most three dimensions');
  }
});

test('every Product tab id has an anchor and every Customers tab a trigger', () => {
  const view = fs.readFileSync(path.join(SRC, 'features/founder/product/product-view.tsx'), 'utf8');
  for (const tab of nav.FOUNDER_SECTIONS.product.tabs) assert.match(view, new RegExp(`section='product' tab='${tab}'`), tab);
  const customers = fs.readFileSync(path.join(SRC, 'features/founder/customers/customers-view.tsx'), 'utf8');
  for (const tab of nav.FOUNDER_SECTIONS.customers.tabs) assert.match(customers, new RegExp(`TabsTrigger value='${tab}'`), tab);
  assert.ok(nav.FOUNDER_REDIRECTS.some((redirect) => redirect.source === '/control/workspaces' && redirect.destination === '/founder/customers?tab=workspaces'));
});

/* ---------- customers: saved views and flags ---------- */

test('saved views are the PRD six, each a view the risk route answers', () => {
  assert.deepEqual(risk.RISK_VIEWS.map((view) => view.label), ['High value', 'High AI cost', 'Quota ≥80%', 'Inactive 30d', 'Payment risk', 'At-risk']);
  const source = fs.readFileSync(path.join(ROOT, 'src/rafii_control/founder_risk.py'), 'utf8');
  const block = source.slice(source.indexOf('VIEWS = {'), source.indexOf('}', source.indexOf('VIEWS = {')));
  const views = Object.fromEntries([...block.matchAll(/'([a-z0-9_]+)': (?:'([a-z_]+)'|None)/g)].map((match) => [match[1], match[2] ?? null]));
  for (const view of risk.RISK_VIEWS) assert.equal(views[view.id], view.rule, `${view.id} → ${view.rule}`);
  assert.ok('flagged' in views, 'the chips read the flagged view');
  assert.equal(risk.resolveSavedView('inactive'), 'inactive_30d', 'earlier links keep working');
  assert.equal(risk.resolveSavedView('quota'), 'quota_80');
  assert.equal(risk.resolveSavedView('high_ai_cost'), 'high_ai_cost');
  assert.equal(risk.resolveSavedView('nope'), 'all');
  assert.equal(risk.resolveSavedView(null), 'all');
  assert.equal(risk.riskPath('demo', 'quota_80'), '/customers/risk?mode=demo&view=quota_80');
  assert.ok(risk.canReadRisk(['customers.read', 'workspaces.read'], 'live'));
  assert.ok(!risk.canReadRisk(['customers.read'], 'live'));
  assert.ok(risk.canReadRisk(['customers.read'], 'demo'));
});

const FLAG = (id, extra = {}) => ({ id, version: 'v1', label: id, basis: id === 'at_risk' ? 'hypothesis' : 'observed', trigger: `${id} trigger`, since: '2026-09-01T00:00:00Z', evidence: {}, ...extra });

test('flag chips are a join of the server flags onto a customer’s workspaces, one per rule', () => {
  const answer = {
    mode: 'live', view: 'flagged', asOf: '2026-10-01T00:00:00Z', timeZone: 'America/Indiana/Indianapolis', rulesVersion: 'v1', rules: [], total: 2, truncated: false, limit: 200, basis: 'observed_rules',
    rows: [
      { workspaceId: 'w-1', name: 'One', ownerId: 'u-1', plan: 'Studio', status: 'past_due', createdAt: null, flags: [FLAG('payment_risk'), FLAG('inactive'), FLAG('at_risk', { evidence: { because: ['inactive', 'payment_risk'] } })], flagCount: 3 },
      { workspaceId: 'w-2', name: 'Two', ownerId: 'u-1', plan: 'Starter', status: 'active', createdAt: null, flags: [FLAG('inactive')], flagCount: 1 }
    ]
  };
  assert.equal(risk.verifyRisk(answer, 'live', 'flagged'), answer);
  assert.throws(() => risk.verifyRisk(answer, 'demo', 'flagged'));
  assert.throws(() => risk.verifyRisk({ ...answer, view: 'at_risk' }, 'live', 'flagged'));
  const index = risk.flagIndex(answer.rows);
  const joined = risk.joinFlags(['w-1', 'w-2', 'w-9', 7], index);
  assert.deepEqual(joined.map((entry) => [entry.flag.id, entry.workspaceIds]), [['payment_risk', ['w-1']], ['inactive', ['w-1', 'w-2']], ['at_risk', ['w-1']]]);
  assert.deepEqual(risk.joinFlags('w-2', index).map((entry) => entry.flag.id), ['inactive']);
  assert.deepEqual(risk.joinFlags(undefined, index), []);
  assert.ok(risk.isHypothesisFlag(joined[2].flag));
  assert.ok(!risk.isHypothesisFlag(joined[0].flag));
  assert.equal(risk.evidenceText(joined[2].flag), 'because inactive, payment risk');
});

test('evidence is written with its unit; nothing is computed from it', () => {
  const format = load('features/founder/customers/kit/format.ts');
  assert.equal(risk.evidenceText({ evidence: { aiCost30dUsdMicro: 12_340_000, p95AiCost30dUsdMicro: 8_100_000, costPopulation: 42 } }), 'AI cost, 30 days $12.34 · 95th percentile $8.10 · workspaces with cost 42');
  assert.equal(risk.evidenceText({ evidence: { cashMtdMinor: 2900, currency: 'EUR', p90CashMtdMinor: 1500 } }), `cash this month ${format.minor(2900, 'EUR')} · 90th percentile ${format.minor(1500, 'EUR')}`);
  assert.equal(risk.evidenceText({ evidence: { usedShare: 0.85, usedUsdMicro: 850_000, stopUsdMicro: 1_000_000 } }), `used 85% · budget used ${format.usdMicro(850_000)} · budget stop $1.00`);
  assert.equal(risk.evidenceText({ evidence: { lastActiveAt: '2026-08-01T12:00:00Z', daysInactive: 61 } }), `last active ${format.whenDate('2026-08-01T12:00:00Z')} · days inactive 61`);
  assert.equal(risk.evidenceText({ evidence: { subscriptionStatus: 'past_due', cancelAtPeriodEnd: false } }), 'subscription past due', 'a false flag is left out');
  assert.equal(risk.evidenceText({ evidence: { highestTier: true, plan: 'Studio' } }), 'highest-priced plan · plan Studio');
  assert.equal(risk.evidenceText({ evidence: { newSignal: 3 } }), 'new signal 3');
  assert.equal(risk.evidenceText({ evidence: {} }), '');
});

test('a rule says how it was evaluated, including a missing source', () => {
  assert.equal(risk.ruleStateText({ state: 'measured' }), 'Evaluated on every workspace.');
  assert.equal(risk.ruleStateText({ state: 'unavailable', reason: 'source_not_configured' }), 'Not available: its source is not configured.');
  assert.equal(risk.ruleStateText({ state: 'unavailable', reason: 'demo_not_simulated' }), 'Not available: not simulated in the Demo dataset.');
  assert.equal(risk.ruleStateText({ state: 'partial', fallback: 'reconnect_events' }), 'Partly evaluated; read from reconnect notices until connection health is collected.');
  assert.equal(risk.ruleStateText({ state: 'not_evaluated' }), 'Not evaluated for this list.');
});
