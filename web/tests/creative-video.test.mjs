import assert from 'node:assert/strict';
import test from 'node:test';
import { createApi } from '../src/lib/api/client.ts';
import { draftScene, changedScenes, editIssue, captionTrack } from '../src/features/creative-video/scene-edit.ts';
import { canAuthorizeQuote, parseCreditLimit } from '../src/features/creative-video/intelligence.ts';

const scene = {
  sceneId: 'opening', direction: 'Show the new lamp in use.', caption: 'Read comfortably.',
  durationMs: 1583, purpose: 'Hook', clipId: 'original', clipOrigin: 'generated', estimatedUsdMicro: 100000
};
const second = { ...scene, sceneId: 'middle', clipId: 'other' };

test('scene edits preserve millisecond timing and never resubmit an unchanged clip', () => {
  const drafts = { opening: draftScene(scene), middle: draftScene(second) };
  assert.deepEqual(changedScenes([scene, second], drafts), []);
  drafts.opening.caption = 'See the warm light.';
  assert.deepEqual(changedScenes([scene, second], drafts), [{
    sceneId: 'opening', direction: scene.direction, caption: 'See the warm light.', durationMs: 1583
  }]);
  drafts.opening.direction = 'Show the lamp from above.';
  assert.equal('clipId' in changedScenes([scene, second], drafts)[0], false);
});

test('new footage needs its own rights confirmation and the reference is never eligible', () => {
  const draft = { ...draftScene(scene), clipId: 'different' };
  assert.match(editIssue([scene], { opening: draft }, 'reference'), /right/i);
  draft.clipRightsConfirmed = true;
  assert.equal(editIssue([scene], { opening: draft }, 'reference'), null);
  assert.deepEqual(changedScenes([scene], { opening: draft })[0], {
    sceneId: 'opening', direction: scene.direction, caption: scene.caption, durationMs: 1583,
    clipId: 'different', clipRightsConfirmed: true
  });
  draft.clipId = 'reference';
  assert.match(editIssue([scene], { opening: draft }, 'reference'), /reference/i);
  draft.clipId = '';
  assert.equal(changedScenes([scene], { opening: draft })[0].clipId, null);
  assert.equal('clipRightsConfirmed' in changedScenes([scene], { opening: draft })[0], false);
});

test('the clip start is independent of reference timing and preserves the assigned footage', () => {
  const saved = { ...scene, sourceStartMs: 4250, trimStartMs: 1250 };
  const draft = draftScene(saved);
  assert.equal(draft.startSeconds, '1.25');
  assert.deepEqual(changedScenes([saved], { opening: draft }), []);
  draft.startSeconds = '0.125';
  const [cut] = changedScenes([saved], { opening: draft });
  assert.equal(cut.trimStartMs, 125);
  assert.equal(cut.clipId, undefined);
  assert.equal(editIssue([saved], { opening: draft }, null), null);
  for (const value of ['-1', '', '0.1234', '90', '1e1']) {
    assert.ok(editIssue([saved], { opening: { ...draft, startSeconds: value } }, null));
  }
});

test('invalid and overlong timelines cannot be saved', () => {
  for (const value of ['', '0', '-1', '0.041', '8.001', '0.1234', 'Infinity']) {
    const draft = { ...draftScene(scene), seconds: value };
    assert.ok(editIssue([scene], { opening: draft }, 'reference'), value);
  }
  const many = Array.from({ length: 12 }, (_, i) => ({ ...scene, sceneId: String(i), durationMs: 8000 }));
  assert.match(editIssue(many, {}, 'reference'), /90/);
});

test('credit limits preserve the smallest wallet unit and incomplete prices cannot authorize a take', () => {
  assert.equal(parseCreditLimit('10.001'), 10001);
  assert.equal(parseCreditLimit('0.001'), 1);
  for (const value of ['1e3', '-2', '', '0.0001', '12345678901234567890']) assert.equal(parseCreditLimit(value), null);
  const quote = { id: 'server-quote', expiresAt: 200, eligible: true, estimatedUsdMicro: 150000, estimatedMilliCredits: 10000, availableMilliCredits: 20000, maximumMilliCredits: 10001 };
  assert.equal(canAuthorizeQuote(quote, 100000), true);
  for (const difference of [{ estimatedUsdMicro: null }, { estimatedMilliCredits: null }, { eligible: false },
    { id: null }, { expiresAt: 100 }, { expiresAt: NaN }, { availableMilliCredits: 9999 }, { availableMilliCredits: undefined }, { maximumMilliCredits: 9999 }]) {
    assert.equal(canAuthorizeQuote({ ...quote, ...difference }, 100000), false);
  }
});

