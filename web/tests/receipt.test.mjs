import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import ts from '../node_modules/typescript/lib/typescript.js';
import React from '../node_modules/react/index.js';
import { renderToStaticMarkup } from '../node_modules/react-dom/server.node.js';
// Compile the actual UI component, not a test copy; resolve React from web.
function component() {
  const filename = new URL('../src/features/queue/publication-receipt.tsx', import.meta.url);
  const source = readFileSync(filename, 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS }}).outputText;
  const exports = {};
  new Function('require','exports',output)(createRequire(filename),exports);
  return exports.PublicationReceipt;
}
const Receipt = component();
const job = { state:'verified', manifest:{platform:'Instagram'}, container:'555', providerReference:'999', url:'https://www.instagram.com/p/ABC/', verification:{method:'provider_lookup',at:1800000000} };
test('receipt shows persisted container, reference, verified link and provenance', () => {
  const html=renderToStaticMarkup(React.createElement(Receipt, {job}));
  for(const text of ['555','999','https://www.instagram.com/p/ABC/','provider lookup']) assert.ok(html.includes(text));
});
test('unverified or unsafe URL is never a verified publication link', () => {
  for (const update of [{state:'uncertain'},{url:'javascript:alert(1)'},{url:'https://evil.test/'},{verification:{method:'manual',at:1}}]) {
    const html=renderToStaticMarkup(React.createElement(Receipt, {job:{...job,...update}}));
    assert.ok(!html.includes('<a '));
  }
});
test('actual PostgreSQL snapshot reaches the UI without losing receipt fields', () => {
  const persisted = JSON.parse(readFileSync(new URL('../../docs/postriff-research-20260918/evidence/receipt-snapshot.json', import.meta.url),'utf8'));
  const html = renderToStaticMarkup(React.createElement(Receipt, {job:persisted}));
  for (const text of ['555','999','https://www.instagram.com/p/ABC/','provider lookup']) assert.ok(html.includes(text));
});

test('accepted LinkedIn receipt provides owner inspection without claiming API verification', () => {
  const accepted = {...job,state:'provider_accepted',manifest:{platform:'LinkedIn'},container:undefined,providerReference:'urn:li:share:123',url:'https://www.linkedin.com/feed/update/urn:li:share:123/',verification:null};
  const html = renderToStaticMarkup(React.createElement(Receipt, {job:accepted}));
  assert.ok(html.includes('Open post to confirm'));
  assert.ok(html.includes('Publication is not API verified'));
  assert.ok(html.includes('Do not resubmit'));
  assert.ok(!html.includes('Open verified post'));
  const stale = renderToStaticMarkup(React.createElement(Receipt, {job:{...accepted,verification:{method:'provider_lookup',at:1}}}));
  assert.ok(stale.includes('Open post to confirm'));
  assert.ok(!stale.includes('Verified ·'));
  for (const update of [{state:'uncertain'}, {url:'https://www.linkedin.com/feed/update/urn:li:share:999/'}, {url:'https://evil.test/feed/update/urn:li:share:123/'}, {providerReference:'bad'}, {manifest:{platform:'Instagram'}}]) {
    const unsafe = renderToStaticMarkup(React.createElement(Receipt, {job:{...accepted,...update}}));
    assert.ok(!unsafe.includes('<a '), JSON.stringify(update));
  }
});

// Synthetic receipts only: render the real component; no provider transport or navigation.
const discord = {
  state: 'provider_accepted', providerReference: '7777777/4444444',
  url: 'https://discord.com/channels/555555/7777777/4444444', verification: null,
  manifest: {platform: 'Discord', workspaceId: 'synthetic-workspace', channelId: 'synthetic-connection', destinationId: 'synthetic-destination',
    discord: {schema: 'rafii.discord.publish.v2', target: {id: 'synthetic-destination', workspaceId: 'synthetic-workspace', connectionId: 'synthetic-connection',
      applicationId: '1234567', botUserId: '9000009', linkedUserId: '4242424', guildId: '555555', channelId: '7777777'}}}
};
const renderReceipt = value => renderToStaticMarkup(React.createElement(Receipt, {job: value}));
const withTarget = update => ({...discord, manifest: {...discord.manifest,
  discord: {...discord.manifest.discord, target: {...discord.manifest.discord.target, ...update}}}});

test('accepted Discord links its frozen message and keeps verification pending', () => {
  for (const verification of [null, {method: 'provider_lookup', at: 1800000000}]) {
    const html = renderReceipt({...discord, verification});
    assert.ok(html.includes(`href="${discord.url}"`));
    assert.ok(html.includes('Open Discord message'));
    assert.ok(html.includes('Accepted by Discord. Verification is pending. Do not resubmit.'));
    assert.ok(!html.includes('Verified ·'));
    assert.ok(!html.includes('Open verified post'));
  }
});

test('Discord provider lookup verifies only a bound receipt', () => {
  const verified = {...discord, state: 'verified', verification: {method: 'provider_lookup', at: 1800000000}};
  const html = renderReceipt(verified);
  assert.ok(html.includes(`href="${discord.url}"`));
  assert.ok(html.includes('Open Discord message'));
  assert.ok(html.includes('Verified · provider lookup'));
  assert.ok(!html.includes('Verification is pending'));
  for (const verification of [null, {method: 'manual', at: 1800000000}, {method: 'provider_lookup', at: NaN}, {method: 'provider_lookup', at: 1e20}]) {
    const unverified = renderReceipt({...verified, verification});
    assert.ok(!unverified.includes('Verified ·'));
  }
  const mismatch = renderReceipt({...verified, providerReference: '7777777/9999999'});
  assert.ok(!mismatch.includes('<a '));
  assert.ok(!mismatch.includes('Verified ·'));
});

