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
    for (const key of ['accessClosed', 'capacityReached', 'rateDelayed', 'coordinatorUnavailable', 'scheduleTiming']) {
      assert.ok(typeof packs[locale][key] === 'string' && packs[locale][key].trim(), `${locale}:${key}`);
    }
  }
  assert.notEqual(packs['zh-Hant'].accessClosed, packs.en.accessClosed);
  assert.notEqual(packs['zh-Hans'].capacityReached, packs.en.capacityReached);
  assert.notEqual(packs['zh-Hant'].rateDelayed, packs.en.rateDelayed);
  assert.notEqual(packs['zh-Hans'].coordinatorUnavailable, packs.en.coordinatorUnavailable);
});

test('no refusal promises a waitlist or a date that nothing records, and none shows operator wording', () => {
  const packs = JSON.parse(read('src/lib/channels/discord-copy.json'));
  for (const copy of Object.values(packs)) {
    for (const key of ['accessClosed', 'capacityReached', 'rateDelayed', 'coordinatorUnavailable']) {
      assert.doesNotMatch(copy[key], /rate policy|coordinat|reviewed|SafetyPolicy|503|429/i, key);
      assert.doesNotMatch(copy[key], /waitlist|等候名單|等候名单|soon|即將|即将/i, key);
    }
  }
});

test('one helper maps every launch refusal code to the localized copy, and both connect views use it', () => {
  const helper = read('src/lib/channels/discord-refusal.ts');
  assert.match(helper, /discord_access_closed[\s\S]{0,80}copy\.accessClosed/);
  assert.match(helper, /discord_capacity_reached[\s\S]{0,80}copy\.capacityReached/);
  assert.match(helper, /discord_rate_delayed[\s\S]{0,80}copy\.rateDelayed/);
  assert.match(helper, /discord_rate_coordinator_unavailable[\s\S]{0,80}copy\.coordinatorUnavailable/);
  const sheet = read('src/features/channels/connect-sheet.tsx');
  assert.match(sheet, /provider\.discordAccess\?\.status === 'closed' \? dc\.accessClosed/);
  assert.match(sheet, /err instanceof ApiError \? discordRefusal\(err, dc\)/);
  assert.match(read('src/features/channels/connect-return.tsx'), /provider === 'discord' \? discordRefusal\(err, dc\)/);
});

test('the provider type carries the per-workspace access verdict', () => {
  assert.match(read('src/lib/api/types.ts'), /discordAccess\?: \{ status: 'open' \| 'closed'/);
});

test('the schedule dialog tells the person that posts due in the same minute can arrive late', () => {
  assert.match(read('src/features/queue/schedule-dialog.tsx'), /data-discord-timing>\{discordUiCopy\.scheduleTiming\}/);
});
