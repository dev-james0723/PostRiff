'use client';

/**
 * Growth credit bridge (Pricing v2): a Creator workspace pays for Post Doctor, rewrites, Genome, postmortems and
 * audience runs through a credit quote for that exact request. The server answers `402 approval_required` when a
 * request has no quote; this hook then prices the same body, shows the most it can cost, and resends it with the
 * quote only after the person confirms. Nothing runs or is charged before that.
 */
import { useCallback, useMemo, useState } from 'react';
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

  const run = useCallback(
    async (kind: GrowthCreditKind, body: Record<string, unknown>, send: (body: Record<string, unknown>) => Promise<T>): Promise<T | null> => {
      try {
        return await send(body);
      } catch (error) {
        if (!needsCreditApproval(error) || !workspaceId) throw error;
        setQuoting(true);
        try {
          const quote = await requester.send<GrowthCreditQuote>('POST', `${ws(workspaceId)}/growth/credit-quotes`, { kind, request: body });
          setPending({ quote, resend: () => send({ ...body, creditQuoteId: quote.quoteId }) });
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
