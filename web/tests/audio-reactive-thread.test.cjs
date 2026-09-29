const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(relative) {
  const file = path.join(__dirname, '..', 'src', relative);
  const source = fs.readFileSync(file, 'utf8');
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const audio = load('lib/media/audio-reactive.ts');

test('audio spectrum collapses to stable normalized liquid-rail bands', () => {
  const spectrum = Uint8Array.from({ length: 128 }, (_, index) =>
    index < 24 ? 255 : index < 64 ? 128 : 0
  );
  const bands = audio.collapseSpectrum(spectrum, 24);
  assert.equal(bands.length, 24);
  assert.ok(bands.every((value) => value >= 0 && value <= 1));
  assert.ok(bands[0] > bands.at(-1));
});

test('audio bands resample to the exact number of visible thread clusters', () => {
  assert.deepEqual(audio.resampleBands([0, 1], 3), [0, 0.5, 1]);
  assert.deepEqual(audio.resampleBands([], 4), [0, 0, 0, 0]);
  assert.equal(audio.resampleBands([0.2, 0.8], 1)[0], 0.5);
});

test('spectral flux spikes on a fresh onset and falls on a steady frame', () => {
  const previous = new Float32Array(4);
  const onset = audio.spectralFlux(Uint8Array.from([0, 255, 255, 0]), previous);
  const steady = audio.spectralFlux(Uint8Array.from([0, 255, 255, 0]), previous);
  assert.ok(onset > 0.5);
  assert.equal(steady, 0);
});

test('global music level gives the Mono Beads rail a subtle movement floor', () => {
  const points = audio.buildRailMotion({
    count: 12,
    activeIndex: 5,
    level: 0.55,
    transient: 0.35,
    bands: [1, 0, 0, 0, 0, 0],
    waveform: [],
    tickMs: 1200
  });
  assert.equal(points.length, 12);
  assert.ok(points.every((point) => point.width > 2.25));
  assert.ok(points.every((point) => point.width === point.height));
});

test('external playback capture has priority over Rafii-owned media frames', () => {
  const store = audio.useAudioReactive;
  store.getState().setExternalState('active');
  store.getState().setFrame('external', 0.8, [0.8]);
  store.getState().setFrame('rafii', 0.2, [0.2]);
  assert.equal(store.getState().source, 'external');
  assert.equal(store.getState().level, 0.8);
  store.getState().setExternalState('idle');
  store.getState().setFrame('rafii', 0.2, [0.2]);
  assert.equal(store.getState().source, 'rafii');
  store.getState().deactivate('rafii');
});

test('thread rail reserves a dedicated gutter and exposes local music sync', () => {
  const nav = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'features', 'context-navigation', 'thread-navigator.tsx'),
    'utf8'
  );
  const conversation = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'features', 'agent', 'conversation-view.tsx'),
    'utf8'
  );
  assert.match(nav, /hidden w-12 lg:block/);
  assert.match(nav, /startExternalAudioSync/);
  assert.match(nav, /Audio is analysed locally and is not uploaded/);
  assert.match(conversation, /lg:pr-14/);
});

test('external capture requests system or window audio rather than guessing from Media Session state', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'lib', 'media', 'audio-reactive.ts'),
    'utf8'
  );
  assert.match(source, /systemAudio: 'include'/);
  assert.match(source, /windowAudio: 'system'/);
  assert.doesNotMatch(source, /fetch\(/);
});


test('Rafii-owned cross-origin media opts into CORS before Web Audio analysis', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'features', 'now-playing', 'now-playing-bar.tsx'), 'utf8');
  assert.match(source, /element\.crossOrigin = 'anonymous';\s*element\.src = track\.url;/);
  assert.match(source, /<video ref=\{video\} crossOrigin='anonymous'/);
});


