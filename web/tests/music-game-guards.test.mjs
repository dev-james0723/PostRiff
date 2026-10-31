/** Note Garden source guards: no timers (no time pressure), no network or tracking APIs, no cookies in game code. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const roots = ['src/lib/music-game', 'src/components/music-game', 'src/app/play'].map((dir) => new URL(`../${dir}`, import.meta.url).pathname);
const files = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)]));
const sources = roots.flatMap(files).filter((f) => /\.(ts|tsx)$/.test(f)).map((f) => ({ f, text: readFileSync(f, 'utf8') }));

test('game code exists where expected', () => {
  assert.ok(sources.length >= 8, `found ${sources.length} files`);
});

test('no timers: questions are never timed and nothing advances on its own', () => {
  for (const { f, text } of sources) assert.doesNotMatch(text, /\b(setTimeout|setInterval|requestIdleCallback)\s*\(/, f);
});

test('no network, tracking or cookie APIs in game code', () => {
  for (const { f, text } of sources) {
    assert.doesNotMatch(text, /\b(fetch|sendBeacon|XMLHttpRequest|WebSocket|EventSource|importScripts)\s*\(|new\s+(XMLHttpRequest|WebSocket|EventSource)\b/, f);
    assert.doesNotMatch(text, /document\.cookie|@vercel\/analytics|posthog|gtag\(/, f);
  }
});

test('no server routes or server actions under /play', () => {
  for (const { f, text } of sources) {
    assert.ok(!/route\.tsx?$/.test(f), `${f} is a route handler`);
    assert.doesNotMatch(text, /['"]use server['"]/, f);
  }
});
