import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import { validateAndMergeUi, type UiValidatorRequest } from '@/lib/agent-runtime/ui-parser';
import { BOUNDS, CONTRACT_VERSION } from '@/lib/agent-runtime/ui-contracts';

/**
 * Trusted OpenUI parser seam (A-owned route; C owns the imported adapter). Called server-to-server by the Python presenter
 * (src/postriff_phase2/agent_runtime_v2/ui_validator.py) with an HMAC over timestamp + body hash. Parses and applies policy
 * only: no rendering, network, queries or tool execution. Errors never echo source text (Sentry sees no DSL).
 */
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const KEY_ID = 'v1';
const SKEW_SECONDS = 60;
const HEADERS = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } as const;

function deny(status: number, code: string) {
  return Response.json({ accepted: false, errors: [code] }, { status, headers: HEADERS });
}

function verified(secret: string, stamp: string, signature: string, body: Buffer): boolean {
  const digest = createHash('sha256').update(body).digest('hex');
  const expected = createHmac('sha256', secret).update(`${KEY_ID}\n${stamp}\n${digest}`).digest();
  let given: Buffer;
  try {
    given = Buffer.from(signature, 'hex');
  } catch {
    return false;
  }
  return given.length === expected.length && timingSafeEqual(given, expected);
}

export async function POST(request: Request) {
  const secret = process.env.RAFII_GENUI_VALIDATOR_SECRET;
  if (!secret || secret.length < 32) return deny(503, 'validation_unavailable');
  const length = Number(request.headers.get('content-length') ?? '0');
  if (!Number.isFinite(length) || length <= 0 || length > BOUNDS.requestBodyBytes) return deny(413, 'source_too_large');
  if (!(request.headers.get('content-type') ?? '').startsWith('application/json')) return deny(415, 'bad_request');
  if (request.headers.get('x-rafii-validator-key') !== KEY_ID) return deny(401, 'unauthorized');
  const stamp = request.headers.get('x-rafii-validator-timestamp') ?? '';
  const signature = request.headers.get('x-rafii-validator-signature') ?? '';
  const now = Math.floor(Date.now() / 1000);
  if (!/^\d{9,11}$/.test(stamp) || Math.abs(now - Number(stamp)) > SKEW_SECONDS || !/^[0-9a-f]{64}$/.test(signature)) {
    return deny(401, 'unauthorized');
  }
  const body = Buffer.from(await request.arrayBuffer());
  if (body.length > BOUNDS.requestBodyBytes) return deny(413, 'source_too_large');
  if (!verified(secret, stamp, signature, body)) return deny(401, 'unauthorized');
  let input: UiValidatorRequest;
  try {
    input = JSON.parse(body.toString('utf8')) as UiValidatorRequest;
  } catch {
    return deny(400, 'bad_request');
  }
  if (!input || input.contractVersion !== CONTRACT_VERSION) return deny(400, 'contract_mismatch');
  try {
    return Response.json(validateAndMergeUi(input), { status: 200, headers: HEADERS });
  } catch {
    return Response.json({ accepted: false, errors: ['validator_error'] }, { status: 200, headers: HEADERS });
  }
}
