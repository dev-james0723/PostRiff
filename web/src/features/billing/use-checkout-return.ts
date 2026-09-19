'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { UseQueryResult } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { Usage } from '@/lib/api/types';
import { CONFIRM } from './billing-copy';
import { CONFIRM_DEADLINE_MS, confirmPollDelay } from './billing-model';

export type ConfirmPhase = 'idle' | 'confirming' | 'confirmed' | 'timeout';

/** A last word if a refetch never settles: the deadline plus one full slow interval. */
const WATCHDOG_MS = CONFIRM_DEADLINE_MS + 15_000;

/**
 * The return from the provider's checkout page (`?checkout=success|cancelled`, set by
 * `hosted.billing_checkout`). Nothing is recorded until the provider's webhook arrives, so on
 * success the page re-reads `/usage` with backoff (2s → 10s, at most 2 minutes) until
 * `lifecycle.status` is `active`, then removes the query parameter. It never reports success
 * from the redirect alone.
 *
 * Polling lives here rather than in `useUsage` options, which this feature may not change.
 */
export function useCheckoutReturn(usage: UseQueryResult<Usage>): ConfirmPhase {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const outcome = params.get('checkout');
  const [phase, setPhase] = useState<ConfirmPhase>(() => (outcome === 'success' ? 'confirming' : 'idle'));
  const startedAt = useRef<number | null>(null);
  const attempt = useRef(0);
  const cancelledShown = useRef(false);

  const status = usage.data?.lifecycle?.status;
  const hasData = usage.data !== undefined;
  const { refetch, dataUpdatedAt, errorUpdatedAt } = usage;

  // One poll per settled read: each new result (or error) schedules the next check.
  useEffect(() => {
    if (phase !== 'confirming' || !hasData) return;
    if (status === 'active') {
      setPhase('confirmed');
      return;
    }
    startedAt.current ??= Date.now();
    const remaining = CONFIRM_DEADLINE_MS - (Date.now() - startedAt.current);
    if (remaining <= 0) {
      setPhase('timeout');
      return;
    }
    const timer = window.setTimeout(() => {
      attempt.current += 1;
      void refetch();
    }, Math.min(confirmPollDelay(attempt.current), remaining));
    return () => window.clearTimeout(timer);
  }, [phase, hasData, status, dataUpdatedAt, errorUpdatedAt, refetch]);

  useEffect(() => {
    if (phase !== 'confirming') return;
    const timer = window.setTimeout(() => setPhase((current) => (current === 'confirming' ? 'timeout' : current)), WATCHDOG_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  // The parameter goes once there is an answer, so a reload does not start polling again.
  useEffect(() => {
    const settled = phase === 'confirmed' || phase === 'timeout';
    if (outcome === 'cancelled' && !cancelledShown.current) {
      cancelledShown.current = true;
      toast.info(CONFIRM.cancelled);
    }
    if (!outcome || (outcome === 'success' && !settled)) return;
    const next = new URLSearchParams(params.toString());
    next.delete('checkout');
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [phase, outcome, params, pathname, router]);

  return phase;
}
