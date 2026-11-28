const { after, before, test } = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { spawnSync } = require('node:child_process');
const { studioRoutes } = require('./studio-http.cjs');

let server, origin;
before(async () => {
  let dispatch;
  server = createServer(async (req, res) => {
    if (!await dispatch(req, res, new URL(req.url, origin).pathname)) {
      res.writeHead(404); res.end();
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  origin = 'http://127.0.0.1:' + port;
  dispatch = studioRoutes(port);
});
after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
const call = (action, body = {}, headers = {}) => fetch(origin + '/studio-api/' + action, {
  method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body)
});

test('local edit page, sample byte ranges, and same-origin rights checks', async () => {
  const page = await fetch(origin + '/local-studio');
  assert.equal(page.headers.get('x-rafii-studio-view'), 'local-edit');
  assert.match(await page.text(), /id="workspace-transfer"/);
  const range = await fetch(origin + '/studio-clips/original-1', { headers: { Range: 'bytes=0-15' } });
  assert.equal(range.status, 206);
  const prefix = Buffer.from(await range.arrayBuffer());
  assert.equal(prefix.subarray(4, 8).toString(), 'ftyp');
  assert.equal(prefix.length, 16);
  assert.equal((await fetch(origin + '/studio-clips/original-1', { headers: { Range: 'bytes=9999999999-' } })).status, 416);
  assert.equal((await fetch(origin + '/studio-clips/hidden')).status, 404);
  assert.equal((await fetch(origin + '/studio-api/render')).status, 405);
  assert.equal((await call('analyze', {}, { Origin: 'https://example.org' })).status, 403);
  assert.equal((await fetch(origin + '/studio-api/sample', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
  })).status, 403);
  assert.equal((await call('analyze')).status, 403);
  assert.equal((await call('analyze', {}, { 'Content-Type': 'text/plain' })).status, 415);
  assert.equal((await call('run')).status, 404);
});

test('HTTP renders playable original and scene revision from actual measured media', async () => {
  const sample = await (await call('sample')).json();
  const measured = await (await call('analyze', { rightsConfirmed: true })).json();
  assert.deepEqual(measured.scenes.map(s => s.startMs), [0, 1250, 2750]);
  const blueprint = await (await call('blueprint', {
    rightsConfirmed: true, referenceSha256: measured.sha256, brief: 'Show how to set a timer', brand: 'Rafii'
  })).json();
  assert.equal(blueprint.referenceSha256, measured.sha256);
  assert.equal(blueprint.scenes.length, 3);
  const overview = await call('reference-frames', {
    rightsConfirmed: true, referenceSha256: measured.sha256, coverage: 'intervals', page: 0
  });
  assert.equal(overview.status, 200);
  assert.equal((await overview.json()).frames.filter(frame => frame.jpeg && frame.timeMs !== null).length, 4);
  async function frames(scenes) {
    const response = await call('render', { scenes, aspectRatio: sample.aspectRatio });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('content-type'), 'video/mp4');
    const file = Buffer.from(await response.arrayBuffer());
    const decoded = spawnSync('ffmpeg', ['-v','error','-i','pipe:0','-map','0:v:0','-f','framemd5','pipe:1'], { input: file });
    assert.equal(decoded.status, 0, decoded.stderr.toString());
    return decoded.stdout.toString().split('\n').filter(l => l && l[0] !== '#').map(l => l.split(',').at(-1).trim());
  }
  const before = await frames(sample.scenes);
  const revised = structuredClone(sample.scenes);
  revised[0].clipId = 'revised-intro';
  revised[0].caption = 'A different opening';
  const after = await frames(revised);
  assert.equal(before.length, 96);
  assert.notDeepEqual(before.slice(0, 30), after.slice(0, 30));
  assert.deepEqual(before.slice(30), after.slice(30));
});
