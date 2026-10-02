const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

/**
 * Founder voice, notices, briefing versions and the founder workspace (CONTRACTS §8.E, §8.H): the pure modules behind
 * the founder panel's voice strip (`features/founder/agent/voice-api.ts`) and Settings (`features/founder/settings/
 * comms.ts`), plus the contracts they share with Control (blocker codes, notice events) read from the Python sources.
 * TypeScript is transpiled in place; relative imports resolve to the sibling sources; no network, no model, no browser.
 */
const SRC = path.join(__dirname, '..', 'src');
const ROOT = path.join(__dirname, '..', '..');
const cache = new Map();

function load(relative) {
  const file = path.join(SRC, relative);
  if (cache.has(file)) return cache.get(file);
  const source = fs.readFileSync(file, 'utf8');
  const { outputText } = ts.transpileModule(source, { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  cache.set(file, mod.exports);
  const localRequire = (specifier) => {
    if (specifier.startsWith('.')) {
      const resolved = path.resolve(path.dirname(file), specifier);
      const candidate = ['.ts', '.tsx', '/index.ts', '/index.tsx'].map((ext) => resolved + ext).find((name) => fs.existsSync(name));
      if (candidate) return load(path.relative(SRC, candidate));
    }
    return require(specifier);
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  cache.set(file, mod.exports);
  return mod.exports;
}

const voice = load('features/founder/agent/voice-api.ts');
const comms = load('features/founder/settings/comms.ts');
const contact = load('features/founder/settings/contact-policy.ts');
const nav = load('config/founder-nav.ts');
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), 'utf8');

const PAGE = { route: '/founder/settings', section: 'settings', mode: 'live', environment: 'local', selectedEntity: null, chart: null, period: null, filters: {}, incidentId: null, uiCapabilities: ['navigate'] };

function recorder(answer = (pathName, init) => ({ requestId: 'r1', environment: 'local', asOf: 'now', dataState: 'not_applicable', receiptIds: [], data: { path: pathName, body: init.body } })) {
  const calls = [];
  const fetch = async (pathName, init = {}) => {
    calls.push({ path: pathName, ...init });
    return answer(pathName, init);
  };
  return { calls, fetch };
}

// --- voice: availability and blockers -------------------------------------------------------------------------------------
test('voice is available only when the status says so; every blocker keeps its fixed code', () => {
  assert.deepEqual(voice.voiceBlockers({ available: true, blockers: [] }), []);
  assert.deepEqual(voice.voiceBlockers({ available: false, blockers: ['founder_voice_disabled', 'ops_workspace_not_configured'] }), ['founder_voice_disabled', 'ops_workspace_not_configured']);
  // An unreadable status or an unavailable one without codes is never shown as available.
  assert.deepEqual(voice.voiceBlockers(null), ['status_unavailable']);
  assert.deepEqual(voice.voiceBlockers({ available: false, blockers: [] }), ['status_unavailable']);
  assert.deepEqual(voice.voiceBlockers({ available: false, blockers: ['Not A Code', 42, 'agent_runtime_off'] }), ['agent_runtime_off']);
  assert.match(voice.voiceBlockerCopy('founder_voice_disabled'), /RAFII_FOUNDER_VOICE_ENABLED/);
  assert.match(voice.voiceBlockerCopy('ops_workspace_not_configured'), /Founder workspace/);
  assert.match(voice.voiceBlockerCopy('something_new'), /does not know yet/);
});

test('every blocker Control can send for founder voice has words in the panel', () => {
  const source = read('src/rafii_control/founder_voice.py');
  const codes = new Set();
  for (const re of [/blockers\.append\('([a-z_]+)'\)/g, /PolicyDisabled\('([a-z_]+)'\)/g, /return '([a-z_]+)'/g, /code='(voice_session_ended)'/g]) {
    for (const match of source.matchAll(re)) codes.add(match[1]);
  }
  for (const code of ['founder_voice_disabled', 'ops_workspace_not_configured', 'consumer_runtime_unavailable', 'agent_runtime_off', 'voice_route_unavailable', 'voice_session_ended']) {
    assert.ok(codes.has(code), `founder_voice.py no longer emits ${code}`);
  }
  for (const code of codes) assert.ok(voice.VOICE_BLOCKER_COPY[code], `no copy for voice blocker ${code}`);
});

// --- voice: the founder host the voice controller calls -----------------------------------------------------------------
test('starting a call posts the browser offer to the founder route in the panel’s data mode', async () => {
  const { calls, fetch } = recorder(() => ({ requestId: 'r1', data: { voiceSessionId: 'v1', conversationId: 'c1', sdp: 'v=0 answer' } }));
  const api = voice.createFounderVoiceApi({ fetch, mode: 'live', pageContext: () => PAGE });
  const started = await api.voiceStart('founder:live:local', { sdp: 'v=0 offer', conversationId: null, locale: undefined });
  assert.deepEqual(started, { voiceSessionId: 'v1', conversationId: 'c1', sdp: 'v=0 answer' });
  assert.equal(calls[0].path, '/agent/voice/sessions?mode=live');
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(calls[0].body, { sdp: 'v=0 offer', mode: 'live' });

  const demo = recorder();
  const demoApi = voice.createFounderVoiceApi({ fetch: demo.fetch, mode: 'demo', pageContext: () => PAGE });
  await demoApi.voiceStart('founder:demo:local', { sdp: 'v=0 offer', conversationId: 'c9', voice: 'cedar' });
  assert.equal(demo.calls[0].path, '/agent/voice/sessions?mode=demo');
  assert.deepEqual(demo.calls[0].body, { sdp: 'v=0 offer', mode: 'demo', conversationId: 'c9', voice: 'cedar' });
});

test('a spoken request is one founder turn on the call’s delegation route, with the founder page context', async () => {
  const { calls, fetch } = recorder(() => ({ requestId: 'r2', data: { conversationId: 'c1', runId: 'run1', status: 'completed', result: { answerText: 'Two incidents are open.', speakableSummary: '' }, speakable: 'Two incidents are open.' } }));
  const api = voice.createFounderVoiceApi({ fetch, mode: 'live', pageContext: () => PAGE });
  const out = await api.turn('founder:live:local', {
    message: 'x'.repeat(5000),
    idempotencyKey: 'voice:v1:d1',
    conversationId: 'c1',
    modality: 'voice',
    pageContext: { route: '/app', uiCapabilities: ['voice'] },
    timeZone: 'America/Indiana/Indianapolis',
    locale: 'en',
    delegationId: 'd1',
    voiceSessionId: 'v 1'
  });
  assert.equal(calls[0].path, '/agent/voice/sessions/v%201/delegations?mode=live');
  assert.equal(calls[0].body.delegationId, 'd1');
  assert.equal(calls[0].body.message.length, voice.MAX_SPOKEN_REQUEST);
  // The customer app's page context never reaches Control; the founder one does.
  assert.deepEqual(calls[0].body.pageContext, PAGE);
  assert.equal(calls[0].body.timeZone, 'America/Indiana/Indianapolis');
  assert.ok(!('attachments' in calls[0].body) && !('idempotencyKey' in calls[0].body) && !('modality' in calls[0].body));
  // Rafii says the server's speakable form when the turn has no spoken summary of its own.
  assert.equal(out.result.speakableSummary, 'Two incidents are open.');
  assert.equal(out.result.answerText, 'Two incidents are open.');
});

test('the spoken words are only ever the server’s', () => {
  const own = { conversationId: 'c', runId: 'r', status: 'completed', result: { answerText: 'A', speakableSummary: 'Own words.' }, speakable: 'Other words.' };
  assert.equal(voice.withSpokenSummary(own).result.speakableSummary, 'Own words.');
  const none = { conversationId: 'c', runId: 'r', status: 'completed', result: { answerText: 'A', speakableSummary: '' } };
  assert.equal(voice.withSpokenSummary(none).result.speakableSummary, '');
  const noResult = { conversationId: 'c', runId: 'r', status: 'failed', result: null, speakable: 'Words.' };
  assert.equal(voice.withSpokenSummary(noResult).result, null);
});

test('a spoken request without a voice session is refused before any request', async () => {
  const { calls, fetch } = recorder();
  const mapped = [];
  const api = voice.createFounderVoiceApi({ fetch, mode: 'live', pageContext: () => PAGE, toError: (error) => (mapped.push(error), error) });
  await assert.rejects(() => api.turn('founder:live:local', { message: 'hello', idempotencyKey: 'k', conversationId: null, modality: 'voice', pageContext: {} }), (error) => error.code === 'voice_session_missing' && error.status === 400);
  assert.equal(calls.length, 0);
  assert.equal(mapped.length, 1);
});

test('progress polling never calls Control; transcript and end go to the call’s routes', async () => {
  const { calls, fetch } = recorder();
  const api = voice.createFounderVoiceApi({ fetch, mode: 'live', pageContext: () => PAGE });
  assert.deepEqual(await api.conversationState('founder:live:local', 'c1'), { task: null, images: [], pendingApprovals: [] });
  assert.equal(calls.length, 0);
  await api.voiceTranscript('founder:live:local', 'v1', [{ role: 'user', text: 'How is MRR?', startMs: 10 }]);
  await api.voiceEnd('founder:live:local', 'v1', { usageSeconds: null, reason: 'user_ended' });
  assert.deepEqual(
    calls.map((call) => [call.path, call.body]),
    [
      ['/agent/voice/sessions/v1/transcript?mode=live', { turns: [{ role: 'user', text: 'How is MRR?', startMs: 10 }] }],
      ['/agent/voice/sessions/v1/end?mode=live', { reason: 'user_ended' }]
    ]
  );
});

test('a failed voice request reaches the controller through the error mapping', async () => {
  const refusal = Object.assign(new Error('Founder voice is off.'), { status: 409, code: 'POLICY_DISABLED', blocker: 'founder_voice_disabled' });
  const fetch = async () => {
    throw refusal;
  };
  const api = voice.createFounderVoiceApi({ fetch, mode: 'live', pageContext: () => PAGE, toError: (error) => ({ mapped: error.blocker }) });
  await assert.rejects(() => api.voiceStart('w', { sdp: 'v=0' }), (error) => error.mapped === 'founder_voice_disabled');
});

test('one call per data mode and environment', () => {
  assert.equal(voice.founderVoiceKey('live', 'production'), 'founder:live:production');
  assert.equal(voice.founderVoiceKey('demo', null), 'founder:demo:unknown');
  assert.equal(voice.unwrapData({ requestId: 'r', data: { a: 1 } }).a, 1);
  assert.deepEqual(voice.unwrapData({ a: 1 }), { a: 1 });
  assert.equal(voice.voicePath('live', 'v1', 'end'), '/agent/voice/sessions/v1/end?mode=live');
});

// --- notices: preferences, readiness and routing --------------------------------------------------------------------------
const PREFS = {
  revision: 3,
  events: { 'founder.incident_opened': { email: false, push: true }, 'founder.briefing_ready': { email: true, push: false } },
  digest: { enabled: true, hour: 7, email: false },
  quietHours: { start: 1290, end: 420, timeZone: 'Asia/Hong_Kong' },
  updatedAt: 1790000000
};

test('the notice events and blocker words match Control', () => {
  const source = read('src/rafii_control/founder_notifications.py');
  const events = /NOTICE_EVENTS = \(([^)]*)\)/.exec(source)[1].match(/'([^']+)'/g).map((item) => item.slice(1, -1));
  assert.deepEqual([...comms.NOTICE_EVENTS], events);
  const codes = new Set();
  for (const re of [/(?:out|blockers)\.append\('([a-z_]+)'\)/g, /reason = 'off', '([a-z_]+)'/g, /\('(?:off|digest)', '([a-z_]+)'\)/g, /\('([a-z_]+)' if routes/g, /blocker = '([a-z_]+)'/g]) {
    for (const match of source.matchAll(re)) codes.add(match[1]);
  }
  for (const code of ['live_delivery_disabled', 'channel_not_in_policy', 'deployment_flag_unset', 'outbox_unavailable', 'quiet_hours', 'preference_off', 'digest_disabled', 'not_routed']) {
    assert.ok(codes.has(code), `founder_notifications.py no longer emits ${code}`);
  }
  for (const code of [...codes, 'notifications_not_installed']) assert.ok(comms.NOTICE_BLOCKER_COPY[code], `no copy for notice code ${code}`);
});

