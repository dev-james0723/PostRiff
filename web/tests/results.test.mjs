/**
 * Business results presentation (src/features/growth/results/present.ts): sources never blend, money stays per
 * currency, unavailable is not zero, declarations are built only from what the person entered, EN + zh-Hant agree.
 *
 *   node --test web/tests/results.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  COPY,
  amountText,
  checkDeclaration,
  classView,
  countPhrase,
  currencyDigits,
  duration,
  isoToLocal,
  linkResultsText,
  localToIso,
  moneyLines,
  parseAmount,
  pickLanguage,
  problemText,
  stateSentence,
  unverifiedText
} from '../src/features/growth/results/present.ts';

const en = COPY.en;
const zh = COPY['zh-Hant'];

test('language follows the saved language: Traditional Chinese or English', () => {
  for (const tag of ['zh-Hant', 'zh-TW', 'zh-HK', 'zh-Hant-HK', 'yue']) assert.equal(pickLanguage(tag), 'zh-Hant', tag);
  for (const tag of ['en', 'en-GB', 'zh-Hans', 'zh-CN', 'ja', '', null, undefined]) assert.equal(pickLanguage(tag), 'en', String(tag));
});

test('both languages carry the same keys, so no string falls back to undefined', () => {
  const shape = (value) => (typeof value === 'object' && value !== null ? Object.fromEntries(Object.keys(value).sort().map((k) => [k, shape(value[k])])) : typeof value);
  assert.deepEqual(shape(zh), shape(en));
});

test('AC16: a source with no data reads as unavailable, never as zero', () => {
  const none = classView('first_party_reported', null, en, 'en');
  assert.equal(none.available, false);
  assert.equal(none.headline, 'No results in this period');
  assert.doesNotMatch(none.headline, /\b0\b/);
  assert.equal(classView('provider_native', null, en, 'en').headline, 'Not connected');
  assert.equal(classView('user_declared', null, zh, 'zh-Hant').headline, '這段期間沒有成果');
});

test('AC16: the three sources keep plain, different labels', () => {
  const labels = ['user_declared', 'first_party_reported', 'provider_native'].map((p) => en.classes[p]);
  assert.deepEqual(labels, ['You reported', 'Reported by your connected tools', 'Platform-reported']);
  assert.equal(new Set(labels).size, 3);
  assert.equal(new Set(Object.values(zh.classes)).size, 3);
});

test('AC16: money is one line per currency and never a cross-currency total', () => {
  const lines = moneyLines({ usd: { minor: 12000, events: 1 }, twd: { minor: 280000, events: 2 } }, 'en-US');
  assert.equal(lines.length, 2);
  assert.deepEqual(lines.map((l) => l.currency), ['twd', 'usd']);
  assert.match(lines[1].text, /\$120\.00/);
  assert.match(lines[0].text, /2,800/);
  const view = classView('user_declared', { counts: { sale: 3, lead: 2 }, money: { usd: { minor: 500, events: 1 } }, reversed: 1, unattributed: 4, associated: 1 }, en, 'en');
  assert.equal(view.headline, '2 leads · 3 sales');
  assert.deepEqual(view.notes, ['1 came through your tracking links', '4 not linked to a tracking link', '1 reversed']);
});

test('a class whose results were all reversed says so instead of showing nothing', () => {
  const view = classView('user_declared', { counts: {}, money: {}, reversed: 2, unattributed: 0, associated: 0 }, en, 'en');
  assert.equal(view.available, true);
  assert.equal(view.headline, en.allWithdrawn);
  assert.deepEqual(view.notes, ['2 reversed']);
});

test('counts use singular and plural, in a fixed order', () => {
  assert.equal(countPhrase({ sale: 1, booking: 2, newsletter_signup: 1 }, en), '2 bookings · 1 newsletter sign-up · 1 sale');
  assert.equal(countPhrase({ lead: 3 }, zh), '潛在客戶 3');
  assert.equal(countPhrase({}, en), '');
});

test('amounts become whole minor units in the currency’s own precision', () => {
  assert.equal(currencyDigits('usd'), 2);
  assert.equal(currencyDigits('jpy'), 0);
  assert.equal(parseAmount('45', 'usd'), 4500);
  assert.equal(parseAmount('45.5', 'usd'), 4550);
  assert.equal(parseAmount('1,234.56', 'usd'), 123456);
  assert.equal(parseAmount('4500', 'jpy'), 4500);
  assert.equal(parseAmount('', 'usd'), null);
  for (const bad of ['45.555', '-1', 'abc', '1e3', '45.', '4500.5']) assert.equal(parseAmount(bad, bad === '4500.5' ? 'jpy' : 'usd'), undefined, bad);
  assert.equal(amountText(4550, 'usd'), '45.50');
  assert.equal(amountText(4500, 'jpy'), '4500');
});

test('a declaration is built only from what was entered', () => {
  const iso = () => '2026-10-01T15:00:00.000Z';
  const base = { type: 'sale', occurredAt: '2026-10-01T23:00', amount: '120', currency: 'USD', quantity: '2', note: '  workshop   seat ', linkId: '', campaignRef: '' };
  const ok = checkDeclaration(base, en, iso);
  assert.deepEqual(ok, { ok: true, value: { type: 'sale', occurredAt: '2026-10-01T15:00:00.000Z', amount: { minor: 12000, currency: 'usd' }, quantity: 2,
                                           note: 'workshop seat', linkId: null, campaignRef: null } });
  const noAmount = checkDeclaration({ ...base, type: 'lead', amount: '' }, en, iso);
  assert.equal(noAmount.ok && noAmount.value.amount, null);
  const cases = [
    [{ ...base, type: 'lead' }, 'amount', en.form.amountOnlyFor],
    [{ ...base, currency: 'dollars' }, 'currency', en.form.currencyInvalid],
    [{ ...base, amount: '12.345' }, 'amount', en.form.amountInvalid],
    [{ ...base, quantity: '0' }, 'quantity', en.form.quantityInvalid],
    [{ ...base, quantity: '1.5' }, 'quantity', en.form.quantityInvalid],
    [{ ...base, occurredAt: '' }, 'occurredAt', en.form.dateInvalid],
    [{ ...base, campaignRef: 'has space' }, 'campaignRef', en.form.campaignInvalid]
  ];
  for (const [form, field, message] of cases) assert.deepEqual(checkDeclaration(form, en, iso), { ok: false, field, message }, JSON.stringify(form));
});

test('state sentences explain why numbers may change', () => {
  const sources = { errored: 0, paused: 0 };
  assert.equal(stateSentence('unavailable', true, sources, en), en.states.unavailable);
  assert.equal(stateSentence('partial', true, sources, en), en.states.open);
  assert.equal(stateSentence('partial', true, { errored: 1, paused: 0 }, en), en.states.problem);
  assert.equal(stateSentence('partial', false, { errored: 0, paused: 1 }, en), en.states.paused);
  assert.equal(stateSentence('available', false, sources, en), en.states.available);
});

test('durations, health codes and click wording', () => {
  assert.equal(duration(30, en), 'just now');
  assert.equal(duration(120, en), '2 minutes');
  assert.equal(duration(3 * 86_400 + 5, en), '3 days');
  assert.equal(duration(7200, zh), '2 小時');
  assert.equal(problemText('signature_mismatch', en), 'the signature didn’t match');
  // A code this version doesn't know reads as a plain sentence, never as the raw code.
  assert.equal(problemText('something_new', en), en.errors.unknown);
  assert.equal(problemText('something_new', zh), zh.errors.unknown);
  for (const code of ['reversal_test_mismatch', 'result_time_future', 'result_event_id_invalid', 'timestamp_outside_window', 'rate_limited', 'conflicting_payload']) {
    assert.notEqual(problemText(code, en), en.errors.unknown, code);
    assert.doesNotMatch(problemText(code, zh), /_/, code);
  }
  assert.match(en.clicksNotPeople, /not per person/);
  assert.match(en.links.note, /not per person/);
  assert.match(zh.links.note, /不代表人數/);
  assert.equal(en.links.clicks(1), '1 click');
});

test('a source never set up reads as not connected / nothing recorded, not as an empty period', () => {
  const none = { connections: { active: 0, paused: 0, removed: 0, errored: 0 }, declarations: false };
  assert.equal(classView('first_party_reported', null, en, 'en', none).headline, en.notConnected);
  assert.equal(classView('user_declared', null, en, 'en', none).headline, en.noneRecorded);
  assert.equal(classView('user_declared', null, zh, 'zh-Hant', none).headline, zh.noneRecorded);
  const used = { connections: { active: 0, paused: 0, removed: 1, errored: 0 }, declarations: true };
  assert.equal(classView('first_party_reported', null, en, 'en', used).headline, en.noResults);   // a tool was connected once
  assert.equal(classView('user_declared', null, en, 'en', used).headline, en.noResults);
  assert.equal(classView('provider_native', null, en, 'en', used).headline, en.notConnected);
  for (const view of [classView('first_party_reported', null, en, 'en', none), classView('user_declared', null, en, 'en', none)]) assert.equal(view.available, false);
});

test('a link’s results are told per source and never added together', () => {
  assert.equal(linkResultsText({}, en), null);
  assert.equal(linkResultsText(undefined, en), null);
  assert.equal(linkResultsText({ first_party_reported: 3 }, en), 'Results through this link: 3 reported by your connected tools');
  const both = linkResultsText({ first_party_reported: 1, user_declared: 2 }, en);
  assert.equal(both, 'Results through this link: 2 you reported · 1 reported by your connected tools');
  assert.doesNotMatch(both, /\b3\b/);                                   // never a blended total
  assert.equal(linkResultsText({ user_declared: 2, first_party_reported: 1 }, zh), '經由此連結的成果：你自行記錄 2 項 · 由你連接的工具回報 1 項');
});

test('unsigned deliveries are a bounded, labelled count apart from health', () => {
  assert.equal(unverifiedText(null, 'x', en), null);
  assert.equal(unverifiedText({ refused: 0, capped: false }, 'x', en), null);
  assert.match(unverifiedText({ refused: 7, capped: false }, '1 Oct', en), /^Refused 7 deliveries since 1 Oct/);
  assert.match(unverifiedText({ refused: 999, capped: true }, '1 Oct', en), /Refused 999\+ deliveries/);
  assert.match(unverifiedText({ refused: 5, capped: false }, '1 Oct', en), /can’t add results or change this connection’s status/);
  assert.match(unverifiedText({ refused: 5, capped: false }, '10月1日', zh), /已拒絕 5 個/);
});

test('the declaration form reads and writes times in the person’s zone, like the ledger', () => {
  const at = Date.UTC(2026, 9, 1, 15, 30) / 1000;   // 15:30 UTC = 23:30 in Hong Kong, 11:30 in New York (EDT)
  assert.equal(isoToLocal(at, 'Asia/Hong_Kong'), '2026-10-01T23:30');
  assert.equal(isoToLocal(at, 'America/New_York'), '2026-10-01T11:30');
  assert.equal(localToIso('2026-10-01T23:30', 'Asia/Hong_Kong'), '2026-10-01T15:30:00.000Z');
  assert.equal(localToIso('2026-10-01T11:30', 'America/New_York'), '2026-10-01T15:30:00.000Z');
  assert.equal(localToIso('2026-11-01T09:00', 'America/New_York'), '2026-11-01T14:00:00.000Z');   // after clocks go back (EST)
  for (const zone of ['Asia/Hong_Kong', 'America/New_York', 'Europe/London', 'UTC']) {
    assert.equal(localToIso(isoToLocal(at, zone), zone), new Date(at * 1000).toISOString(), zone);   // round trip
  }
  assert.equal(localToIso('not a time', 'Asia/Hong_Kong'), null);
  assert.equal(isoToLocal(at, 'Not/AZone'), isoToLocal(at));               // an unknown zone falls back to the browser's
  const ok = checkDeclaration({ type: 'lead', occurredAt: '2026-10-01T23:30', amount: '', currency: '', quantity: '1', note: '', linkId: '', campaignRef: '' },
    en, (local) => localToIso(local, 'Asia/Hong_Kong'));
  assert.equal(ok.ok && ok.value.occurredAt, '2026-10-01T15:30:00.000Z');
  assert.match(en.form.zone('Asia/Hong_Kong'), /Asia\/Hong_Kong/);
});

test('no customer-facing string hides behind implementation words or blends sources', () => {
  const text = JSON.stringify(COPY, (key, value) => (typeof value === 'function' ? value(2, 'lead') : value));
  for (const word of [/\bpayload\b/i, /\bbackend\b/i, /\bdatabase\b/i, /\bschema\b/i, /\bROI\b/, /\btotal revenue\b/i, /\bRAFII\b/]) assert.doesNotMatch(text, word);
});
