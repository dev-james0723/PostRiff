/**
 * Founder actions in the browser (CONTRACTS §8.F): the routes and bodies the confirm dialog sends match the server's
 * registered routes, every refusal the server can answer has fixed copy (never a server sentence), Demo and missing
 * capabilities disable the actions with a reason, a block needs the typed word, and the dialog keeps the a11y and
 * Live-only rules. `model.ts` is transpiled in place, as the pages load it.
 *
 *   node --test web/tests/founder-actions.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const ROOT = path.join(__dirname, '..', '..');
const SRC = path.join(__dirname, '..', 'src');
const ACTIONS = path.join(SRC, 'features', 'founder', 'actions');
const cache = new Map();

function load(relative) {
  const file = path.join(SRC, relative);
  if (cache.has(file)) return cache.get(file);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  cache.set(file, mod.exports);
  const localRequire = (specifier) => {
    if (specifier.startsWith('.')) {
      const resolved = path.resolve(path.dirname(file), specifier);
      const candidate = ['.ts', '.tsx', '/index.ts'].map((ext) => resolved + ext).find((name) => fs.existsSync(name));
      if (candidate) return load(path.relative(SRC, candidate));
    }
    return require(specifier);
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  cache.set(file, mod.exports);
  return mod.exports;
}

const model = load('features/founder/actions/model.ts');
const SERVER = fs.readFileSync(path.join(ROOT, 'src', 'rafii_control', 'founder_actions.py'), 'utf8');
const CONSUMER = fs.readFileSync(path.join(ROOT, 'src', 'postriff_phase2', 'operator_actions.py'), 'utf8');
const source = (name) => fs.readFileSync(path.join(ACTIONS, name), 'utf8');

const WS = '20000000-0000-4000-8000-000000000001';
const RES = '40000000-0000-4000-8000-000000000001';
const USER = '30000000-0000-4000-8000-000000000001';
const GRANT = '50000000-0000-4000-8000-000000000001';

/** `http.register_route('POST', r'…', …, 'founder_actions', '<handler>', …)` → {handler: RegExp}. */
function serverRoutes() {
  const routes = {};
  const pattern = /http\.register_route\('(GET|POST)', r'([^']+)'(?: \+ _ID_PATH \+ r'([^']+)')?, '([a-z.]+)', 'founder_actions', '([a-z_]+)'/g;
  const idPath = /_ID_PATH = '([^']+)'/.exec(SERVER)[1];
  for (const match of SERVER.matchAll(pattern)) {
    const regex = match[3] === undefined ? match[2] : match[2] + idPath + match[3];
    routes[match[5]] = { method: match[1], regex: new RegExp(`^${regex}$`), capability: match[4] };
  }
  return routes;
}

test('every preview and confirm path is a registered Live route with the action capability', () => {
  const routes = serverRoutes();
  const strip = (value) => {
    assert.ok(value.endsWith('?mode=live'), `${value} names Live explicitly`);
    return value.slice(0, -'?mode=live'.length);
  };
  const cases = [
    ['reconcile', 'reconcile_preview', 'reconcile_confirm', ''],
    ['credits_adjust', 'credits_preview', 'credits_confirm', ''],
    ['account_block', 'block_preview', 'block_confirm', USER],
    ['account_unblock', 'unblock_preview', 'unblock_confirm', USER]
  ];
  for (const [kind, preview, confirm, target] of cases) {
    assert.match(strip(model.previewPath(kind, target)), routes[preview].regex, kind);
    assert.match(strip(model.confirmPath({ kind, targetId: target })), routes[confirm].regex, kind);
    assert.equal(routes[preview].capability, model.CAPABILITY[kind]);
    assert.equal(routes[confirm].capability, model.CAPABILITY[kind]);
  }
  assert.match(strip(model.previewPath('refund_intent')), routes.refund_preview.regex);
  assert.equal(routes.refund_preview.capability, 'refunds.prepare');
  assert.equal(model.confirmPath({ kind: 'refund_intent', targetId: '' }), null, 'a refund intent has no confirm route');
  assert.equal(routes.list_actions.method, 'GET');
  assert.equal(routes.list_actions.capability, 'audit.read');
});

