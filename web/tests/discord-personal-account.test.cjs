/** Actual helper execution and component SSR. No provider requests or browser-acceptance claims. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const root = path.resolve(__dirname, '..');
function load(relative) {
  const filename = path.join(root, relative);
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true}, fileName: filename});
  const loaded = new Module(filename, module);
  loaded.filename = filename; loaded.paths = Module._nodeModulePaths(path.dirname(filename));
  loaded._compile(result.outputText, filename); return loaded.exports;
}
const helperPath = 'src/lib/channels/discord-personal-account.ts';
const componentPath = 'src/features/channels/discord-personal-accounts.tsx';
const identity = {id:'identity-1', account:'Synthetic customer', userId:'111111',
  status:'linked', expiresAt:9999999999, discoverGuilds:true};
const provider = {id:'discord', platform:'Discord', discordConnectionsV2:true,
  configured:true, connectReady:true, capabilities:{identity:true, publish:true}};
const helperExists = fs.existsSync(path.join(root, helperPath));
const componentExists = fs.existsSync(path.join(root, componentPath));
test('personal-account helper and main-page component are implemented', () => {
  assert.equal(helperExists, true, 'personal account capability helper is missing');
  assert.equal(componentExists, true, 'first-class personal account section is missing');
});
if (helperExists) {
  const {discordDiscoveryState, discordCanConnect} = load(helperPath);
  test('server discovery distinguishes identity, reconnect, scope and ready states', () => {
    assert.equal(discordDiscoveryState(undefined), 'choose_identity');
    for (const status of ['disconnected','reconnect_required','unknown'])
      assert.equal(discordDiscoveryState({...identity,status}), 'reconnect_required');
    for (const discoverGuilds of [false,undefined,'true',1])
      assert.equal(discordDiscoveryState({...identity,discoverGuilds}), 'scope_required');
    assert.equal(discordDiscoveryState(identity), 'ready');
  });
  test('personal connection cannot bypass role, rollout or configuration', () => {
    assert.equal(discordCanConnect(provider, true), true);
    assert.equal(discordCanConnect(provider, false), false);
    assert.equal(discordCanConnect(undefined, true), false);
    for (const fields of [{discordConnectionsV2:false},{connectReady:false},{executionPaused:true},
      {configured:false},{configurationState:'partial_configuration'},
      {configurationState:'invalid_configuration'},{capabilities:{identity:false,publish:true}}])
      assert.equal(discordCanConnect({...provider,...fields}, true), false);
  });
}
if (componentExists) {
  const {DiscordPersonalAccounts} = load(componentPath);
  const render = overrides => renderToStaticMarkup(React.createElement(DiscordPersonalAccounts,
    {identities:[], available:true, canManage:true, canConnect:true,
      onConnect:()=>{}, onManage:()=>{}, ...overrides}));
  test('identity connection is visible without any bot or server channel', () => {
    const html = render({});
    assert.match(html, /Personal Discord accounts/);
    assert.match(html, /Connect personal Discord account/);
    assert.match(html, /does not authorize publishing as you/);
    assert.match(html, /No personal Discord account linked/);
    assert.doesNotMatch(html, /Publish now|Schedule post|Post as you/);
  });
  test('linked accounts render independently, with truthful scope and stored status', () => {
    const html = render({identities:[identity]});
    assert.match(html, /id="discord-identity-identity-1"/);
    assert.match(html, /Synthetic customer/);
    assert.match(html, /Server-list permission granted/);
    assert.match(html, /Manage personal account/);
    assert.match(render({identities:[{...identity,discoverGuilds:false}]}), /Server-list permission not granted/);
  });
  test('existing identities remain visible when new connections are unavailable', () => {
    const html = render({identities:[identity],available:false,canConnect:false});
    assert.match(html, /Synthetic customer/);
    assert.match(html, /New connections are currently unavailable/);
    assert.match(html, /disabled=""/);
  });
  test('unauthorized role does not gain connect or management buttons', () => {
    const html = render({identities:[identity],canManage:false,canConnect:false});
    assert.doesNotMatch(html, /<button/);
    assert.match(html, /workspace permission/);
  });
  test('provider-controlled identity text is escaped and no fields can add publishing', () => {
    const html = render({identities:[{...identity,account:'<img src=x onerror=bad()>',
      canPublish:true,canSchedule:true,postAsPersonalUser:true,access_token:'synthetic-secret'}]});
    assert.doesNotMatch(html, /<img|synthetic-secret|Publish now|Schedule post|Post as you/);
    assert.match(html, /&lt;img/);
  });
}
if (helperExists) {
  test('Discord missing scopes never imply Assisted or personal-user publishing', () => {
    const {missingScopePublishingMessage} = load(helperPath);
    assert.match(missingScopePublishingMessage('discord'), /unavailable/);
    assert.doesNotMatch(missingScopePublishingMessage('discord'), /Assisted|as you/);
    assert.equal(missingScopePublishingMessage('linkedin'), 'Publishing stays Assisted.');
  });
}
test('connection-sheet wiring invalidates pending results on platform change', () => {
  const text = fs.readFileSync(path.join(root,'src/features/channels/connect-sheet.tsx'),'utf8');
  const choose = text.slice(text.indexOf('  function choosePlatform('),text.indexOf('  async function start()'));
  assert.match(choose, /discordRequestGeneration\.current\s*\+=\s*1/);
  assert.match(choose, /if \(busy\) return/);
});
test('Discord start and reconnect wiring fence stale results and clear old destinations', () => {
  const text = fs.readFileSync(path.join(root,'src/features/channels/connect-sheet.tsx'),'utf8');
  const start = text.slice(text.indexOf('  async function start()'),text.indexOf('  async function checkCode()'));
  assert.match(start, /generation !== discordRequestGeneration\.current/);
  const reconnect = text.slice(text.indexOf('  function prepareDiscordReconnect('),text.indexOf('  async function loadDiscordGuilds()'));
  assert.match(reconnect, /setDiscordGuild\(''\)/);
  assert.match(reconnect, /setDiscordGuilds\(\[\]\)/);
  assert.match(text, /dc\.reconnectNotice/);
  const copy = JSON.parse(fs.readFileSync(path.join(root, 'src/lib/channels/discord-copy.json')));
  assert.match(copy.en.reconnectNotice, /Reconnecting requires server and channel authorization again/);
});
