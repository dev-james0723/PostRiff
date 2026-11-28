import assert from 'node:assert/strict';
import test from 'node:test';
import { campaignPhotoBrief, photoTurnRequest } from '../src/features/creative-video/campaign-photo-brief.ts';

const scene = { sceneId: 'scene-2', purpose: 'Demonstration', direction: 'Restricted voice preference', caption: 'Private saved copy', sourceStartMs: 2000 };
const project = { id: 'p1', revision: 4, title: 'Orbit', brief: 'Introduce our new blue dial.', platform: 'Instagram', aspectRatio: '9:16',
  context: { preferences: ['unrelated secret preference'] }, referenceAssetId: 'third-party-reference',
  analysis: { scenes: [{ startMs: 0, endMs: 2000, measurements: { meanLuma: 0.1 } }, { startMs: 2000, endMs: 3500, measurements: { meanLuma: 0.9 } }] },
  scenes: [{ sceneId: 'scene-1' }, scene] };

test('the two formats create different editable prompts from first-party campaign data', () => {
  const a = campaignPhotoBrief('thumbnail', project, scene);
  const b = campaignPhotoBrief('product', project, scene);
  assert.notEqual(a, b);
  for (const text of [a, b]) {
    assert.match(text, /Orbit/); assert.match(text, /2/); assert.match(text, /new blue dial/);
    assert.match(text, /bright setting/);
    assert.doesNotMatch(text, /Restricted|Private saved|secret preference|third-party-reference/);
    assert.ok(text.length <= 1000);
  }
});

test('a reviewed prompt reaches /image with just the selected photo and a stable account-scoped request key', async () => {
  const scope = ['account-a', 'workspace-a', project.id, '4', scene.sceneId, 'thumbnail'];
  const a = await photoTurnRequest(scope, ' An original still ', 'selected-asset');
  assert.deepEqual(a.command, { name: 'image', args: 'An original still' });
  assert.equal(a.message, '/image An original still'); assert.deepEqual(a.attachments, [{ assetId: 'selected-asset', role: 'reference' }]);
  assert.deepEqual(await photoTurnRequest(scope, 'An original still', 'selected-asset'), a);
  for (const other of [await photoTurnRequest(scope, 'Other still', 'selected-asset'),
                        await photoTurnRequest(scope, 'An original still', ''),
                        await photoTurnRequest(['account-b', ...scope.slice(1)], 'An original still', 'selected-asset')])
    assert.notEqual(other.idempotencyKey, a.idempotencyKey);
  assert.equal((await photoTurnRequest(scope, 'An original still', '')).attachments, undefined);
  await assert.rejects(photoTurnRequest(scope, 'x'.repeat(1001), ''));
  await assert.rejects(photoTurnRequest(scope, '   ', ''));
});
