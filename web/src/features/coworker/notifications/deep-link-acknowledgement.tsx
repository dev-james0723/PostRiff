'use client';

import { useEffect, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { coworkerKeys, useCoworkerApi, useCoworkerFlag } from '@/lib/coworker/hooks';

/** Mounted after AppGate: a provider pixel or unauthenticated URL fetch cannot acknowledge an event. */
export function DeepLinkAcknowledgement() {
  const search = useSearchParams();
  const delivery = search.get('notification');
  const { api, w, enabled } = useCoworkerApi();
  const on = useCoworkerFlag('RAFII_NOTIFICATIONS_V2_ENABLED');
  const client = useQueryClient();
  const recorded = useRef<string | null>(null);
  useEffect(() => {
    if (!enabled || !w || on !== true || !delivery || !/^[0-9a-f-]{36}$/i.test(delivery)) return;
    const key = `${w}:${delivery}`;
    if (recorded.current === key) return;
    recorded.current = key;
    void api.acknowledgeNotification(w, delivery).then(() => client.invalidateQueries({ queryKey: coworkerKeys.notifications(w) })).catch(() => {
      // Failed acknowledgement is never presented as success; navigation/refocus can retry safely.
      recorded.current = null;
    });
  }, [api, w, enabled, on, delivery, client]);
  return null;
}