test('workspace requests carry the guard, revision, quote identity and a stable create key', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => { calls.push({ url, ...options }); return Response.json({}); };
  try {
    const api = createApi(async () => 'fixture-session');
    const create = { requestId: 'one-request', title: 'Product demo', brief: 'Show the new lamp',
      referenceAssetId: 'ref', rightsConfirmed: true, aspectRatio: '9:16', platform: 'Instagram' };
    await api.creativeVideoList('team/1');
    await api.creativeVideoCreate('team/1', create);
    await api.creativeVideoProject('team/1', 'proj/2');
    await api.creativeVideoEdit('team/1', 'proj/2', { revision: 3, scenes: [] });
    await api.creativeVideoGenerate('team/1', 'proj/2', { revision: 3, sceneId: 'opening', quoteId: 'q-123', confirmed: true });
    await api.creativeVideoPoll('team/1', 'proj/2', { revision: 3, sceneId: 'opening' });
    await api.creativeVideoRender('team/1', 'proj/2', { revision: 3 });
    await api.creativeVideoProject('team/1', 'proj/2', 2);
    const base = '/api/workspaces/team%2F1/creative-video/projects';
    assert.deepEqual(calls.map(c => c.url), [base, base, base+'/proj%2F2', ...['edit','generate','poll','render'].map(a => base+'/proj%2F2/'+a), base+'/proj%2F2?revision=2']);
    assert.equal(JSON.parse(calls[1].body).requestId, 'one-request');
    assert.deepEqual(JSON.parse(calls[4].body), { revision: 3, sceneId: 'opening', quoteId: 'q-123', confirmed: true });
    assert.ok(calls.every(c => c.headers.Authorization === 'Bearer fixture-session' && c.headers['X-PostRiff-Request'] === 'founder-alpha'));
    assert.equal(calls.length, 8);
  } finally { globalThis.fetch = original; }
});

test('playback captions use the exported frame boundaries and original text as plain text', () => {
  assert.equal(captionTrack([]), null);
  const track = captionTrack([
    { caption: '  Look <closer> & compare. ', startMs: 42, endMs: 1583 },
    { caption: '', startMs: 1583, endMs: 2000 }
  ]);
  assert.equal(track, 'WEBVTT\n\n00:00:00.042 --> 00:00:01.583\nLook &lt;closer&gt; &amp; compare.\n');
});

test('scene quotes and cancellation use guarded workspace routes; approval sends only the reviewed quote', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => { calls.push({ url, ...options }); return Response.json({}); };
  try {
    const api = createApi(async () => 'fixture-session');
    const scene = { revision: 3, sceneId: 'opening' };
    const settings = { mode: 'manual', level: 'cinematic', model: 'fixture-camera', maxMilliCredits: 27500 };
    await api.creativeVideoQuote('team/1', 'project/2', { ...scene, settings });
    await api.creativeVideoGenerate('team/1', 'project/2', { ...scene, quoteId: 'q-1', confirmed: true });
    await api.creativeVideoCancel('team/1', 'project/2', scene);
    await api.creativeVideoReview('team/1', 'project/2', { ...scene, accepted: true });
    const base = '/api/workspaces/team%2F1/creative-video/projects/project%2F2/';
    assert.deepEqual(calls.map(c => c.url), ['quote', 'generate', 'cancel', 'review'].map(action => base + action));
    assert.deepEqual(calls.map(c => JSON.parse(c.body)), [
      { ...scene, settings }, { ...scene, quoteId: 'q-1', confirmed: true }, scene, { ...scene, accepted: true }
    ]);
    assert.ok(calls.every(c => c.headers['X-PostRiff-Request'] === 'founder-alpha' && c.headers.Authorization === 'Bearer fixture-session'));
  } finally { globalThis.fetch = original; }
});
