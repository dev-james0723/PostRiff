// node --test app/test_studio_editor.cjs
// Exercises the shipped editor controller and the real Media worker without a
// network listener. The DOM adapter covers edit events, not visual layout or playback.
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

class Control {
  constructor(tag = 'div') {
    this.tag = tag;
    this.textContent = '';
    this.value = '';
    this.children = [];
    this.files = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.dataset = {};
    this.classList = { toggle() {} };
  }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  async fire(type) {
    for (const handler of this.listeners.get(type) || []) await handler({ target: this, preventDefault() {} });
  }
  get valueAsNumber() { return Number(this.value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  add(node) { this.append(node); }
  setAttribute(k, v) { this.attributes.set(k, v); }
  getAttribute(k) { return this.attributes.get(k); }
  removeAttribute(k) { this.attributes.delete(k); }
  reportValidity() { return true; }
  reset() {}
  remove() {}
  click() {}
  focus() {}
  load() {}
  pause() {}
}

function worker(action, body, timeout) {
  const result = spawnSync(process.env.RAFII_STUDIO_PYTHON || 'python3', [path.join(__dirname, 'studio_media.py')], {
    input: JSON.stringify({ ...body, action }), timeout, killSignal: 'SIGKILL', maxBuffer: 65 * 1024 * 1024
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw Error(action + ' failed: ' + result.stderr);
  const type = action === 'render' ? 'video/mp4' : 'application/json';
  return new Response(result.stdout, { headers: { 'Content-Type': type } });
}

function openEditor({ offline = false, workerTimeoutMs = () => 90000 } = {}) {
  const controls = new Map();
  const regions = new Map();
  const storage = new Map();
  const events = [], downloads = [];
  const html = readFileSync(path.join(__dirname, 'studio-editor.html'), 'utf8');
  for (const match of html.matchAll(/<(\w+)[^>]*?\bid="([^"]+)"/g)) controls.set(match[2], new Control(match[1]));
  const get = id => {
    assert(controls.has(id), 'Missing editor control ' + id);
    return controls.get(id);
  };
  const panels = ['scene', 'media', 'blueprint'].map(id => {
    const button = new Control('button');
    button.dataset.panel = id;
    button.setAttribute('aria-controls', id + '-panel');
    return button;
  });
  const document = {
    getElementById: get, body: new Control('body'),
    querySelectorAll: () => panels,
    querySelector(selector) {
      if (!regions.has(selector)) regions.set(selector, new Control());
      return regions.get(selector);
    },
    createElement(tag) {
      const control = new Control(tag);
      if (tag === 'a') control.click = () => downloads.push({ url: control.href, name: control.download });
      return control;
    },
    dispatchEvent: event => events.push(event)
  };
  const context = {
    document, URL, Blob, crypto: webcrypto, confirm: () => true,
    CustomEvent: class {
      constructor(type, options) { this.type = type; this.detail = options?.detail; }
    },
    Option: class { constructor(label, value) { this.label = label; this.value = value; } },
    FileReader: class {
      async readAsDataURL(file) {
        this.result = 'data:application/octet-stream;base64,' + Buffer.from(await file.arrayBuffer()).toString('base64');
        this.onload();
      }
    },
    sessionStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
    setTimeout: (fn, ms) => setTimeout(fn, ms).unref(),
    fetch: async (url, options) => {
      if (offline) return Response.json({ message: 'Media worker unavailable.' }, { status: 503 });
      const action = url.split('/studio-api/')[1], payload = JSON.parse(options.body);
      if (action !== 'sample') assert.equal(payload.rightsConfirmed, true, 'Missing media consent');
      return worker(action, payload, workerTimeoutMs());
    }
  };
  vm.runInNewContext(readFileSync(path.join(__dirname, 'studio-editor.js'), 'utf8'), context);
  return {
    get, storage, downloads, setOnline: () => { offline = false; },
    click: id => get(id).fire('click'),
    submit: id => get(id).fire('submit'),
    state: () => JSON.parse(storage.get('rafii.local-video-edit.v1')),
    output: () => events.findLast(event => event.type === 'rafii:cut-ready')?.detail.blob,
    async ready() {
      const end = Date.now() + 5000;
      while (get('project-actions').inert && get('retry-editor').hidden && Date.now() < end) {
        await new Promise(resolve => setImmediate(resolve));
      }
      assert(Date.now() < end, 'Editor did not finish starting');
    }
  };
}

function soundtrack() {
  const rate = 16000, samples = 8000;
  const wav = Buffer.alloc(44 + samples * 2);
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
  wav.write('data', 36); wav.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++) wav.writeInt16LE(Math.round(18000 * Math.sin(2 * Math.PI * 440 * i / rate)), 44 + i * 2);
  return new File([wav], 'Practice tone.wav');
}

module.exports = { openEditor };

if (require.main === module) test('an unavailable worker preserves the saved edit and supports retry', async () => {
  const ui = openEditor({ offline: true });
  const key = 'rafii.local-video-edit.v1';
  const saved = JSON.stringify({ format: 'rafii-local-edit-v1', name: 'Saved session', revision: 2, aspectRatio: '1:1',
    brief: '', brand: '', audience: '', subject: '', clips: [], scenes: [], reference: null });
  ui.storage.set(key, saved);
  await ui.ready();
  // Let the async failure propagate through working() into the boot error UI.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.get('retry-editor').hidden, false);
  assert.equal(ui.get('project-actions').inert, true);
  assert.equal(ui.storage.get(key), saved);
  ui.setOnline();
  await ui.click('retry-editor');
  assert.equal(ui.get('heading').textContent, 'Saved session');
  assert.equal(ui.get('project-actions').inert, false);
});

if (require.main === module) test('edit, export, reopen, relink and adapt the real local media', async () => {
  const ui = openEditor();
  await ui.ready();
  assert.equal(ui.get('heading').textContent, 'Timer study');
  assert.equal(ui.get('timeline').children.length, 3);
  await ui.click('preview');
  const original = ui.output();
  assert(original?.size > 20000);
  const source = readFileSync(path.join(__dirname, '../docs/creative-intelligence/examples/timer-study/revised-intro.mp4'));
  const importVideo = async name => {
    ui.get('production-rights').checked = true;
    ui.get('production-file').files = [new File([source], name)];
    await ui.submit('import-form');
  };
  await importVideo('New opening.mp4');
  const clipId = ui.state().clips.at(-1).clipId;
  assert.match(clipId, /^upload-[0-9a-f]{64}$/);
  ui.get('scene-clip').value = clipId;
  ui.get('trim').value = '.250';
  ui.get('length').value = '.750';
  ui.get('caption').value = 'Edited opening';
  await ui.get('scene-form').fire('input');
  await ui.submit('scene-form');
  assert.equal(ui.state().scenes[0].durationMs, 750);
  await ui.click('later');
  assert.equal(ui.state().scenes[1].clipId, clipId);
  const importAudio = async () => {
    ui.get('audio-file').files = [soundtrack()];
    ui.get('audio-rights').checked = true;
    await ui.submit('audio-form');
  };
  await importAudio();
  await ui.click('export');
  const captions = ui.get('player').children.find(node => node.tag === 'track');
  const vtt = await (await fetch(captions.src)).text();
  assert.match(vtt, /00:00:01\.500 --> 00:00:02\.250\nEdited opening/);
  const edited = Buffer.from(await ui.output().arrayBuffer());
  const probe = spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name', '-of', 'json', 'pipe:0'], { input: edited });
  assert.equal(probe.status, 0);
  assert.deepEqual(JSON.parse(probe.stdout).streams.map(s => s.codec_name), ['h264', 'aac', 'mov_text']);
  assert.match(ui.downloads.at(-1).name, /\.mp4$/);
  await ui.click('save');
  const saved = await (await fetch(ui.downloads.at(-1).url)).text();
  assert.equal(JSON.parse(saved).scenes[1].clipId, clipId);
  assert(!saved.includes(source.toString('base64').slice(0, 80)));
  ui.get('open-file').files = [new File([saved], 'Edit.rafii.json')];
  await ui.get('open-file').fire('change');
  assert.equal(ui.get('export').disabled, true);
  await importVideo('Renamed original.mp4');
  assert.equal(ui.get('export').disabled, true);
  await importAudio();
  assert.equal(ui.get('export').disabled, false);
  await ui.click('preview');
  assert.deepEqual(Buffer.from(await ui.output().arrayBuffer()), edited);
  ui.get('reference-source').value = 'sample';
  ui.get('reference-rights').checked = true;
  await ui.submit('reference-form');
  assert.equal(ui.state().reference.shots.length, 3);
  ui.get('brief').value = 'Show how to set the practice timer.';
  ui.get('brand').value = 'Meridian';
  ui.get('subject').value = 'practice timer';
  await ui.get('brief-form').fire('input');
  await ui.click('blueprint');
  assert.match(ui.state().scenes[0].direction, /Meridian/);
  assert(ui.state().scenes.every(s => s.clipId === null));
  assert.equal(ui.get('export').disabled, true);
  await ui.click('undo');
  assert.equal(ui.state().scenes[1].clipId, clipId);
});
