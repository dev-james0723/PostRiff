/**
 * Lane F — "Change this view" suggestion chips (surfaces/edit-suggestions.ts): computed in the browser from the view itself,
 * no request and no model. Proves, on the accepted journey examples J01–J09 with their manifests (lane D's catalog): the exact
 * chips and their order, at most 4, deterministic; every chip grounded in the manifest (binding, argument, enum value) and
 * never the value already shown; explicit ISO dates in the right zone; the live selection's count; the three languages (other
 * locales read English); and that no record title, manifest description, binding name or DSL ever reaches a chip.
 *
 *   node --test web/tests/agent-ui-edit-suggestions.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { REPO, createLoader } = require('./agent-ui-journeys/_load.cjs');

const loader = createLoader();
const suggest = loader.load('src/features/agent/generative-ui/surfaces/edit-suggestions.ts');
const copy = loader.load('src/features/agent/generative-ui/surfaces/edit-suggestions-copy.ts');
const locale = loader.load('src/features/agent/generative-ui/core/locale.tsx');

const EXAMPLES = path.join(REPO, 'src/postriff_phase2/agent_runtime_v2/generated/journey-examples');
const catalog = JSON.parse(fs.readFileSync(path.join(EXAMPLES, 'journeys.json'), 'utf8'));
const dCatalog = JSON.parse(fs.readFileSync(path.join(__dirname, 'agent-ui-journeys', 'fixtures', 'd-catalog.json'), 'utf8'));
const read = (file) => fs.readFileSync(path.join(EXAMPLES, file), 'utf8').trim();

// 2026-10-09 12:00 in Hong Kong.
const NOW = Date.UTC(2026, 9, 9, 4, 0, 0);
const HK = 'Asia/Hong_Kong';
const SECRET = 'Secret recital 2026';

/** The journey's manifest bindings (lane D's catalog), each with a private-looking description that must never show. */
function manifest(journey) {
  return dCatalog.journeys[journey].queries.map((q) => ({ name: q.name, description: `PRIVATE DESCRIPTION of ${q.name}`, argsSchema: q.argsSchema }));
}

function chipsFor(journey, over = {}) {
  const entry = catalog.journeys[journey];
  return suggest.suggestEdits({
    source: read(entry.editCase.base),
    queries: manifest(journey),
    journeyIds: [journey],
    selection: null,
    language: 'en',
    timeZone: HK,
    now: NOW,
    ...over,
  });
}

const selection = (type, n) => ({ items: Array.from({ length: n }, (_, i) => ({ type, id: `${type}_${i + 1}`, title: i === 0 ? SECRET : `Item ${i + 1}` })),
  visible: Array.from({ length: n + 1 }, (_, i) => ({ type, id: `${type}_${i + 1}` })), listId: '$picked' });

const labels = (chips) => chips.map((c) => c.label);
const instructions = (chips) => chips.map((c) => c.instruction);

