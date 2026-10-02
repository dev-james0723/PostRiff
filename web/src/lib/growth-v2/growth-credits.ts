'use client';

/**
 * Growth credit bridge (Pricing v2): a Creator workspace pays for Post Doctor, rewrites, Genome, postmortems and
 * audience runs through a credit quote for that exact request. The server answers `402 approval_required` when a
 * request has no quote; this hook then prices the same body, shows the most it can cost, and resends it with the
 * quote only after the person confirms. Nothing runs or is charged before that.
 *
 * A confirmed limit stays with its request key. When the confirmed request's response is lost and the person tries
 * again, the same key goes back with the same quote, and the server answers with the run it already made — no second
 * charge and no "request key belongs to another input". A quote the server calls used or expired (the first send
 * never arrived) is forgotten and priced again.
 *
 * A waiting limit belongs to the exact request it priced. The panel cancels it whenever an input or the consent
 * changes, and `confirm(current)` takes the request as the screen shows it now: if it differs from the priced one,
 * nothing is sent and the person starts again (a limit is never spent on a request they no longer see).
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { createRequester, ws } from './request';

export type GrowthCreditKind = 'check' | 'rewrite' | 'genome' | 'postmortem' | 'audience';
export interface GrowthCreditQuote {
  quoteId: string;
  maxMilliCredits: number;
  maxCredits: number;
  expiresAt: number;
  kind: GrowthCreditKind;
}

export function needsCreditApproval(error: unknown): boolean {
  return error instanceof ApiError && error.status === 402 && error.code === 'approval_required';
}

/**
 * The server's own sentences for a quote that can no longer pay (`credit_wallet.CreditBook`: `quote` used or expired,
 * `claim` already claimed, `prepare` policy or request changed). They carry no code of their own — only the generic
 * 409 `conflict` every uncoded 409 gets (`AlphaError`) — so the exact sentence is matched.
 */
const STALE_QUOTE_MESSAGES: ReadonlySet<string> = new Set([
  'Credit approval is used or expired. Review it again.',
  'This credit approval was already claimed.',
  'The model or credit policy changed. Review again.'
]);

/** The server refused a remembered quote as used, expired or changed: price it again. Any other 409 is its own error. */
export function staleCreditApproval(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && (!error.code || error.code === 'conflict') && STALE_QUOTE_MESSAGES.has(error.message);
}

/** Said when Confirm meets a request that no longer matches the one its limit priced: nothing was sent. */
export const REQUEST_CHANGED = 'This request changed after its credit limit was shown, so nothing was sent or charged. Start it again to see the limit for it.';

/** Key order never matters; the quote id is not part of the request a quote prices. */
function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item && typeof item === 'object' && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item as Record<string, unknown>).toSorted(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
      : item
  );
}

/** Whether two Growth request bodies are the same request (what a credit quote binds: everything but the quote id). */
export function sameGrowthRequest(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const { creditQuoteId: _a, ...left } = a;
  const { creditQuoteId: _b, ...right } = b;
  return canonical(left) === canonical(right);
}

/** The body a request goes out with: its confirmed quote, when this request key already has one. */
export function withConfirmedQuote(body: Record<string, unknown>, confirmed: ReadonlyMap<string, string>): Record<string, unknown> {
  const key = typeof body.requestKey === 'string' ? body.requestKey : null;
  const quoteId = key ? confirmed.get(key) : undefined;
  return quoteId ? { ...body, creditQuoteId: quoteId } : body;
}

interface Pending<T> {
  quote: GrowthCreditQuote;
  /** The exact request the quote priced (without the quote id). */
  body: Record<string, unknown>;
  send: (body: Record<string, unknown>) => Promise<T>;
}

/**
 * `run(kind, body, send)` sends once; if a quote is needed it parks the request until `confirm(current)` or `cancel()`.
 * `confirm` sends only when `current` (the request as the screen shows it now) is still the priced one.
 */
export function useGrowthCreditApproval<T>(workspaceId: string | null) {
  const { getToken } = useAuth();
  const requester = useMemo(() => createRequester(getToken), [getToken]);
  const [pending, setPending] = useState<Pending<T> | null>(null);
  const [quoting, setQuoting] = useState(false);
  // request key → the quote the person confirmed for it (kept for retries after a lost response).
  const confirmed = useRef(new Map<string, string>());
  // Every cancel moves this on: a quote that arrives after the input or consent changed is never parked.
  const generation = useRef(0);

  const run = useCallback(
    async (kind: GrowthCreditKind, body: Record<string, unknown>, send: (body: Record<string, unknown>) => Promise<T>): Promise<T | null> => {
      const key = typeof body.requestKey === 'string' ? body.requestKey : null;
      const outgoing = withConfirmedQuote(body, confirmed.current);
      const started = generation.current;
      try {
        return await send(outgoing);
      } catch (error) {
        const stale = outgoing !== body && staleCreditApproval(error);
        if (stale && key) confirmed.current.delete(key);
        if ((!needsCreditApproval(error) && !stale) || !workspaceId) throw error;
        setQuoting(true);
        try {
          const quote = await requester.send<GrowthCreditQuote>('POST', `${ws(workspaceId)}/growth/credit-quotes`, { kind, request: body });
          if (generation.current === started) setPending({ quote, body, send });
          return null;
        } finally {
          setQuoting(false);
        }
      }
    },
    [requester, workspaceId]
  );

  const confirm = useCallback(
    async (current: Record<string, unknown> | null): Promise<T | null> => {
      if (!pending) return null;
      setPending(null);
      const { quote, body, send } = pending;
      if (!current || !sameGrowthRequest(current, body)) throw new Error(REQUEST_CHANGED);
      const key = typeof body.requestKey === 'string' ? body.requestKey : null;
      if (key) confirmed.current.set(key, quote.quoteId);
      return send({ ...body, creditQuoteId: quote.quoteId });
    },
    [pending]
  );

  const cancel = useCallback(() => {
    generation.current += 1;
    setPending(null);
  }, []);
  return { run, confirm, cancel, pending: pending?.quote ?? null, quoting };
}

export function creditLimitLabel(quote: GrowthCreditQuote): string {
  return `This uses up to ${quote.maxCredits.toLocaleString('en', { maximumFractionDigits: 1 })} credits from your balance; you pay only the actual cost. Nothing runs until you confirm.`;
}

/**
 * The checkbox sentence before an AI run, in this workspace's billing words: a daily allowance exists only on legacy
 * plans (whose sentence is unchanged); on a credit plan each run shows its credit limit first; otherwise no claim.
 * `sentence` is the action without its ending, e.g. "Analyze these eligible comments with the allowed AI models".
 */
export function growthUseConsent(sentence: string, mode: 'free_preview' | 'managed_credits' | 'legacy_allowances' | null): string {
  if (mode === 'managed_credits') return `${sentence}. Rafii shows the credit limit before anything runs.`;
  if (mode === 'legacy_allowances') return `${sentence} within my daily allowance.`;
  return `${sentence}.`;
}
