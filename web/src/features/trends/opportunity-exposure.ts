'use client';
import { useEffect, useRef } from 'react';
import {
  exposureInputSchema,
  type ExposureInput,
  type TrendExposure,
  type TrendOpportunity
} from '@/lib/coworker/trend-types';
import type { TrendApi } from './api';

export type ExposurePage = {
  token: string | null;
  candidates: ExposureInput['eligible_candidates'];
};
type Session = {
  key: string;
  eventId: string;
  attempts: number;
  payload?: ExposureInput;
  result?: TrendExposure;
  pending?: Promise<string | undefined>;
};
/** Page order is significant. A missing token never becomes a fabricated view. */
export function exposurePage(
  token: string | null | undefined,
  opportunities: TrendOpportunity[]
): ExposurePage {
  return {
    token: token ?? null,
    candidates: opportunities
      .filter(
        (op) => ['candidate', 'ready'].includes(op.state) && op.verification_state === 'verified'
      )
      .map((op) => ({ opportunity_id: op.id, revision: op.revision }))
  };
}

/** At most one observer/timer and two attempts per mounted candidate binding.
 * This measures a client-reported card intersection, not attention or causality.
 */
export function useOpportunityExposure(
  api: TrendApi,
  workspace: string,
  op: TrendOpportunity,
  page: ExposurePage,
  enabled: boolean
) {
  const anchorRef = useRef<HTMLHeadingElement>(null);
  const session = useRef<Session | null>(null);
  const current = useRef({ page, op, enabled });
  current.current = { page, op, enabled };
  const key = JSON.stringify([
    workspace,
    op.id,
    op.revision,
    op.trust_receipt_id,
    op.context_digest,
    page.candidates
  ]);
  const getExposure = useRef<() => Promise<string | undefined>>(async () => undefined);
  const measurable =
    Boolean(page.token) && page.candidates.length > 0 && page.candidates.length <= 20;
  useEffect(() => {
    getExposure.current = async () => undefined;
    if (!enabled || !measurable || typeof IntersectionObserver === 'undefined') return;
    const element = anchorRef.current?.closest('[data-trend-opportunity]');
    if (!element) return;
    if (session.current?.key !== key)
      session.current = { key, eventId: crypto.randomUUID(), attempts: 0 };
    const bound = session.current;
    let mounted = true;
    let intersecting = false;
    let since: number | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();
    const active = () =>
      mounted &&
      current.current.enabled &&
      element.isConnected &&
      document.visibilityState === 'visible' &&
      intersecting;
    const clear = () => {
      clearTimeout(timer);
      timer = undefined;
      since = null;
    };
    // IO v2 marks the existing glass/filter surfaces compromised even when
    // readable. Use native geometric intersection plus current hit-testing.
    const unobscured = () => {
      const rect = element.getBoundingClientRect();
      if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= innerHeight || rect.left >= innerWidth)
        return false;
      const hit = document.elementFromPoint(
        (Math.max(0, rect.left) + Math.min(innerWidth, rect.right)) / 2,
        (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2
      );
      return Boolean(hit && element.contains(hit));
    };
    const record = async (): Promise<string | undefined> => {
      if (bound.result && Date.parse(bound.result.expires_at) > Date.now())
        return bound.result.exposure_id;
      if (bound.pending) return bound.pending;
      // Recheck immediately before dispatch; hidden/unmounted timers cannot report.
      if (!active() || since === null || performance.now() - since < 500 || bound.attempts >= 2)
        return undefined;
      if (!unobscured()) {
        clear();
        return undefined;
      }
      if (!bound.payload) {
        const latest = current.current;
        const parsed = exposureInputSchema.safeParse({
          event_id: bound.eventId,
          exposure_token: latest.page.token,
          opportunity_id: latest.op.id,
          opportunity_revision: latest.op.revision,
          trust_receipt_id: latest.op.trust_receipt_id,
          context_digest: latest.op.context_digest,
          eligible_candidates: latest.page.candidates
        });
        if (!parsed.success) return undefined;
        bound.payload = parsed.data;
      }
      bound.attempts += 1;
      const payload = bound.payload;
      bound.pending = api
        .recordExposure(workspace, payload, abort.signal)
        .then(({ data }) => {
          if (
            data.event_id !== payload.event_id ||
            data.opportunity_id !== payload.opportunity_id ||
            data.opportunity_revision !== payload.opportunity_revision ||
            data.trust_receipt_id !== payload.trust_receipt_id ||
            data.context_digest !== payload.context_digest ||
            data.eligible_candidate_count !== payload.eligible_candidates.length ||
            Date.parse(data.expires_at) <= Date.now()
          )
            return undefined;
          bound.result = data;
          return data.exposure_id;
        })
        .catch(() => undefined)
        .finally(() => {
          bound.pending = undefined;
        });
      return bound.pending;
    };
    const update = () => {
      if (!active() || !unobscured()) {
        clear();
        return;
      }
      if (since !== null || bound.result) return;
      since = performance.now();
      const check = () => {
        if (!active() || !unobscured()) {
          clear();
          return;
        }
        if (since !== null && performance.now() - since >= 500) {
          void record();
          return;
        }
        timer = setTimeout(check, 50);
      };
      timer = setTimeout(check, 50);
    };
    const observer = new IntersectionObserver(
      ([entry]) => {
        intersecting = Boolean(
          entry?.isIntersecting &&
          entry.intersectionRect.width > 0 &&
          entry.intersectionRect.height > 0
        );
        update();
      },
      { threshold: 0 }
    );
    observer.observe(element);
    let resumedFrame = 0;
    const resume = () => { cancelAnimationFrame(resumedFrame); resumedFrame = requestAnimationFrame(update); };
    document.addEventListener('visibilitychange', update);
    document.addEventListener('pointerup', resume, { passive: true });
    document.addEventListener('keyup', resume);
    document.addEventListener('focusin', resume);
    document.addEventListener('scroll', resume, { capture: true, passive: true });
    // Actions may await a qualified in-flight view or retry its exact UUID/body once.
    // Fast actions without a measured view preserve the optional-ID API contract.
    getExposure.current = record;
    return () => {
      mounted = false;
      clear();
      observer.disconnect();
      document.removeEventListener('visibilitychange', update);
      document.removeEventListener('pointerup', resume);
      document.removeEventListener('keyup', resume);
      document.removeEventListener('focusin', resume);
      document.removeEventListener('scroll', resume, true);
      cancelAnimationFrame(resumedFrame);
      abort.abort();
      getExposure.current = async () => undefined;
    };
  }, [api, workspace, key, enabled, measurable]);
  return { anchorRef, getExposure: () => getExposure.current() };
}