test('J01–J09: the exact chips for each accepted journey example, in a fixed order, at most 4', () => {
  const expected = {
    J01: [['Needs review', 'Show only drafts that need review'], ['Scheduled', 'Show only scheduled drafts'], ['Saved web sources', 'Also show my saved web sources'],
      ['Remove the note', 'Remove the note']],
    J02: [['Next week', 'Change the period to the following week (2026-10-12 to 2026-10-18)'], ['Next month', 'Change the period to next month (2026-11-01 to 2026-11-30)'],
      ['Waiting for you', 'Also show the proposals waiting for me']],
    J03: [['Only documents', 'Show only documents'], ['Only videos', 'Show only videos']],
    J04: [['Learning status', 'Also show what learning is doing now'], ['Only active samples', 'Show only the writing samples in use'],
      ['What you’ve allowed', 'Also show what I’ve allowed'], ['Remove the note', 'Remove the note']],
    J05: [['Campaign timeline', 'Add the campaign timeline'], ['Only posts', 'Show only this campaign’s posts'], ['Only drafts', 'Show only this campaign’s drafts'],
      ['Waiting for you', 'Also show the proposals waiting for me']],
    J06: [['Chart of views by week', 'Add a chart of views by week'], ['Last 7 days', 'Change the period to the last 7 days (2026-10-03 to 2026-10-09)'],
      ['Previous 30 days', 'Change the period to the 30 days before (2026-08-09 to 2026-09-07)'], ['Compare likes', 'Compare likes instead of views']],
    J07: [['Saved web sources', 'Also show my saved web sources'], ['What you’ve allowed', 'Also show what I’ve allowed']],
    J08: [['Accounts to reconnect', 'Also show which accounts need reconnecting'], ['Only paused', 'Show only paused automations'], ['Only active', 'Show only active automations'],
      ['Publishing queue', 'Also show the publishing queue']],
    J09: [['By model', 'Break AI cost down by model'], ['Only critical', 'Show only critical items'], ['Last month', 'Change the period to last month'],
      ['Compare with before', 'Compare cost with the previous period']],
  };
  for (const [journey, want] of Object.entries(expected)) {
    const chips = chipsFor(journey);
    assert.deepEqual(chips.map((c) => [c.label, c.instruction]), want, journey);
    assert.ok(chips.length <= suggest.MAX_SUGGESTIONS, `${journey}: at most 4`);
    assert.deepEqual(chipsFor(journey), chips, `${journey}: the same view gives the same chips`);
  }
});

test('the tested edit of each journey is offered right after any selection chip (when the view qualifies)', () => {
  assert.equal(chipsFor('J02')[0].rule, 'seed');
  assert.equal(chipsFor('J02')[0].id, 'period:next');
  assert.equal(chipsFor('J03')[0].id, 'filter:library_search.kind:document');
  assert.equal(chipsFor('J04')[0].id, 'add:voice_learning_status');
  assert.equal(chipsFor('J05')[0].id, 'add:campaign_timeline');
  assert.equal(chipsFor('J06')[0].id, 'shape:analytics_series');
  assert.equal(chipsFor('J08')[0].id, 'add:connections_status');
  assert.equal(chipsFor('J09')[0].id, 'filter:founder_costs.dimension:model');
  const rules = chipsFor('J08', { selection: selection('automation', 1) }).map((c) => c.rule);
  assert.deepEqual(rules.slice(0, 2), ['selection', 'seed'], 'the live selection comes first, then the seed');
});

test('ordering never depends on the manifest’s order or on the call', () => {
  for (const journey of Object.keys(catalog.journeys)) {
    const reversed = chipsFor(journey, { queries: manifest(journey).reverse() });
    assert.deepEqual(reversed, chipsFor(journey), journey);
  }
});

test('the current value is never offered (no no-op chips)', () => {
  const all = Object.keys(catalog.journeys).flatMap((j) => chipsFor(j));
  const text = instructions(all).join('\n');
  assert.doesNotMatch(text, /Show all files/, 'J03 kind:"all" never yields "all"');
  assert.doesNotMatch(text, /aren’t scheduled/, 'J01 status:"unscheduled" never yields "not scheduled"');
  assert.doesNotMatch(text, /by feature/, 'J09 dimension:"feature" never yields "feature"');
  assert.doesNotMatch(text, /this month so far/, 'J09 period:"mtd" never yields "mtd"');
  assert.doesNotMatch(text, /Compare views/, 'J06 metric:"views" never yields "views"');
  assert.doesNotMatch(text, /last 30 days/, 'J06 already shows a 30-day window');
  assert.doesNotMatch(text, /2026-10-05 to 2026-10-11/, 'J02 never offers its own week');
  // A view that already compares the picked pages gets no comparison chip.
  const compared = `${read('J07-research-brief.openui')}\nmatrix = ComparisonMatrix(results, $selectedPages)`;
  assert.ok(!chipsFor('J07', { source: compared, selection: selection('web_page', 2) }).some((c) => c.rule === 'selection'));
});