test('Discord never links a missing, legacy or foreign frozen authorization', () => {
  const invalid = [
    {...discord, manifest: {...discord.manifest, discord: undefined}},
    {...discord, manifest: {...discord.manifest, discord: {...discord.manifest.discord, schema: 'legacy'}}},
    {...discord, manifest: {...discord.manifest, discord: {...discord.manifest.discord, target: undefined}}},
    withTarget({id: 'other-destination'}), withTarget({id: ''}),
    withTarget({workspaceId: 'other-workspace'}), withTarget({connectionId: 'other-connection'}),
    withTarget({guildId: '666666'}), withTarget({channelId: '8888888'})
  ];
  for (const value of invalid) assert.ok(!renderReceipt(value).includes('<a '), JSON.stringify(value));
});

test('Discord rejects unsafe URLs and every destination or message mismatch', () => {
  const path = '/channels/555555/7777777/4444444';
  const urls = [
    `http://discord.com${path}`, `javascript:alert(1)`, `https://evil.test${path}`,
    `https://discord.com.evil.test${path}`, `https://www.discord.com${path}`,
    `https://discord.com@evil.test${path}`, `https://user:password@discord.com${path}`,
    `https://discord.com:443${path}`, `https://discord.com:8443${path}`,
    `${discord.url}?x=1`, `${discord.url}#message`, `${discord.url}?`, `${discord.url}#`, `${discord.url}/`,
    'https://discord.com/channels/666666/7777777/4444444',
    'https://discord.com/channels/555555/8888888/4444444',
    'https://discord.com/channels/555555/7777777/9999999',
    'https://discord.com/channels/555555/7777777/%34444444'
  ];
  for (const url of urls) assert.ok(!renderReceipt({...discord, url}).includes('<a '), url);
  for (const providerReference of [undefined, '', '4444444', '8888888/4444444', '7777777/9999999', '7777777/4444444/extra', '7777777/4444444\n']) {
    assert.ok(!renderReceipt({...discord, providerReference}).includes('<a '), String(providerReference));
  }
});

test('Discord requires string Snowflakes and preserves IDs beyond number precision', () => {
  for (const guildId of ['', 'abcde', '1234', '1'.repeat(26), 555555]) assert.ok(!renderReceipt(withTarget({guildId})).includes('<a '));
  for (const channelId of ['', 'abcde', '1234', '1'.repeat(26), 7777777]) assert.ok(!renderReceipt(withTarget({channelId})).includes('<a '));
  for (const messageId of ['abcde', '1234', '1'.repeat(26)]) {
    assert.ok(!renderReceipt({...discord, providerReference: `7777777/${messageId}`, url: `https://discord.com/channels/555555/7777777/${messageId}`}).includes('<a '));
  }
  const trailingNewlineGuild = {...withTarget({guildId: '555555\n'}), url: 'https://discord.com/channels/555555\n/7777777/4444444'};
  assert.ok(!renderReceipt(trailingNewlineGuild).includes('<a '));
  const guildId = '12345678901234567890', channelId = '23456789012345678901', messageId = '34567890123456789012';
  const large = {...withTarget({guildId, channelId}), providerReference: `${channelId}/${messageId}`, url: `https://discord.com/channels/${guildId}/${channelId}/${messageId}`};
  assert.ok(renderReceipt(large).includes(`href="${large.url}"`));
});

test('Discord scheduled, failed, held and uncertain states cannot present a delivery link', () => {
  for (const state of ['scheduled', 'approved', 'failed', 'held', 'uncertain', 'submitting', 'cancelled']) {
    const html = renderReceipt({...discord, state, verification: {method: 'provider_lookup', at: 1800000000}});
    assert.ok(!html.includes('<a '), state);
    assert.ok(!html.includes('Verified ·'), state);
  }
});

test('verified Threads and LinkedIn receipt routes remain available', () => {
  for (const [platform, url] of [['Threads', 'https://www.threads.net/@synthetic/post/ABC_1/'], ['LinkedIn', 'https://www.linkedin.com/feed/update/urn:li:share:123/']]) {
    assert.ok(renderReceipt({...job, manifest: {platform}, url}).includes(`href="${url}"`));
  }
});

test('Mastodon verified links bind to the exact connected instance', () => {
  const mastodon = {...job, providerReference:'123', manifest:{platform:'Mastodon',providerAccountId:'100@mastodon.social'},url:'https://mastodon.social/@owner/123'};
  assert.ok(renderToStaticMarkup(React.createElement(component(), {job:mastodon})).includes('Open verified post'));
  for (const url of ['https://mastodon.online/@owner/123','https://mastodon.social.evil.test/@owner/123','https://mastodon.social/@owner/123?access_token=SECRET','https://mastodon.social/@owner/123#fragment'])
    assert.ok(!renderToStaticMarkup(React.createElement(component(), {job:{...mastodon,url}})).includes('<a '));
});

test('partial Mastodon threads show saved IDs without whole-thread verification', () => {
  const partial = {...job, state:'processing', verification:null, providerReference:'100', manifest:{platform:'Mastodon',providerAccountId:'10@mastodon.social',payload:{threadParts:['Second','Third']}}, progress:{version:3,stage:'thread_wait',threadReferences:['100','101'],threadVerified:0}};
  const html = renderToStaticMarkup(React.createElement(component(), {job:partial}));
  for (const text of ['2 of 3','100','101','0 read back','complete thread is not verified']) assert.ok(html.includes(text));
  assert.ok(!html.includes('<a '));
});
