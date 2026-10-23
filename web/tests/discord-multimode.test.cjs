/** Synthetic presenter/locale tests. Runtime result pending cloud execution. */
const test = require('node:test'); const assert = require('node:assert/strict');
const fs = require('node:fs'); const path = require('node:path'); const Module = require('node:module');
const ts = require('typescript'); const React = require('react'); const {renderToStaticMarkup} = require('react-dom/server');
const root = path.resolve(__dirname, '..');
function load(relative) {
  const filename = path.join(root, relative);
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true},fileName:filename});
  const loaded = new Module(filename, module); loaded.filename = filename; loaded.paths = Module._nodeModulePaths(path.dirname(filename));
  loaded._compile(result.outputText, filename); return loaded.exports;
}
test('additional modes are separate truthful unavailable choices', () => {
  assert.ok(fs.existsSync(path.join(root, 'src/features/channels/discord-mode-choices.tsx')));
  const {DiscordModeChoices} = load('src/features/channels/discord-mode-choices.tsx');
  const html = renderToStaticMarkup(React.createElement(DiscordModeChoices, {purpose:'identity',busy:false,onChange:()=>{}}));
  assert.match(html, /Incoming webhook/); assert.match(html, /User-installed app/);
  assert.match(html, /unavailable/i); assert.doesNotMatch(html, /Post as you|Assisted/);
  assert.equal((html.match(/disabled=""/g)||[]).length, 2);
});
test('enabled webhook explicit and untrusted install URL refused', () => {
  const {DiscordModeChoices} = load('src/features/channels/discord-mode-choices.tsx');
  const html = renderToStaticMarkup(React.createElement(DiscordModeChoices, {purpose:'webhook',busy:false,onChange:()=>{},
    modes:{webhook:{enabled:true},userInstall:{enabled:true,installUrl:'https://evil.invalid/'}}}));
  assert.match(html, /aria-pressed="true"/); assert.doesNotMatch(html, /href="https:\/\/evil/);
});
test('all existing UI packs cover personal modes and sender copy', () => {
  const packs = JSON.parse(fs.readFileSync(path.join(root, 'src/lib/channels/discord-copy.json')));
  assert.deepEqual(Object.keys(packs).sort(), ['en','zh-Hans','zh-Hant']);
  const keys = Object.keys(packs.en).sort(); assert.ok(keys.length >= 30);
  for (const locale of ['zh-Hant','zh-Hans']) {
    assert.deepEqual(Object.keys(packs[locale]).sort(), keys);
    for (const key of keys) assert.ok(packs[locale][key].trim(), locale + ':' + key);
  }
});

test('all three language packs disclose the bot-free owner/admin boundary', () => {
  const {DiscordModeChoices} = load('src/features/channels/discord-mode-choices.tsx');
  const packs = JSON.parse(fs.readFileSync(path.join(root, 'src/lib/channels/discord-copy.json')));
  for (const copy of Object.values(packs)) {
    const html = renderToStaticMarkup(React.createElement(DiscordModeChoices,
      {purpose:'webhook', busy:false, onChange:()=>{}, copy, modes:{webhook:{enabled:true},userInstall:{enabled:false}}}));
    assert.ok(html.includes(copy.webhookNotice));
    assert.ok(copy.webhookIdentityLabel.trim());
    assert.ok(copy.webhookIdentityNone.trim());
  }
});

test('private mapping removal remains available while paused or reconnect-required', () => {
  const helpers = load('src/lib/channels/discord-personal-account.ts');
  assert.equal(typeof helpers.discordPrivateLinkActions, 'function', 'private removal is incorrectly tied to new-install eligibility');
  for (const status of ['linked', 'reconnect_required', 'disconnected']) {
    assert.deepEqual(helpers.discordPrivateLinkActions({status, privateDraftsConfigured:true}, false), {bind:false,remove:true});
  }
  assert.deepEqual(helpers.discordPrivateLinkActions({status:'linked',privateDraftsLinked:true}, false), {bind:false,remove:true});
  assert.deepEqual(helpers.discordPrivateLinkActions({status:'linked',privateDraftsConfigured:false}, true), {bind:true,remove:false});
  assert.deepEqual(helpers.discordPrivateLinkActions({status:'reconnect_required'}, true), {bind:false,remove:false});
  const sheet = fs.readFileSync(path.join(root, 'src/features/channels/connect-sheet.tsx'), 'utf8');
  assert.match(sheet, /discordPrivateLinkActions\(link,[^\n]+\)\.remove/);
});