test('grounding: every chip names a manifest binding/argument/value; no curated label, no chip; J04/J05/J07 plan edits stay out', () => {
  // Without the binding in the manifest, its chip disappears.
  const noConnections = manifest('J08').filter((q) => q.name !== 'connections_status');
  assert.ok(!chipsFor('J08', { queries: noConnections }).some((c) => c.id === 'add:connections_status'));
  // An enum value the manifest does not accept is never offered.
  const narrowed = manifest('J03').map((q) => (q.name === 'library_search'
    ? { ...q, argsSchema: { ...q.argsSchema, properties: { ...q.argsSchema.properties, kind: { type: 'string', enum: ['all', 'image'] } } } } : q));
  assert.deepEqual(labels(chipsFor('J03', { queries: narrowed })), ['Only photos']);
  // Bindings without a curated label (recovery_guides, task_progress, library_collections, …) never yield a chip.
  for (const journey of Object.keys(catalog.journeys)) {
    for (const chip of chipsFor(journey)) {
      const [rule, rest] = [chip.id.split(':')[0], chip.id.split(':').slice(1).join(':')];
      if (rule === 'add' || chip.id === 'shape:analytics_series') {
        assert.ok(manifest(journey).some((q) => `${q.name}` === rest || chip.id === `shape:${q.name}`), `${journey}: ${chip.id} is a manifest binding`);
      }
      if (rule === 'filter') {
        const [bindingArg, value] = rest.split(':');
        const [binding, arg] = bindingArg.split('.');
        const prop = manifest(journey).find((q) => q.name === binding).argsSchema.properties[arg];
        assert.ok(prop.enum ? prop.enum.includes(value) : prop.type === 'boolean', `${journey}: ${chip.id} is in the manifest`);
      }
    }
  }
  const text = Object.keys(catalog.journeys).flatMap((j) => instructions(chipsFor(j))).join('\n');
  assert.doesNotMatch(text, /evidence for each trait|progress by step|sort the sources/i, 'the three underivable plan edits are absent');
  assert.deepEqual(suggest.suggestEdits({ source: read('J01-drafts-studio.openui'), queries: [], journeyIds: ['J01'], selection: null, language: 'en', timeZone: HK, now: NOW }), [],
    'no manifest, no chips');
});