test('request bodies carry exactly the fields the server validates', () => {
  const reconcile = model.reconcileRequest({ workspaceId: WS, reservationId: RES, outcome: 'failed', actualText: '0.0042', evidence: ' gateway req 3f2a91 ' });
  assert.equal(reconcile.ok, true);
  assert.deepEqual(reconcile.request.body, { workspaceId: WS, reservationId: RES, outcome: 'failed', actualUsdMicro: 4200, evidence: 'gateway req 3f2a91' });
  assert.match(SERVER, /_fields\(body, \('requestId', 'workspaceId', 'reservationId', 'outcome', 'actualUsdMicro', 'evidence'\)\)/);

  const grant = model.creditsRequest({ workspaceId: WS, operation: 'grant', creditsText: '2.5', expiresAt: '2026-11-01T00:00:00.000Z', reasonCode: 'goodwill' });
  assert.deepEqual(grant.request.body, { workspaceId: WS, operation: 'grant', milliCredits: 2500, expiresAt: '2026-11-01T00:00:00.000Z', reasonCode: 'goodwill' });
  const reverse = model.creditsRequest({ workspaceId: WS, operation: 'reverse', creditsText: '1', grantId: GRANT, reasonCode: 'billing_correction' });
  assert.deepEqual(reverse.request.body, { workspaceId: WS, operation: 'reverse', milliCredits: 1000, grantId: GRANT, reasonCode: 'billing_correction' });

  const block = model.blockRequest({ targetType: 'user', targetId: USER, reasonCode: 'abuse', approvalRef: 'ticket-1042' });
  assert.equal(block.request.path, `/actions/accounts/${USER}/block/preview?mode=live`);
  assert.deepEqual(block.request.body, { targetType: 'user', reasonCode: 'abuse', approvalRef: 'ticket-1042' });
  assert.deepEqual(model.unblockRequest({ targetType: 'workspace', targetId: WS, reasonCode: 'mistake' }).request.body, { targetType: 'workspace', reasonCode: 'mistake' });

  const refund = model.refundRequest({ workspaceId: WS, paymentIntentId: 'pi_fixture0001', amountText: '12.50', currency: 'USD', reasonCode: 'requested_by_customer' });
  assert.deepEqual(refund.request.body, { workspaceId: WS, paymentIntentId: 'pi_fixture0001', amountMinor: 1250, currency: 'usd', reasonCode: 'requested_by_customer' });

  // Incomplete or unsafe input never becomes a request; each says what is missing.
  for (const check of [
    model.reconcileRequest({ workspaceId: WS, reservationId: RES, outcome: 'failed', actualText: '0.1234567', evidence: 'x' }),
    model.reconcileRequest({ workspaceId: WS, reservationId: RES, outcome: 'failed', actualText: '1', evidence: 'mail me at a@b.c' }),
    model.reconcileRequest({ workspaceId: 'ws-1', reservationId: RES, outcome: 'failed', actualText: '1', evidence: 'ref' }),
    model.creditsRequest({ workspaceId: WS, operation: 'grant', creditsText: '0.05', expiresAt: 'x', reasonCode: 'goodwill' }),
    model.creditsRequest({ workspaceId: WS, operation: 'grant', creditsText: '1', reasonCode: 'goodwill' }),
    model.blockRequest({ targetType: 'user', targetId: USER, reasonCode: 'abuse', approvalRef: 'free text with spaces' }),
    model.refundRequest({ workspaceId: WS, paymentIntentId: 'pi_1', amountText: '1.234', currency: 'usd', reasonCode: 'other' })
  ]) {
    assert.equal(check.ok, false);
    assert.ok(check.reason.length > 10);
  }
});

test('inputs parse to the integers the server takes, without float rounding', () => {
  assert.equal(model.parseUsdMicro('0.0123'), 12300);
  assert.equal(model.parseUsdMicro('100'), 100_000_000);
  assert.equal(model.parseUsdMicro('100.000001'), null);
  assert.equal(model.parseUsdMicro('-1'), null);
  assert.equal(model.parseCreditsMilli('2.5'), 2500);
  assert.equal(model.parseCreditsMilli('50000'), 50_000_000);
  assert.equal(model.parseCreditsMilli('0.05'), null);
  assert.equal(model.parseMinor('12.5'), 1250);
  assert.equal(model.parseMinor('0.1'), 10);
  assert.equal(model.parseMinor('abc'), null);
  assert.equal(model.grantExpiry(30, new Date('2026-10-01T00:00:00Z')), '2026-10-31T00:00:00.000Z');
});

