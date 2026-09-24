const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load() {
  const file = path.join(__dirname, 'schedule.ts');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
const S = load();
const iso = (ms, zone) => new Intl.DateTimeFormat('en-CA', { timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'shortOffset' }).format(new Date(ms));

// The same cases as tests/test_postriff_campaigns.py, so the preview matches the server.
test('several weekdays: earliest next day, then in order (Tuesday 3 March 2026, 12:00 UTC)', () => {
  const after = Date.UTC(2026, 2, 3, 12);
  const runs = S.nextRuns({ weekdays: ['Wednesday', 'Monday'], localTime: '09:00', timeZone: 'Asia/Hong_Kong' }, after, 3);
  assert.deepEqual(runs.map((ms) => new Date(ms).toISOString()), ['2026-03-04T01:00:00.000Z', '2026-03-09T01:00:00.000Z', '2026-03-11T01:00:00.000Z']);
  assert.equal(new Date(S.nextRun({ weekday: 'Monday', localTime: '09:00', timeZone: 'Asia/Hong_Kong' }, after)).toISOString(), '2026-03-09T01:00:00.000Z');
});

test('a run exactly at "now" moves to the following week; one second later too', () => {
  const at = Date.UTC(2026, 2, 9, 1); // Monday 09:00 in Hong Kong
  const schedule = { weekdays: ['Monday'], localTime: '09:00', timeZone: 'Asia/Hong_Kong' };
  assert.equal(new Date(S.nextRun(schedule, at)).toISOString(), '2026-03-16T01:00:00.000Z');
  assert.equal(new Date(S.nextRun(schedule, at - 1000)).toISOString(), '2026-03-09T01:00:00.000Z');
});

test('spring gap moves to the next valid minute; autumn repeat uses the earlier offset', () => {
  const spring = S.nextRun({ weekdays: ['Sunday'], localTime: '02:30', timeZone: 'America/New_York' }, Date.UTC(2026, 2, 7, 12));
  assert.match(iso(spring, 'America/New_York'), /2026-03-08, 03:00 GMT-4/);
  const autumn = S.nextRun({ weekdays: ['Sunday'], localTime: '01:30', timeZone: 'America/New_York' }, Date.UTC(2026, 9, 31, 12));
  assert.equal(new Date(autumn).toISOString(), '2026-11-01T05:30:00.000Z');
});

test('incomplete schedules have no next run', () => {
  assert.equal(S.nextRun({ weekdays: [], localTime: '09:00', timeZone: 'UTC' }, 0), null);
  assert.equal(S.nextRun({ weekdays: ['Monday'], localTime: '25:00', timeZone: 'UTC' }, 0), null);
  assert.equal(S.nextRun({ weekdays: ['Monday'], localTime: '09:00', timeZone: 'Not/AZone' }, 0), null);
  assert.deepEqual(S.nextRuns({ weekdays: [], localTime: '09:00', timeZone: 'UTC' }, 0), []);
});

test('labels: days, zones, budget and plain run wording', () => {
  assert.equal(S.daysLabel({ weekdays: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] }), 'Weekdays');
  assert.equal(S.daysLabel({ weekdays: ['Sunday', 'Saturday'] }), 'Weekends');
  assert.equal(S.daysLabel({ weekdays: ['monday'] }), 'Mondays');
  assert.equal(S.daysLabel({ weekdays: ['Friday', 'Monday', 'Wednesday'] }), 'Mon, Wed and Fri');
  assert.equal(S.daysLabel({ weekday: 'Monday' }), 'Mondays');
  assert.equal(S.zoneLabel('America/Argentina/Buenos_Aires'), 'Buenos Aires');
  assert.equal(S.weeklyCeilingMicro(250_000, { weekdays: ['Monday', 'Thursday'] }), 500_000);
  assert.equal(S.usd(500_000), '$0.50');
  assert.equal(S.usd(20_000), '$0.020');
  assert.equal(S.runText({ state: 'held', reason: 'destinations_unavailable' }).detail, 'None of its accounts is connected any more.');
  assert.equal(S.runText({ state: 'cancelled', reason: 'definition_changed' }).detail, 'The automation was edited before this run.');
  assert.equal(S.statusText({ status: 'paused', pauseReason: 'destinations_unavailable' }).needsEdit, true);
  assert.equal(S.statusText({ status: 'draft' }).needsOwner, true);
  assert.deepEqual(S.missingFacts('Promote my spring recital', { date: '2026-04-18' }), ['venue']);
  assert.deepEqual(S.missingFacts('Weekly tips', {}), []);
});

// Phase 2 kinds: the same cases as ScheduleKindTests in tests/test_postriff_campaigns.py.
test('monthly: a day the month lacks runs on its last day; "last" follows the month', () => {
  const after = Date.UTC(2026, 2, 3, 12);
  const runs = S.nextRuns({ kind: 'monthly', monthDays: [31, 15], localTime: '18:00', timeZone: 'Asia/Hong_Kong' }, after, 4);
  assert.deepEqual(runs.map((ms) => iso(ms, 'Asia/Hong_Kong').slice(0, 17)), ['2026-03-15, 18:00', '2026-03-31, 18:00', '2026-04-15, 18:00', '2026-04-30, 18:00']);
  const last = S.nextRuns({ kind: 'monthly', monthDays: ['last'], localTime: '09:00', timeZone: 'UTC' }, Date.UTC(2026, 0, 31, 10), 2);
  assert.deepEqual(last.map((ms) => new Date(ms).toISOString().slice(0, 10)), ['2026-02-28', '2026-03-31']);
  assert.equal(S.monthDaysLabel({ monthDays: [15, 1] }), 'Monthly on the 1st and 15th');
  assert.equal(S.monthDaysLabel({ monthDays: ['last'] }), 'Monthly on the last day');
  assert.deepEqual(S.maxRuns({ kind: 'monthly', monthDays: [1, 15], localTime: '09:00', timeZone: 'UTC' }), { runs: 2, per: 'month' });
});

