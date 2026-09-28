const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');

function load(relative) {
  const file = path.join(WEB, relative);
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}

const M = load('src/features/site-agent/calendar-card-model.ts');

test('calendar counts preserve real zero and leave unknown values unavailable', () => {
  assert.equal(M.calendarCountText(0), '0');
  assert.equal(M.calendarCountText(12), '12');
  for (const value of [null, undefined, -1, 1.5, Number.NaN, '0', false])
    assert.equal(M.calendarCountText(value), '—', String(value));
  assert.equal(M.calendarCountAria('Scheduled', null), 'Scheduled: count unavailable');
  assert.equal(M.calendarCountAria('Scheduled', 0), 'Scheduled: 0');
});

test('the six lifecycle states remain separate', () => {
  const states = [
    'scheduled',
    'awaiting_approval',
    'in_flight',
    'failed_held_uncertain',
    'published',
    'verified'
  ];
  assert.deepEqual(
    states.map((state) => M.CALENDAR_STATUS_META[state].label),
    [
      'Scheduled',
      'Awaiting approval',
      'In flight',
      'Failed / held / uncertain',
      'Published, confirming',
      'Verified live'
    ]
  );
  assert.notEqual(M.CALENDAR_STATUS_META.published.label, M.CALENDAR_STATUS_META.verified.label);
});

test('source copy distinguishes verified, unverified and unavailable queue state', () => {
  assert.equal(M.calendarSourceText('verified', 'verified'), 'Calendar verified · queue checked');
  assert.match(M.calendarSourceText('verified', 'unavailable'), /unavailable/);
  assert.match(M.calendarSourceText('unverified', 'verified'), /could not be verified/);
});

test('the calendar component exposes navigation only and no mutation controls', () => {
  const source = fs.readFileSync(
    path.join(WEB, 'src/features/site-agent/calendar-card.tsx'),
    'utf8'
  );
  assert.doesNotMatch(
    source,
    /<Button\b|useWorkspaceApi|applyProposal|ReviewApproveButton|scheduleDraft|publishNow|changeProvider/i
  );
  assert.match(source, /Open Calendar/);
  assert.match(source, /Read-only snapshot/);
});
