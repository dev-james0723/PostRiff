/**
 * Rafii's guided walkthroughs (docs/design/rafii-live-agent/CONTRACTS.md, Contract 5) and the answer actions that
 * start them (Contract 2): the steps match the guide manifest both ways, every step can be shown, the cursor only
 * clicks what the pages mark safe, and an answer's actions run once, for the newest request only.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const ROOT = path.join(WEB, '..');

function load(rel) {
  const file = path.join(WEB, rel);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const G = load('src/features/rafii-guide/guides.ts');
const A = load('src/features/rafii-guide/auto-actions.ts');
const GEO = load('src/features/rafii-guide/geometry.ts');
const MANIFEST_FILE = path.join(WEB, 'src/lib/site-agent/guide-manifest.json');
const manifest = JSON.parse(fs.readFileSync(MANIFEST_FILE, 'utf8'));
const routes = JSON.parse(fs.readFileSync(path.join(WEB, 'src/lib/site-agent/route-manifest.json'), 'utf8'));
const ACTIONS = new Set(['point', 'click', 'await-click', 'await-visible']);
const PLACEMENTS = new Set(['top', 'bottom', 'left', 'right']);

/** Every .tsx file of the app, minus the guide feature itself. */
function sources(dir = path.join(WEB, 'src'), out = []) {
  for (const name of fs.readdirSync(dir)) {
    const file = path.join(dir, name);
    if (fs.statSync(file).isDirectory()) sources(file, out);
    else if (name.endsWith('.tsx') && !file.includes(`${path.sep}rafii-guide${path.sep}`)) out.push({ file: path.relative(WEB, file), lines: fs.readFileSync(file, 'utf8').split('\n') });
  }
  return out;
}
const SOURCES = sources();

/** `[data-tour="…"]` ids a selector names. */
const tourIds = (selector) => [...selector.matchAll(/\[data-tour="([^"]+)"\]/g)].map((match) => match[1]);
/** Source lines that give an element this data-tour id (plain or conditional). */
const linesFor = (id) =>
  SOURCES.flatMap(({ file, lines }) =>
    lines
      .map((line, index) => ({ file, line, index }))
      .filter(({ line }) => line.includes(`data-tour='${id}'`) || line.includes(`data-tour="${id}"`) || (line.includes('data-tour={') && line.includes(`'${id}'`)))
  );

test('the guide manifest twin matches the API copy byte for byte', () => {
  const api = path.join(ROOT, 'src', 'postriff_phase2', 'site_agent', 'guide_manifest.json');
  assert.equal(fs.readFileSync(MANIFEST_FILE, 'utf8'), fs.readFileSync(api, 'utf8'));
});

test('every manifest guide has steps, and every guide with steps is in the manifest', () => {
  const manifestIds = manifest.guides.map((guide) => guide.id);
  const stepIds = G.GUIDES.map((guide) => guide.id);
  assert.equal(new Set(stepIds).size, stepIds.length, 'a guide id is repeated');
  assert.deepEqual([...stepIds].sort(), [...manifestIds].sort());
  for (const id of manifestIds) assert.ok(G.guideFor(id), id);
  assert.equal(G.guideFor('not_a_guide'), null);
  assert.equal(G.guideFor('toString'), null);
});

test('each guide starts on the page its manifest entry names', () => {
  for (const entry of manifest.guides) {
    const route = routes.routes.find((item) => item.id === entry.routeId);
    assert.ok(route, `${entry.id}: unknown route ${entry.routeId}`);
    assert.equal(G.guideFor(entry.id).route, route.pattern, entry.id);
  }
});

test('every step has a target, words and a known action', () => {
  for (const guide of G.GUIDES) {
    assert.ok(guide.steps.length > 0, guide.id);
    assert.ok(typeof guide.done === 'string' && guide.done.trim().length > 0, `${guide.id}: closing words`);
    assert.ok(!guide.steps[0].optional, `${guide.id}: the first step is what the guide is about`);
    guide.steps.forEach((step, index) => {
      const where = `${guide.id} step ${index + 1}`;
      assert.ok(Array.isArray(step.target) && step.target.length > 0, `${where}: target`);
      for (const selector of step.target) assert.ok(typeof selector === 'string' && selector.trim().length > 0, `${where}: empty selector`);
      assert.ok(typeof step.say === 'string' && step.say.trim().length > 0, `${where}: words`);
      assert.ok(step.say.length <= 160, `${where}: keep the caption short`);
      assert.ok(ACTIONS.has(step.action), `${where}: action ${step.action}`);
      if (step.placement !== undefined) assert.ok(PLACEMENTS.has(step.placement), `${where}: placement`);
      if (step.route !== undefined) assert.ok(step.route.startsWith('/app'), `${where}: route`);
    });
  }
});

test('every data-tour id a guide names exists on a page', () => {
  const ids = new Set(G.GUIDES.flatMap((guide) => guide.steps.flatMap((step) => step.target.flatMap(tourIds))));
  assert.ok(ids.size > 20);
  for (const id of ids) assert.ok(linesFor(id).length > 0, `no element carries data-tour="${id}"`);
});

test('click steps only press elements the pages mark data-guide-safe', () => {
  let clicks = 0;
  for (const guide of G.GUIDES) {
    for (const step of guide.steps.filter((item) => item.action === 'click')) {
      clicks += 1;
      for (const selector of step.target) {
        const ids = tourIds(selector);
        assert.ok(ids.length > 0, `${guide.id}: ${selector} names no data-tour id`);
        const kind = G.GUIDE_SAFE[ids[0]];
        assert.ok(kind, `${guide.id}: ${ids[0]} is not in GUIDE_SAFE`);
        if (kind === 'tabs') assert.match(selector, /\[role="tab"\]/, `${guide.id}: only a tab inside ${ids[0]} may be pressed`);
        else assert.ok(selector.startsWith(`[data-tour="${ids[0]}"]`) && !/\s/.test(selector), `${guide.id}: ${selector} must be the marked element itself`);
      }
    }
  }
  assert.ok(clicks >= 8);
});

test('safe ids carry data-guide-safe in the page source, and nothing else does', () => {
  const marked = SOURCES.flatMap(({ file, lines }) => lines.map((line, index) => ({ file, line, index })).filter(({ line }) => /data-guide-safe/.test(line)));
  for (const { file, line, index } of marked) {
    const id = /data-tour='([^']+)'/.exec(line)?.[1];
    assert.ok(id, `${file}:${index + 1}: data-guide-safe without a data-tour id on the same line`);
    const kind = G.GUIDE_SAFE[id];
    assert.ok(kind, `${file}:${index + 1}: ${id} is marked safe but not listed in GUIDE_SAFE`);
    assert.equal(/data-guide-safe='tabs'/.test(line), kind === 'tabs', `${file}:${index + 1}: ${id} should be marked "${kind}"`);
  }
  for (const id of Object.keys(G.GUIDE_SAFE)) {
    const lines = linesFor(id);
    assert.ok(lines.length > 0, `${id}: no element`);
    for (const { file, line, index } of lines) assert.match(line, /data-guide-safe/, `${file}:${index + 1}: every ${id} element must be marked`);
  }
});