test('a preferences draft starts from the saved values, and every unsaved event defaults on', () => {
  const draft = comms.draftFromPreferences(PREFS);
  assert.deepEqual(draft.events['founder.incident_opened'], { email: false, push: true });
  assert.deepEqual(draft.events['founder.source_unavailable'], { email: true, push: true });
  assert.equal(draft.digestHour, '7');
  assert.equal(draft.digestEmail, false);
  assert.equal(draft.quietStart, '21:30');
  assert.equal(draft.quietEnd, '07:00');
  assert.equal(draft.timeZone, 'Asia/Hong_Kong');
});

test('saving sends every section in the server’s shape, or names the first problem', () => {
  const draft = comms.draftFromPreferences(PREFS);
  const ok = comms.preferencesPatch(draft);
  assert.deepEqual(Object.keys(ok.patch).toSorted(), ['digest', 'events', 'quietHours']);
  assert.deepEqual(Object.keys(ok.patch.events), [...comms.NOTICE_EVENTS]);
  assert.deepEqual(ok.patch.digest, { enabled: true, hour: 7, email: false });
  assert.deepEqual(ok.patch.quietHours, { start: 1290, end: 420, timeZone: 'Asia/Hong_Kong' });
  assert.match(comms.preferencesPatch({ ...draft, digestHour: '24' }).error, /0 to 23/);
  assert.match(comms.preferencesPatch({ ...draft, digestHour: '7.5' }).error, /whole hour/);
  assert.match(comms.preferencesPatch({ ...draft, quietEnd: '25:00' }).error, /Quiet hours/);
  assert.match(comms.preferencesPatch({ ...draft, timeZone: 'Not a zone!' }).error, /IANA/);
  assert.match(comms.preferencesPatch({ ...draft, timeZone: ' ' }).error, /IANA/);
});

