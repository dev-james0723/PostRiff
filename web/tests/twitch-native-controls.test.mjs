import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  actionStateLabel, capabilityAvailable, capabilityGroup, canCancelAction, canPauseAction, canReconcileAction, clipDownloadHref,
  parseFields, reviewCanApprove, reviewScheduledInstant, safeDisplay, scheduledInstant, submissionSignature,
  twitchAuthorizeUrl, verificationLabel
} from '../src/features/twitch/contracts.ts';
import { createApi, ApiError, APP_GUARD_HEADER } from '../src/lib/api/client.ts';

test('Twitch scope grants and offline implementation never imply live availability', () => {
  for (const capability of [undefined, {}, { status: 'implemented_offline', liveVerified: false }, { availability: { state: 'unverified' } }]) {
    assert.equal(capabilityAvailable(capability), false);
  }
  assert.equal(capabilityAvailable({ availability: { state: 'available' } }), true);
  assert.equal(capabilityAvailable({ action: 'twitch.stream.key.get', risk: 'secret', availability: { state: 'available' } }), false);
  assert.equal(verificationLabel({ verification: 'verified', liveVerified: false }), 'Unverified');
  assert.equal(verificationLabel({ verification: 'verified', liveVerified: true }), 'Verified');
  assert.equal(verificationLabel({ verification: 'verified', liveVerified: true, availability: { state: 'blocked' } }), 'Blocked');
});

test('native controls separate stream scheduling, chat, moderation, media, money and limited analytics', () => {
  const expected = {
    'twitch.stream.get': 'channel', 'twitch.schedule.create': 'schedule', 'twitch.marker.create': 'schedule',
    'twitch.chat.reply': 'chat', 'twitch.chat.delete': 'moderation', 'twitch.chat.message.delete': 'moderation', 'twitch.automod.update': 'moderation',
    'twitch.clips.get': 'media', 'twitch.video.delete': 'media', 'twitch.poll.create': 'engagement',
    'twitch.reward.update': 'engagement', 'twitch.ads.schedule.get': 'monetization',
    'twitch.subscription.get': 'monetization', 'twitch.bits.get': 'monetization',
    'twitch.eventsub.create': 'events', 'twitch.analytics.game.get': 'analytics'
  };
  for (const [action, group] of Object.entries(expected)) assert.equal(capabilityGroup({ action, group: 'Unknown group' }), group);
});

test('a supported empty string clears native text fields while untouched optional fields stay omitted', () => {
  const fields = { prompt: { type: 'string', minLength: 0, maxLength: 200 } };
  assert.deepEqual(parseFields(fields, {}), {});
  assert.deepEqual(parseFields(fields, { prompt: '' }), { prompt: '' });
});

test('strict payload parsing preserves exact content and explicitly selected false without inventing defaults', () => {
  const fields = {
    message: { type: 'string', required: true, maxLength: 500 },
    for_source_only: { type: 'boolean' },
    reply_parent_message_id: { type: 'string' }
  };
  const message = '  Exact message\nSecond line  ';
  assert.deepEqual(parseFields(fields, { message, for_source_only: 'false' }), { message, for_source_only: false });
  assert.deepEqual(parseFields(fields, { message }), { message });
  assert.throws(() => parseFields(fields, { message, for_source_only: 'yes' }), /Choose Yes or No/);
  assert.throws(() => parseFields(fields, { message, broadcaster_id: 'someone-else' }), /Unexpected field/);
  assert.throws(() => parseFields(fields, JSON.parse('{"message":"x","__proto__":{"role":"owner"}}')), /Unexpected field/);
  assert.throws(() => parseFields(fields, { message: 'x'.repeat(501) }), /at most 500/);
});

test('numeric limits are enforced before a preview, including JSON schema minimum and maximum', () => {
  const fields = { duration: { type: 'integer', required: true, minimum: 1, maximum: 1209600 } };
  assert.deepEqual(parseFields(fields, { duration: '30' }), { duration: 30 });
  for (const invalid of ['', ' ', 'NaN', Infinity, '2.5', '-1', '1209601', '9007199254740994']) {
    assert.throws(() => parseFields(fields, { duration: invalid }));
  }
});

test('Twitch message lengths count Unicode characters consistently with the native server', () => {
  const fields = { message: { type: 'string', required: true, minLength: 1, maxLength: 500 } };
  const message = '🎹'.repeat(500);
  assert.deepEqual(parseFields(fields, { message }), { message });
  assert.throws(() => parseFields(fields, { message: `${message}🎹` }), /at most 500/);
});

