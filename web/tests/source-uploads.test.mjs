/**
 * Source upload presentation (src/lib/growth-v2/source-uploads-model.ts): limits checked before a file is sent,
 * truthful states in English and Traditional Chinese, and bounded status polling (PRD R-FWR-04, R-NFR-03/04).
 *
 *   node --test web/tests/source-uploads.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyFile, COPY, copyFor, errorText, formatCredits, formatDuration, formatMegabytes, languageFor, pollDelay, presentState, reasonText, transcriptText } from '../src/lib/growth-v2/source-uploads-model.ts';

const LIMITS = {
  limits: { audio: { maxBytes: 30_000_000, maxSeconds: 600 }, pdf: { maxBytes: 20_000_000, maxPages: 100, maxCharacters: 60_000 } },
  formats: { pdf: { supported: true }, audio: { supported: true } }
};
const NO_AUDIO = { ...LIMITS, formats: { pdf: { supported: true }, audio: { supported: false } } };
const SERVER_REASONS = ['mime_mismatch', 'over_limit', 'size_mismatch', 'duration_unreadable', 'unsupported', 'no_text_layer', 'encrypted', 'pdf_unreadable',
  'pdf_parser_unavailable', 'transcription_route_not_enabled', 'provider_limit', 'outcome_unknown', 'transcript_empty', 'storage_unavailable', 'extraction_timeout',
  'attempts_exhausted', 'object_missing', 'object_changed', 'provider_refused', 'user_cancelled', 'user_deleted', 'review_expired', 'retention_elapsed',
  'source_retracted', 'upload_expired', 'membership_revoked', 'account_deletion', 'lease_expired', 'worker_error', 'quote_missing', 'upload_missing'];

const view = (job, extra = {}) => ({ kind: 'pdf', state: 'committed', reason: null, next: 'wait', job: job && { attempts: 1, maxAttempts: 3, reason: null, kind: 'pdf_text', ...job }, ...extra });

test('the person’s display language picks English or Traditional Chinese', () => {
  for (const tag of ['zh-Hant', 'zh-HK', 'zh-TW', 'zh-Hant-MO', 'yue-Hant-HK']) assert.equal(languageFor(tag), 'zh-Hant', tag);
  for (const tag of ['en', 'en-GB', 'zh-CN', 'zh-Hans', 'fr', '', undefined]) assert.equal(languageFor(tag), 'en', String(tag));
  assert.equal(copyFor('zh-HK'), COPY['zh-Hant']);
});

test('both languages carry every string, and the Chinese copy is really Chinese', () => {
  assert.deepEqual(Object.keys(COPY['zh-Hant']).sort(), Object.keys(COPY.en).sort());
  for (const [key, value] of Object.entries(COPY['zh-Hant'])) {
    const sample = typeof value === 'function' ? value(1, '2', 3) : value;
    assert.match(String(sample), /[一-鿿]/, key);
  }
});

test('AC11 limits are stated before a file is chosen', () => {
  assert.equal(COPY.en.limitsPdf(formatMegabytes(20_000_000), 100, '60,000'), 'PDF: up to 20 MB, 100 pages and 60,000 characters of text.');
  assert.match(COPY.en.limitsAudio(formatMegabytes(30_000_000), 10), /10 minutes and 30 MB/);
  assert.match(COPY.en.limitsAudio('30 MB', 10), /credits; you see the cost first/);
});

test('AC11 files are classified and checked against the published limits', () => {
  assert.deepEqual(classifyFile({ name: 'Brief.PDF', type: '', size: 1000 }, LIMITS), { ok: true, kind: 'pdf', mime: 'application/pdf' });
  assert.deepEqual(classifyFile({ name: 'memo.m4a', type: 'audio/x-m4a', size: 1000 }, LIMITS), { ok: true, kind: 'audio', mime: 'audio/x-m4a' });
  assert.deepEqual(classifyFile({ name: 'memo.mp3', type: '', size: 1000 }, LIMITS), { ok: true, kind: 'audio', mime: 'audio/mpeg' });
  assert.deepEqual(classifyFile({ name: 'voice.opus', type: '', size: 1000 }, LIMITS), { ok: true, kind: 'audio', mime: 'audio/ogg' });
  assert.deepEqual(classifyFile({ name: 'talk.srt', type: '', size: 10 }, LIMITS), { ok: true, kind: 'transcript', format: 'srt' });
  assert.deepEqual(classifyFile({ name: 'talk.vtt', type: 'text/vtt', size: 10 }, LIMITS), { ok: true, kind: 'transcript', format: 'vtt' });
  const big = classifyFile({ name: 'big.pdf', type: 'application/pdf', size: 24_300_000 }, LIMITS);
  assert.equal(big.ok, false);
  assert.equal(big.code, 'over_limit');
  assert.equal(big.message, 'This file is 24 MB; the limit is 20 MB.');
  assert.equal(classifyFile({ name: 'huge.srt', type: '', size: 5_000_000 }, LIMITS).code, 'over_limit');
  assert.equal(classifyFile({ name: 'rec.webm', type: 'audio/webm', size: 10 }, LIMITS).code, 'webm');
  assert.equal(classifyFile({ name: 'clip.mov', type: 'video/quicktime', size: 10 }, LIMITS).code, 'unsupported_format');
  assert.equal(classifyFile({ name: 'page.html', type: 'text/html', size: 10 }, LIMITS).code, 'unsupported_format');
});

test('AC11 without a transcription route, audio says so plainly and points to transcripts', () => {
  const refused = classifyFile({ name: 'memo.m4a', type: 'audio/mp4', size: 10 }, NO_AUDIO);
  assert.equal(refused.code, 'audio_unavailable');
  assert.match(refused.message, /transcript \(SRT, VTT or TXT\)/);
  assert.match(classifyFile({ name: 'memo.m4a', type: 'audio/mp4', size: 10 }, NO_AUDIO, 'zh-Hant').message, /逐字稿/);
});

test('every reason the server can give has words in both languages', () => {
  for (const reason of SERVER_REASONS) {
    for (const lang of ['en', 'zh-Hant']) {
      const said = reasonText(reason, lang);
      assert.ok(said && !said.includes('_'), `${reason}/${lang}`);
    }
  }
  assert.equal(reasonText(null, 'en'), null);
  assert.equal(reasonText('something_new', 'en'), 'Something new');
});

test('states are truthful: an unknown outcome keeps its cost pending and is not offered as a retry', () => {
  const unknown = presentState(view({ state: 'failed', reason: 'outcome_unknown', kind: 'transcription' }), 'en');
  assert.equal(unknown.tone, 'error');
  assert.match(unknown.detail, /cost is held/);
  assert.match(unknown.detail, /won’t be retried automatically/);
  assert.equal(presentState(view({ state: 'needs_review', reason: 'quote_required', kind: 'transcription' }), 'en').label, 'Needs your OK to transcribe');
  assert.equal(presentState(view({ state: 'needs_review', reason: 'page_selection_required' }), 'en').label, 'Choose pages');
  assert.equal(presentState(view({ state: 'needs_review', reason: 'text_review' }), 'en').label, 'Ready to review');
  assert.equal(presentState(view({ state: 'queued', attempts: 1, reason: 'storage_unavailable' }), 'en').label, 'Retrying soon (attempt 2 of 3)');
  assert.equal(presentState(view({ state: 'completed' }), 'en').label, 'Source created');
  assert.equal(presentState(view(null, { state: 'rejected', reason: 'mime_mismatch' }), 'en').detail, 'The file isn’t the type it says it is, so it was deleted.');
  assert.equal(presentState(view({ state: 'unsupported', reason: 'no_text_layer' }), 'zh-Hant').label, '不支援');
  for (const job of [{ state: 'queued' }, { state: 'running' }, { state: 'needs_review', reason: 'text_review' }, { state: 'completed' }, { state: 'failed', reason: 'storage_unavailable' }]) {
    for (const lang of ['en', 'zh-Hant']) {
      const said = presentState(view(job), lang);
      assert.doesNotMatch(`${said.label} ${said.detail ?? ''}`, /publish|scheduled|posted|發佈|排程/i, JSON.stringify(job));
    }
  }
});

test('R-NFR-04 status polling is bounded and stops when nothing is running', () => {
  assert.equal(pollDelay(view({ state: 'queued' }), 0), 2000);
  assert.equal(pollDelay(view({ state: 'running' }), 45_000), 5000);
  assert.equal(pollDelay(view({ state: 'running' }), 181_000), false);
  assert.equal(pollDelay(view({ state: 'needs_review', reason: 'text_review' }), 0), false);
  assert.equal(pollDelay(view(null, { state: 'pending' }), 0), false);
  assert.equal(pollDelay(undefined, 0), false);
});

test('known error codes are said in the person’s language; others keep the server’s sentence', () => {
  assert.equal(errorText('review_required', 'Review the text first: nothing becomes a source until a person has read it.', 'zh-Hant'), '請先檢查文字。');
  assert.equal(errorText('insufficient_budget', 'This transcription can use up to 1.2 credits.', 'en'), 'This transcription can use up to 1.2 credits.');
  assert.equal(errorText('something_else', 'Server words.', 'zh-Hant'), 'Server words.');
  // AC11: a limit refusal keeps the measured value from the server in every language.
  assert.equal(errorText('over_limit', 'This recording is 10:01 long; the limit is 10:00.', 'zh-Hant'), 'This recording is 10:01 long; the limit is 10:00.');
  assert.equal(errorText(undefined, 'Fallback.', 'en'), 'Fallback.');
});

test('formatting helpers', () => {
  assert.equal(formatDuration(612.4), '10:12');
  assert.equal(formatDuration(null), '0:00');
  assert.equal(formatCredits(12300), '12.3');
  assert.equal(formatMegabytes(4_200_000), '4.2 MB');
  assert.equal(transcriptText('﻿WEBVTT'), 'WEBVTT');
});
