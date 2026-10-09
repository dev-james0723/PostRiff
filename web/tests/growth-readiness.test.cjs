const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { parseReadiness, readinessCopy, STATE_COPY } = require('../src/lib/feature-readiness.ts');
const {
  GROWTH_REASON_COPY,
  AUDIENCE_REASON_COPY,
  MEASUREMENT_REASON_COPY,
  requestKeyAfterError,
  requestErrorMessage,
  metricValue,
  ageLabel
} = require('../src/features/growth/readiness-copy.ts');

// Every reason code the Growth server can send (src/postriff_phase2/growth/readiness.py).
const SERVER_REASONS = [
  'growth_off', 'postmortem_off', 'audience_off', 'growth_schema_unavailable', 'analytics_connection_required',
  'analytics_permission_required', 'comments_permission_required', 'measurement_enrollment_required', 'measurement_paused',
  'measurement_off', 'no_verified_publications', 'no_comments', 'sample_below_minimum', 'growth_consent_required',
  'role_edit_required', 'growth_budget_unconfigured', 'growth_daily_limit'
];

const payload = (state, reasonCodes, nextStep = null, extra = {}) =>
  parseReadiness({ state, reasonCodes, canRead: true, canRun: false, lastSuccessfulReadAt: null, nextStep, ...extra });

test('every Growth reason the server sends has its own title and detail', () => {
  for (const code of SERVER_REASONS) {
    const copy = GROWTH_REASON_COPY[code];
    assert.ok(copy && copy.title && copy.detail, code);
  }
  for (const code of ['no_connection', 'comments_permission_required', 'no_owned_posts', 'no_comments', 'growth_consent_required']) {
    assert.ok(AUDIENCE_REASON_COPY[code]?.title && AUDIENCE_REASON_COPY[code]?.detail, code);
  }
  for (const reason of ['enrollment_open', 'already_enrolled', 'reviewed_cohort', 'self_serve_paused', 'cohort_full', 'workspace_not_eligible', 'enrollment_unavailable']) {
    assert.ok(MEASUREMENT_REASON_COPY[reason], reason);
  }
});

test('outages, spending limits and admission never ask anyone to reconnect', () => {
  for (const code of ['growth_schema_unavailable', 'growth_budget_unconfigured', 'growth_daily_limit', 'measurement_paused',
    'measurement_enrollment_required', 'measurement_off', 'growth_off', 'postmortem_off', 'audience_off', 'sample_below_minimum']) {
    const copy = GROWTH_REASON_COPY[code];
    assert.doesNotMatch(copy.title + ' ' + copy.detail, /reconnect/i, code);
  }
  for (const text of Object.values(MEASUREMENT_REASON_COPY)) assert.doesNotMatch(text, /reconnect/i);
  const outage = payload('temporarily_unavailable', ['growth_schema_unavailable'], { kind: 'wait' }, { canRead: false });
  const copy = readinessCopy(outage, GROWTH_REASON_COPY);
  assert.equal(copy.title, GROWTH_REASON_COPY.growth_schema_unavailable.title);
  assert.equal(copy.action, 'Check back later');
  assert.doesNotMatch(copy.title + copy.detail + copy.action, /reconnect|connect an account/i);
});

test('each readiness state renders a non-empty title and the right next step for owners and everyone else', () => {
  const cases = [
    ['feature_disabled', ['growth_off'], null, ''],
    ['not_entitled', ['measurement_paused'], null, ''],
    ['setup_required', ['analytics_connection_required'], { kind: 'connect', href: '/app/channels' }, 'Connect an account'],
    ['setup_required', ['growth_consent_required'], { kind: 'consent', href: '/app/growth?view=results&permissions=true' }, 'Review and allow'],
    ['setup_required', ['growth_consent_required'], { kind: 'contact_owner' }, 'Ask the workspace owner'],
    ['setup_required', ['measurement_enrollment_required'], { kind: 'consent', href: '/app/growth#growth-measurement' }, 'Review and allow'],
    ['temporarily_unavailable', ['growth_budget_unconfigured'], { kind: 'wait' }, 'Check back later'],
    ['insufficient_data', ['no_verified_publications'], null, ''],
    ['insufficient_data', ['sample_below_minimum'], null, '']
  ];
  for (const [state, reasons, step, action] of cases) {
    const parsed = payload(state, reasons, step);
    assert.ok(parsed, `${state} ${reasons} must be a valid payload`);
    const copy = readinessCopy(parsed, GROWTH_REASON_COPY);
    assert.ok(copy.title.length > 0 && copy.detail.length > 0, state);
    assert.equal(copy.action, action, `${state} ${reasons}`);
    assert.notEqual(copy.title, STATE_COPY[state].title, 'Growth keeps its own reason copy');
  }
});

test('a failed run rotates the request key; an uncertain or in-flight one keeps it so nothing is paid twice', () => {
  const key = 'stable-request-key-123';
  for (const code of ['growth_request_failed', 'growth_key_conflict', 'growth_input_changed']) {
    assert.equal(requestKeyAfterError(key, { status: 409, code }), null, code);
  }
  for (const code of ['growth_request_unknown', 'growth_request_pending', 'growth_daily_limit', 'growth_budget_unconfigured', undefined]) {
    assert.equal(requestKeyAfterError(key, { status: code ? 409 : 0, code }), key, String(code));
  }
  assert.equal(requestKeyAfterError(key, new TypeError('network')), key);
  assert.equal(requestKeyAfterError(key, null), key);
  assert.match(requestErrorMessage({ code: 'growth_request_unknown' }, 'x'), /uncertain.*Nothing was sent again/);
  assert.match(requestErrorMessage({ code: 'growth_request_failed' }, 'x'), /try again/i);
  assert.equal(requestErrorMessage(new Error('Plain message'), 'x'), 'Plain message');
  assert.equal(requestErrorMessage(undefined, 'Fallback'), 'Fallback');
});

test('a measured zero is 0 and a reading that was never taken is a dash', () => {
  assert.equal(metricValue(0), '0');
  assert.equal(metricValue(null), '—');
  assert.equal(metricValue(undefined), '—');
  assert.equal(metricValue(Number.NaN), '—');
  assert.equal(ageLabel(1399), '23 minutes');
  assert.equal(ageLabel(20), '1 minute');
  assert.equal(ageLabel(5 * 3600), '5 hours');
  assert.equal(ageLabel(9 * 86400), '9 days');
  assert.equal(ageLabel(null), null);
});

test('no Growth screen still says it is "not enabled here yet"', () => {
  const dir = path.resolve(__dirname, '../src/features/growth');
  for (const file of fs.readdirSync(dir).filter((f) => /\.(tsx?|css)$/.test(f))) {
    assert.doesNotMatch(fs.readFileSync(path.join(dir, file), 'utf8'), /not enabled here yet/i, file);
  }
});
