// Connection Health Center (web): complete en / zh-Hant / zh-Hans copy for every server state, reason and line;
// no client-side upgrade of a state; the panel and page mount only where the server admitted the workspace; reconnect
// only through the existing Connect sheet.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const ROOT = path.join(WEB, '..');
const read = (file) => fs.readFileSync(path.join(WEB, file), 'utf8');

function load(file) {
  const source = path.join(WEB, file);
  const result = ts.transpileModule(fs.readFileSync(source, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true } });
  const mod = { exports: {} };
  const local = (name) => require(name.startsWith('.') ? path.join(path.dirname(source), name) : name);
  new Function('require', 'module', 'exports', result.outputText)(local, mod, mod.exports);
  return mod.exports;
}

const packs = JSON.parse(read('src/lib/channels/health-copy.json'));
const python = fs.readFileSync(path.join(ROOT, 'src/postriff_phase2/connection_health.py'), 'utf8');
function tuple(name) {
  const match = python.match(new RegExp(`^${name} = \\(([^)]*)\\)`, 'm'));
  assert.ok(match, `connection_health.${name} is a literal tuple`);
  return [...match[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

test('three complete packs with the same keys and the same placeholders', () => {
  assert.deepEqual(Object.keys(packs).sort(), ['en', 'zh-Hans', 'zh-Hant']);
  const keys = Object.keys(packs.en).sort();
  for (const lang of ['zh-Hant', 'zh-Hans']) {
    assert.deepEqual(Object.keys(packs[lang]).sort(), keys, lang);
    for (const key of keys) {
      assert.ok(packs[lang][key].trim(), `${lang}.${key} is empty`);
      const holes = (text) => [...text.matchAll(/\{([a-zA-Z]+)\}/g)].map((m) => m[1]).sort();
      assert.deepEqual(holes(packs[lang][key]), holes(packs.en[key]), `${lang}.${key} placeholders`);
    }
  }
});

test('every server state, reason and line status has words in every language', () => {
  const { lineKey, badgeKey } = load('src/lib/channels/health.ts');
  const states = tuple('STATES');
  const statuses = tuple('LINE_STATUSES');
  const reasons = tuple('REASONS');
  assert.ok(states.includes('ready') && statuses.includes('not_offered') && reasons.includes('access_revoked'));
  for (const lang of Object.keys(packs)) {
    const copy = packs[lang];
    for (const state of states) {
      assert.ok(copy[`state.${state}`], `${lang} state.${state}`);
      assert.ok(copy[`stateLine.${state}`], `${lang} stateLine.${state}`);
      assert.ok(copy[badgeKey({ state, reasons: [] })], `${lang} badge for ${state}`);
    }
    for (const reason of reasons) assert.ok(copy[`reason.${reason}`], `${lang} reason.${reason}`);
    assert.ok(copy[badgeKey({ state: 'expired', reasons: ['access_revoked'] })]);
    assert.ok(copy[badgeKey({ state: 'expired', reasons: ['reconnect_required'] })]);
    for (const name of ['publishing', 'analytics', 'history', 'comments']) {
      assert.ok(copy[`line.${name}`], `${lang} line.${name}`);
      for (const status of statuses) assert.ok(copy[lineKey(name, { status })], `${lang} ${name}/${status}`);
    }
    assert.ok(copy[lineKey('publishing', { status: 'assisted', detail: 'awaiting_review' })]);
    for (const capability of ['publish', 'analytics', 'comments_read', 'reply', 'posts_read']) assert.ok(copy[`capability.${capability}`]);
    for (const preset of tuple('AUTONOMY_PRESETS')) assert.ok(copy[`preset.${preset}`], `${lang} preset.${preset}`);
    for (const category of tuple('AUTONOMY_CATEGORIES')) assert.ok(copy[`category.${category}`], `${lang} category.${category}`);
    for (const effective of tuple('AUTONOMY_EFFECTIVE')) assert.ok(copy[`effective.${effective}`], `${lang} effective.${effective}`);
  }
});

test('display preferences pick one whole pack', () => {
  const { healthCopy, fill, copyFor } = load('src/lib/channels/health-copy.ts');
  assert.equal(healthCopy('zh-HK').lang, 'zh-Hant');
  assert.equal(healthCopy('zh-Hant-TW').lang, 'zh-Hant');
  assert.equal(healthCopy('yue-Hant-HK').lang, 'zh-Hant');
  assert.equal(healthCopy('zh-CN').lang, 'zh-Hans');
  assert.equal(healthCopy('zh-Hans-SG').lang, 'zh-Hans');
  assert.equal(healthCopy('fr-FR').lang, 'en');
  assert.equal(healthCopy('').lang, 'en');
  assert.equal(fill('{a} and {b}', { a: 1 }), '1 and {b}');
  assert.equal(copyFor(packs.en, 'state.nonsense', 'state.not_connected'), packs.en['state.not_connected']);
});

test('only the server can say ready; gaps never read as working', () => {
  const { stateTone, lineWorks, attentionAccounts, panelNumbers, splitPlatforms } = load('src/lib/channels/health.ts');
  for (const state of tuple('STATES')) assert.equal(stateTone(state) === 'success', state === 'ready', state);
  for (const status of tuple('LINE_STATUSES')) assert.equal(lineWorks({ status }), ['available', 'on_request', 'private_only', 'assisted'].includes(status), status);
  const account = (state, platform, name, attention = true) => ({ state, platform, account: name, attention, reasons: [] });
  const platforms = [
    { platform: 'Threads', accounts: [account('limited', 'Threads', '@b'), account('ready', 'Threads', '@ok', false)] },
    { platform: 'YouTube', accounts: [account('expired', 'YouTube', 'Channel')] },
    { platform: 'X', accounts: [] }
  ];
  assert.deepEqual(attentionAccounts({ platforms }).map((a) => a.account), ['Channel', '@b']);
  assert.deepEqual(attentionAccounts({ platforms }, 1).map((a) => a.account), ['Channel']);
  assert.deepEqual(panelNumbers({ counts: { ready: 1, limited: 1, authorized: 2 }, attention: 2 }), { ready: 1, limited: 3, attention: 2 });
  const split = splitPlatforms(platforms);
  assert.deepEqual(split.connected.map((p) => p.platform), ['Threads', 'YouTube']);
  assert.deepEqual(split.other.map((p) => p.platform), ['X']);
});

test('flag off: the panel and the health request exist only behind the server’s admission', () => {
  const channels = read('src/features/channels/channels-view.tsx');
  assert.match(channels, /data\?\.connectionHealth\?\.available === true && <ConnectionHealthPanel \/>/);
  const view = read('src/features/channels/health/connection-health-view.tsx');
  assert.match(view, /useConnectionHealth\(\{ enabled: admitted \}\)/);
  assert.match(view, /const admitted = channels\.data\?\.connectionHealth\?\.available === true;/);
  const hooks = read('src/lib/api/hooks.ts');
  assert.match(hooks, /connectionHealth: \(w: string\) => \['channels', w, 'health'\] as const/);
  assert.ok(fs.existsSync(path.join(WEB, 'src/app/app/channels/health/page.tsx')));
  // Not in the agent's route manifest: the agent links to Channels, where the panel lives.
  for (const manifest of ['src/lib/site-agent/route-manifest.json']) assert.doesNotMatch(read(manifest), /channels\/health/);
});

test('reconnect goes only through the existing Connect sheet, never a direct OAuth call or raw HTML', () => {
  const files = ['src/features/channels/health/connection-health-view.tsx', 'src/features/channels/health/connection-health-panel.tsx', 'src/features/channels/health/health-parts.tsx'];
  const text = files.map(read).join('\n');
  assert.match(text, /<ConnectSheet /);
  assert.match(text, /reconnectCapability\(/);
  assert.doesNotMatch(text, /oauthStart|oauth\/start|window\.location|dangerouslySetInnerHTML/);
  for (const banned of [/\bdeployment\b/i, /\bbackend\b/i, /\bdatabase\b/i, /\bpayload\b/i, /\bschema\b/i, /\bstaging\b/i]) {
    for (const lang of Object.keys(packs)) assert.ok(!Object.values(packs[lang]).some((value) => banned.test(value)), `${lang} ${banned}`);
  }
});
