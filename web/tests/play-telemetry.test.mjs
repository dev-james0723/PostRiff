/** Decision D1 = exclude: nothing analytics or telemetry may leave the /play/* routes (children's games). */
import test from 'node:test';
import assert from 'node:assert/strict';
import { dropPlayPageview, isPlayEvent, isPlayPath, isPlayUrl } from '../src/lib/play-path.ts';

test('isPlayPath: exactly /play or under /play/, nothing that merely starts with "play"', () => {
  for (const path of ['/play', '/play/', '/play/note-garden', '/play/note-garden/', '/play//x']) assert.equal(isPlayPath(path), true, path);
  for (const path of ['/player', '/playground', '/app/play', '/plays', '/', '', '/pricing', 'play', undefined, null]) assert.equal(isPlayPath(path), false, String(path));
});

test('isPlayPath is case-sensitive and does not decode: Next serves the game only at the literal lowercase path', () => {
  // Observed on `next start` (2026-10-31): /PLAY/note-garden, /Play/note-garden and /%70lay/note-garden are 404 pages
  // without the game, so they are ordinary site pages and keep the site's analytics.
  for (const path of ['/PLAY/note-garden', '/Play/note-garden', '/%70lay/note-garden']) assert.equal(isPlayPath(path), false, path);
  // An encoded segment below /play/ is still inside the play area (a 404 there sends nothing either).
  assert.equal(isPlayPath('/play/%6Eote-garden'), true);
});

test('isPlayUrl: absolute or relative URLs, with query and hash', () => {
  for (const url of ['https://rafii.io/play/note-garden', 'http://127.0.0.1:3117/play?x=1', '/play/note-garden#top', '/play']) assert.equal(isPlayUrl(url), true, url);
  for (const url of ['https://rafii.io/pricing', '/player', 'https://rafii.io/app/play', 'not a url', '', undefined]) assert.equal(isPlayUrl(url), false, String(url));
});

test('Vercel Analytics beforeSend drops /play page views and events, keeps everything else unchanged', () => {
  assert.equal(dropPlayPageview({ type: 'pageview', url: 'https://rafii.io/play/note-garden' }), null);
  assert.equal(dropPlayPageview({ type: 'event', url: 'https://rafii.io/play' }), null);
  const other = { type: 'pageview', url: 'https://rafii.io/pricing' };
  assert.equal(dropPlayPageview(other), other, 'other routes pass through untouched');
});

test('Sentry events are recognised as /play by request URL or transaction name', () => {
  assert.equal(isPlayEvent({ request: { url: 'https://rafii.io/play/note-garden?x' } }), true);
  assert.equal(isPlayEvent({ transaction: 'GET /play/note-garden' }), true);
  assert.equal(isPlayEvent({ transaction: '/play/[game]' }), true);
  assert.equal(isPlayEvent({ request: { url: 'https://rafii.io/pricing' }, transaction: 'GET /pricing' }), false);
  assert.equal(isPlayEvent({ transaction: 'GET /playground' }), false);
  assert.equal(isPlayEvent({}), false);
});