test('countdown: runs before the event in date order, then finishes', () => {
  const schedule = { kind: 'countdown', eventDate: '2026-03-10', daysBefore: [0, 7, 3, 1, 7], localTime: '10:00', timeZone: 'Asia/Hong_Kong' };
  const runs = S.nextRuns(schedule, Date.UTC(2026, 2, 3, 12), 10);
  assert.deepEqual(runs.map((ms) => iso(ms, 'Asia/Hong_Kong').slice(0, 17)), ['2026-03-07, 10:00', '2026-03-09, 10:00', '2026-03-10, 10:00']);
  assert.equal(S.nextRun(schedule, runs.at(-1) + 1000), null);
  assert.equal(S.nextRun({ ...schedule, eventDate: '2026-02-30' }, 0), null);
  assert.match(S.countdownLabel({ eventDate: '2026-03-10', daysBefore: [7, 1, 0] }, 'en-GB'), /^Countdown to 10 Mar 2026: 7, 1 days before and on the day$/);
  assert.deepEqual(S.maxRuns(schedule), { runs: 4, per: 'countdown' });
  assert.equal(S.ceilingText(250_000, schedule), '4 runs in total · at most $1.00 for the whole countdown');
  assert.equal(S.ceilingText(100_000, { weekdays: ['Monday'], localTime: '09:00', timeZone: 'UTC' }), 'up to 5 runs a month · at most $0.50 a month');
});

// Phase 3 triggers: no clock runs; labels and ceilings follow the daily limit.
test('triggers: no scheduled runs, plain labels, a daily-limit ceiling', () => {
  const idea = { kind: 'on_new_source', sourceKinds: ['idea', 'link'], maxPerDay: 3, timeZone: 'UTC' };
  const strong = { kind: 'on_strong_post', maxPerDay: 1, withinDays: 7, timeZone: 'UTC' };
  assert.equal(S.nextRun(idea, Date.UTC(2026, 2, 3)), null);
  assert.deepEqual(S.nextRuns(strong, Date.UTC(2026, 2, 3), 3), []);
  assert.equal(S.scheduleSummary(idea), 'When you add a new idea or link to Ideas · up to 3 runs a day');
  assert.equal(S.scheduleSummary(strong), 'After a post gets more replies or comments than usual (last 7 days) · up to 1 run a day');
  assert.deepEqual(S.maxRuns(idea), { runs: 93, per: 'month' });
  assert.equal(S.ceilingText(100_000, strong), 'up to 31 runs a month · at most $3.10 a month');
  assert.equal(S.isTrigger(idea), true);
  assert.equal(S.isTrigger({ weekdays: ['Monday'] }), false);
});

// Raffi orchestration (§1): a one-time date and weekly slots with a time each, saved from chat.
test('once: one run on its date, strictly after now; plain words', () => {
  const once = { kind: 'once', date: '2026-10-03', localTime: '09:00', timeZone: 'Asia/Hong_Kong' };
  assert.equal(new Date(S.nextRun(once, Date.UTC(2026, 8, 24))).toISOString(), '2026-10-03T01:00:00.000Z');
  assert.equal(S.nextRun(once, Date.UTC(2026, 9, 3, 1)), null);
  assert.deepEqual(S.nextRuns(once, Date.UTC(2026, 8, 24), 3).length, 1);
  assert.equal(S.nextRun({ ...once, date: '2026-02-30' }, 0), null);
  assert.equal(S.onceLabel(once, 'en-GB'), 'Once on Sat, 3 Oct 2026');
  assert.equal(S.scheduleSummary(once, 'en-GB'), 'Once on Sat, 3 Oct 2026 at 9:00 · Hong Kong time');
  assert.equal(S.onceLabel({}), 'Once (choose the date)');
  assert.deepEqual(S.maxRuns(once), { runs: 1, per: 'once' });
  assert.equal(S.ceilingText(250_000, once), 'one run · at most $0.25 in total');
  assert.equal(S.isFixedForm(once), true);
});

test('slots: each weekday at its own time; days sharing a time are grouped', () => {
  const slots = { weekdays: ['Monday'], localTime: '09:00', slots: [{ weekday: 'Thursday', localTime: '18:00' }, { weekday: 'Monday', localTime: '09:00' }, { weekday: 'saturday', localTime: '9:00' }], timeZone: 'Asia/Hong_Kong' };
  const runs = S.nextRuns(slots, Date.UTC(2026, 2, 3, 12), 4); // Tuesday 3 March 2026, 20:00 in Hong Kong
  assert.deepEqual(runs.map((ms) => iso(ms, 'Asia/Hong_Kong').slice(0, 17)), ['2026-03-05, 18:00', '2026-03-07, 09:00', '2026-03-09, 09:00', '2026-03-12, 18:00']);
  assert.equal(S.slotsLabel(slots, 'en-GB'), 'Mon and Sat at 9:00 and Thursdays at 18:00');
  assert.equal(S.scheduleSummary(slots, 'en-GB'), 'Mon and Sat at 9:00 and Thursdays at 18:00 · Hong Kong time');
  assert.equal(S.runsPerWeek(slots), 3);
  assert.deepEqual(S.maxRuns(slots), { runs: 15, per: 'month' });
  assert.equal(S.isFixedForm(slots), true);
  assert.equal(S.isFixedForm({ weekdays: ['Monday'], localTime: '09:00', timeZone: 'UTC' }), false);
  assert.deepEqual(S.slotsOf({ kind: 'monthly', slots: [{ weekday: 'Monday', localTime: '09:00' }] }), []);
});