test('a block needs the typed word; only a block sends it', () => {
  const action = { kind: 'account_block', previewId: 'p1', revision: '0123456789abcdef' };
  assert.deepEqual(model.confirmBody(action, 'r1', 'BLOCK'), { previewId: 'p1', revision: '0123456789abcdef', requestId: 'r1', confirmation: 'BLOCK' });
  assert.deepEqual(model.confirmBody({ ...action, kind: 'reconcile' }, 'r1', 'BLOCK'), { previewId: 'p1', revision: '0123456789abcdef', requestId: 'r1' });
  assert.equal(model.typedConfirmationOk('account_block', 'block'), false);
  assert.equal(model.typedConfirmationOk('account_block', ' BLOCK '), true);
  assert.equal(model.typedConfirmationOk('credits_adjust', ''), true);
  assert.match(SERVER, /TYPED_BLOCK = 'BLOCK'/);
});

test('Demo, a missing capability and credits off disable an action with a reason', () => {
  const all = ['usage.reconcile', 'credits.adjust', 'accounts.block', 'refunds.prepare', 'audit.read'];
  assert.equal(model.unavailableReason({ kind: 'account_block', mode: 'demo', capabilities: all }), model.DEMO_REASON);
  assert.match(model.unavailableReason({ kind: 'reconcile', mode: 'live', capabilities: ['control.read'] }), /usage\.reconcile/);
  assert.equal(model.unavailableReason({ kind: 'credits_adjust', mode: 'live', capabilities: all, policies: { creditsEnabled: false } }), model.BLOCKER_COPY.credits_not_enabled);
  assert.equal(model.unavailableReason({ kind: 'credits_adjust', mode: 'live', capabilities: all, policies: { creditsEnabled: null } }), null, 'unknown: the preview answers for itself');
  assert.equal(model.unavailableReason({ kind: 'refund_intent', mode: 'live', capabilities: all }), null);
});

