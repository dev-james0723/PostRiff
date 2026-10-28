import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// SC-1 (owner reply 17, 2026-10-28): the destination picker words Facebook and Business Profile exactly as the live
// build does; only the Discord branches differ. A source pin, because the component needs the app providers to render.
const source = readFileSync(new URL('../src/features/channels/destination-picker.tsx', import.meta.url), 'utf8');

test('Facebook and Business Profile picker wording equals the live build', () => {
  for (const live of [
    "'Business Profile location selected'",
    "'Rafii will post in this channel'",
    "label === 'Channel' ? 'Posting channel' : `Posting ${label}`",
    "`Rafii posts on ${platform} only in the ${label === 'Channel' ? 'channel' : label} you choose.`"
  ]) assert.ok(source.includes(live), live);
  for (const added of ['Choose Facebook Page', 'Select the Page for this connection', 'selected. Publishing requires its own permission'])
    assert.ok(!source.includes(added), added);
});

test('the workspace snapshot is refetched after a destination choice for Discord only', () => {
  const choose = source.slice(source.indexOf('async function choose'), source.indexOf('async function remove'));
  assert.ok(choose.includes("if (platform === 'Discord') void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });"));
  assert.equal(choose.split('keys.snapshot').length - 1, 1);
});
