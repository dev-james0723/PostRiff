'use client';

import { useSyncExternalStore } from 'react';
import { avatarSession } from '@/lib/agent-runtime/avatar-bridge';

/** SoulX video overlays the existing Rafii stage only while current-generation frames arrive. */
export function SoulXAvatarLayer() {
  const snapshot = useSyncExternalStore(avatarSession.subscribe, avatarSession.get, avatarSession.get);
  if (snapshot.status === 'idle') return null;
  const frame = snapshot.frame;
  return (
    <div className='pointer-events-none absolute inset-0' data-rafii-soulx={snapshot.status}
      data-rafii-soulx-metrics={process.env.NODE_ENV === 'development' ? JSON.stringify(snapshot.metrics) : undefined}>
      {frame && snapshot.status === 'speaking' && (
        // The frame is produced by the configured local worker, not a user-supplied URL.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={frame.jpeg} alt='' className='h-full w-full object-contain' onLoad={() => requestAnimationFrame(() => avatarSession.displayed(frame.sequence))} />
      )}
      <span className='absolute bottom-1 left-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white' aria-live='polite'>
        {snapshot.status === 'offline' ? 'Avatar offline · voice continues' : `Avatar ${snapshot.status}`}
      </span>
    </div>
  );
}
