/**
 * UI-1: the "Personal Discord accounts" section on Channels appears only when the Discord launch gate is open for this
 * workspace or the workspace already has linked Discord identities. While Discord is closed to a workspace that never
 * linked one, nothing new appears (docs/CUSTOMER-IMPACT-INVENTORY.md, finding UI-1; docs/RC2-SHARED-PATH-FIXES.md).
 * The helper runs for real (Node strips the TypeScript types; the `typescript` package is used when present), and the
 * page wiring is checked in the source. The Connect sheet's closed-gate message (UI-2) is unchanged.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');
const helperPath = 'src/lib/channels/discord-personal-account.ts';

async function loadHelper() {
  let ts = null;
  try { ts = require('typescript'); } catch { ts = null; }
  if (ts) {
    const filename = path.join(root, helperPath);
    const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: filename });
    const loaded = new Module(filename, module);
    loaded.filename = filename; loaded.paths = Module._nodeModulePaths(path.dirname(filename));
    loaded._compile(result.outputText, filename);
    return loaded.exports;
  }
  return import(pathToFileURL(path.join(root, helperPath)).href);
}

const discord = (fields) => ({ id: 'discord', platform: 'Discord', discordConnectionsV2: true, configured: true,
  connectReady: false, capabilities: { identity: true, publish: true }, ...fields });
const identity = { id: 'identity-1', account: 'Synthetic customer', userId: '111111', status: 'linked', expiresAt: 9999999999, discoverGuilds: true };

test('closed gate and no linked identity: the section is not shown', async () => {
  const { showDiscordPersonalAccounts } = await loadHelper();
  assert.equal(typeof showDiscordPersonalAccounts, 'function', 'the visibility helper is missing');
  const closed = discord({ discordAccess: { status: 'closed', reason: 'invite_only', capped: true } });
  assert.equal(showDiscordPersonalAccounts(closed, []), false);
  assert.equal(showDiscordPersonalAccounts(closed, undefined), false);
  assert.equal(showDiscordPersonalAccounts(discord({}), []), false, 'no verdict from the server counts as closed');
  assert.equal(showDiscordPersonalAccounts(undefined, []), false, 'Discord not mounted');
});

test('open gate shows it; linked identities show it whatever the gate says', async () => {
  const { showDiscordPersonalAccounts } = await loadHelper();
  const open = discord({ discordAccess: { status: 'open', capped: true }, connectReady: true });
  assert.equal(showDiscordPersonalAccounts(open, []), true);
  assert.equal(showDiscordPersonalAccounts(discord({ discordAccess: { status: 'open' }, discordConnectionsV2: false }), []), false,
    'the original connect flow has no personal accounts');
  const closed = discord({ discordAccess: { status: 'closed', reason: 'invite_only' } });
  assert.equal(showDiscordPersonalAccounts(closed, [identity]), true);
  assert.equal(showDiscordPersonalAccounts(undefined, [identity]), true);
  assert.equal(showDiscordPersonalAccounts({ ...open, id: 'mastodon' }, []), false);
});

test('the Channels page renders the section only through the helper', () => {
  const page = read('src/features/channels/channels-view.tsx');
  assert.match(page, /\{showDiscordPersonalAccounts\(providers\.find\(provider => provider\.id === 'discord'\), data\?\.discordIdentities\) && \(\s*<DiscordPersonalAccounts /);
  assert.equal(page.match(/<DiscordPersonalAccounts /g).length, 1, 'one render site');
  assert.doesNotMatch(page, /provider\.discordConnectionsV2\) \|\| !!data\?\.discordIdentities\?\.length\) && \(/,
    'the old condition (connections v2 alone) is gone');
});

test('the Connect sheet keeps its closed-gate message (UI-2)', () => {
  assert.match(read('src/features/channels/connect-sheet.tsx'), /provider\.id === 'discord' && provider\.discordAccess\?\.status === 'closed' \? dc\.accessClosed/);
});
