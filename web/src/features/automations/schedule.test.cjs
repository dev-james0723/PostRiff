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