test('every refusal code the server can answer has fixed copy', () => {
  const codes = new Set();
  for (const pattern of [/_invalid\('([a-z_]+)'/g, /_uuid\([^()]*(?:\([^()]*\))?[^()]*, '([a-z_]+)'\)/g, /ActionError\('[A-Z_]+', \d+, '([a-z_]+)'\)/g, /ActionError\(code, (?:\d+|409 if stale else 404), '([a-z_]+)'\)/g, /blocker='([a-z_]+)'/g, /_from_alpha\(error, '([a-z_]+)'\)/g]) {
    for (const match of SERVER.matchAll(pattern)) codes.add(match[1]);
  }
  for (const match of CONSUMER.matchAll(/"refused": "([a-z_]+)"/g)) codes.add(match[1]);
  for (const match of CONSUMER.matchAll(/return \{"refused": "workspace_not_found" if error\.status == 404 else "([a-z_]+)"\}/g)) codes.add(match[1]);
  codes.add('workspace_not_found');
  assert.ok(codes.size > 25, `found ${codes.size} codes`);
  const missing = [...codes].filter((code) => !(code in model.BLOCKER_COPY));
  assert.deepEqual(missing, []);
  assert.match(model.BLOCKER_COPY.credits_not_enabled, /Credits are not enabled/);
  assert.match(model.BLOCKER_COPY.refund_policy_not_decided, /refund policy has not been decided/);
});

/** Stands in for the founder client's FounderApiError: fixed copy, status, code and blocker. */
function apiError(status, code, blocker, message = 'Fixed client copy.') {
  return Object.assign(new Error(message), { name: 'FounderApiError', status, code, blocker });
}

test('failures become fixed copy: step-up, policy, stale preview, unknown outcome, never a server sentence', () => {
  const stepUp = model.actionFailure(apiError(403, 'STEP_UP_REQUIRED'));
  assert.equal(stepUp.stepUp, true);
  assert.match(stepUp.description, /Sign in again/);
  const credits = model.actionFailure(apiError(409, 'POLICY_DISABLED', 'credits_not_enabled'));
  assert.equal(credits.title, 'Switched off by policy');
  assert.equal(credits.description, model.BLOCKER_COPY.credits_not_enabled);
  assert.equal(model.actionFailure(apiError(409, 'POLICY_DISABLED', 'refund_policy_not_decided')).description, model.BLOCKER_COPY.refund_policy_not_decided);
  const expired = model.actionFailure(apiError(409, 'STALE_PREVIEW', 'preview_expired'));
  assert.equal(expired.previewAgain, true);
  assert.match(expired.description, /expired after 5 minutes/);
  const moved = model.actionFailure(apiError(409, 'STALE_PREVIEW', 'target_changed'));
  assert.equal(moved.previewAgain, true);
  const unknown = model.actionFailure(apiError(503, 'SOURCE_UNAVAILABLE', 'outcome_unknown_retry_same_request'));
  assert.equal(unknown.retrySame, true);
  assert.equal(model.actionFailure(apiError(409, 'IDEMPOTENCY_CONFLICT', 'request_id_used')).previewAgain, true);
  assert.match(model.actionFailure(apiError(429, 'RATE_LIMITED')).description, /ten a minute/);
  // A non-client error never shows its own text.
  const foreign = model.actionFailure(new Error('psql: relation does not exist'));
  assert.doesNotMatch(foreign.description, /psql/);
  const unmapped = model.actionFailure(apiError(400, 'VALIDATION_FAILED', 'some_new_code', 'The request could not be verified. Reload and retry.'));
  assert.equal(unmapped.description, 'The request could not be verified. Reload and retry.');
});

test('the active block of a person or of one of their workspaces is found', () => {
  const blocks = [
    { blockId: 'b1', userId: null, workspaceId: WS, reasonCode: 'spam', blockedAt: '2026-10-01T00:00:00Z' },
    { blockId: 'b2', userId: USER, workspaceId: null, reasonCode: 'abuse', blockedAt: '2026-10-01T00:00:00Z' }
  ];
  assert.equal(model.activeBlockFor(blocks, USER, [WS]).blockId, 'b2');
  assert.equal(model.activeBlockFor(blocks, 'someone-else', [WS]).blockId, 'b1');
  assert.equal(model.activeBlockFor(blocks, 'someone-else', []), null);
});

test('the preview facts are written, not computed', () => {
  assert.equal(model.factText('estimatedUsdMicro', 5000), '$0.0050');
  assert.equal(model.factText('availableMilliCredits', 15000), '15 credits');
  assert.equal(model.factText('paidMinor', 1500, { currency: 'usd' }), '$15.00');
  assert.equal(model.factText('customerCharged', false), 'No');
  assert.equal(model.factText('frozenWorkspaceIds', [WS]), WS);
  assert.equal(model.factText('frozenWorkspaceIds', []), 'None');
  assert.equal(model.factText('reasonCode', 'appeal_granted'), 'appeal granted');
  assert.equal(model.factText('lot', null), 'Not recorded');
  assert.equal(model.factText('wallet', { availableMilliCredits: 1 }), null, 'a nested object is its own list');
  assert.equal(model.factLabel('apiTokensRefused'), 'API tokens refused');
  assert.equal(model.factLabel('someNewKey'), 'Some new key');
});

test('the dialog is named, returns focus, stays Live-only and sends only through the founder client', () => {
  const files = fs.readdirSync(ACTIONS).filter((name) => /\.(ts|tsx)$/.test(name));
  for (const name of files) {
    const text = source(name);
    assert.doesNotMatch(text, /dangerouslySetInnerHTML/, name);
    assert.doesNotMatch(text, /\bfetch\(/, `${name} sends through founderFetch only`);
    assert.doesNotMatch(text, /finalFocus=\{false\}|initialFocus=\{false\}/, `${name} keeps Base UI focus return`);
    assert.doesNotMatch(text, /mode=demo/, `${name} never writes to Demo`);
    assert.doesNotMatch(text, /autoFocus/, name);
  }
  const dialog = source('confirm-action-dialog.tsx');
  assert.match(dialog, /<RafiiDialogHeader eyebrow=\{KIND_LABEL\[kind\]\} title=\{title\}/, 'the dialog is named by its title');
  assert.match(dialog, /Sign in again/);
  assert.match(dialog, /typedConfirmationOk\(kind, typed\)/);
  const customer = source('customer-actions.tsx');
  assert.match(customer, /aria-describedby=\{blockReason \? reasonsId : undefined\}/, 'a disabled action points at its reason');
  const sheet = fs.readFileSync(path.join(SRC, 'features', 'founder', 'customers', 'customer-sheet.tsx'), 'utf8');
  assert.match(sheet, /<CustomerActions key=\{customer\.id\} customerId=\{customer\.id\}/);
  const api = source('api.ts');
  assert.match(api, /scope\.mode === 'live' && scope\.capabilities\.includes\('audit\.read'\)/, 'the listing is requested only when it can succeed');
  const index = source('index.ts');
  for (const name of ['ConfirmActionDialog', 'CustomerActions', 'useReconcileAction', 'FounderActionsLog']) assert.match(index, new RegExp(`\\b${name}\\b`));
});
