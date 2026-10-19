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

const NOV = Array.from({ length: 10 }, (_, i) => `2026-11-${String(i + 1).padStart(2, '0')}`);
const ZERO_STATUSES = [
  'scheduled',
  'awaiting_approval',
  'in_flight',
  'failed_held_uncertain',
  'published',
  'verified'
].map((key) => ({ key, label: key, count: 0 }));
const VERIFIED = { calendarRange: 'verified', queueSummary: 'verified' };

test('the day grid is Monday-first, pads outside days and keeps unknown counts unknown', () => {
  // 1 Nov 2026 is a Sunday: six blank cells, then the range, then blanks to the end of the week.
  const days = NOV.map((date, i) => ({ date, count: i === 2 ? 2 : i === 4 ? null : 0 }));
  const grid = M.calendarGrid(days);
  assert.equal(grid.length, 3);
  assert.ok(grid.every((week) => week.length === 7));
  assert.deepEqual(grid[0].slice(0, 6), [null, null, null, null, null, null]);
  assert.equal(grid[0][6].date, '2026-11-01');
  assert.equal(grid[0][6].day, 1);
  assert.equal(grid[1][1].count, 2);
  assert.equal(grid[1][1].label, 'Tue 3 Nov: 2 posts');
  assert.equal(grid[1][0].label, 'Mon 2 Nov: no posts');
  assert.equal(grid[1][3].count, null);
  assert.equal(grid[1][3].label, 'Thu 5 Nov: count unavailable');
  assert.equal(grid[2][1].date, '2026-11-10');
  assert.deepEqual(grid[2].slice(2), [null, null, null, null, null]);
  assert.deepEqual(M.WEEKDAY_INITIALS, ['M', 'T', 'W', 'T', 'F', 'S', 'S']);
});

test('the day grid ignores malformed days and renders nothing without days', () => {
  assert.deepEqual(M.calendarGrid(undefined), []);
  assert.deepEqual(M.calendarGrid([]), []);
  assert.deepEqual(M.calendarGrid([{ date: 'soon', count: 1 }]), []);
  assert.equal(M.calendarDayLabel('2026-11-03', 1), 'Tue 3 Nov: 1 post');
  assert.equal(M.calendarDayLabel('2026-11-03', -1), 'Tue 3 Nov: count unavailable');
});

test('zero status tiles collapse; unknown and non-zero stay visible', () => {
  const statuses = [
    { key: 'scheduled', label: 'Scheduled', count: 3 },
    { key: 'awaiting_approval', label: 'Awaiting approval', count: 0 },
    { key: 'in_flight', label: 'In flight', count: null },
    { key: 'verified', label: 'Verified live', count: 0 }
  ];
  assert.deepEqual(
    M.visibleCalendarStatuses(statuses).map((status) => status.key),
    ['scheduled', 'in_flight']
  );
});

test('an empty range is one line only when every count is a verified zero', () => {
  const empty = { total: 0, statuses: ZERO_STATUSES, sources: VERIFIED };
  assert.equal(M.calendarRangeIsEmpty(empty), true);
  assert.equal(M.calendarRangeIsEmpty({ ...empty, total: null }), false);
  assert.equal(M.calendarRangeIsEmpty({ ...empty, total: 1 }), false);
  assert.equal(
    M.calendarRangeIsEmpty({
      ...empty,
      statuses: [...ZERO_STATUSES.slice(1), { key: 'scheduled', label: 'Scheduled', count: null }]
    }),
    false
  );
  assert.equal(
    M.calendarRangeIsEmpty({ ...empty, sources: { ...VERIFIED, calendarRange: 'unverified' } }),
    false
  );
  assert.equal(M.calendarEmptyText('1–10 Nov'), 'Nothing scheduled in 1–10 Nov');
});

test('queue chips collapse zeros to one clear chip but never hide unknown counts', () => {
  const zero = { awaitingApproval: 0, needsAttention: 0, inFlight: 0, published: 0, verified: 0 };
  assert.deepEqual(M.queueChips(zero), [
    { key: 'clear', text: 'Queue clear', aria: 'Queue clear: all counts 0' }
  ]);
  const mixed = M.queueChips({ ...zero, awaitingApproval: 2, inFlight: null });
  assert.deepEqual(
    mixed.map((chip) => chip.text),
    ['2 awaiting approval', '— in flight']
  );
  assert.equal(mixed[1].aria, 'in flight: count unavailable');
  const unknown = M.queueChips({});
  assert.equal(unknown.length, 1);
  assert.equal(unknown[0].text, 'Queue —');
  assert.equal(unknown[0].aria, 'Queue counts unavailable');
});

test('the card draws the grid and collapses zeros instead of listing them', () => {
  const source = fs.readFileSync(
    path.join(WEB, 'src/features/site-agent/calendar-card.tsx'),
    'utf8'
  );
  assert.match(source, /calendarGrid\(/);
  assert.match(source, /visibleCalendarStatuses\(/);
  assert.match(source, /queueChips\(/);
  assert.doesNotMatch(source, /No stored entries in this range/);
});
