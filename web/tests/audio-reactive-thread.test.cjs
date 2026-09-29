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

function setGlobal(key, value) {
  Object.defineProperty(global, key, { configurable: true, writable: true, value });
}

function FakeMediaStream(tracks) {
  return { tracks };
}

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

test('external capture keeps the analyser graph live without echoing shared audio', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'lib', 'media', 'audio-reactive.ts'),
    'utf8'
  );
  assert.match(source, /const silentSink = context\.createGain\(\)/);
  assert.match(source, /silentSink\.gain\.value = 0/);
  assert.match(source, /analyser\.connect\(silentSink\)/);
  assert.match(source, /silentSink\.connect\(context\.destination\)/);
  const externalGraph = source.slice(source.indexOf('const audioOnly'));
  assert.equal((externalGraph.match(/\.connect\(context\.destination\)/g) ?? []).length, 1);
});

test('external capture wires a zero-gain sink at runtime', async () => {
  const globalKeys = [
    'navigator',
    'AudioContext',
    'MediaStream',
    'requestAnimationFrame',
    'cancelAnimationFrame'
  ];
  const originalGlobals = new Map(
    globalKeys.map((key) => [key, { exists: key in global, value: global[key] }])
  );
  const connections = [];
  const audioTrack = {
    addEventListener() {},
    stop() {}
  };
  const videoTrack = {
    addEventListener() {},
    stop() {}
  };
  const stream = {
    getAudioTracks: () => [audioTrack],
    getVideoTracks: () => [videoTrack],
    getTracks: () => [audioTrack, videoTrack]
  };

  class FakeNode {
    constructor(name) {
      this.name = name;
      this.gain = { value: 1 };
    }

    connect(target) {
      connections.push([this.name, target.name]);
      return target;
    }
  }

  class FakeAudioContext {
    constructor() {
      this.destination = { name: 'destination' };
    }

    createAnalyser() {
      const analyser = new FakeNode('analyser');
      analyser.frequencyBinCount = 256;
      analyser.fftSize = 512;
      analyser.getByteFrequencyData = () => {};
      analyser.getByteTimeDomainData = () => {};
      return analyser;
    }

    createMediaStreamSource() {
      return new FakeNode('media-stream-source');
    }

    createGain() {
      return new FakeNode('silent-sink');
    }

    resume() {
      return Promise.resolve();
    }

    close() {
      return Promise.resolve();
    }
  }

  setGlobal('navigator', { mediaDevices: { getDisplayMedia: async () => stream } });
  setGlobal('AudioContext', FakeAudioContext);
  setGlobal('MediaStream', FakeMediaStream);
  setGlobal('requestAnimationFrame', () => 1);
  setGlobal('cancelAnimationFrame', () => {});

  try {
    await audio.startExternalAudioSync();
    assert.deepEqual(connections, [
      ['media-stream-source', 'analyser'],
      ['analyser', 'silent-sink'],
      ['silent-sink', 'destination']
    ]);
    assert.equal(audio.useAudioReactive.getState().externalState, 'active');
  } finally {
    audio.stopExternalAudioSync();
    for (const [key, original] of originalGlobals) {
      if (original.exists) setGlobal(key, original.value);
      else delete global[key];
    }
  }
});