test('privacy and copy: no titles, descriptions, binding names, DSL or implementation words in any label or instruction', () => {
  const bindings = Object.values(dCatalog.queries).map((q) => q.name);
  const views = [];
  for (const journey of Object.keys(catalog.journeys)) {
    for (const language of ['en', 'zh-Hant', 'zh-Hans']) {
      for (const sel of [null, selection('draft', 2), selection('draft', 1), selection('web_page', 3), selection('automation', 1), selection('media', 1)]) {
        views.push(...chipsFor(journey, { language, selection: sel }));
      }
    }
  }
  assert.ok(views.length > 50);
  for (const chip of views) {
    for (const text of [chip.label, chip.instruction]) {
      assert.ok(text && text.trim(), `${chip.id}: non-empty`);
      assert.ok(!text.includes(SECRET) && !text.includes('Item 2'), `${chip.id}: no selection title`);
      assert.ok(!/PRIVATE DESCRIPTION/.test(text), `${chip.id}: no manifest description`);
      assert.ok(!/Query\(|RafiiRoot|\$|[{}]/.test(text), `${chip.id}: no DSL or unfilled placeholder: ${text}`);
      for (const name of bindings) assert.ok(!text.includes(name), `${chip.id}: no binding name (${name})`);
      assert.doesNotMatch(text, /\b(schema|database|payload|backend|deployment|staging)\b/i, `${chip.id}: no implementation words`);
      assert.doesNotMatch(text, /\bfree\b|\$\d|US\$|USD/i, `${chip.id}: never a price or "free"`);
    }
  }
});

test('dates: "last 7 days" is today−6..today in the person’s zone; the Query’s own zone wins; spans keep their length', () => {
  const source = 'root = RafiiRoot([t])\nposts = Query("analytics_posts", {start: "2026-09-01", end: "2026-09-30"}, null)\nt = MetricTable(posts, ["views"])';
  const at = (iso, timeZone, src = source) => suggest.suggestEdits({ source: src, queries: manifest('J06'), journeyIds: [], selection: null, language: 'en', timeZone, now: Date.parse(iso) })
    .find((c) => c.id === 'period:last7').instruction;
  // 16:01 UTC: already 10 Oct 00:01 in Hong Kong, still 9 Oct 09:01 in Los Angeles.
  assert.equal(at('2026-10-09T16:01:00Z', HK), 'Change the period to the last 7 days (2026-10-04 to 2026-10-10)');
  assert.equal(at('2026-10-09T16:01:00Z', 'America/Los_Angeles'), 'Change the period to the last 7 days (2026-10-03 to 2026-10-09)');
  // 15:59 UTC: 23:59 on 9 Oct in Hong Kong.
  assert.equal(at('2026-10-09T15:59:00Z', HK), 'Change the period to the last 7 days (2026-10-03 to 2026-10-09)');
  // 07:59 UTC on 10 Oct: 00:59 in Los Angeles.
  assert.equal(at('2026-10-10T07:59:00Z', 'America/Los_Angeles'), 'Change the period to the last 7 days (2026-10-04 to 2026-10-10)');
  // A literal zone on the Query decides the day, whatever the person's zone.
  const zoned = source.replace('end: "2026-09-30"}', 'end: "2026-09-30", zone: "Asia/Hong_Kong"}');
  assert.equal(at('2026-10-09T16:01:00Z', 'America/Los_Angeles', zoned), 'Change the period to the last 7 days (2026-10-04 to 2026-10-10)');
  // An invalid person zone falls back to UTC (never throws).
  assert.equal(at('2026-10-09T16:01:00Z', 'Not/A_Zone'), 'Change the period to the last 7 days (2026-10-03 to 2026-10-09)');
  // A span shift keeps the base length: J02's 7 days → the next 7; J06's 30 → the 30 before.
  assert.match(instructions(chipsFor('J02')).join('\n'), /\(2026-10-12 to 2026-10-18\)/);
  assert.match(instructions(chipsFor('J06')).join('\n'), /\(2026-08-09 to 2026-09-07\)/);
  // "Next month" is the full next calendar month, across a year end.
  const december = chipsFor('J02', { now: Date.UTC(2026, 11, 15, 4) }).find((c) => c.id === 'period:nextMonth');
  assert.equal(december.instruction, 'Change the period to next month (2027-01-01 to 2027-01-31)');
  const february = chipsFor('J02', { now: Date.UTC(2028, 0, 20, 4) }).find((c) => c.id === 'period:nextMonth');
  assert.equal(february.instruction, 'Change the period to next month (2028-02-01 to 2028-02-29)');
  // A period bound to a $variable is the person's own control: no date chip.
  const bound = '$from = "2026-10-01"\nroot = RafiiRoot([t])\nposts = Query("analytics_posts", {start: $from, end: "2026-10-07"}, null)\nt = MetricTable(posts, ["views"])';
  assert.ok(!suggest.suggestEdits({ source: bound, queries: manifest('J06'), journeyIds: [], selection: null, language: 'en', timeZone: HK, now: NOW }).some((c) => c.rule === 'period'));
});

test('selection: 0 or 1 picked drafts → no comparison; 2 → "Compare only the 2 selected drafts"; the count is the live selection’s', () => {
  assert.ok(!chipsFor('J01').some((c) => c.rule === 'selection'));
  const one = chipsFor('J01', { selection: selection('draft', 1) });
  assert.equal(one[0].instruction, 'Show the details of the selected draft');
  const two = chipsFor('J01', { selection: selection('draft', 2) });
  assert.deepEqual([two[0].label, two[0].instruction], ['Compare the 2 selected', 'Compare only the 2 selected drafts']);
  assert.equal(two[0].id, 'selection:draft:compare');
  assert.equal(two.length, 4);
  const five = chipsFor('J01', { selection: selection('draft', 5) });
  assert.ok(!five.some((c) => c.rule === 'selection'), 'DraftCompare takes 2 to 4 drafts');
  const pages = chipsFor('J07', { selection: selection('web_page', 3) });
  assert.equal(pages[0].instruction, 'Compare the 3 selected pages side by side');
  const mixed = { items: [{ type: 'draft', id: 'd1' }, { type: 'web_page', id: '2' }] };
  assert.ok(!chipsFor('J01', { selection: mixed }).some((c) => c.rule === 'selection'), 'a mixed selection has no single noun');
  assert.ok(!chipsFor('J01', { selection: { items: 'nope' } }).some((c) => c.rule === 'selection'));
});

test('a filled suggestion is re-checked at "Update view": selection, day and revision changes stop it (nothing is sent)', () => {
  const filled = chipsFor('J01', { selection: selection('draft', 2) })[0];
  assert.equal(suggest.staleSuggestion(filled, chipsFor('J01', { selection: selection('draft', 2) })), null, 'unchanged: send');
  assert.equal(suggest.staleSuggestion(filled, chipsFor('J01', { selection: selection('draft', 1) })), 'selection', 'one item now: "Your selection changed"');
  assert.equal(suggest.staleSuggestion(filled, chipsFor('J01', { selection: selection('draft', 3) })), 'selection', 'the count in the words changed');
  const week = chipsFor('J06').find((c) => c.id === 'period:last7');
  assert.equal(suggest.staleSuggestion(week, chipsFor('J06', { now: NOW + 86_400_000 })), 'stale', 'the day rolled over: the dates changed');
  const doc = chipsFor('J03')[0];
  const documentsView = read('J03-library-search.openui').replace('kind: "all"', 'kind: "document"');
  assert.equal(suggest.staleSuggestion(doc, chipsFor('J03', { source: documentsView })), 'stale', 'a newer revision already shows documents');
});

test('languages: English, Traditional Chinese (Hong Kong wording) and Simplified Chinese; other locales read English', () => {
  assert.deepEqual(labels(chipsFor('J03', { language: 'zh-Hant' })), ['只看文件', '只看影片']);
  assert.deepEqual(instructions(chipsFor('J03', { language: 'zh-Hant' })), ['只顯示文件', '只顯示影片']);
  assert.deepEqual(labels(chipsFor('J03', { language: 'zh-Hans' })), ['只看文档', '只看视频']);
  assert.match(instructions(chipsFor('J08', { language: 'zh-Hant' })).join('\n'), /自動化/);
  assert.equal(chipsFor('J06', { language: 'zh-Hant' })[1].instruction, '把時段改為最近 7 日（2026-10-03 至 2026-10-09）');
  assert.equal(chipsFor('J06', { language: 'zh-Hans' })[1].instruction, '把时段改为最近 7 天（2026-10-03 至 2026-10-09）');
  assert.equal(chipsFor('J01', { language: 'zh-Hant', selection: selection('draft', 2) })[0].instruction, '只比較已選的 2 份草稿');
  for (const tag of ['fr', 'de-DE', 'ja']) {
    const language = locale.createGenUiLocale({ locale: tag, timeZone: HK }).language;
    assert.equal(language, 'en', `${tag} → English chrome`);
    assert.deepEqual(chipsFor('J03', { language }), chipsFor('J03'));
  }
  // Every template and table entry has three non-empty strings.
  const triples = [];
  const visit = (value) => {
    if (Array.isArray(value) && value.length === 3 && value.every((v) => typeof v === 'string')) triples.push(value);
    else if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === 'object') Object.values(value).forEach(visit);
  };
  for (const name of ['SELECTION_CHIPS', 'FILTER_CHIPS', 'DATE_PERIOD_CHIPS', 'ENUM_PERIOD_CHIPS', 'ADD_CHIPS', 'METRIC_NAMES', 'SHAPE_CHIPS', 'REMOVE_CHIPS']) visit(copy[name]);
  assert.ok(triples.length > 80, `${triples.length} triples`);
  for (const t of triples) {
    assert.ok(t.every((s) => s.trim().length > 0), JSON.stringify(t));
    assert.notEqual(t[1], t[0], `zh-Hant is translated: ${t[0]}`);
  }
  // The edit chrome is localized in core/locale.tsx (English byte-identical to what tests and e2e scenes find).
  const en = locale.createGenUiLocale({ locale: 'en' });
  const hk = locale.createGenUiLocale({ locale: 'zh-HK' });
  const cn = locale.createGenUiLocale({ locale: 'zh-CN' });
  assert.deepEqual([en.t('changeView'), en.t('whatShouldChange'), en.t('updateView')], ['Change this view', 'What should change?', 'Update view']);
  for (const key of ['changeView', 'whatShouldChange', 'editPlaceholder', 'editBilling', 'updateView', 'suggestions', 'restoreText', 'chipAdded', 'selectionChanged',
    'suggestionStale', 'newerVersion', 'keptEarlier', 'editConflict', 'editBusy', 'editUnavailable', 'editFailed', 'editNotActor', 'editBudget', 'editBudgetUnknown', 'editPaused']) {
    assert.ok(en.t(key) && hk.t(key) && cn.t(key), key);
    assert.notEqual(hk.t(key), en.t(key), `${key} has zh-Hant`);
    assert.notEqual(cn.t(key), en.t(key), `${key} has zh-Hans`);
  }
});

