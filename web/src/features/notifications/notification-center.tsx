'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { NotificationStack, type NotificationStackItem } from '@/components/motion/notification-stack';
import { NotificationCard } from '@/components/ui/notification-card';
import { StateMessage } from '@/components/rafii';
import { chooseSurfaces, sortNotifications, type NotificationViewModel } from './presentation';
import { requireConfirmedAction, type ConfirmedNotificationResult } from './actions';

export interface NotificationCenterProps {
  items: readonly NotificationViewModel[];
  loading?: boolean;
  partial?: boolean;
  onRead?: (item: NotificationViewModel) => Promise<ConfirmedNotificationResult>;
  onArchive?: (item: NotificationViewModel) => Promise<ConfirmedNotificationResult>;
  onViewAll: () => void;
  onNavigate?: () => void;
}

export function NotificationCenter({
  items, loading = false, partial = false, onRead, onArchive, onViewAll, onNavigate
}: NotificationCenterProps) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const ordered = useMemo(() => sortNotifications(items).filter((item) => chooseSurfaces(item).includes('center')), [items]);

  async function mutate(item: NotificationViewModel, action: 'read' | 'dismissed') {
    const key = item.id + ':' + action;
    if (pending) return;
    const request = action === 'read' ? onRead : onArchive;
    if (!request) return;
    setPending(key);
    setErrors((previous) => ({ ...previous, [item.id]: '' }));
    try {
      await requireConfirmedAction(() => request(item), action);
      if (action === 'dismissed') toast.success('Archived');
      else toast.success('Marked as read');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not update this notification. Try again.';
      setErrors((previous) => ({ ...previous, [item.id]: message }));
      toast.error(message);
    } finally {
      setPending(null);
    }
  }

  const stackItems: NotificationStackItem[] = ordered.map((item) => ({
    id: item.id,
    title: item.title,
    description: item.description,
    trailing: item.unread ? 'Unread' : undefined,
    expandedContent: (
      <NotificationCard
        id={item.id}
        title={item.title}
        body={item.description ?? ''}
        status={item.unread ? 'unread' : 'read'}
        kind={item.kind}
        createdAt={item.createdAt > 0 ? new Date(item.createdAt) : undefined}
        actions={item.href ? [{ id: 'open', label: item.openLabel ?? 'Open', type: 'redirect', style: 'primary' }] : []}
        onAction={() => {
          if (!item.href) return;
          onNavigate?.();
          router.push(item.href);
        }}
        onMarkAsRead={onRead && item.source !== 'attention' ? () => { void mutate(item, 'read'); } : undefined}
        onArchive={item.dismissible && onArchive ? () => { void mutate(item, 'dismissed'); } : undefined}
        loadingActionId={pending === item.id + ':read' ? 'read' : pending === item.id + ':dismissed' ? 'archive' : undefined}
        error={errors[item.id]}
      />
    )
  }));

  return (
    <section aria-label='Notification center' className='min-w-0'>
      {partial && <StateMessage kind='partial' layout='inline' title='Some updates couldn’t load.' description='Available notifications are shown below.' />}
      {loading && !ordered.length && <StateMessage kind='loading' layout='inline' title='Loading notifications…' />}
      {(!loading || ordered.length > 0) && (
        <NotificationStack
          interactive
          items={stackItems}
          maxVisible={3}
          collapsedLabel='Notification center'
          emptyLabel={partial ? 'Available sources have no updates.' : 'All caught up'}
          onViewAll={onViewAll}
          classNames={{ content: 'py-3', card: 'overflow-hidden' }}
        />
      )}
    </section>
  );
}
