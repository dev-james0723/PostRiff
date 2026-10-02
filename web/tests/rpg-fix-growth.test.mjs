/**
 * Product Growth v2 fix pass F1 (Growth credit bridge, web): a lost response is retried with the same request key and
 * the confirmed quote (no second charge, no 409), a used/expired quote is priced again, and Genome, postmortem and
 * Audience Miner use the same credit confirmation as Post Doctor (focus + live region).
 *
 *   node --test web/tests/rpg-fix-growth.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const WEB = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(WEB, 'src');
const read = (path) => readFileSync(join(SRC, path), 'utf8');

/** Load a TypeScript module with chosen imports replaced (`stubs[spec]`); everything else resolves like the app. */
function load(file, stubs = {}, cache = new Map()) {
  if (cache.has(file)) return cache.get(file).exports;
  const out = ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023, jsx: ts.JsxEmit.ReactJSX } });
  const mod = { exports: {} };
  cache.set(file, mod);
  const local = (spec) => {
    if (spec in stubs) return stubs[spec];
    if (!spec.startsWith('@/') && !spec.startsWith('.')) return require(spec);
    const base = spec.startsWith('@/') ? join(SRC, spec.slice(2)) : join(dirname(file), spec);
    for (const candidate of [`${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
      try {
        if (statSync(candidate).isFile()) return load(candidate, stubs, cache);
      } catch {}
    }
    throw new Error(`Cannot resolve ${spec} from ${file}`);
  };
  new Function('require', 'module', 'exports', out.outputText)(local, mod, mod.exports);
  return mod.exports;
}

class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** Just enough React for one hook rendered again and again: state slots persist between renders. */
function fakeReact() {
  const slots = [];
  let index = 0;
  return {
    render(hook) {
      index = 0;
      return hook();
    },
    useState(initial) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? initial() : initial;
      return [slots[slot], (value) => (slots[slot] = typeof value === 'function' ? value(slots[slot]) : value)];
    },
    useMemo(make) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = make();
      return slots[slot];
    },
    useCallback(fn) {
      index++;
      return fn;
    },
    useRef(initial) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = { current: initial };
      return slots[slot];
    }
  };
}

function harness() {
  const react = fakeReact();
  const quotes = [];
  const requester = {
    async send(method, path, body) {
      const quote = { quoteId: `q-${quotes.length + 1}`, maxMilliCredits: 120_000, maxCredits: 120, expiresAt: 1, kind: body.kind };
      quotes.push({ path, body, quote });
      return quote;
    }
  };
  const credits = load(join(SRC, 'lib/growth-v2/growth-credits.ts'), {
    react,
    '@/lib/api/client': { ApiError },
    '@/lib/auth/session': { useAuth: () => ({ getToken: async () => 'token' }) },
    './request': { createRequester: () => requester, ws: (w) => `/api/workspaces/${w}` }
  });
  const render = () => react.render(() => credits.useGrowthCreditApproval('w-1'));
  return { credits, render, quotes };
}

test('a lost response is retried with the same key and the confirmed quote: replayed, never charged twice', async () => {
  const { render, quotes } = harness();
  const sent = [];
  let lose = true;
  const send = async (body) => {
    sent.push(body);
    if (!body.creditQuoteId) throw new ApiError('Review the credit limit for this request first.', 402, 'approval_required');
    if (lose) {
      lose = false;
      throw new TypeError('Failed to fetch'); // the server ran it; the browser never heard back
    }
    return { runId: 'run-1' };
  };
  const body = { text: 'One idea.', confirmed: true, requestKey: 'key-1234567890abcdef' };
  assert.equal(await render().run('check', body, send), null, 'parked until the person confirms');
  const pending = render();
  assert.equal(pending.pending.quoteId, 'q-1');
  await assert.rejects(pending.confirm(body), TypeError);
  assert.deepEqual(await render().run('check', body, send), { runId: 'run-1' });
  assert.deepEqual(sent.map((b) => b.creditQuoteId ?? null), [null, 'q-1', 'q-1'], 'the retry resends the confirmed quote with the same key');
  assert.ok(sent.every((b) => b.requestKey === body.requestKey));
  assert.equal(quotes.length, 1, 'no second quote, no second approval');
});

test('a quote the server calls used or expired is priced again; other refusals pass through', async () => {
  const { render, quotes } = harness();
  const sent = [];
  let stale = true;
  const send = async (body) => {
    sent.push(body);
    if (!body.creditQuoteId) throw new ApiError('approval', 402, 'approval_required');
    if (body.creditQuoteId === 'q-1' && sent.length > 2 && stale) {
      stale = false;
      throw new ApiError('Credit approval is used or expired. Review it again.', 409);
    }
    if (sent.length === 2) throw new TypeError('Failed to fetch');
    return { ok: body.creditQuoteId };
  };
  const body = { confirmed: true, requestKey: 'key-abcdefabcdef1234' };
  await render().run('genome', body, send);
  await assert.rejects(render().confirm(body), TypeError);
  assert.equal(await render().run('genome', body, send), null, 'asks again instead of failing forever');
  assert.equal(render().pending.quoteId, 'q-2');
  assert.deepEqual(await render().confirm(body), { ok: 'q-2' });
  assert.equal(quotes.length, 2);
  const conflict = async () => {
    throw new ApiError('That request key belongs to another input.', 409, 'growth_key_conflict');
  };
  await assert.rejects(render().run('check', { requestKey: 'key-0000000000000000' }, conflict), /another input/);
});

test('helpers: the confirmed quote rides only with its own key; legacy consent wording is unchanged', () => {
  const { credits } = harness();
  const confirmed = new Map([['key-a', 'q-a']]);
  assert.deepEqual(credits.withConfirmedQuote({ requestKey: 'key-a', x: 1 }, confirmed), { requestKey: 'key-a', x: 1, creditQuoteId: 'q-a' });
  const other = { requestKey: 'key-b' };
  assert.equal(credits.withConfirmedQuote(other, confirmed), other);
  // Only the server's own stale-quote sentences (rpg-fix-web-2 L5); a bare 409 is its own error.
  assert.equal(credits.staleCreditApproval(new ApiError('Credit approval is used or expired. Review it again.', 409, 'conflict')), true);
  assert.equal(credits.staleCreditApproval(new ApiError('used', 409)), false);
  assert.equal(credits.staleCreditApproval(new ApiError('pending', 409, 'growth_request_pending')), false);
  const sentence = 'Analyze these eligible comments with the allowed AI models';
  assert.equal(credits.growthUseConsent(sentence, 'legacy_allowances'), 'Analyze these eligible comments with the allowed AI models within my daily allowance.');
  assert.doesNotMatch(credits.growthUseConsent(sentence, 'managed_credits'), /daily allowance/);
  assert.match(credits.growthUseConsent(sentence, 'managed_credits'), /credit limit before anything runs/);
  assert.doesNotMatch(credits.growthUseConsent(sentence, null), /allowance|credit/);
});

test('Genome, postmortem and Audience Miner pay through the confirmed credit limit like Post Doctor', () => {
  const wiring = [
    ['features/growth/genome-panel.tsx', "credits.run('genome'", 'api.analyzeHistory'],
    ['features/growth/growth-studio.tsx', "credits.run('postmortem'", 'api.postmortem'],
    ['features/growth/audience-miner.tsx', "credits.run('audience'", 'api.analyzeAudience']
  ];
  for (const [file, run, call] of wiring) {
    const source = read(file);
    assert.ok(source.includes(run), `${file} sends through the credit approval`);
    assert.ok(source.includes('useGrowthCreditApproval'), file);
    assert.match(source, /<GrowthCreditConfirm quote=\{credits\.pending\}/, `${file} shows the shared confirmation`);
    assert.match(source, /credits\.confirm\(requestBody\(\)\)/, `${file} confirms the request as the screen shows it now`);
    const direct = source.split(`${call}(`).length - 1;
    assert.equal(direct, 1, `${file} calls ${call} only inside credits.run`);
  }
  for (const file of ['features/growth/growth-studio.tsx', 'features/growth/audience-miner.tsx']) {
    assert.doesNotMatch(read(file), /'[^']*within my daily allowance\.'/, `${file} no longer hard-codes the allowance sentence`);
  }
  const doctor = read('features/growth/post-doctor-panel.tsx');
  assert.match(doctor, /export function GrowthCreditConfirm/);
  assert.match(doctor, /role='status' aria-live='polite'/, 'the waiting limit is announced');
  assert.match(doctor, /if \(quote\) group\.current\?\.focus\(\)/, 'focus moves to the confirmation');
  assert.match(doctor, /<GrowthCreditConfirm quote=\{credits\.pending\}/);
});
