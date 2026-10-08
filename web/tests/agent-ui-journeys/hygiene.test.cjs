/**
 * Lane E — shipping-code hygiene for the journey components:
 *   - every journey spec has exactly one renderer (consumer and founder maps kept apart);
 *   - every view reads only keys lane D's data contract declares (fixtures/d-shapes.json, kept equal to
 *     ui_domain.shapes by tests/test_agent_ui_journeys.py), and every rendered fixture validates against its view;
 *   - no fixture data, network calls, raw HTML or eval in shipping files; no direct react-lang import;
 *   - the copy audit (implementation words, product name) passes on lane E's paths.
 *
 *   node --test web/tests/agent-ui-journeys/hygiene.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { WEB } = require('./_load.cjs');
const { makeEnvironment } = require('./_harness.cjs');

const FIXTURES = path.join(__dirname, 'fixtures');
const OWN = ['src/features/agent/generative-ui/components/journeys', 'src/features/agent/generative-ui/journeys'];
const shipping = () =>
  OWN.flatMap((dir) =>
    fs
      .readdirSync(path.join(WEB, dir))
      .filter((f) => /\.(ts|tsx)$/.test(f))
      .map((f) => path.join(WEB, dir, f)),
  );

const env = makeEnvironment();
const specs = env.load('components/journeys/specs');
const consumer = env.load('components/journeys/renderers');
const founder = env.load('components/journeys/founder-renderers');
const views = env.load('journeys/views');
const contract = JSON.parse(fs.readFileSync(path.join(FIXTURES, 'd-shapes.json'), 'utf8'));

test('every journey spec has one renderer; founder renderers are only in the founder map', () => {
  const consumerNames = specs.CONSUMER_JOURNEY_SPECS.map((s) => s.name).sort();
  const founderNames = specs.FOUNDER_JOURNEY_SPECS.map((s) => s.name).sort();
  assert.deepEqual(Object.keys(consumer.JOURNEY_RENDERERS).sort(), consumerNames);
  assert.deepEqual(Object.keys(founder.FOUNDER_JOURNEY_RENDERERS).sort(), founderNames);
  for (const name of founderNames) assert.ok(!(name in consumer.JOURNEY_RENDERERS), `${name} is not in the consumer bundle map`);
  const seam = env.load('core/founder-journey-renderers');
  assert.equal(seam.FOUNDER_JOURNEY_RENDERERS, founder.FOUNDER_JOURNEY_RENDERERS);
});

/** Unwrap optional/nullable/default/pipe wrappers of a zod v4 schema. */
function core(schema) {
  let s = schema;
  for (let i = 0; i < 8 && s && s.def; i += 1) {
    const t = s.def.type;
    if (t === 'optional' || t === 'nullable' || t === 'default' || t === 'readonly' || t === 'nonoptional') s = s.def.innerType;
    else if (t === 'pipe') s = s.def.in;
    else break;
  }
  return s;
}

test('every view reads only keys lane D declares for that binding (lists included)', () => {
  for (const [binding, view] of Object.entries(views.VIEWS)) {
    const declared = contract.shapes[binding];
    assert.ok(declared, `${binding} is a D binding`);
    if (contract.open.includes(binding)) continue;
    const shape = core(view).shape;
    for (const key of Object.keys(shape)) {
      assert.ok(declared.keys.includes(key), `${binding}.${key} is not in D's shape`);
      const inner = core(shape[key]);
      if (inner && inner.def && inner.def.type === 'array' && declared.lists[key]) {
        const row = core(inner.def.element);
        if (row && row.shape) for (const rowKey of Object.keys(row.shape)) assert.ok(declared.lists[key].includes(rowKey), `${binding}.${key}[].${rowKey} is not in D's shape`);
      }
    }
  }
});

test('every rendered fixture is a valid result envelope whose data validates against its view', () => {
  const contracts = env.load('../../../lib/agent-runtime/ui-contracts');
  let checked = 0;
  for (const file of fs.readdirSync(FIXTURES).filter((f) => /^J0\d-.*\.json$/.test(f))) {
    const all = JSON.parse(fs.readFileSync(path.join(FIXTURES, file), 'utf8'));
    for (const [binding, scenarios] of Object.entries(all)) {
      if (binding === 'actions') continue;
      for (const [scenario, envelope] of Object.entries(scenarios)) {
        assert.equal(contracts.uiQueryResultSchema.safeParse(envelope).success, true, `${file}:${binding}:${scenario} envelope`);
        if (scenario === 'invalid' || envelope.data === null || ['denied', 'unavailable'].includes(envelope.state)) continue;
        const parsed = views.VIEWS[binding].safeParse(envelope.data);
        assert.equal(parsed.success, true, `${file}:${binding}:${scenario} ${parsed.success ? '' : JSON.stringify(parsed.error.issues.slice(0, 3))}`);
        checked += 1;
      }
    }
  }
  assert.ok(checked >= 30, `${checked} fixtures validated`);
});

