/**
 * Regression guard for the Vercel Functions request-body cap (4.5 MB): an image the library upload queue sends
 * must stay small enough, after base64 + JSON encoding, that the request never gets refused before it reaches
 * the app. See use-upload-queue.ts and src/lib/image/fit-for-upload.ts.
 *
 *   node --test web/tests/library-upload-body-size.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { SAFE_SEND_BYTES } from '../src/lib/image/fit-for-upload.ts';

// Mirrors use-library.ts MAX_UPLOAD_BYTES (the app/server image size limit). Not imported directly: that module
// pulls in `@/...`-aliased app code this plain `node --test` run can't resolve.
const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;

const VERCEL_BODY_CAP = 4_500_000;
// The actual request body: `{"action":"p2_media_upload","payload":{"data":"<base64>"},"revision":<n>}`.
const JSON_ENVELOPE_OVERHEAD = 256;

function worstCaseBodyBytes(rawBytes) {
  const base64Bytes = Math.ceil(rawBytes / 3) * 4;
  return base64Bytes + JSON_ENVELOPE_OVERHEAD;
}

test('SAFE_SEND_BYTES keeps the base64 upload body under the Vercel Functions body cap', () => {
  const body = worstCaseBodyBytes(SAFE_SEND_BYTES);
  assert.ok(body < VERCEL_BODY_CAP, `worst-case body ${body} must be under the ${VERCEL_BODY_CAP} byte cap`);
});

test('SAFE_SEND_BYTES is below the app/server image size limit, so re-encoding actually shrinks the file', () => {
  assert.ok(SAFE_SEND_BYTES < MAX_UPLOAD_BYTES);
});

test('an image just over the old failure threshold (~3.3 MB raw) would have exceeded the Vercel cap unencoded', () => {
  const raw = Math.ceil(3.3 * 1024 * 1024);
  assert.ok(worstCaseBodyBytes(raw) > VERCEL_BODY_CAP, 'this is the bug this fix addresses: confirms the reported threshold');
});

console.log('Library upload body-size assertions passed');
