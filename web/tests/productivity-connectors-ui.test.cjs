const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', 'src');
const read = (...parts) => fs.readFileSync(path.join(SRC, ...parts), 'utf8');

test('productivity connector client uses the hosted connector endpoints', () => {
  const client = read('lib', 'api', 'client.ts');
  assert.match(client, /connectorCatalog:.*\/connectors/);
  assert.match(client, /connectorOauthStart:/);
  assert.match(client, /connectorOauthComplete:/);
  assert.match(client, /connectorSearch:/);
  assert.match(client, /connectorRefresh:/);
  assert.match(client, /connectorDisconnect:/);
});

test('the one plus sheet owns skills and connected apps, with on-demand connector search', () => {
  const sheet = read('features', 'agent', 'attachments', 'plus-sheet.tsx');
  assert.match(sheet, /label: 'Skill'/);
  assert.match(sheet, /label: 'Connected apps'/);
  assert.match(sheet, /catalog\?\.skills/);
  assert.match(sheet, /api\.connectorCatalog\(workspaceId\)/);
  assert.match(sheet, /api\.connectorOauthStart\(workspaceId, provider\)/);
  assert.match(sheet, /api\.connectorSearch\(workspaceId, selected, query\.trim\(\), 12\)/);
  assert.match(sheet, /onRemember\(found\)/);
  assert.doesNotMatch(sheet, /setInterval|background sync/i);
});

test('Recent posts opens the existing consent-separated writing-sample review on Home and conversation chat', () => {
  const sheet = read('features', 'agent', 'attachments', 'plus-sheet.tsx');
  const bar = read('features', 'agent', 'attachments', 'attachment-bar.tsx');
  const home = read('features', 'agent', 'home-view.tsx');
  const conversation = read('features', 'agent', 'conversation-view.tsx');
  assert.match(sheet, /label: 'Recent posts'/);
  assert.match(sheet, /onRecentPosts\?\.\(\)/);
  assert.match(bar, /onRecentPosts=\{onRecentPosts\}/);
  assert.match(home, /Review my recent Instagram and LinkedIn posts and help me learn how I write\./);
  assert.match(conversation, /Review my recent Instagram and LinkedIn posts and help me learn how I write\./);
  assert.match(home, /<VoiceLearningPanel/);
  assert.match(conversation, /<VoiceLearningPanel/);
});

test('OAuth provider return has public forwarding and authenticated completion surfaces', () => {
  const publicPage = read('app', 'connectors', 'connect', 'forwarder.tsx');
  const appPage = read('app', 'app', 'connectors', 'connect', 'page.tsx');
  const handler = read('features', 'connectors', 'connect-return.tsx');
  assert.match(publicPage, /\/app\/connectors\/connect/);
  assert.match(appPage, /ProductivityConnectorReturn/);
  assert.match(handler, /connectorOauthComplete/);
  assert.match(handler, /\/app\?connector=/);
});

test('connector items remembered by the composer feed local @ results only', () => {
  const hook = read('features', 'agent', 'attachments', 'use-composer-attachments.ts');
  const search = read('features', 'agent', 'attachments', 'use-picker-search.ts');
  assert.match(hook, /connectorItems/);
  assert.match(hook, /rememberConnectorItems/);
  assert.match(hook, /catalog\?\.skills/);
  assert.match(search, /LEGACY_SERVER_CATEGORIES/);
  assert.match(search, /'posts'[\s\S]*'library'/);
  assert.doesNotMatch(search.match(/LEGACY_SERVER_CATEGORIES[\s\S]*?\];/)?.[0] ?? '', /skills|connectors/);
});
