/** Source-wiring checks: the Discord launch gate and server cap reach the person in their own language. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');

test('every language pack words the gate and the capacity refusal', () => {
  const packs = JSON.parse(read('src/lib/channels/discord-copy.json'));
  for (const locale of ['en', 'zh-Hant', 'zh-Hans']) {
    for (const key of ['accessClosed', 'capacityReached']) {
      assert.ok(typeof packs[locale][key] === 'string' && packs[locale][key].trim(), `${locale}:${key}`);
    }
  }
  assert.notEqual(packs['zh-Hant'].accessClosed, packs.en.accessClosed);
  assert.notEqual(packs['zh-Hans'].capacityReached, packs.en.capacityReached);
});

test('neither refusal promises a waitlist or a date that nothing records', () => {
  const packs = JSON.parse(read('src/lib/channels/discord-copy.json'));
  for (const copy of Object.values(packs)) {
    for (const key of ['accessClosed', 'capacityReached']) {
      assert.doesNotMatch(copy[key], /waitlist|等候名單|等候名单|soon|即將|即将/i, key);
    }
  }
});

test('the connect sheet maps the refusal codes and the closed state to that copy', () => {
  const sheet = read('src/features/channels/connect-sheet.tsx');
  assert.match(sheet, /discord_access_closed[\s\S]{0,80}copy\.accessClosed/);
  assert.match(sheet, /discord_capacity_reached[\s\S]{0,80}copy\.capacityReached/);
  assert.match(sheet, /provider\.discordAccess\?\.status === 'closed' \? dc\.accessClosed/);
  assert.match(sheet, /err instanceof ApiError \? discordRefusal\(err, dc\)/);
});

test('the provider type carries the per-workspace access verdict', () => {
  assert.match(read('src/lib/api/types.ts'), /discordAccess\?: \{ status: 'open' \| 'closed'/);
});
