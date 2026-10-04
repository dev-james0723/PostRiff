'use client';

import type { FC } from 'react';
import { Icons } from '@/components/icons';
import type { NotificationKind } from '@/features/notifications/presentation';
import { cn } from '@/lib/utils';

export type NotificationStatus = 'unread' | 'read' | 'archived';
export type ActionType = 'redirect' | 'api_call' | 'workflow' | 'modal';
export type ActionStyle = 'primary' | 'danger' | 'default';

export interface NotificationAction {
  id: string;
  label: string;
  type: ActionType;
  style?: ActionStyle;
  executed?: boolean;
}

export interface NotificationCardProps {
  id: string;
  title: string;
  body: string;
  status?: NotificationStatus;
  createdAt?: string | Date;
  actions?: NotificationAction[];
  onMarkAsRead?: (id: string) => void;
  onAction?: (notificationId: string, actionId: string, actionType: ActionType) => void;
  loadingActionId?: string;
  kind?: NotificationKind;
  error?: string | null;
  onArchive?: (id: string) => void;
  className?: string;
}

const formatDate = (date: string | Date): string => {
  const d = new Date(date);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric'
  });
};

const getActionIcon = (actionType: ActionType) => {
  const iconProps = { size: 12, strokeWidth: 2.5 };
  switch (actionType) {
    case 'redirect':
      return <Icons.externalLink {...iconProps} />;
    case 'api_call':
      return <Icons.check {...iconProps} />;
    case 'workflow':
      return <Icons.clock {...iconProps} />;
    case 'modal':
      return <Icons.alertCircle {...iconProps} />;
    default:
      return null;
  }
};

export const NotificationCard: FC<NotificationCardProps> = ({
  id,
  title,
  body,
  status = 'unread',
  createdAt,
  actions = [],
  onMarkAsRead,
  onAction,
  loadingActionId,
  kind = 'info',
  error,
  onArchive,
  className
}) => {
  const isUnread = status === 'unread';
  const semantic = kind === 'critical' || kind === 'security' ? 'text-destructive'
    : kind === 'warning' ? 'text-amber-700 dark:text-amber-300'
      : 'text-foreground';
  const KindIcon = kind === 'security' ? Icons.lock
    : kind === 'critical' || kind === 'warning' ? Icons.warning
      : kind === 'success' ? Icons.circleCheck : Icons.notification;

  return (
    <div
      className={cn(
        'group relative w-full rounded-2xl border border-border/70 bg-background text-foreground shadow-[0_5px_18px_rgb(0_0_0/0.06)]',
        className
      )}
    >
      <div className='px-4 py-3.5'>
        <div className='flex items-start justify-between gap-3'>
          <KindIcon aria-hidden='true' className={cn('mt-0.5 size-4 shrink-0', semantic)} />
          <div className='min-w-0 flex-1 space-y-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <h3
                className={cn(
                  'text-[15px] leading-tight font-semibold',
                  isUnread ? 'text-foreground' : 'text-muted-foreground'
                )}
              >
                {title}
              </h3>
              {isUnread && <span className='rounded-full border border-foreground/30 px-1.5 py-0.5 text-[10px] font-medium leading-none'>Unread</span>}
            </div>
            {body && <p className='mb-0 text-[13px] leading-relaxed text-muted-foreground'>{body}</p>}
          </div>
          {isUnread && onMarkAsRead && (
            <button
              type='button'
              disabled={loadingActionId === 'read'}
              onClick={() => onMarkAsRead(id)}
              className={cn(
                'rafii-focus grid size-11 shrink-0 place-items-center rounded-xl transition-colors',
                'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
              aria-label={'Mark ' + title + ' as read'}
            >
              {loadingActionId === 'read' ? <Icons.spinner size={16} className='animate-spin' /> : <Icons.check size={16} />}
            </button>
          )}
        </div>

        <div className='mt-3 flex flex-wrap items-end justify-between gap-2'>
          {actions.length > 0 && (
            <div className='flex flex-wrap items-center gap-2'>
              {actions.slice(0, 2).map((action) => {
                const isLoading = loadingActionId === action.id;
                const isExecuted = action.executed || false;
                const showLoading = isLoading && action.type !== 'modal';

                return (
                  <button
                    key={action.id}
                    type='button'
                    disabled={isLoading || isExecuted}
                    onClick={() => onAction?.(id, action.id, action.type)}
                    className={cn(
                      'rafii-focus flex min-h-11 items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-medium transition',
                      action.style === 'primary'
                        ? 'bg-primary/10 text-primary hover:bg-primary/20'
                        : action.style === 'danger'
                          ? 'bg-destructive/10 text-destructive hover:bg-destructive/20'
                          : 'bg-accent text-muted-foreground hover:bg-accent hover:text-foreground',
                      showLoading && 'opacity-50',
                      isExecuted && 'cursor-not-allowed opacity-60'
                    )}
                  >
                    {showLoading ? (
                      <Icons.spinner size={14} className='animate-spin' />
                    ) : (
                      <>
                        <span>{action.label}</span>
                        {isExecuted ? (
                          <Icons.check size={12} strokeWidth={2.5} />
                        ) : (
                          getActionIcon(action.type)
                        )}
                      </>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {/* Timestamp */}
          {createdAt && (
            <span className='text-muted-foreground inline-block text-[11px]'>
              {formatDate(createdAt)}
            </span>
          )}
        </div>
        {onArchive && (
          <button type='button' onClick={() => onArchive(id)} disabled={loadingActionId === 'archive'}
            className='rafii-focus mt-1 min-h-11 rounded-lg px-2 text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground'
            aria-label={'Archive ' + title}>
            {loadingActionId === 'archive' ? 'Archiving…' : 'Archive'}
          </button>
        )}
        {error && <p role='alert' className='mt-2 text-xs text-destructive'>{error}</p>}
      </div>
    </div>
  );
};
