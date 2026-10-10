/**
 * Free, on-device understanding of a Library recording: is there speech, and if so what is said. Nothing is sent to
 * a paid service. The speech check reads loudness patterns of the decoded samples; speech recognition runs an open
 * Whisper model in a Web Worker in this browser (downloaded once per device and cached by the browser). Only the
 * resulting words — or "no speech" — are saved; the server then writes the summary with the same model-free
 * extractor it uses for documents.
 */
import { downloadAudio, readMonoPcm, SPEECH_RATE } from './audio-peaks';

/** Pinned, CDN-served transformers.js (ESM); loaded only inside the worker, never bundled into the app. */
const TRANSFORMERS = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1';
const MODEL = 'onnx-community/whisper-base';
/** On a phone, transcription takes roughly as long as the audio itself: a summary is made from the first 5 minutes. */
export const UNDERSTAND_SECONDS = 5 * 60;
const WINDOW = SPEECH_RATE * 30;

export type HeardStage =
  | { stage: 'reading'; seconds: number }
  | { stage: 'checking' }
  | { stage: 'downloading'; fraction: number | null }
  | { stage: 'transcribing'; seconds: number; total: number };
export type Heard = { speech: false } | { speech: true; text: string; partial: boolean };

/**
 * Share (0–1) of sounding one-second windows that move like speech: syllable-rate loudness with frequent dips to
 * less than half the window's average (pauses between words). Sustained music rarely dips that often.
 */
export function speechLikelihood(pcm: Float32Array, rate = SPEECH_RATE): number {
  const frame = Math.round(rate * 0.02), perWindow = 50;
  const energies: number[] = [];
  for (let start = 0; start + frame <= pcm.length; start += frame) {
    let sum = 0;
    for (let at = start; at < start + frame; at++) sum += pcm[at] * pcm[at];
    energies.push(sum / frame);
  }
  let loudest = 1e-12;
  for (const value of energies) if (value > loudest) loudest = value;
  let sounding = 0, speechy = 0;
  for (let first = 0; first + perWindow <= energies.length; first += perWindow) {
    const window = energies.slice(first, first + perWindow);
    const mean = window.reduce((sum, value) => sum + value, 0) / perWindow;
    if (mean < loudest * 1e-4) continue; // silence
    sounding++;
    const dips = window.filter(value => value < mean * 0.5).length / perWindow;
    if (dips >= 0.3) speechy++;
  }
  return sounding ? speechy / sounding : 0;
}

/** Brackets, music marks and the stock phrases Whisper is known to invent over music or silence. */
const INVENTED = [
  /\[[^\]]*\]|\([^)]*\)|【[^】]*】|♪|♫|🎵/g,
  /thank(s| you)( so much)? for watching[.!]?/gi,
  /please subscribe[^.!?]*[.!?]?/gi,
  /subtitles? (by|provided by)[^.!?]*[.!?]?/gi,
  /字幕[^。！？\n]*/g,
  /請不吝點贊[^。！？\n]*|请不吝点赞[^。！？\n]*|訂閱[^。！？\n]*|订阅[^。！？\n]*/g,
  /明鏡與點點欄目|明镜与点点栏目/g
];

/** What remains after removing invented filler; empty when nothing was really said. */
export function cleanTranscript(text: string): string {
  let clean = text;
  for (const pattern of INVENTED) clean = clean.replace(pattern, ' ');
  clean = clean.replace(/\s+/g, ' ').trim();
  // Whisper repeats one short line over music ("Thank you. Thank you. Thank you.").
  const sentences = clean.split(/[.!?。！？]+/).map(sentence => sentence.trim()).filter(Boolean);
  if (sentences.length >= 3 && new Set(sentences.map(sentence => sentence.toLowerCase())).size <= Math.ceil(sentences.length / 4)) return '';
  return clean;
}

/** Enough real words for the length of audio heard (characters for CJK, words otherwise). */
function saysSomething(text: string, seconds: number) {
  const cjk = (text.match(/[㐀-鿿가-힯぀-ヿ]/g) ?? []).length;
  const words = text.replace(/[㐀-鿿가-힯぀-ヿ]/g, ' ').split(/\s+/).filter(word => /[A-Za-z\u00c0-\u024f\u0400-\u04ff]{2,}/.test(word)).length;
  const amount = words + cjk / 2;
  return amount >= 8 && amount >= seconds / 60 * 6;
}

