'use client';

import { useMemo } from 'react';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useIsMobile } from '@/hooks/use-mobile';
import { useAudit } from '@/lib/api/hooks';
import type { AuditEvent, ChannelView } from '@/lib/api/types';
import { capabilityLabel } from '@/lib/channels/capabilities';
import { formatDateTime } from '@/lib/time';

function text(value: unknown) {
  return typeof value === 'string' && value ? value : null;
}

function list(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/** One plain line per audit event about this account. Unknown kinds fall back to the raw kind. */
export function describeChannelEvent(event: AuditEvent): { label: string; detail: string | null; tone: 'neutral' | 'warning' } {
  const meta = event.meta ?? {};
  switch (event.kind) {
    case 'channel.connected': {
      const capability = text(meta.capability);
      const level = text(meta.publishLevel);
      const missing = list(meta.missingScopes);
      const parts = [
        capability ? `${capabilityLabel(capability)} requested` : null,
        level ? `publish ${level}` : null,
        missing.length ? `missing scopes: ${missing.join(', ')}` : null
      ].filter(Boolean);
      return { label: 'Connected', detail: parts.length ? parts.join(' · ') : null, tone: missing.length ? 'warning' : 'neutral' };
    }
    case 'channel.verified': {
      const state = text(meta.state);
      const verified = state === 'publish_verified' || state === 'read_verified';
      return { label: verified ? 'Re-verified' : 'Re-verify found a problem', detail: state ? state.replace(/_/g, ' ') : null, tone: verified ? 'neutral' : 'warning' };
    }
    case 'channel.disconnected':
      return { label: 'Disconnected', detail: meta.remoteRevoked ? 'token revoked at the provider' : 'token wiped here; the provider did not confirm a revoke', tone: 'neutral' };
    default:
      return { label: event.kind.replace(/[._]/g, ' '), detail: null, tone: 'neutral' };
  }
}

/** The audit trail for one account: every connect, re-verify and disconnect the workspace recorded. */
export function ChannelHistorySheet({
  channel,
  open,
  onOpenChange
}: {
  channel: ChannelView;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const isMobile = useIsMobile();
  const audit = useAudit();
  const events = useMemo(
    () => (audit.data?.events ?? []).filter((event) => event.subject === channel.id),
    [audit.data, channel.id]
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side={isMobile ? 'bottom' : 'right'} className='data-[side=bottom]:max-h-[92dvh] data-[side=right]:sm:max-w-md'>
        <SheetHeader>
          <SheetTitle className='flex items-center gap-2'>
            <ChannelIcon platform={channel.platform} name={channel.platform} size='xs' />
            {channel.platform} · {channel.account}
          </SheetTitle>
          <SheetDescription>
            From the workspace audit trail. The trail returns the last 200 workspace events, so older accounts may show only part of their history.
          </SheetDescription>
        </SheetHeader>
        <div className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4'>
          {audit.isLoading ? (
            <div className='flex flex-col gap-2' aria-busy>
              <Skeleton className='h-10 w-full' />
              <Skeleton className='h-10 w-full' />
              <Skeleton className='h-10 w-3/4' />
            </div>
          ) : audit.error ? (
            <Alert variant='destructive'>
              <Icons.alertCircle className='size-4' />
              <AlertTitle>History could not be loaded</AlertTitle>
              <AlertDescription>{audit.error instanceof Error ? audit.error.message : 'The audit trail did not respond.'}</AlertDescription>
            </Alert>
          ) : events.length === 0 ? (
            <p className='text-muted-foreground text-sm'>No events for this account in the last 200 workspace events.</p>
          ) : (
            <ol className='flex flex-col divide-y'>
              {events.map((event, index) => {
                const described = describeChannelEvent(event);
                return (
                  <li key={event.id ?? `${event.kind}-${event.at}-${index}`} className='flex flex-col gap-0.5 py-2.5'>
                    <div className='flex items-baseline justify-between gap-3'>
                      <span className={described.tone === 'warning' ? 'text-amber-700 dark:text-amber-300 text-sm font-medium' : 'text-sm font-medium'}>
                        {described.label}
                      </span>
                      <time className='text-muted-foreground shrink-0 text-xs' dateTime={new Date(event.at * 1000).toISOString()}>
                        {formatDateTime(event.at)}
                      </time>
                    </div>
                    {described.detail && <span className='text-muted-foreground text-xs'>{described.detail}</span>}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
        <SheetFooter className='flex-row justify-end'>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