test('what the person must do themselves is never marked safe', () => {
  const theirs = new Set(G.GUIDES.flatMap((guide) => guide.steps.filter((step) => step.action !== 'click').flatMap((step) => step.target.flatMap(tourIds))));
  for (const id of ['connect-continue', 'connect-authorize', 'schedule-prepare', 'queue-approve', 'automation-save', 'voice-sample-save', 'composer-generate', 'library-upload', 'memory-access-confirm']) {
    assert.ok(theirs.has(id), `${id} should be a step the person does`);
    assert.equal(G.GUIDE_SAFE[id], undefined, `${id} must never be clicked for the person`);
    for (const { file, line, index } of linesFor(id)) assert.doesNotMatch(line, /data-guide-safe/, `${file}:${index + 1}`);
  }
  // Connecting an account: the cursor opens the sheet and picks the platform; Continue and the sign-in are the person's.
  const connect = G.guideFor('connect_account').steps;
  assert.deepEqual(connect.map((step) => step.action).slice(0, 5), ['point', 'click', 'click', 'point', 'await-click']);
  assert.match(connect[4].say, /sign-in/);
  assert.match(connect[4].say, /yourself/);
});

test('isGuideSafe accepts marked elements, and tabs inside a marked tab list only', () => {
  const node = (attrs, parent = null) => ({
    getAttribute: (name) => (name in attrs ? attrs[name] : null),
    closest(selector) {
      assert.equal(selector, '[data-guide-safe]');
      for (let current = this; current; current = current.parent) if (current.getAttribute('data-guide-safe') !== null) return current;
      return null;
    },
    parent
  });
  const tabs = node({ 'data-guide-safe': 'tabs' });
  const plain = node({});
  assert.equal(G.isGuideSafe(node({ 'data-guide-safe': 'true' })), true);
  assert.equal(G.isGuideSafe(node({ 'data-guide-safe': '' })), true);
  assert.equal(G.isGuideSafe(node({ role: 'tab' }, tabs)), true);
  assert.equal(G.isGuideSafe(node({}, tabs)), false, 'a non-tab inside a tab list');
  assert.equal(G.isGuideSafe(tabs), false, 'the tab list itself');
  assert.equal(G.isGuideSafe(node({ role: 'tab' }, plain)), false, 'a tab in an unmarked list');
  assert.equal(G.isGuideSafe(node({ role: 'button' })), false);
  assert.equal(G.isGuideSafe(null), false);
});