test('shipping journey code has no fixture data, network calls, raw HTML, eval or direct react-lang import', () => {
  const fixtureMarkers = ['v_7f3c2a91', 'c_51a7e', 't_weekly_tips', 'job_1', 'rcpt_', 'Recital week notes', 'jamesau', 'City Hall', 'example.org'];
  for (const file of shipping()) {
    const source = fs.readFileSync(file, 'utf8');
    const rel = path.relative(WEB, file);
    for (const marker of fixtureMarkers) assert.ok(!source.includes(marker), `${rel} contains fixture data "${marker}"`);
    assert.ok(!/dangerouslySetInnerHTML|\binnerHTML\b|\beval\(|new Function\(/.test(source), `${rel} uses raw HTML or eval`);
    assert.ok(!/\bfetch\(|XMLHttpRequest|localStorage|sessionStorage/.test(source), `${rel} reaches the network or browser storage itself`);
    assert.ok(!/@openuidev\/react-lang/.test(source), `${rel} imports react-lang directly (use core/openui.ts)`);
    assert.ok(!/console\.(log|info|debug)/.test(source), `${rel} logs`);
  }
});

test('the copy audit passes on lane E paths (no implementation words, product name spelled Rafii)', async () => {
  const audit = await import(pathToFileURL(path.join(WEB, 'scripts', 'copy-audit.mjs')).href);
  const banned = audit.audit({ patterns: audit.BANNED, roots: OWN });
  assert.deepEqual(banned, []);
  const naming = audit.audit({ patterns: audit.NAMING, roots: OWN, wholeLine: true });
  assert.deepEqual(naming, []);
});

// OpenUI passes a query-bound prop as null (or leaves it out) until its Query answers — always during SSR and streaming.
// Every journey component must then show the quiet loading state, never "can't show this data" or a crash.
const LITERALS = {
  DraftEditor: { actionId: 'draft_edit', name: 'draftText' },
  RescheduleForm: { actionId: 'schedule_prepare', target: 'job' },
  VoiceAnalyzeLocal: { actionId: 'voice_profile_analyze_local' },
  VoiceSampleImport: { actionId: 'voice_samples_import', name: 'pasted' },
  CampaignBriefForm: { actionId: 'campaign_create', name: 'brief' },
  CampaignBriefEditor: { actionId: 'campaign_update', name: 'edit' },
  CampaignLinkDrafts: { actionId: 'campaign_link' },
  AutomationChangeForm: { actionId: 'automation_change_prepare', name: 'change' },
};

test('every journey component renders a loading state (not an error) while its query prop is null or absent', () => {
  const { render, textOf } = require('./_harness.cjs');
  const all = [...specs.CONSUMER_JOURNEY_SPECS, ...specs.FOUNDER_JOURNEY_SPECS];
  let bound = 0;
  for (const spec of all) {
    const renderer = consumer.JOURNEY_RENDERERS[spec.name] ?? founder.FOUNDER_JOURNEY_RENDERERS[spec.name];
    const usesData = 'data' in spec.props.shape;
    for (const data of usesData ? [null, undefined] : [undefined]) {
      const props = { ...(LITERALS[spec.name] ?? {}), ...(usesData ? { data } : {}), title: null, selected: null, cursor: null };
      const html = render(makeEnvironment(), renderer, props);
      const text = textOf(html);
      assert.doesNotMatch(text, /couldn’t show this data|can’t be shown|isn’t available here/, `${spec.name} with data=${String(data)}`);
      assert.match(html, new RegExp(`data-genui="${spec.name}"`), `${spec.name} root is tagged`);
      if (usesData) {
        assert.match(html, /aria-busy="true"/, `${spec.name} shows loading rows`);
        bound += 1;
      }
    }
  }
  assert.ok(bound >= 80, `${bound} bound renders`);
});
