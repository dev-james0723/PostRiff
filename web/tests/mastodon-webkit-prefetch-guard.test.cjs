const { test } = require('node:test');
const assert = require('node:assert/strict');
const { isWebKitNavigationPrefetchAbort: accepts } = require('./mastodon-webkit-prefetch-guard.cjs');

const err = (message, nearHardNavigation = true, name = 'Error') => ({ message, nearHardNavigation, name });
test('only known same-origin WebKit Next RSC aborts near a hard navigation qualify', () => {
  const canonical = 'Fetch API cannot load http://127.0.0.1:4448/app/queue?_rsc=itLCS_zoLmGw38wI due to access control checks.';
  const logfile = '/127.0.0.1:4448/app/workspace/members?_rsc=3WD-QtP-z6QVZymg due to access control checks.';
  assert.equal(accepts('webkit', err(canonical)), true);
  assert.equal(accepts('webkit', err(logfile, true, 'TypeError')), true);
  // Real 2026-10-17 Depot WebKit failure uses this unusual Error.name.
  assert.equal(accepts('webkit', err(logfile, true, 'Fetch API cannot load http')), true);
  assert.equal(accepts('webkit', err(canonical, true, 'Fetch API cannot load http')), true);
  // Even with the new name, no uncorrelated or cross-origin error is masked.
  assert.equal(accepts('webkit', err(logfile, false, 'Fetch API cannot load http')), false);
  assert.equal(accepts('chromium', err(logfile, true, 'Fetch API cannot load http')), false);
  assert.equal(accepts('webkit', err('127.0.0.1:4448/app/queue?_rsc=ab1 Internal Server Error', true, 'Fetch API cannot load http')), false);

  for (const bad of [
    ['chromium', err(canonical)],
    ['webkit', err(canonical, false)],
    ['webkit', err('TypeError: Cannot read properties of undefined')],
    ['webkit', err('Fetch API cannot load https://mastodon.social/api/v1/statuses?_rsc=abc due to access control checks.')],
    ['webkit', err('Fetch API cannot load http://127.0.0.1:4348/api/workspaces?_rsc=abc due to access control checks.')],
    ['webkit', err('Fetch API cannot load http://127.0.0.1:4448/app/queue due to access control checks.')],
    ['webkit', err('Fetch API cannot load http://127.0.0.1:4448/app/queue?_rsc=abc due to access control checks.', true, 'SecurityError')],
    ['webkit', err('Fetch API cannot load http://127.0.0.1:4448/app/queue?_rsc=abc due to access control checks. '+'.'.repeat(1024))],
    ['webkit', err('Fetch API cannot load http://127.0.0.1:4448/app/queue?_rsc=abc due to access control checks. Additional error')],
  ]) assert.equal(accepts(...bad), false, JSON.stringify(bad));
});
