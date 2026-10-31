/**
 * Launch switch, checked over HTTP against a local production server (`next build && next start`):
 *   off: next build && next start -p 3127 -H 127.0.0.1                   -> PLAY_EXPECT=off node tests/play-launch-http.cjs
 *   on:  RAFII_PLAY_ENABLED=1 for both build and start                    -> PLAY_EXPECT=on node tests/play-launch-http.cjs
 * Off: every /play route is a 404 whose page names nothing of the game, and no query, header or cookie turns it on.
 * On: the game is served. Both: other pages are unaffected.
 */
const assert = require('node:assert/strict');

const base = process.env.RAFII_PLAY_URL || 'http://127.0.0.1:3127';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local server only');
const expect = process.env.PLAY_EXPECT;
if (!['on', 'off'].includes(expect)) throw new Error('Set PLAY_EXPECT=on or PLAY_EXPECT=off');

// Redirects are followed: Next answers a header-only RSC request with a 307 to ?_rsc, and /play/ with a 308 to /play.
const get = async (path, headers = {}) => {
  const res = await fetch(base + path, { headers, redirect: 'follow' });
  return { status: res.status, body: await res.text() };
};
// What the game's page and metadata say about itself (title, description, game text), and its client component.
const GAME = /Note Garden|children aged 6 to 10|music game|"NoteGarden"/i;

(async () => {
  for (const path of ['/', '/pricing']) assert.equal((await get(path)).status, 200, path);
  const page = await get('/play/note-garden');
  if (expect === 'on') {
    assert.equal(page.status, 200);
    assert.match(page.body, /<title>Note Garden/);
  } else {
    assert.equal(page.status, 404);
    assert.doesNotMatch(page.body, GAME, 'the 404 for a disabled /play route must not describe the game');
    const attempts = [
      ['/play/note-garden?RAFII_PLAY_ENABLED=1', {}],
      ['/play/note-garden', { 'x-rafii-play-enabled': '1', cookie: 'RAFII_PLAY_ENABLED=1' }],
      ['/play/note-garden', { rsc: '1' }],
      ['/play', {}],
      ['/play/', {}]
    ];
    for (const [path, headers] of attempts) {
      const res = await get(path, headers);
      if (headers.rsc) {
        // Next serves the prerendered not-found tree for an RSC request to this route (HTTP 200): it must be that tree.
        assert.match(res.body, /Page not found/, `${path} RSC must carry the not-found tree`);
      } else {
        assert.equal(res.status, 404, `${path} ${JSON.stringify(headers)}`);
      }
      assert.doesNotMatch(res.body, GAME, `${path} must not describe or load the game`);
    }
  }
  console.log(`play launch switch (${expect}): OK`);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
