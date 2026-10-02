/**
 * Source upload intake decisions (src/lib/growth-v2/source-uploads-model.ts; RAFII Product Growth review M20 and lows):
 * the panel is gated on the feature but keeps earlier uploads manageable when it is off, only readable formats are
 * offered, page ranges are explained before they are sent (with the server's own character count), server sentences
 * read in Traditional Chinese with their measured values kept, and the wiring that stops focus theft and aborts a
 * stopped transcript.
 *
 *   node --test web/tests/source-uploads-intake.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { classifyFile, COPY, errorText, pageRangeProblem, panelMode, pickerFor } from '../src/lib/growth-v2/source-uploads-model.ts';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));
const read = (path) => readFileSync(SRC + path, 'utf8');
const CJK = /[一-鿿]/;

test('the panel: gated on the feature, earlier uploads stay manageable when it is off, nothing flashes while unknown', () => {
  assert.equal(panelMode('loading', true, 5), 'hidden', 'not known yet: neither an "off" note nor a switched-off route');
  assert.equal(panelMode('on', true, 0), 'full');
  assert.equal(panelMode('on', true, 4), 'full');
  assert.equal(panelMode('on', false, 0), 'hidden');
  assert.equal(panelMode('on', false, 2), 'view');
  assert.equal(panelMode('off', true, 0), 'hidden', 'off with nothing from before: nothing renders');
  assert.equal(panelMode('off', true, 3), 'manage', 'off: earlier uploads stay readable, cancellable and deletable');
  assert.equal(panelMode('off', false, 3), 'manage');
  for (const lang of ['en', 'zh-Hant']) assert.ok(COPY[lang].titleManage && COPY[lang].offNote);
  assert.match(COPY.en.offNote, /turned off/);
  assert.match(COPY.en.offNote, /delete earlier uploads/);
});

test('only what this deployment can read is offered: no audio while audio is unsupported', () => {
  const limits = (pdf, audio, accepts) => ({ formats: { pdf: { supported: pdf }, audio: { supported: audio, accepts } } });
  const noAudio = pickerFor(limits(true, false, ['audio/mp4']), 'en');
  assert.equal(noAudio.title, 'Upload a PDF or transcript');
  assert.doesNotMatch(noAudio.accept, /audio|\.m4a|\.mp3|\.wav|\.ogg|\.opus/);
  assert.match(noAudio.accept, /\.pdf/);
  assert.match(noAudio.accept, /\.srt,\.vtt,\.txt/);
  assert.equal(noAudio.hint, 'PDF, or a transcript (SRT, VTT, TXT)');
  assert.doesNotMatch(`${noAudio.title} ${noAudio.hint}`, /M4A|MP3|WAV|recording/i);

  const someAudio = pickerFor(limits(true, true, ['audio/mpeg', 'audio/wav']), 'en');
  assert.equal(someAudio.title, 'Upload a PDF or recording');
  assert.match(someAudio.accept, /\.mp3/);
  assert.match(someAudio.accept, /\.wav/);
  assert.doesNotMatch(someAudio.accept, /\.m4a|audio\/mp4/, 'only the formats the private bucket accepts');
  assert.equal(someAudio.hint, 'PDF, MP3, WAV, or a transcript (SRT, VTT, TXT)');

  const transcriptsOnly = pickerFor(limits(false, false, []), 'en');
  assert.equal(transcriptsOnly.title, 'Upload a transcript');
  assert.equal(transcriptsOnly.hint, 'A transcript (SRT, VTT, TXT)');
  assert.doesNotMatch(transcriptsOnly.accept, /pdf|audio/);

  const zh = pickerFor(limits(true, false, []), 'zh-Hant');
  assert.equal(zh.title, '上載 PDF 或逐字稿');
  assert.equal(zh.hint, 'PDF，或逐字稿（SRT、VTT、TXT）');
  const loading = pickerFor(null, 'en');
  assert.equal(loading.title, 'Upload a file', 'unknown limits advertise nothing');
  assert.equal(loading.hint, '');
});

test('a refused file is told only about formats this deployment reads', () => {
  const limits = (pdf, audio, accepts) => ({
    limits: { audio: { maxBytes: 30_000_000, maxSeconds: 600 }, pdf: { maxBytes: 20_000_000, maxPages: 100, maxCharacters: 60_000 } },
    formats: { pdf: { supported: pdf }, audio: { supported: audio, accepts } }
  });
  const mov = { name: 'clip.mov', type: 'video/quicktime', size: 10 };
  assert.equal(classifyFile(mov, limits(true, true)).message, 'Choose a PDF, a recording (M4A, MP3, WAV, Ogg/Opus) or a transcript (SRT, VTT, TXT).');
  assert.equal(classifyFile(mov, limits(true, false)).message, 'Choose a PDF or a transcript (SRT, VTT, TXT).');
  assert.equal(classifyFile(mov, limits(false, false)).message, 'Choose a transcript (SRT, VTT, TXT).');
  assert.equal(classifyFile(mov, limits(true, true), 'zh-Hant').message, '請選擇 PDF、錄音（M4A、MP3、WAV、Ogg/Opus）或逐字稿（SRT、VTT、TXT）。');
  assert.equal(classifyFile(mov, limits(true, false), 'zh-Hant').message, '請選擇 PDF 或逐字稿（SRT、VTT、TXT）。');
  const webm = { name: 'rec.webm', type: 'audio/webm', size: 10 };
  assert.equal(classifyFile(webm, limits(true, false)).code, 'audio_unavailable', 'no "export as M4A" while audio is off');
  assert.equal(classifyFile(webm, limits(true, true)).code, 'webm');
  const m4a = classifyFile({ name: 'memo.m4a', type: 'audio/x-m4a', size: 10 }, limits(true, true, ['audio/mpeg']));
  assert.equal(m4a.code, 'unsupported_format', 'a type the private bucket doesn’t take is refused before upload');
  assert.equal(m4a.message, 'Choose a PDF, a recording (MP3) or a transcript (SRT, VTT, TXT).');
  assert.equal(classifyFile({ name: 'memo.mp3', type: '', size: 10 }, limits(true, true, ['audio/mpeg'])).ok, true);
});

test('a page range is explained in place, before anything is sent', () => {
  const pdf = { total: 12, maxPages: 5 };
  assert.equal(pageRangeProblem({ from: 1, to: 5 }, pdf, 'en'), null);
  assert.equal(pageRangeProblem({ from: 0, to: 5 }, pdf, 'en'), 'Start at page 1 or later.', 'an emptied field reads as 0');
  assert.equal(pageRangeProblem({ from: 4, to: 2 }, pdf, 'en'), 'The last page can’t come before the first.');
  assert.equal(pageRangeProblem({ from: 10, to: 13 }, pdf, 'en'), 'This PDF has 12 pages; choose pages within it.');
  assert.equal(pageRangeProblem({ from: 1, to: 6 }, pdf, 'en'), 'Choose at most 5 pages at a time.');
  assert.equal(pageRangeProblem({ from: 1.5, to: 3 }, pdf, 'en'), 'Use whole page numbers.');
  for (const range of [{ from: 0, to: 1 }, { from: 3, to: 2 }, { from: 1, to: 13 }, { from: 1, to: 6 }, { from: 1.5, to: 2 }]) {
    assert.match(pageRangeProblem(range, pdf, 'zh-Hant'), CJK, JSON.stringify(range));
  }
});

test('the character limit uses the server’s own count: page texts plus a blank line between pages', () => {
  const pdf = { total: 3, maxPages: 100, maxChars: 60_000, pages: [{ page: 1, chars: 30_000 }, { page: 2, chars: 30_000 }, { page: 3, chars: 10 }] };
  assert.equal(pageRangeProblem({ from: 1, to: 2 }, pdf, 'en'), 'These pages have about 60,002 characters of text; the limit is 60,000. Choose fewer pages.');
  assert.equal(pageRangeProblem({ from: 2, to: 3 }, pdf, 'en'), null, '30,012 fits');
  assert.equal(pageRangeProblem({ from: 1, to: 1 }, pdf, 'en'), null);
  assert.equal(pageRangeProblem({ from: 1, to: 2 }, { total: 3, maxPages: 100, maxChars: 60_000 }, 'en'), null, 'unmeasured pages are left to the server');
});

test('server sentences read in Traditional Chinese, with every measured value kept', () => {
  const measured = [
    ['over_limit', 'This file is 24 MB; the limit is 20 MB.', '這個檔案有 24 MB，上限是 20 MB。'],
    ['over_limit', 'This recording is 10:01 long; the limit is 10:00.', '這段錄音長 10:01，上限是 10:00。'],
    ['over_limit', 'This recording is longer or larger than the transcription route accepts (10:00, 25 MB).', '這段錄音超出轉錄路線可接受的長度或大小（10:00、25 MB）。'],
    ['over_limit', 'This text has 61,000 characters; the limit is 60,000.', '這段文字有 61,000 個字元，上限是 60,000。'],
    ['over_limit', 'This transcript file has 700,000 characters; the limit is 600,000.', '這個逐字稿檔案有 700,000 個字元，上限是 600,000。'],
    ['over_limit', 'This transcript has 61,000 characters; the limit is 60,000. Shorten it first.', '這份逐字稿有 61,000 個字元，上限是 60,000。請先刪減。'],
    ['insufficient_budget', 'This transcription can use up to 1.2 credits. Set the limit to at least 1.2.', '這次轉錄最多可能使用 1.2 點。請把上限設為至少 1.2 點。']
  ];
  for (const [code, sentence, chinese] of measured) {
    assert.equal(errorText(code, sentence, 'zh-Hant'), chinese);
    assert.equal(errorText(code, sentence, 'en'), sentence, 'English keeps the server’s sentence');
  }
  const codes = ['source_created', 'captions_required', 'not_a_pdf', 'not_awaiting_pages', 'invalid_pages', 'sample_read_only', 'quote_required', 'not_awaiting_quote',
    'quote_not_needed', 'revision_limit', 'not_awaiting_review', 'source_empty', 'not_ready', 'upload_not_pending', 'unsafe_url', 'workspace_revision_conflict',
    'idempotency_conflict', 'feature_disabled', 'storage_unavailable', 'review_required', 'upgrade_required', 'credits_required'];
  for (const code of codes) {
    const server = `The server's own sentence for ${code}.`;
    assert.match(errorText(code, server, 'zh-Hant'), CJK, code);
    assert.doesNotMatch(errorText(code, server, 'zh-Hant'), /server's own/, code);
  }
  assert.equal(errorText('source_created', 'A source was already created from this text.', 'en'), 'A source was already created from this text.');
  assert.equal(errorText('brand_new_code', 'Brand new words.', 'zh-Hant'), 'Brand new words.', 'an unknown code keeps the server’s sentence');
});

test('wiring: no limits request while the feature is off, focus moves only on the person’s action, a stopped transcript aborts', () => {
  const panel = read('features/ideas/source-upload-panel.tsx');
  assert.match(panel, /useGrowthFeatureState\('sourceUploads'\)/);
  assert.match(panel, /useSourceUploadLimits\(feature === 'on'\)/);
  assert.match(panel, /panelMode\(/);
  assert.doesNotMatch(panel, /\[view\?\.next\]/, 'no focus effect keyed on the polled next step (M20)');
  assert.match(panel, /if \(takeFocus\) heading\.current\?\.focus\(\)/, 'the detail takes focus once, on opening');
  assert.match(panel, /setTakeFocus\(focusIsWithin\(/, 'a finished upload never pulls focus from elsewhere');
  assert.match(panel, /rows\.current\.get\(id\)/, 'closing returns focus to the upload’s row');
  assert.match(panel, /<Surface as='section' lang=\{lang\}/);
  assert.match(panel, /accept=\{picker\.accept\}/);
  assert.match(panel, /pageRangeProblem\(/);
  assert.match(panel, /wasStopped\(error, controller\.signal\)/);
  const hooks = read('lib/growth-v2/source-uploads-hooks.ts');
  assert.match(hooks, /api\.addTranscript\(w, \{[^}]*\}, input\.signal\)/);
});