test('poll choices and nested reward inputs remain typed, bounded and strict', () => {
  const fields = {
    choices: { type: 'array', required: true, minItems: 2, maxItems: 5, items: { type: 'object', properties: { title: { type: 'string', required: true, maxLength: 25 } } } },
    max_per_stream: { type: 'object', properties: { enabled: { type: 'boolean', required: true }, value: { type: 'integer', minimum: 1 } } }
  };
  assert.deepEqual(parseFields(fields, { choices: [{ title: 'One' }, { title: 'Two' }], max_per_stream: { enabled: 'false' } }), { choices: [{ title: 'One' }, { title: 'Two' }], max_per_stream: { enabled: false } });
  assert.throws(() => parseFields(fields, { choices: [{ title: 'One' }] }), /at least 2/);
  assert.throws(() => parseFields(fields, { choices: [{ title: 'One' }, { title: 'Two', hidden_role: 'owner' }] }), /Unexpected field/);
  assert.throws(() => parseFields(fields, { choices: [{ title: 'One' }, {}] }), /required/);
});

test('enum fields reject unoffered actions and values', () => {
  const fields = { status: { type: 'string', required: true, enum: ['ACTIVE', 'CANCELED'] } };
  assert.deepEqual(parseFields(fields, { status: 'CANCELED' }), { status: 'CANCELED' });
  assert.throws(() => parseFields(fields, { status: 'RESOLVED' }), /available value/);
});

test('nested schema required-property lists survive array and object composition', () => {
  const fields = { choices: { type: 'array', required: true, items: { type: 'object', required: ['title', 'meta'], properties: { title: { type: 'string' }, meta: { type: 'object', required: ['enabled'], properties: { enabled: { type: 'boolean' } } } } } } };
  assert.throws(() => parseFields(fields, { choices: [{}] }), /title is required/);
  assert.throws(() => parseFields(fields, { choices: [{ title: 'Yes', meta: {} }] }), /enabled is required/);
  assert.deepEqual(parseFields(fields, { choices: [{ title: 'Yes', meta: { enabled: 'false' } }] }), { choices: [{ title: 'Yes', meta: { enabled: false } }] });
});

test('editing the payload, operation or execution time invalidates the review fingerprint', () => {
  const signature = submissionSignature('twitch.chat.send', { message: 'Hello', for_source_only: true });
  assert.equal(signature, submissionSignature('twitch.chat.send', { for_source_only: true, message: 'Hello' }));
  assert.notEqual(signature, submissionSignature('twitch.chat.send', { message: 'Hello ', for_source_only: true }));
  assert.notEqual(signature, submissionSignature('twitch.chat.send', { message: 'Hello', for_source_only: false }));
  assert.notEqual(signature, submissionSignature('twitch.chat.reply', { message: 'Hello', for_source_only: true }));
  assert.notEqual(signature, submissionSignature('twitch.chat.send', { message: 'Hello', for_source_only: true }, '2030-01-01T00:00:00.000Z'));
});

test('a content-rights or past-broadcast declaration is part of the exact local approval fingerprint', () => {
  for (const [action, declaration] of [['twitch.clip.download', 'rightsConfirmed'], ['twitch.marker.create', 'pastBroadcastsEnabled']]) {
    const signature = submissionSignature(action, {}, undefined, { [declaration]: true });
    assert.notEqual(signature, submissionSignature(action, {}));
    assert.notEqual(signature, submissionSignature(action, {}, undefined, { [declaration]: false }));
  }
});

test('approval requires a fresh server SHA-256 preview on the exact authorization generation', () => {
  const now = Date.parse('2026-10-18T18:00:00Z');
  const draft = { state: 'draft', payloadHash: 'a'.repeat(64), generation: 7, expiresAt: now / 1000 + 60 };
  assert.equal(reviewCanApprove(draft, 7, now), true);
  assert.equal(reviewCanApprove(draft, '7', now), true);
  for (const generation of [undefined, 0, 8, '']) assert.equal(reviewCanApprove(draft, generation, now), false);
  for (const patch of [{ state: 'approved' }, { payloadHash: 'guessed-hash' }, { expiresAt: null }, { expiresAt: now / 1000 }, { expiresAt: 'invalid' }]) assert.equal(reviewCanApprove({ ...draft, ...patch }, 7, now), false);
});