test('audio meter uses faster whole-rail response tuning', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'lib', 'media', 'audio-reactive.ts'),
    'utf8'
  );
  assert.match(source, /smoothingTimeConstant = 0\.54/);
  assert.match(source, /now - this\.lastCommit >= 22/);
  assert.match(source, /globalPulse \* 0\.1/);
  assert.match(source, /waveformPeak \* 0\.64/);
  assert.match(source, /travellingTransient \* 0\.1/);
});


test('time-domain waveform sampler preserves spatial peaks and valleys', () => {
  const samples = Uint8Array.from({ length: 97 }, (_, index) => {
    const phase = (index / 96) * Math.PI * 4;
    return Math.round(128 + Math.sin(phase) * 118);
  });
  const profile = audio.sampleWaveform(samples, 12);
  assert.equal(profile.length, 12);
  assert.ok(Math.max(...profile) > 0.9);
  assert.ok(Math.min(...profile) < 0.45);
});

test('waveform peaks create different Mono Bead diameters and response speeds', () => {
  const points = audio.buildRailMotion({
    count: 8,
    activeIndex: -1,
    level: 0.42,
    transient: 0.15,
    bands: [0.4, 0.5, 0.4, 0.5],
    waveform: [0.05, 0.2, 0.95, 0.25, 0.08, 0.82, 0.18, 0.05],
    tickMs: 1600
  });
  const widths = points.map((point) => point.width);
  const speeds = points.map((point) => point.transitionMs);
  assert.ok(Math.max(...widths) - Math.min(...widths) >= 3.5);
  assert.ok(Math.max(...speeds) - Math.min(...speeds) > 20);
  assert.ok(points[2].width > points[0].width);
  assert.ok(points[2].transitionMs < points[0].transitionMs);
});

test('Mono Bead peak contrast outweighs the shared global pulse', () => {
  const points = audio.buildRailMotion({
    count: 6,
    activeIndex: -1,
    level: 0.65,
    transient: 0,
    bands: [0.5, 0.5, 0.5],
    waveform: [0, 0.15, 1, 0.2, 0.75, 0.05],
    tickMs: 900
  });
  assert.ok(points[2].width - points[0].width >= 3.5);
});


test('Mono Beads stay circular, tiny at rest, and preserve selected hierarchy', () => {
  const idle = audio.buildRailMotion({
    count: 10,
    activeIndex: -1,
    level: 0,
    transient: 0,
    bands: [0, 0, 0],
    waveform: [0, 0, 0],
    tickMs: 0
  });
  assert.ok(idle.every((point) => point.width === point.height));
  assert.ok(Math.max(...idle.map((point) => point.width)) <= 3);

  const selected = audio.buildRailMotion({
    count: 10,
    activeIndex: 4,
    level: 0,
    transient: 0,
    bands: [0, 0, 0],
    waveform: [0, 0, 0],
    tickMs: 0
  });
  assert.ok(selected[4].width >= 4);
  assert.ok(selected[4].width > selected[3].width);
  assert.equal(selected[4].opacity, 1);
});

test('Mono Bead halo appears only for meaningful peaks', () => {
  const points = audio.buildRailMotion({
    count: 6,
    activeIndex: -1,
    level: 0.2,
    transient: 0,
    bands: [0.2, 0.2, 0.2],
    waveform: [0.02, 0.1, 1, 0.12, 0.05, 0.02],
    tickMs: 600
  });
  assert.ok(points[2].glowPx > points[0].glowPx);
  assert.ok(points[2].haloOpacity > points[0].haloOpacity);
  assert.equal(points[0].glowPx, 0);
});

test('Thread Map renders a hairline Mono Beads spine without shrinking hit targets', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'features', 'context-navigation', 'thread-navigator.tsx'),
    'utf8'
  );
  assert.match(source, /data-mono-bead-spine/);
  assert.match(source, /data-mono-bead/);
  assert.match(source, /min-w-10/);
  assert.match(source, /size-3/);
  assert.match(source, /rounded-full/);
});