test('channel readiness says which gate is closed, by name', () => {
  assert.match(comms.readinessLine('inApp', { ready: true, blockers: [] }), /Always on/);
  assert.match(comms.readinessLine('email', { ready: true, blockers: [] }), /emailed now/);
  assert.equal(comms.readinessLine('email', { ready: false, blockers: ['live_delivery_disabled', 'deployment_flag_unset'] }), 'Live delivery is off in Contact & calls.');
  assert.match(comms.readinessLine('push', { ready: false, blockers: ['deployment_flag_unset'] }), /RAFII_FOUNDER_PUSH_ENABLED/);
  assert.match(comms.blockerCopy('deployment_flag_unset', 'email'), /RAFII_FOUNDER_EMAIL_ENABLED/);
  assert.equal(comms.readinessLine('push', undefined), 'Readiness unknown.');
});

test('routes and notice channels read as the server planned them', () => {
  assert.equal(comms.routeSummary({ email: 'immediate', push: 'immediate' }), 'In-app, email now, push now');
  assert.equal(comms.routeSummary({ email: 'digest', push: 'off' }), 'In-app, email in the daily digest');
  assert.equal(comms.routeSummary({ email: 'off', push: 'off' }), 'In-app only');
  const notice = {
    channels: { in_app: { mode: 'immediate', state: 'delivered' }, email: { mode: 'immediate', outbox: 'disabled' }, push: { mode: 'off', reason: 'quiet_hours' } },
    digest: { state: 'pending', id: null }
  };
  assert.deepEqual(comms.noticeChannelLines(notice), ['In-app: delivered', 'Email: due now, but no outbox here', 'Push: off (quiet_hours)', 'waiting for the next digest']);
  assert.deepEqual(comms.noticeChannelLines({ channels: {}, digest: { state: 'none' } }), ['In-app: recorded', 'Email: not recorded', 'Push: not recorded']);
  assert.equal(comms.severityStatus('critical'), 'danger');
  assert.equal(comms.severityStatus('security'), 'danger');
  assert.equal(comms.severityStatus('warning'), 'warning');
  assert.equal(comms.severityStatus('info'), 'info');
});

