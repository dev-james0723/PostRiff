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

/** The server refused a remembered quote as used, expired or changed (`credit_wallet.CreditBook`): price it again. */
export function staleCreditApproval(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && !error.code;
}

/** The body a request goes out with: its confirmed quote, when this request key already has one. */
export function withConfirmedQuote(body: Record<string, unknown>, confirmed: ReadonlyMap<string, string>): Record<string, unknown> {
  const key = typeof body.requestKey === 'string' ? body.requestKey : null;
  const quoteId = key ? confirmed.get(key) : undefined;
  return quoteId ? { ...body, creditQuoteId: quoteId } : body;
}

interface Pending<T> {
  quote: GrowthCreditQuote;
  resend: () => Promise<T>;
}

/** `run(kind, body, send)` sends once; if a quote is needed it parks the request until `confirm()` or `cancel()`. */
export function useGrowthCreditApproval<T>(workspaceId: string | null) {
  const { getToken } = useAuth();
  const requester = useMemo(() => createRequester(getToken), [getToken]);
  const [pending, setPending] = useState<Pending<T> | null>(null);
  const [quoting, setQuoting] = useState(false);
  // request key → the quote the person confirmed for it (kept for retries after a lost response).
  const confirmed = useRef(new Map<string, string>());

  const run = useCallback(
    async (kind: GrowthCreditKind, body: Record<string, unknown>, send: (body: Record<string, unknown>) => Promise<T>): Promise<T | null> => {
      const key = typeof body.requestKey === 'string' ? body.requestKey : null;
      const outgoing = withConfirmedQuote(body, confirmed.current);
      try {
        return await send(outgoing);
      } catch (error) {
        const stale = outgoing !== body && staleCreditApproval(error);
        if (stale && key) confirmed.current.delete(key);
        if ((!needsCreditApproval(error) && !stale) || !workspaceId) throw error;
        setQuoting(true);
        try {
          const quote = await requester.send<GrowthCreditQuote>('POST', `${ws(workspaceId)}/growth/credit-quotes`, { kind, request: body });
          setPending({
            quote,
            resend: () => {
              if (key) confirmed.current.set(key, quote.quoteId);
              return send({ ...body, creditQuoteId: quote.quoteId });
            }
          });
          return null;
        } finally {
          setQuoting(false);
        }
      }
    },
    [requester, workspaceId]
  );

  const confirm = useCallback(async (): Promise<T | null> => {
    if (!pending) return null;
    const { resend } = pending;
    setPending(null);
    return resend();
  }, [pending]);

  const cancel = useCallback(() => setPending(null), []);
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
