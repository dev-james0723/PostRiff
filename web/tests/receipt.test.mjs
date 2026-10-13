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
const job = { state:'verified', manifest:{platform:'Instagram'}, container:'555', providerReference:'999', url:'https://www.instagram.com/p/ABC/', verification:{method:'provider_lookup',at:1800000000} };
test('receipt shows persisted container, reference, verified link and provenance', () => {
  const html=renderToStaticMarkup(React.createElement(component(), {job}));
  for(const text of ['555','999','https://www.instagram.com/p/ABC/','provider lookup']) assert.ok(html.includes(text));
});
test('unverified or unsafe URL is never a verified publication link', () => {
  for (const update of [{state:'uncertain'},{url:'javascript:alert(1)'},{url:'https://evil.test/'},{verification:{method:'manual',at:1}}]) {
    const html=renderToStaticMarkup(React.createElement(component(), {job:{...job,...update}}));
    assert.ok(!html.includes('<a '));
  }
});
test('actual PostgreSQL snapshot reaches the UI without losing receipt fields', () => {
  const persisted = JSON.parse(readFileSync(new URL('../../docs/postriff-research-20260918/evidence/receipt-snapshot.json', import.meta.url),'utf8'));
  const html = renderToStaticMarkup(React.createElement(component(), {job:persisted}));
  for (const text of ['555','999','https://www.instagram.com/p/ABC/','provider lookup']) assert.ok(html.includes(text));
});

test('accepted LinkedIn receipt provides owner inspection without claiming API verification', () => {
  const accepted = {...job,state:'provider_accepted',manifest:{platform:'LinkedIn'},container:undefined,providerReference:'urn:li:share:123',url:'https://www.linkedin.com/feed/update/urn:li:share:123/',verification:null};
  const html = renderToStaticMarkup(React.createElement(component(), {job:accepted}));
  assert.ok(html.includes('Open post to confirm'));
  assert.ok(html.includes('Publication is not API verified'));
  assert.ok(html.includes('Do not resubmit'));
  assert.ok(!html.includes('Open verified post'));
  const stale = renderToStaticMarkup(React.createElement(component(), {job:{...accepted,verification:{method:'provider_lookup',at:1}}}));
  assert.ok(stale.includes('Open post to confirm'));
  assert.ok(!stale.includes('Verified ·'));
  for (const update of [{state:'uncertain'}, {url:'https://www.linkedin.com/feed/update/urn:li:share:999/'}, {url:'https://evil.test/feed/update/urn:li:share:123/'}, {providerReference:'bad'}, {manifest:{platform:'Instagram'}}]) {
    const unsafe = renderToStaticMarkup(React.createElement(component(), {job:{...accepted,...update}}));
    assert.ok(!unsafe.includes('<a '), JSON.stringify(update));
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