test('an answer asks for a safe action, guide, link or style change', () => {
  const action = { type: 'ui_action', action: 'activate', actionId: 'channels.connect', label: 'Connect account', auto: true };
  const guide = { type: 'guide_card', guideId: 'connect_account', routeId: 'channels', href: '/app/channels', title: 'Connect', summary: '', auto: true };
  const link = { type: 'navigation_card', label: 'Open Channels', href: '/app/channels', routeId: 'channels', auto: true };
  const style = { type: 'voice_command', command: 'style', style: { pace: 'slower' } };
  assert.deepEqual(A.autoActionsOf([action, guide, link], 'text'), [{ kind: 'activate', actionId: 'channels.connect', label: 'Connect account' }], 'a safe page action wins');
  assert.deepEqual(A.autoActionsOf([action], 'voice'), [{ kind: 'activate', actionId: 'channels.connect', label: 'Connect account' }], 'voice and text use the same action path');
  assert.deepEqual(A.autoActionsOf([link], 'text'), [{ kind: 'navigate', href: '/app/channels' }]);
  assert.deepEqual(A.autoActionsOf([link, guide], 'text'), [{ kind: 'guide', guideId: 'connect_account' }], 'a guide opens its own page');
  assert.deepEqual(A.autoActionsOf([guide, style], 'text'), [{ kind: 'guide', guideId: 'connect_account' }, { kind: 'style', style: { pace: 'slower' } }]);
  assert.deepEqual(A.autoActionsOf([guide, style], 'voice'), [{ kind: 'guide', guideId: 'connect_account' }], 'the call carries out voice commands itself');
  assert.deepEqual(A.autoActionsOf([{ ...link, auto: false }, { ...guide, auto: undefined }], 'text'), [], 'only what the person asked for runs');
  assert.deepEqual(A.autoActionsOf([{ type: 'voice_command', command: 'mute' }, { type: 'guide_card', auto: true, guideId: '' }, null, 'text', 3], 'text'), []);
  assert.deepEqual(A.autoActionsOf(undefined, 'text'), []);
});

test('the ledger runs each answer once, and never an answer older than one that already ran', () => {
  const ledger = A.createAutoLedger();
  const first = ledger.begin();
  const second = ledger.begin();
  assert.ok(second > first);
  assert.equal(ledger.claim('answer-2', second), true);
  assert.equal(ledger.claim('answer-2', second), false, 'a re-render or a repeated callback runs nothing');
  assert.equal(ledger.claim('answer-1', first), false, 'the older request answered late: latest only');
  assert.equal(ledger.claim('answer-1', first), false);
  const third = ledger.begin();
  assert.equal(ledger.claim('answer-3', third), true);
  assert.equal(ledger.claim('', ledger.begin()), false);
  assert.equal(ledger.claim(null, ledger.begin()), false);
  assert.equal(ledger.claim(undefined, ledger.begin()), false);
  const small = A.createAutoLedger(2);
  for (const id of ['a', 'b', 'c']) assert.equal(small.claim(id, small.begin()), true);
  assert.equal(small.claim('c', small.begin()), false, 'the newest ids are remembered');
});

test('the cursor glides for 600 to 900 ms along a gentle curve and lands inside the target', () => {
  assert.equal(GEO.glideDuration(0), 600);
  assert.equal(GEO.glideDuration(5000), 900);
  const mid = GEO.glideDuration(400);
  assert.ok(mid > 600 && mid < 900);
  const from = { x: 100, y: 400 };
  const to = { x: 700, y: 400 };
  assert.deepEqual(GEO.curvePoint(from, to, 0), from);
  assert.deepEqual(GEO.curvePoint(from, to, 1), to);
  const half = GEO.curvePoint(from, to, 0.5);
  assert.ok(half.y < 400 && half.y > 300, 'bows gently upward');
  assert.ok(Math.abs(half.x - 400) < 1);
  const back = GEO.curvePoint(to, from, 0.5);
  assert.ok(back.y < 400, 'upward both ways');
  const button = { left: 10, top: 20, width: 120, height: 40 };
  const aim = GEO.anchorOf(button);
  assert.ok(aim.x > 10 && aim.x < 130 && aim.y > 20 && aim.y < 60);
  const section = { left: 0, top: 0, width: 800, height: 600 };
  const corner = GEO.anchorOf(section);
  assert.ok(corner.x <= 56 && corner.y <= 30, 'a large region is pointed at near its title');
});
