// node app/reproduce_studio_example.cjs path/to/veo-experiment-20261127.mp4
// Run the shipped editor with its offline DOM harness and real local media worker.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { resolveObjectURL } = require('node:buffer');
const { openEditor } = require('./test_studio_editor.cjs');

const examples = path.resolve(__dirname, '../docs/creative-intelligence/examples');
const referenceDir = path.join(examples, 'timer-study');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const durations = [1250, 1500, 1250];
const captions = ['一個念頭', '變成一條片', '由一個鏡頭開始'];
const revisedCTA = '試剪你嘅第一條片';
const timeMs = () => Math.round(performance.now());
const expiresAt = Date.now() + 120000;
function remainingMs() {
  const remaining = expiresAt - Date.now();
  if (remaining <= 0) throw new Error('Time limit reached during ' + stage);
  return Math.min(30000, remaining);
}
function toolLimits() {
  return { timeout: remainingMs(), killSignal: 'SIGKILL', maxBuffer: 16 * 1024 * 1024 };
}
let stage = 'verify original media';
function progress(name) {
  stage = name;
  console.error('[Studio example] ' + name);
}
function ffmpeg(args, input) {
  return execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-xerror', ...args], { ...toolLimits(), input });
}
function voiceWav(source) {
  const pcm = ffmpeg(['-i', source, '-map', '0:a:0', '-t', '4', '-ar', '48000', '-ac', '2', '-f', 's16le', 'pipe:1']);
  assert.equal(pcm.length, 4 * 48000 * 2 * 2);
  const header = Buffer.alloc(44);
  header.write('RIFF'); header.writeUInt32LE(pcm.length + 36, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(2, 22);
  header.writeUInt32LE(48000, 24); header.writeUInt32LE(192000, 28); header.writeUInt16LE(4, 32);
  header.writeUInt16LE(16, 34); header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}
function streamInfo(raw) {
  return JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-count_frames', '-show_entries',
    'stream=codec_type,codec_name,width,height,avg_frame_rate,sample_rate,channels,duration,nb_read_frames',
    '-of', 'json', 'pipe:0'], { ...toolLimits(), input: raw })).streams;
}
function frameHashes(raw) {
  return ffmpeg(['-i', 'pipe:0', '-map', '0:v:0', '-an', '-pix_fmt', 'yuv420p', '-f', 'framehash', '-hash', 'sha256', 'pipe:1'], raw)
    .toString().split('\n').filter(line => line && !line.startsWith('#')).map(line => line.split(',').at(-1).trim());
}
function audioCorrelation(wav, mp4) {
  const audio = data => ffmpeg(['-i','pipe:0','-map','0:a:0','-ac','1','-ar','16000','-t','4','-f','s16le','pipe:1'], data);
  const first = audio(wav), second = audio(mp4);
  assert.equal(first.length, 128000);
  assert.equal(second.length, first.length);
  let aa = 0, ab = 0, bb = 0;
  for (let i = 0; i < first.length; i += 2) {
    const a = first.readInt16LE(i), b = second.readInt16LE(i);
    aa += a*a; ab += a*b; bb += b*b;
  }
  return ab / Math.sqrt(aa*bb);
}
async function main() {
  if (process.argv.length !== 3) throw Error('Supply the authorized original Veo experiment MP4.');
  progress(stage);
  const source = path.resolve(process.argv[2]);
  const material = fs.readFileSync(source);
  const production = JSON.parse(fs.readFileSync(path.join(examples, 'veo-experiment-20261127.json')));
  assert.equal(sha(material), production.sha256);
  const timerSha = sha(fs.readFileSync(path.join(referenceDir, 'reference.mp4')));
  const expectedRef = JSON.parse(fs.readFileSync(path.join(referenceDir, 'reference-analysis.json')));
  const originalTimer = JSON.parse(fs.readFileSync(path.join(referenceDir, 'render-receipt.json')));
  assert.equal(timerSha, expectedRef.sha256);
  const nativeClips = ['original-2', 'original-3'].map((id, index) => {
    const digest = sha(fs.readFileSync(path.join(referenceDir, id + '.mp4')));
    assert.equal(digest, originalTimer.firstExport.scenes[index + 1].clipSha256);
    return { id, sha256: digest };
  });
  progress('extract the four-second narration');
  const wav = voiceWav(source);
  const wavName = 'Cantonese narration.wav';
  const media = new File([material], path.basename(source), { type: 'video/mp4' });
  const voice = new File([wav], wavName, { type: 'audio/wav' });
  progress('open the editor');
  const ui = openEditor({ workerTimeoutMs: remainingMs });
  await ui.ready();
  const field = (id, value) => { ui.get(id).value = value; };
  const timings = {};
  async function timed(name, task) {
    progress(name);
    const start = timeMs(); const result = await task(); timings[name] = timeMs() - start; return result;
  }
  async function relink() {
    progress('relink source footage');
    ui.get('production-file').files = [media]; ui.get('production-rights').checked = true;
    await ui.submit('import-form');
    progress('relink narration');
    ui.get('audio-file').files = [voice]; ui.get('audio-rights').checked = true;
    await ui.submit('audio-form');
    assert.equal(ui.state().soundtrack.audioId, 'audio-' + sha(wav));
  }
  async function editScene(index, changes) {
    await ui.get('timeline').children[index].children[0].fire('click');
    for (const [id, value] of Object.entries(changes)) field(id, value);
    await ui.get('scene-form').fire('input');
    await ui.submit('scene-form');
  }
  async function exportCut(version) {
    assert.equal(ui.get('export').disabled, false);
    await timed(version + 'Render', () => ui.click('export'));
    assert.equal(ui.get('notice').textContent, 'MP4 exported.');
    const raw = Buffer.from(await ui.output().arrayBuffer());
    await ui.click('save');
    const project = await resolveObjectURL(ui.downloads.at(-1).url).text();
    progress(version + ' frame verification');
    return { raw, project, hashes: frameHashes(raw) };
  }

  field('reference-source', 'sample'); ui.get('reference-rights').checked = true;
  await timed('referenceAnalysis', () => ui.submit('reference-form'));
  const reference = ui.state().reference;
  assert.equal(reference.sha256, timerSha);
  assert.deepEqual(reference.shots.map(s => s.endMs - s.startMs), durations);
  for (const [key, value] of Object.entries({
    'project-name': '一個念頭，變成一條片', aspect: '9:16', brand: 'Rafii', subject: 'an idea taking shape on an edit timeline',
    audience: 'Hong Kong creators making their first short film',
    brief: 'Open on a presenter and a paper bird. Use the timer cuts to give the idea a rhythm, then invite the viewer to make a first cut.'
  })) field(key, value);
  await ui.get('brief-form').fire('input');
  await timed('brandBlueprint', () => ui.click('blueprint'));
  assert.deepEqual(ui.state().scenes.map(s => s.durationMs), durations);
  assert(ui.state().scenes.every(s => s.direction.includes('Rafii') && !s.clipId));
  await relink();
  const generated = 'upload-' + production.sha256;
  for (const [index, id] of [generated, 'original-2', 'original-3'].entries()) {
    await editScene(index, { 'scene-clip': id, caption: captions[index] });
  }
  const first = await exportCut('first');
  await editScene(0, { trim: '1.25' });
  await editScene(2, { caption: revisedCTA });
  const revised = await exportCut('revised');

  const firstState = JSON.parse(first.project), nextState = JSON.parse(revised.project);
  assert.equal(nextState.scenes[0].trimStartMs, 1250);
  assert.equal(nextState.scenes[0].clipId, generated);
  assert.equal(nextState.scenes[2].caption, revisedCTA);
  assert.deepEqual(firstState.scenes[1], nextState.scenes[1]);
  assert.deepEqual(firstState.reference, nextState.reference);
  for (const [version, cut] of Object.entries({ first, revised })) {
    ui.get('open-file').files = [new File([cut.project], version + '.rafii.json')];
    await ui.get('open-file').fire('change');
    assert.equal(ui.get('export').disabled, true);
    await relink();
    assert.equal(ui.get('export').disabled, false);
    await timed(version + 'ReopenRender', () => ui.click('preview'));
    assert.equal(sha(Buffer.from(await ui.output().arrayBuffer())), sha(cut.raw));
  }
  assert.equal(first.hashes.length, 96);
  assert.equal(revised.hashes.length, 96);
  assert(first.hashes.slice(0,30).every((digest, i) => digest !== revised.hashes[i]));
  assert.deepEqual(first.hashes.slice(30), revised.hashes.slice(30));
  function describe(version, cut, expectedCaptions) {
    progress('verify ' + version + ' streams, captions and narration');
    const streams = streamInfo(cut.raw);
    assert.deepEqual(streams.map(s => s.codec_name), ['h264', 'aac', 'mov_text']);
    assert.equal(streams[0].width, 720); assert.equal(streams[0].height, 1280);
    assert.equal(streams[0].avg_frame_rate, '24/1'); assert.equal(Number(streams[0].duration), 4);
    const srt = ffmpeg(['-i', 'pipe:0', '-map', '0:s:0', '-f', 'srt', 'pipe:1'], cut.raw).toString().replaceAll('\r','');
    const cues = srt.trim().split(/\n\n+/).map(cue => cue.split('\n').slice(1));
    assert.deepEqual(cues.map(c => c[1]), expectedCaptions);
    assert.deepEqual(cues.map(c => c[0]), ['00:00:00,000 --> 00:00:01,250','00:00:01,250 --> 00:00:02,750','00:00:02,750 --> 00:00:04,000']);
    const correlation = audioCorrelation(wav, cut.raw);
    assert(correlation > 0.98);
    return { sha256: sha(cut.raw), bytes: cut.raw.length, projectSha256: sha(cut.project), revision: JSON.parse(cut.project).revision,
      streams, captions: cues, correlationWithSourceVoiceAt16kHz: Number(correlation.toFixed(6)) };
  }
  const receipt = { createdAt: new Date().toISOString(), scope: 'Shipped editor controller, offline DOM harness and real Studio media worker. Private local render.',
    node: process.version, gitBase: execFileSync('git',['rev-parse','HEAD'],{...toolLimits(),cwd:__dirname}).toString().trim(),
    applicationSourceSha256: Object.fromEntries(['studio-editor.js','studio_media.py'].map(name => [name, sha(fs.readFileSync(path.join(__dirname,name)))])),
    inputs: { referenceSha256: timerSha, productionFile: media.name, productionSha256: production.sha256, originalTimerClips: nativeClips,
      voiceFile: wavName, voiceSha256: sha(wav), voiceOrigin: 'Complete 4-second audio from the earlier original Veo presenter take, decoded locally to stereo 48 kHz PCM.' },
    historicalGeneration: { model: production.model, estimateUsd: production.budget.estimate_usd, billedUsd: production.budget.actual_billed_usd,
      receipt: 'docs/creative-intelligence/examples/veo-experiment-20261127.json', transcriptFromOriginalReceipt: production.playback.speech_check.transcript },
    newProviderRequests: 0, newProviderSpendUsd: 0, measuredMs: timings,
    first: describe('first', first, captions), revised: describe('revised', revised, [captions[0], captions[1], revisedCTA]),
    decodedPictureComparison: { method: 'SHA-256 of each decoded YUV420p frame; zero-based indices.', changedFramesInclusive: [0,29],
      identicalFramesInclusive: [30,95], identicalCount: 66, identicalTailHashListSha256: sha(first.hashes.slice(30).join('\n')) },
    reopen: 'Opened each saved JSON in the editor, relinked the hashed video and WAV, and confirmed a byte-identical second render.',
    limits: 'Cantonese voice is reused as a continuous voiceover. Captions are switchable timed text. Local project brand context. Creative approval and publication were outside this run.'
  };
  const root = path.join(__dirname,'.local-evidence');
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  const folder = fs.mkdtempSync(path.join(root,'presenter-cut-'));
  const files = { 'first-cut.mp4': first.raw, 'revised-cut.mp4': revised.raw, 'first.rafii.json': first.project,
    'revised.rafii.json': revised.project, [wavName]: wav, 'receipt.json': JSON.stringify(receipt, null, 2) + '\n' };
  for (const [name,data] of Object.entries(files)) fs.writeFileSync(path.join(folder,name), data, { mode: 0o600, flag:'wx' });
  console.log(folder);
  console.log(JSON.stringify({ measuredMs: timings, first: receipt.first.sha256, revised: receipt.revised.sha256, identicalTailFrames: 66 }));
}
// The individual child limits also cover synchronous waits while this JS timer cannot run.
const deadline = setTimeout(() => {
  console.error('Studio example timed out during ' + stage);
  process.exit(1);
}, 120000);
main().catch(error => { console.error('Studio example failed during ' + stage, error); process.exitCode = 1; })
  .finally(() => clearTimeout(deadline));
