'use client';

import { useCallback, useEffect, useState } from 'react';
import type { ButtonState } from '@/components/motion/button';
import { ApiError } from '@/lib/api/client';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export const PORTAL = 'portal';

export interface BillingRedirect {
  /** Button state for a target: `portal` or a plan terms id. */
  stateFor: (target: string) => ButtonState;
  /** The backend's own words for the last failure on that target (409, 429, 502, 503…). */
  errorFor: (target: string) => string | null;
  busy: boolean;
  openPortal: () => void;
  startCheckout: (planTermsId: string) => void;
}

/**
 * Checkout and the billing portal are provider-hosted pages: the API returns a URL and the
 * browser leaves. The loading state is the real request; on success the page navigates away
 * (no success flash), on failure the button shows the error and the message stays readable.
 */
export function useBillingRedirect(): BillingRedirect {
  const { api, workspaceId } = useWorkspaceApi();
  const [pending, setPending] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ target: string; message: string } | null>(null);

  // Coming back with the browser's Back button can restore this page from memory mid-"loading".
  useEffect(() => {
    const reset = (event: PageTransitionEvent) => {
      if (event.persisted) setPending(null);
    };
    window.addEventListener('pageshow', reset);
    return () => window.removeEventListener('pageshow', reset);
  }, []);

  const go = useCallback(
    async (target: string, request: () => Promise<{ url: string }>) => {
      if (pending) return;
      setFailure(null);
      setPending(target);
      try {
        const { url } = await request();
        window.location.assign(url);
      } catch (err) {
        setPending(null);
        setFailure({
          target,
          message:
            err instanceof ApiError
              ? err.message
              : target === PORTAL
                ? 'The billing portal could not be opened.'
                : 'Checkout could not be started.'
        });
      }
    },
    [pending]
  );

  return {
    stateFor: (target) => (pending === target ? 'loading' : failure?.target === target ? 'error' : 'idle'),
    errorFor: (target) => (failure?.target === target ? failure.message : null),
    busy: pending !== null,
    openPortal: () => void go(PORTAL, () => api.portal(workspaceId)),
    startCheckout: (planTermsId) => void go(planTermsId, () => api.checkout(workspaceId, planTermsId))
  };
}
