/**
 * Deep links from the server (notification payloads, attention items, push data) are followed only when they are
 * same-origin relative paths inside the app. The page helper (src/lib/coworker/safe-href.ts) and the service
 * worker (public/sw.js) must agree on every case.
 *
 *   node --test web/tests/coworker-deeplink.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { APP_FALLBACK, queueDraftHref, safeAppHref } from '../src/lib/coworker/safe-href.ts';

const here = path.dirname(fileURLToPath(import.meta.url));

function swSafeUrl() {
  const context = vm.createContext({ self: { location: { origin: 'https://rafii.example' }, addEventListener: () => undefined }, URL });
  vm.runInContext(fs.readFileSync(path.join(here, '../public/sw.js'), 'utf8'), context);
  return context.rafiiSafeUrl;
}

const KEEP = [
  ['/app', '/app'],
  ['/app/weekly', '/app/weekly'],
  ['/app/weekly?week=wk_1&tab=opportunities', '/app/weekly?week=wk_1&tab=opportunities'],
  ['/app?x=1', '/app?x=1'],
  ['/app#top', '/app#top'],
  ['/app/queue?view=drafts&draft=v_1', '/app/queue?view=drafts&draft=v_1'],
  ['/app/a/./b', '/app/a/b']
];
const REFUSE = [
  'https://evil.example/app',
  'http://rafii.example/app',
  '//evil.example/app',
  '///evil.example',
  'javascript:alert(1)',
  'data:text/html,<script>alert(1)</script>',
  '/application',
  '/apps',
  '/auth/sign-in',
  '/app/../auth/sign-in',
  '/app/%2e%2e/auth',
  '/app\\evil',
  '/app\\@evil.example',
  '/app evil',
  '/app\nLocation: https://evil.example',
  '/app\u0000',
  'app/weekly',
  '',
  '/app/' + 'x'.repeat(600),
  null,
  undefined,
  42,
  { href: '/app' },
  ['/app']
];

test('keeps same-origin /app paths', () => {
  for (const [input, expected] of KEEP) assert.equal(safeAppHref(input), expected, JSON.stringify(input));
});

test('refuses everything else and falls back to /app', () => {
  for (const input of REFUSE) assert.equal(safeAppHref(input), APP_FALLBACK, JSON.stringify(input));
});

test('the service worker applies exactly the same rule', () => {
  const sw = swSafeUrl();
  for (const [input] of KEEP) assert.equal(sw(input), safeAppHref(input), JSON.stringify(input));
  for (const input of REFUSE) assert.equal(sw(input), APP_FALLBACK, JSON.stringify(input));
});

test('Queue drafts links encode the draft id and point at the drafts view', () => {
  assert.equal(queueDraftHref('v_123'), '/app/queue?view=drafts&draft=v_123');
  assert.equal(queueDraftHref('a/b?c'), '/app/queue?view=drafts&draft=a%2Fb%3Fc');
  assert.equal(queueDraftHref(null), '/app/queue?view=drafts');
  assert.equal(safeAppHref(queueDraftHref('a/b?c')), queueDraftHref('a/b?c'));
});