test('scheduled actions retain exact timezone offsets and reject past or invalid time', () => {
  const now = Date.parse('2026-10-18T18:00:00Z');
  assert.equal(scheduledInstant('', now), undefined);
  assert.equal(scheduledInstant('2026-10-19T19:30:00-04:00', now), '2026-10-19T23:30:00.000Z');
  assert.throws(() => scheduledInstant('2026-10-18T18:00:00Z', now), /future time/);
  assert.throws(() => scheduledInstant('tomorrow', now), /future time/);
});

test('restoring a preview distinguishes requested scheduling from the worker timestamp for immediate work', () => {
  const preview = { executeAt: '2026-10-19T19:30:00-04:00' };
  assert.equal(reviewScheduledInstant(preview, { schedulable: true }), undefined);
  assert.equal(reviewScheduledInstant({ ...preview, scheduled: false }, { schedulable: true }), undefined);
  assert.equal(reviewScheduledInstant({ ...preview, scheduled: true }, { schedulable: false }), undefined);
  assert.equal(reviewScheduledInstant({ ...preview, scheduled: true }, { schedulable: true }), '2026-10-19T23:30:00.000Z');
});

test('durable queue controls never label approval or a lost response as provider success', () => {
  assert.equal(actionStateLabel('approved'), 'Approved · waiting for worker');
  assert.match(actionStateLabel('unknown'), /Outcome unknown/);
  assert.match(actionStateLabel('ambiguous'), /inspect before retry/);
  assert.match(actionStateLabel('outcome_unknown'), /Outcome unknown/);
  assert.match(actionStateLabel('accepted'), /resource processing/);
  assert.match(actionStateLabel('partial'), /Partially confirmed/);
  assert.equal(actionStateLabel('dispatching'), 'Sending to Twitch');
  for (const state of ['running', 'claimed', 'succeeded', 'unknown', 'ambiguous', 'accepted', 'partial', 'outcome_unknown', 'dispatching']) {
    assert.equal(canPauseAction(state), false);
    assert.equal(canCancelAction(state), false);
  }
  assert.equal(canCancelAction('draft'), true);
  assert.equal(canPauseAction('scheduled'), true);
});

test('authorization navigation only accepts official HTTPS Twitch authorization links', () => {
  const allowed = 'https://id.twitch.tv/oauth2/authorize?client_id=test&state=test';
  assert.equal(twitchAuthorizeUrl(allowed), allowed);
  for (const bad of [null, '', 'javascript:alert(1)', 'http://id.twitch.tv/oauth2/authorize', 'https://id.twitch.tv.evil.example/oauth2/authorize', 'https://id.twitch.tv@evil.example/oauth2/authorize', 'https://user:pass@id.twitch.tv/oauth2/authorize', 'https://id.twitch.tv/oauth2/token']) assert.equal(twitchAuthorizeUrl(bad), null);
});

test('reconciliation is offered only for a saved provider lookup receipt and never permits a mutation retry', () => {
  const action = { state: 'accepted', result: { confirmation: { action: 'twitch.clip.lookup', payload: { id: ['clip'] } } } };
  assert.equal(canReconcileAction(action), true);
  assert.equal(canReconcileAction({ ...action, state: 'outcome_unknown' }), true);
  assert.equal(canReconcileAction({ ...action, state: 'partial' }), false);
  assert.equal(canReconcileAction({ ...action, result: null }), false);
  assert.equal(canReconcileAction({ ...action, result: { confirmation: { action: 'twitch.clip.create' } } }), false);
});

test('sensitive clip links accept only exact official CDN hosts without alternate ports or credentials', () => {
  for (const host of ['clips.twitch.tv', 'assets.twitchcdn.net', 'production.assets.clips.twitchcdn.net', 'vod-secure.twitch.tv', 'video-edge.ttvnw.net']) {
    const url = `https://${host}/clip.mp4?token=synthetic`;
    assert.equal(clipDownloadHref(url), url);
  }
  for (const url of [null, 'javascript:alert(1)', 'http://clips.twitch.tv/a', 'https://clips.twitch.tv.evil.example/a', 'https://evilttvnw.net/a', 'https://u:p@clips.twitch.tv/a', 'https://clips.twitch.tv:8443/a', 'https://clips.twitch.tv/a#secret', ' https://clips.twitch.tv/a', 'https://clips.twitch.tv/\\evil', 'https://clips.twitch.tv/a\nb']) assert.equal(clipDownloadHref(url), null);
});