const WORKER = `
import { pipeline, env, Tensor } from '${TRANSFORMERS}';
env.allowLocalModels = false;
let asr = null;
// Whisper's own language guess from the first window (the library otherwise assumes English and would translate).
async function detectLanguage(audio) {
  const { input_features } = await asr.processor(audio);
  const config = asr.model.generation_config;
  const start = new Tensor('int64', BigInt64Array.from([BigInt(config.decoder_start_token_id)]), [1, 1]);
  const { logits } = await asr.model({ input_features, decoder_input_ids: start });
  const scores = logits.data, offset = scores.length - logits.dims.at(-1);
  let best = null, top = -Infinity;
  for (const [token, id] of Object.entries(config.lang_to_id || {})) {
    if (scores[offset + id] > top) { top = scores[offset + id]; best = token.slice(2, -2); }
  }
  return best;
}
self.onmessage = async (event) => {
  const { pcm, window } = event.data;
  try {
    asr ??= await pipeline('automatic-speech-recognition', '${MODEL}', {
      dtype: { encoder_model: 'q8', decoder_model_merged: 'q8' },
      device: 'wasm',
      progress_callback: (p) => { if (p.status === 'progress' && p.total) self.postMessage({ type: 'download', loaded: p.loaded, total: p.total, file: p.file }); }
    });
    let language = null;
    try { language = await detectLanguage(pcm.subarray(0, Math.min(pcm.length, window))); } catch (error) { language = null; }
    self.postMessage({ type: 'language', language });
    let text = '';
    for (let at = 0; at < pcm.length; at += window) {
      const options = language ? { task: 'transcribe', language } : { task: 'transcribe' };
      const out = await asr(pcm.subarray(at, Math.min(pcm.length, at + window)), options);
      text += ' ' + (out && out.text ? out.text : '');
      self.postMessage({ type: 'progress', done: Math.min(pcm.length, at + window), total: pcm.length });
    }
    self.postMessage({ type: 'done', text: text.trim(), language });
  } catch (error) {
    self.postMessage({ type: 'error', message: String((error && error.message) || error) });
  }
};
`;

function transcribeOnDevice(pcm: Float32Array, signal: AbortSignal, onStage: (stage: HeardStage) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const script = URL.createObjectURL(new Blob([WORKER], { type: 'text/javascript' }));
    const worker = new Worker(script, { type: 'module' });
    const files = new Map<string, { loaded: number; total: number }>();
    const stop = () => { worker.terminate(); URL.revokeObjectURL(script); };
    signal.addEventListener('abort', () => { stop(); reject(signal.reason); }, { once: true });
    worker.onerror = event => { stop(); reject(new Error(event.message || 'The speech model could not start in this browser.')); };
    worker.onmessage = ({ data }) => {
      if (data.type === 'download') {
        files.set(data.file, { loaded: data.loaded, total: data.total });
        const all = [...files.values()];
        onStage({ stage: 'downloading', fraction: all.reduce((sum, file) => sum + file.loaded, 0) / Math.max(1, all.reduce((sum, file) => sum + file.total, 0)) });
      } else if (data.type === 'progress') {
        onStage({ stage: 'transcribing', seconds: data.done / SPEECH_RATE, total: data.total / SPEECH_RATE });
      } else if (data.type === 'done') { stop(); resolve(String(data.text ?? '')); }
      else if (data.type === 'error') { stop(); reject(new Error(data.message)); }
    };
    onStage({ stage: 'downloading', fraction: null });
    worker.postMessage({ pcm, window: WINDOW }, [pcm.buffer]);
  });
}

/** Listen to one original: speech is transcribed on this device, music (or silence) is reported as no speech. */
export async function hearRecording(url: string, signal: AbortSignal, onStage: (stage: HeardStage) => void): Promise<Heard> {
  const bytes = await downloadAudio(url, signal);
  const pcm = await readMonoPcm(bytes, UNDERSTAND_SECONDS, signal, seconds => onStage({ stage: 'reading', seconds }));
  onStage({ stage: 'checking' });
  const seconds = pcm.length / SPEECH_RATE;
  if (seconds < 1 || speechLikelihood(pcm) < 0.15) return { speech: false };
  const raw = await transcribeOnDevice(pcm, signal, onStage);
  const text = cleanTranscript(raw);
  if (!saysSomething(text, seconds)) return { speech: false };
  return { speech: true, text, partial: bytes.length > 0 && seconds >= UNDERSTAND_SECONDS - 1 };
}