test('the contact policy channel list is read as the server sends it', () => {
  assert.equal(comms.channelListed(['call', 'email'], 'call'), true);
  assert.equal(comms.channelListed(['call', 'email'], 'push'), false);
  assert.equal(comms.channelListed({ phone: true }, 'call'), true);
  assert.equal(comms.channelListed({ email: 'yes' }, 'email'), false);
  assert.equal(comms.channelListed(null, 'email'), false);
});

test('contact edits preserve consent, allow configured limits and represent Unlimited explicitly', () => {
  const policy = { revision: 8, liveDeliveryEnabled: true, channels: ['call', 'email'], destinationRef: 'verified',
    quietStart: 1320, quietEnd: 480, timeZone: 'America/Indiana/Indianapolis', dailyCap: 2, concurrentCap: 1,
    eventAllowlist: ['founder.incident'], budgetUsdMicroDaily: 50_000_000 };
  const draft = contact.draftFromPolicy(policy);
  const saved = contact.policyFromDraft(policy, { ...draft, dailyCap: '5', concurrentCap: '3', budgetMode: 'unlimited' }).policy;
  assert.equal(saved.liveDeliveryEnabled, true);
  assert.deepEqual(saved.channels, policy.channels);
  assert.equal(saved.revision, 8);
  assert.equal(saved.budgetUsdMicroDaily, null);
  assert.equal(saved.dailyCap, 5); assert.equal(saved.concurrentCap, 3);
  assert.equal(contact.draftFromPolicy(saved).budgetMode, 'unlimited');
  assert.match(contact.policyFromDraft(policy, { ...draft, dailyCap: '' }).error, /whole number/);
  assert.match(contact.policyFromDraft(policy, { ...draft, concurrentCap: '11' }).error, /0 to 10/);
  assert.match(contact.policyFromDraft(policy, { ...draft, budgetUsd: '-1' }).error, /Unlimited/);
  assert.match(contact.policyFromDraft(policy, { ...draft, timeZone: 'Mars/Olympus' }).error, /IANA/);
});