test('founder (J09) works from the source alone (no founder library), and broken sources never throw', () => {
  const founder = chipsFor('J09');
  assert.deepEqual(founder.map((c) => c.rule), ['seed', 'filter', 'period', 'shape']);
  assert.ok(founder.some((c) => c.instruction === 'Break AI cost down by model'));
  for (const source of ['', 'root = RafiiRoot(', 'x = )', 'root = RafiiRoot([a])\na = Query(', '\u0000\u0001', 'root = RafiiRoot([' + 'a, '.repeat(500) + '])']) {
    const chips = suggest.suggestEdits({ source, queries: manifest('J01'), journeyIds: ['J01'], selection: null, language: 'en', timeZone: HK, now: NOW });
    assert.ok(Array.isArray(chips) && chips.length <= 4, JSON.stringify(source.slice(0, 20)));
  }
});

test('chart, metric and column chips follow the components the view shows', () => {
  const base = read('J06-performance.openui');
  const withChart = `${base}\nseries = Query("analytics_series", {metric: "views", bucket: "week"}, null)\nchart = MetricChart(series, "bar")`;
  const chips = suggest.suggestEdits({ source: withChart, queries: manifest('J06'), journeyIds: [], selection: null, language: 'en', timeZone: HK, now: NOW });
  assert.ok(chips.some((c) => c.instruction === 'Show the chart as a line'), labels(chips).join(' | '));
  assert.ok(!chips.some((c) => c.instruction === 'Show the chart as bars'), 'never the kind already shown');
  assert.ok(!chips.some((c) => c.id === 'shape:analytics_series'), 'the chart binding is already used');
  const wide = base.replace('["views", "likes", "replies"]', '["views", "reach", "likes", "comments", "shares", "saved"]');
  const full = suggest.suggestEdits({ source: wide, queries: manifest('J06'), journeyIds: ['J06'], selection: null, language: 'en', timeZone: HK, now: NOW });
  assert.ok(!full.some((c) => c.id.startsWith('shape:column:')), 'a table with 6 metrics gets no column chip');
});
