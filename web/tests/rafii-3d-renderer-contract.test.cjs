const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WEB = path.resolve(__dirname, '..');
const AVATAR = path.join(WEB, 'src/features/rafii-voice/rafii-live-avatar.tsx');
const VOICE = path.join(WEB, 'src/features/rafii-voice/voice-mode.tsx');

test('live avatar owns a bounded Three.js lifecycle with local GLB and static fallback', () => {
  assert.ok(fs.existsSync(AVATAR), 'RafiiLiveAvatar component must exist');
  const source = fs.readFileSync(AVATAR, 'utf8');

  for (const expected of [
    'GLTFLoader',
    '/raffi/raffi-live-v1.glb',
    'requestAnimationFrame',
    'cancelAnimationFrame',
    'ResizeObserver',
    'visibilitychange',
    'renderer.dispose()',
    'dispose()',
    '/raffi/full-512.png'
  ]) {
    assert.ok(source.includes(expected), `avatar lifecycle must include: ${expected}`);
  }

  assert.ok(source.includes('aria-hidden'), '3D surface must stay decorative');
  assert.ok(source.includes('data-rafii-3d'), 'stage exposes the browser-test hook');
  assert.ok(source.includes('data-rafii-avatar-mode'), 'stage exposes the current avatar mode');
  assert.ok(source.includes('data-rafii-mouth-open'), 'stage exposes mouth state for interruption verification');
  assert.ok(source.includes('data-rafii-continuous-motion'), 'stage exposes reduced-motion behavior for QA');
});

test('Voice Mode mounts RafiiLiveAvatar only inside the active call surface', () => {
  const source = fs.readFileSync(VOICE, 'utf8');
  assert.ok(source.includes('RafiiLiveAvatar'), 'Voice Mode must render the live 3D avatar');
  assert.ok(source.includes('resolveRafiiAvatarMode'), 'Voice Mode derives visual state from the pure helper');
  assert.ok(source.includes('outputMuted={snapshot.outputMuted}'), 'real stop-talking state reaches the renderer');
  assert.ok(source.includes('level={snapshot.level}'), 'real outgoing WebRTC level reaches the renderer');
  assert.ok(source.includes('reducedMotion={reduced}'), 'existing motion preference reaches the renderer');
});