// --- briefing versions ------------------------------------------------------------------------------------------------------
test('a briefing version says its basis and coverage as counted, never a made-up 0', () => {
  assert.equal(comms.reportBasis({ basis: 'metric_receipts' }), 'Receipted metric queries');
  assert.equal(comms.reportBasis({ basis: 'cron_observations', basisReason: 'query_service_unavailable' }), 'Cron observations without receipts (query service unavailable)');
  assert.equal(comms.reportBasis({}), 'Basis not recorded');
  assert.equal(comms.reportCoverage({ measured: 6, unavailable: 2, total: 8 }), '6 of 8 values available');
  assert.equal(comms.reportCoverage({ measured: 0, unavailable: 0, total: 0 }), '0 of 0 values available');
  assert.equal(comms.reportCoverage({}), 'Coverage not recorded');
  assert.equal(comms.reportCoverage(undefined), 'Coverage not recorded');
  assert.equal(comms.reportTitle({ kind: 'weekly', version: 4 }), 'Weekly briefing v4');
  assert.equal(comms.reportTitle({ kind: 'unknown', version: 1 }), 'Briefing v1');
});

// --- founder workspace and step-up ------------------------------------------------------------------------------------------
test('the founder workspace panel says where the workspace comes from', () => {
  assert.equal(comms.opsWorkspaceSummary({ workspaceId: 'w1', source: 'environment', name: null, canCreate: false }).title, 'Founder workspace set by the server');
  assert.equal(comms.opsWorkspaceSummary({ workspaceId: 'w2', source: 'settings', name: 'Rafii Ops (founder)', canCreate: false }).title, 'Rafii Ops (founder)');
  assert.equal(comms.opsWorkspaceSummary({ workspaceId: null, source: null, name: null, canCreate: true }).state, 'creatable');
  const missing = comms.opsWorkspaceSummary({ workspaceId: null, source: null, name: null, canCreate: false });
  assert.equal(missing.state, 'unavailable');
  assert.match(missing.description, /RAFII_FOUNDER_OPS_WORKSPACE_ID/);
});

test('a stale second factor asks for a fresh sign-in; other refusals keep their meaning', () => {
  assert.equal(comms.writeFailure({ status: 403, code: 'STEP_UP_REQUIRED', message: 'x' }).kind, 'step_up');
  assert.match(comms.writeFailure({ status: 403, code: 'STEP_UP_REQUIRED' }).message, /Sign in again/);
  assert.equal(comms.writeFailure({ status: 403, code: 'FORBIDDEN' }).kind, 'permission');
  assert.equal(comms.writeFailure({ status: 409, code: 'POLICY_DISABLED', blocker: 'notifications_not_installed' }).kind, 'not_installed');
  assert.deepEqual(comms.writeFailure({ status: 503, code: 'SOURCE_UNAVAILABLE', message: 'Source unavailable.' }), { kind: 'error', message: 'Source unavailable.' });
});

// --- page wiring (source checks: the browser gate covers rendering) ------------------------------------------------------
test('Settings answers to exactly the nav’s tab ids', () => {
  const view = fs.readFileSync(path.join(SRC, 'features/founder/settings/settings-view.tsx'), 'utf8');
  const triggers = [...view.matchAll(/<TabsTrigger value='([a-z-]+)'>/g)].map((match) => match[1]);
  const contents = [...view.matchAll(/<TabsContent value='([a-z-]+)'/g)].map((match) => match[1]);
  assert.deepEqual(triggers, [...nav.FOUNDER_SECTIONS.settings.tabs]);
  assert.deepEqual(contents, [...nav.FOUNDER_SECTIONS.settings.tabs]);
});

test('the founder panel keeps its accessible names and offers voice instead of a dead button', () => {
  const chat = fs.readFileSync(path.join(SRC, 'features/founder/agent/chat.tsx'), 'utf8');
  assert.match(chat, /aria-label='Ask Rafii'/);
  assert.match(chat, /aria-label='Send'/);
  assert.match(chat, /aria-label="Rafii's answer"/);
  assert.match(chat, /<FounderVoice /);
  assert.doesNotMatch(chat, /Voice: not yet connected/);
  const strip = fs.readFileSync(path.join(SRC, 'features/founder/agent/voice.tsx'), 'utf8');
  // The disabled state names each blocker by its code, and a call never outlives the panel.
  assert.match(strip, /<code className='font-mono'>\{code\}<\/code>/);
  assert.match(strip, /voiceSession\.end\(\)/);
});
