'use client';

/**
 * The founder UiTransport (lane F; D-A22): the `__Host-rafii-control` cookie plus the CSRF token from `GET /session`, scoped to
 * the data mode and environment, with the control envelope unwrapped. Switching Demo/Live is a scope change.
 */
import { useMemo, useRef } from 'react';
import { createFounderUiTransport } from '@/lib/agent-runtime/use-ui-artifact-stream';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import type { UiTransport } from '@/features/agent/generative-ui/bridges/types';
import { useUiScope } from './transport';

export function useFounderUiTransport(): UiTransport | null {
  const { api, mode, environment, sessionStatus } = useFounderSession();
  const csrf = useRef<Promise<string> | null>(null);
  const transport = useMemo(() => {
    if (sessionStatus !== 'ready') return null;
    csrf.current = null;
    return createFounderUiTransport({
      mode, environment, principal: 'operator',
      csrf: () => {
        if (!csrf.current) {
          csrf.current = api.session().then((envelope) => envelope.data.csrfToken);
          csrf.current.catch(() => {
            csrf.current = null;
          });
        }
        return csrf.current;
      },
      resetCsrf: () => {
        csrf.current = null;
        api.resetSession();
      }
    });
  }, [api, mode, environment, sessionStatus]);
  useUiScope(transport);
  return transport;
}