test('display projection removes nested OAuth and stream credentials while preserving legitimate counts', () => {
  const data = { data: [{ viewer_count: 0, token: 'secret', stream_key: 'secret', refreshToken: 'secret', message: '<script>text</script>' }], authorization: 'Bearer secret' };
  const safe = safeDisplay(data);
  assert.equal(safe.data[0].viewer_count, 0);
  assert.equal(safe.data[0].token, '[Not displayed]');
  assert.equal(safe.data[0].stream_key, '[Not displayed]');
  assert.equal(safe.data[0].refreshToken, '[Not displayed]');
  assert.equal(safe.authorization, '[Not displayed]');
  assert.equal(safe.data[0].message, '<script>text</script>'); // React renders it as text, never innerHTML.
});

test('real API client carries the current session and guard with encoded workspace, connection and action IDs', async () => {
  const requests = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (path, options) => { requests.push({ path, options }); return new Response(JSON.stringify({ state: 'approved' }), { status: 200 }); };
  try {
    const api = createApi(async () => 'test-session');
    await api.twitchConnections('workspace/a');
    await api.twitchOverview('workspace/a', 'connection/b');
    await api.twitchRead('workspace/a', 'connection/b', 'twitch.channel.get', { id: 'target' });
    const body = { action: 'twitch.marker.create', payload: { description: 'Exact' }, executeAt: '2030-01-01T00:00:00Z', pastBroadcastsEnabled: true };
    await api.twitchPreview('workspace/a', 'connection/b', body);
    const receipt = await api.twitchApprove('workspace/a', 'connection/b', 'draft/c', 'f'.repeat(64));
    await api.twitchPause('workspace/a', 'connection/b', 'draft/c');
    await api.twitchCancel('workspace/a', 'connection/b', 'draft/c');
    await api.twitchSecretAccess('workspace/a', 'connection/b', 'draft/c', 'f'.repeat(64));
    await api.twitchReconcile('workspace/a', 'connection/b', 'draft/c');
    assert.equal(receipt.state, 'approved');
    assert.equal(requests[0].path, '/api/workspaces/workspace%2Fa/twitch');
    assert.equal(requests[1].path, '/api/workspaces/workspace%2Fa/twitch/connection%2Fb');
    assert.equal(requests[2].path, '/api/workspaces/workspace%2Fa/twitch/connection%2Fb/read/twitch.channel.get');
    assert.deepEqual(JSON.parse(requests[2].options.body), { payload: { id: 'target' } });
    assert.deepEqual(JSON.parse(requests[3].options.body), body);
    assert.deepEqual(JSON.parse(requests[4].options.body), { payloadHash: 'f'.repeat(64), confirmed: true });
    assert.equal(requests[4].path, '/api/workspaces/workspace%2Fa/twitch/connection%2Fb/actions/draft%2Fc/approve');
    assert.equal(requests[7].path, '/api/workspaces/workspace%2Fa/twitch/connection%2Fb/actions/draft%2Fc/secret-access');
    assert.deepEqual(JSON.parse(requests[7].options.body), { payloadHash: 'f'.repeat(64), confirmed: true });
    assert.equal(requests[8].path, '/api/workspaces/workspace%2Fa/twitch/connection%2Fb/actions/draft%2Fc/reconcile');
    for (const request of requests) {
      assert.equal(request.options.headers.Authorization, 'Bearer test-session');
      for (const [header, value] of Object.entries(APP_GUARD_HEADER)) assert.equal(request.options.headers[header], value);
    }
  } finally { globalThis.fetch = original; }
});

test('the client rejects missing sessions, server denials and network ambiguity without automatic mutation retries', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new TypeError('Connection lost after send'); };
  try {
    await assert.rejects(() => createApi(async () => null).twitchConnections('other-tenant'), (err) => err instanceof ApiError && err.status === 401);
    assert.equal(calls, 0);
    const api = createApi(async () => 'test-session');
    await assert.rejects(() => api.twitchApprove('workspace', 'connection', 'draft', 'f'.repeat(64)), /Connection lost/);
    assert.equal(calls, 1);
    globalThis.fetch = async () => new Response(JSON.stringify({ error: 'Wrong workspace', code: 'permission_denied' }), { status: 403 });
    await assert.rejects(() => api.twitchPreview('workspace', 'connection', { action: 'twitch.chat.send', payload: { message: 'x' } }), (err) => err instanceof ApiError && err.status === 403 && err.code === 'permission_denied');
  } finally { globalThis.fetch = original; }
});
