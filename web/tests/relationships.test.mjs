/**
 * Relationship follow-ups, pure web model (src/lib/growth-v2/relationships-model.ts): EN + zh-Hant copy parity,
 * stage and reminder wording, due-time inputs across DST, snooze choices, honest reply routes and deep links.
 *
 *   node --test web/tests/relationships.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canonicalId,
  dueInput,
  editChanges,
  followUpCopy,
  followUpHref,
  followUpLine,
  followUpLocale,
  historyLine,
  isConflict,
  nextStates,
  pickableResults,
  platformName,
  relationshipQuery,
  replyRouteView,
  replyStatusLabel,
  snoozeChoices,
  stateTone,
  wallTime,
  zoneChoices
} from '../src/lib/growth-v2/relationships-model.ts';

const EN = followUpCopy('en');
const ZH = followUpCopy('zh-Hant');

test('the person’s language picks Traditional Chinese or English', () => {
  for (const tag of ['zh-Hant', 'zh-Hant-HK', 'zh-HK', 'zh-TW', 'yue', 'yue-Hant-HK']) assert.equal(followUpLocale(tag), 'zh-Hant', tag);
  for (const tag of ['en', 'en-GB', 'zh-Hans', 'zh-CN', 'ja', '', null, undefined]) assert.equal(followUpLocale(tag), 'en', String(tag));
  assert.equal(followUpCopy('zh-HK'), ZH);
  assert.equal(followUpCopy('fr'), EN);
});

test('both languages carry every string, with the same shape', () => {
  assert.deepEqual(Object.keys(ZH).sort(), Object.keys(EN).sort());
  for (const [key, value] of Object.entries(EN)) {
    const other = ZH[key];
    assert.equal(typeof other, typeof value, key);
    if (typeof value === 'string') {
      assert.ok(value.trim() && other.trim(), key);
      assert.notEqual(other, value, `${key} is translated`);
    } else if (typeof value === 'function') {
      assert.ok(value('X').includes('X') && other('X').includes('X'), key);
    } else {
      assert.deepEqual(Object.keys(other).sort(), Object.keys(value).sort(), key);
    }
  }
  for (const state of ['new', 'replied', 'waiting', 'follow_up_due', 'won', 'closed']) assert.ok(EN.states[state] && ZH.states[state], state);
  assert.match(EN.remindersNote, /never contact anyone/);
  assert.match(EN.wonHint, /never decides/);
});

test('stages: people choose; won and closed only reopen', () => {
  assert.deepEqual(nextStates('won'), []);
  assert.deepEqual(nextStates('closed'), []);
  assert.deepEqual(nextStates('new'), ['replied', 'waiting', 'follow_up_due', 'won', 'closed']);
  assert.ok(!nextStates('waiting').includes('waiting'));
  assert.equal(stateTone('follow_up_due'), 'warning');
  assert.equal(stateTone('won'), 'success');
  assert.equal(stateTone('closed'), 'neutral');
});

test('reminder line says exactly where the reminder stands', () => {
  const when = (epoch, zone) => `@${epoch}${zone ? `[${zone}]` : ''}`;
  const base = { due: { at: 100, timeZone: 'Asia/Hong_Kong' }, snoozedUntil: null };
  assert.equal(followUpLine({ ...base, due: null, followUp: { status: 'none', dueNow: false } }, EN, when), EN.noDue);
  assert.equal(followUpLine({ ...base, followUp: { status: 'scheduled', dueNow: false } }, EN, when), 'Follow up @100[Asia/Hong_Kong] (Asia/Hong_Kong)');
  assert.equal(followUpLine({ ...base, followUp: { status: 'due', dueNow: true, since: 90 } }, EN, when), 'Due since @90');
  assert.equal(followUpLine({ ...base, followUp: { status: 'snoozed', dueNow: false, until: 200 } }, EN, when), 'Snoozed until @200');
  assert.equal(followUpLine({ ...base, followUp: { status: 'dismissed', dueNow: false } }, ZH, when), ZH.dismissed);
  assert.equal(followUpLine({ ...base, followUp: { status: 'inactive', dueNow: false } }, ZH, when), ZH.inactive);
});

test('due input: a wall time and zone, fold only when the server asked, empty clears', () => {
  assert.equal(dueInput('', 'UTC'), null);
  assert.deepEqual(dueInput('2026-11-01T01:30', 'America/New_York'), { local: '2026-11-01T01:30', timeZone: 'America/New_York' });
  assert.deepEqual(dueInput('2026-11-01T01:30:00', 'America/New_York', 1), { local: '2026-11-01T01:30', timeZone: 'America/New_York', fold: 1 });
  assert.throws(() => dueInput('tomorrow', 'UTC'));
});

test('zone choices: valid IANA names, the record’s first, no duplicates', () => {
  const zones = zoneChoices('Asia/Hong_Kong', 'Asia/Hong_Kong', 'not a zone!', null, 'UTC');
  assert.equal(zones[0], 'Asia/Hong_Kong');
  assert.equal(new Set(zones).size, zones.length);
  assert.ok(!zones.includes('not a zone!'));
  assert.ok(zones.includes('America/New_York'));
});

test('wall times honour the day’s offset across DST', () => {
  const sunday = Date.UTC(2026, 10, 1, 12) / 1000;          // 1 Nov 2026: New York falls back at 02:00
  assert.equal(wallTime(sunday, 'America/New_York', 9, 0), Date.UTC(2026, 10, 1, 14, 0) / 1000);   // 09:00 EST
  assert.equal(wallTime(sunday - 86_400, 'America/New_York', 9, 0), Date.UTC(2026, 9, 31, 13, 0) / 1000);   // 09:00 EDT
  assert.equal(wallTime(sunday, 'Asia/Hong_Kong', 9, 0), Date.UTC(2026, 10, 1, 1, 0) / 1000);
  const spring = Date.UTC(2027, 2, 14, 12) / 1000;          // 14 Mar 2027: clocks go forward at 02:00
  assert.equal(wallTime(spring, 'America/New_York', 9, 0), Date.UTC(2027, 2, 14, 13, 0) / 1000);   // 09:00 EDT
});

test('snooze choices are in the future and the morning one lands at 09:00 local', () => {
  const now = Date.UTC(2026, 9, 1, 20, 0) / 1000;           // 04:00 next day in Hong Kong
  const choices = snoozeChoices(now, 'Asia/Hong_Kong', EN);
  assert.deepEqual(choices.map((c) => c.label), [EN.snoozeHour, EN.snoozeTomorrow, EN.snoozeWeek]);
  assert.ok(choices.every((c) => c.until > now));
  assert.equal(choices[0].until, now + 3600);
  const morning = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Hong_Kong', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(choices[1].until * 1000));
  assert.equal(morning, '09:00');
});

test('reply routes are honest: only direct is a reply; assisted links are https only', () => {
  const direct = replyRouteView({ kind: 'direct', provider: 'threads', approval: 'exact' }, EN);
  assert.deepEqual([direct.kind, direct.label, direct.href], ['direct', EN.reply, null]);
  const assisted = replyRouteView({ kind: 'assisted', provider: 'instagram', href: 'https://www.instagram.com/p/abc/', reason: 'unsupported_provider' }, EN);
  assert.deepEqual([assisted.kind, assisted.label, assisted.href], ['assisted', 'Open on Instagram · assisted', 'https://www.instagram.com/p/abc/']);
  assert.match(assisted.hint, /can't reply on Instagram/);
  for (const href of ['javascript:alert(1)', 'http://instagram.com/p/1', '//evil.example/x']) {
    assert.equal(replyRouteView({ kind: 'assisted', provider: 'instagram', href }, EN).href, null, href);
  }
  assert.equal(replyRouteView(null, ZH).kind, 'assisted');
  assert.equal(replyRouteView({ kind: 'assisted', provider: 'whatsapp', href: null, reason: 'no_thread' }, ZH).label, '在 WhatsApp 開啟 · 協助');
  assert.equal(platformName('threads'), 'Threads');
  assert.equal(platformName(null), 'the platform');
});

test('a follow-up with no conversation and no contact platform says so, in its own language', () => {
  for (const copy of [EN, ZH]) {
    for (const route of [null, { kind: 'assisted', provider: null, href: null, reason: 'no_thread' }]) {
      const view = replyRouteView(route, copy);
      assert.deepEqual([view.kind, view.label, view.hint, view.href], ['assisted', copy.noConversation, copy.noConversationHint, null]);
    }
  }
  // No English fallback inside the Traditional Chinese wording (it read "Rafii 無法在 the platform 回覆"): the only
  // Latin word left is the product name.
  const zhHint = replyRouteView({ kind: 'assisted', provider: null, href: null, reason: 'no_thread' }, ZH).hint;
  assert.doesNotMatch(zhHint, /the platform/);
  assert.match(zhHint, /^[^A-Za-z]*Rafii[^A-Za-z]*$/);
});

test('compact link ids (immune to phone-number redaction) come back as uuids', () => {
  assert.equal(canonicalId('u11111111111141118111111111111111'), '11111111-1111-4111-8111-111111111111');
  assert.equal(canonicalId('3F2A0000123445678901ABCDEFABCDEF'), '3f2a0000-1234-4567-8901-abcdefabcdef');
  assert.equal(canonicalId('3f2a0000-1234-4567-8901-abcdefabcdef'), '3f2a0000-1234-4567-8901-abcdefabcdef');
  assert.equal(canonicalId('not-an-id'), 'not-an-id');
  assert.equal(canonicalId(''), null);
  assert.equal(canonicalId(null), null);
});

test('deep links and queries carry only ids and known filters', () => {
  assert.equal(followUpHref('r 1', 't/2'), '/app/inbox?filter=follow_ups&relationship=r+1&thread=t%2F2');
  assert.equal(followUpHref('r1'), '/app/inbox?filter=follow_ups&relationship=r1');
  assert.equal(relationshipQuery({}), '');
  assert.equal(relationshipQuery({ state: 'open', due: 'due_now', limit: 1, cursor: '', thread: undefined }), '?state=open&due=due_now&limit=1');
  assert.equal(relationshipQuery({ owner: 'me', extra: 'ignored' }), '?owner=me');
  assert.ok(isConflict('revision_conflict') && isConflict('idempotency_conflict') && isConflict('suggestion_changed'));
  assert.ok(!isConflict('result_required') && !isConflict(undefined));
});

test('an edit sends only what the person changed, normalized like the server', () => {
  const start = { displayName: 'Mei', interest: 'Private lessons', nextAction: '' };
  assert.deepEqual(editChanges(start, { ...start }), {});
  assert.deepEqual(editChanges(start, { ...start, displayName: '  Mei  ' }), {});            // whitespace only: no change
  assert.deepEqual(editChanges(start, { ...start, nextAction: 'Send   the schedule ' }), { nextAction: 'Send the schedule' });
  assert.deepEqual(editChanges(start, { ...start, interest: '   ' }), { interest: null });    // emptied: cleared
  assert.deepEqual(editChanges(start, { displayName: 'Mei Chan', interest: 'Private lessons', nextAction: '' }), { displayName: 'Mei Chan' });
  // A field another member changed meanwhile is not in the body unless this person changed it too.
  assert.ok(!('interest' in editChanges(start, { ...start, displayName: 'Mei Chan' })));
});

test('won picks only the person’s own current declarations', () => {
  const items = [
    { id: 'a', status: 'active', provenance: 'user_declared', test: false },
    { id: 'b', status: 'reversed', provenance: 'user_declared', test: false },
    { id: 'c', status: 'active', provenance: 'first_party_reported', test: false },
    { id: 'd', status: 'active', provenance: 'user_declared', test: true }
  ];
  assert.deepEqual(pickableResults(items).map((item) => item.id), ['a']);
  assert.deepEqual(pickableResults([]), []);
});

test('history, reply status and platform words follow the person’s language', () => {
  assert.equal(historyLine({ kind: 'snoozed', from: null, to: null }, EN), 'Snoozed');
  assert.equal(historyLine({ kind: 'state', from: 'new', to: 'waiting' }, EN), 'Stage changed · New → Waiting on them');
  assert.equal(historyLine({ kind: 'state', from: 'new', to: 'waiting' }, ZH), '階段已變更 · 新建立 → 等待對方');
  assert.equal(historyLine({ kind: 'followup_dismissed', from: null, to: null }, ZH), '已略過提醒');
  assert.equal(historyLine({ kind: 'some_new_kind', from: null, to: null }, ZH), ZH.historyKinds.other);   // never the raw enum
  for (const kind of ['created', 'updated', 'state', 'snoozed', 'unsnoozed', 'closed', 'reopened', 'assigned', 'thread_linked', 'thread_unlinked',
                      'note_added', 'note_removed', 'due_changed', 'followup_dismissed', 'followup_restored', 'suggestion_dismissed']) {
    assert.ok(ZH.historyKinds[kind] && !/[a-z_]{3,}/.test(ZH.historyKinds[kind]), kind);
  }
  assert.equal(replyStatusLabel('verified', ZH), '已發佈');
  assert.equal(replyStatusLabel('approved', EN), 'Approved · not sent');
  assert.equal(replyStatusLabel('something_else', ZH), ZH.replyStatus.other);
  assert.equal(replyStatusLabel(undefined, EN), EN.replyStatus.other);
  assert.equal(platformName(null, ZH.thePlatform), '該平台');
  // No conversation and no contact platform: there is nowhere to open, so it says so (never "open on the platform").
  assert.equal(replyRouteView({ kind: 'assisted', provider: null, href: null, reason: 'no_thread' }, ZH).label, ZH.noConversation);
  assert.equal(replyRouteView({ kind: 'assisted', provider: 'whatsapp', href: null }, ZH).label, '在 WhatsApp 開啟 · 協助');
  assert.doesNotMatch(replyRouteView({ kind: 'assisted', provider: null, href: null }, ZH).hint, /the platform/);
  assert.equal(ZH.followUpWith('Mei'), '跟進 Mei');
  assert.match(EN.wonWithdrawnHint, /reopen it/);
});
