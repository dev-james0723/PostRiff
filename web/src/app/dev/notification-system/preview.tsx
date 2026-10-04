'use client';

import { useEffect, useState } from 'react';
import { Icons } from '@/components/icons';
import { NotificationCenter } from '@/features/notifications/notification-center';
import { RafiiLivePill } from '@/features/notifications/live-pill';
import type { RafiiLiveState } from '@/features/notifications/live-state';
import type { NotificationViewModel } from '@/features/notifications/presentation';

const sampleTime = Date.UTC(2026, 9, 3, 17, 0);
const samples: NotificationViewModel[] = [
  { id: 'fixture:critical', source: 'server', sourceId: 'critical', kind: 'critical', priority: 'critical', title: 'Publishing failed', description: 'A scheduled post could not publish. Review the channel before trying again.', createdAt: sampleTime - 120_000, unread: true, actionable: true, durable: true, dismissible: false, href: '/app/channels', openLabel: 'Review failure' },
  { id: 'fixture:action', source: 'server', sourceId: 'action', kind: 'action_required', priority: 'high', title: 'Draft needs approval', description: 'Three drafts are ready for your review.', createdAt: sampleTime - 240_000, unread: true, actionable: true, durable: true, dismissible: false, href: '/app/queue', openLabel: 'Review drafts' },
  { id: 'fixture:info', source: 'server', sourceId: 'info', kind: 'info', priority: 'low', title: 'Post published', description: 'Your scheduled post is live.', createdAt: sampleTime - 360_000, unread: true, actionable: false, durable: true, dismissible: true, href: '/app/analytics' },
  { id: 'fixture:security', source: 'server', sourceId: 'security', kind: 'security', priority: 'critical', title: 'New device sign-in', description: 'Review the recent session and secure your account if this was not you.', createdAt: sampleTime - 480_000, unread: true, actionable: true, durable: true, dismissible: false, href: '/app/account/profile', openLabel: 'Review sessions' }
];

function liveState(value?: string): RafiiLiveState {
  switch (value) {
    case 'running': return { status: 'running', label: 'Rafii · drafting', href: '/app/agent/fixture', count: 1, progress: 42 };
    case 'waiting': return { status: 'waiting', label: 'Needs your input', href: '/app/queue' };
    case 'success': return { status: 'success', label: 'Rafii finished', href: '/app/agent/fixture' };
    case 'error': return { status: 'error', label: 'Rafii couldn’t finish', href: '/app/agent/fixture' };
    default: return { status: 'idle' };
  }
}

export function NotificationSystemPreview({ count, state, partial }: { count?: string; state?: string; partial: boolean }) {
  const number = Math.max(0, Math.min(4, Number(count ?? '3') || 0));
  const [items, setItems] = useState(samples.slice(0, number));
  const [pending, setPending] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const onRead = async (item: NotificationViewModel) => {
    setPending(true);
    await new Promise((resolve) => setTimeout(resolve, 300));
    setItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, unread: false } : entry));
    setPending(false);
    return { verified: true, status: 'read' };
  };
  const onArchive = async (item: NotificationViewModel) => {
    setPending(true);
    await new Promise((resolve) => setTimeout(resolve, 300));
    setItems((current) => current.filter((entry) => entry.id !== item.id));
    setPending(false);
    return { verified: true, status: 'dismissed' };
  };

  return (
    <main data-ready={hydrated ? 'true' : undefined} className='min-h-screen bg-background p-3 text-foreground sm:p-8'>
      <div className='mx-auto max-w-4xl'>
        <p className='mb-4 text-xs font-medium uppercase tracking-widest text-muted-foreground'>Synthetic visual fixture · no provider calls</p>
        <header className='flex min-h-16 items-center justify-between gap-3 rounded-2xl border border-border bg-card px-3 shadow-sm sm:px-5'>
          <span className='truncate text-sm font-semibold'>Rafii workspace</span>
          <div className='flex items-center gap-3'>
            <RafiiLivePill state={liveState(state)} onOpen={() => undefined} />
            <span className='grid size-11 shrink-0 place-items-center rounded-xl border border-border bg-background' aria-hidden='true'><Icons.notification className='size-5' /></span>
          </div>
        </header>
        <div className='mt-6 max-w-[23rem] rounded-2xl border border-border bg-card p-3 shadow-lg sm:p-4'>
          <h1 className='mb-2 text-sm font-semibold'>Notification center</h1>
          <NotificationCenter items={items} partial={partial} loading={pending} onRead={onRead} onArchive={onArchive} onViewAll={() => undefined} />
        </div>
      </div>
    </main>
  );
}
