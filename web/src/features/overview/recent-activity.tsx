'use client';

import type { CSSProperties } from 'react';
import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { useAudit, useChannels, useMe, useMembers } from '@/lib/api/hooks';
import type { AuditEvent, ChannelView, Member, ProviderView } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatBytes, formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { SectionUnavailable } from './retry';

const SHOWN = 8;

/**
 * Plain labels for the kinds the API writes (`hosted.py`, `oauth.py`, `billing.py` → `audit()`).
 * Kinds not listed fall back to the raw kind with its dots and underscores turned into spaces.
 */
const KIND_LABELS: Record<string, string> = {
  'workspace.created': 'Workspace created',
  'channel.connected': 'Channel connected',
  'channel.verified': 'Channel re-verified',
  'channel.disconnected': 'Channel disconnected',
  'oauth.started': 'Connection started',
  'oauth.denied': 'Connection declined at the provider',
  'oauth.rejected': 'Connection attempt rejected',
  'invitation.created': 'Invitation sent',
  'invitation.revoked': 'Invitation withdrawn',
  'invitation.accepted': 'Invitation accepted',
  'invitation.declined': 'Invitation declined',
  'member.updated': 'Member access changed',
  'member.removed': 'Member removed',
  'member.left': 'Member left',
  'billing.checkout_started': 'Checkout started',
  'billing.portal_opened': 'Billing portal opened',
  'data.exported': 'Workspace data exported',
  'data.diagnostics': 'Diagnostics exported',
  'reply.approved': 'Reply approved',
  'memory.egress_decided': 'Memory processing choice saved',
  'research.egress_decided': 'Web research choice saved',
  'session.revoked': 'Signed out a device',
  'session.revoked_others': 'Signed out other devices'
};

function kindLabel(event: AuditEvent) {
  if (event.kind === 'channel.verified') {
    const state = event.meta?.state;
    if (typeof state === 'string' && state !== 'publish_verified' && state !== 'read_verified') return 'Re-verify found a problem';
  }
  const label = KIND_LABELS[event.kind];
  if (label) return label;
  const raw = event.kind.replace(/[._]/g, ' ');
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function text(value: unknown) {
  return typeof value === 'string' && value ? value : null;
}

function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface Lookups {
  channels: readonly ChannelView[];
  providers: readonly ProviderView[];
}

function providerName(id: unknown, providers: readonly ProviderView[]) {
  const value = text(id);
  if (!value) return null;
  return providers.find((provider) => provider.id === value)?.platform ?? capitalise(value);
}

/**
 * What the event was about, from fields the API already keeps content-free: the account a channel
 * event names, the provider, a role, a plan or a size. Raw ids are never shown as a subject.
 */
function subjectOf(event: AuditEvent, { channels, providers }: Lookups) {
  const meta = event.meta ?? {};
  switch (event.kind) {
    case 'channel.connected':
    case 'channel.verified':
    case 'channel.disconnected': {
      const channel = channels.find((item) => item.id === event.subject);
      return channel ? `${channel.platform} · ${channel.account}` : providerName(meta.provider, providers);
    }
    case 'oauth.started':
    case 'oauth.denied':
    case 'reply.approved':
      return providerName(meta.provider, providers);
    case 'invitation.created':
    case 'invitation.accepted':
    case 'member.updated': {
      const role = text(meta.role);
      return role ? `Role: ${role}` : null;
    }
    case 'workspace.created': {
      const plan = text(meta.plan);
      return plan ? `${capitalise(plan)} plan` : null;
    }
    case 'data.exported':
      return typeof meta.bytes === 'number' ? formatBytes(meta.bytes) : null;
    case 'memory.egress_decided':
      return typeof meta.cloud === 'boolean' ? (meta.cloud ? 'Cloud processing allowed' : 'Kept on this device') : null;
    case 'research.egress_decided':
      return typeof meta.web === 'boolean' ? (meta.web ? 'Web research allowed' : 'Web research off') : null;
    default:
      return null;
  }
}

/** "You", a teammate's role, or the first characters of their id: members carry no names or emails here. */
function actorOf(event: AuditEvent, me: string | undefined, members: readonly Member[]) {
  if (!event.actor) return null;
  if (me && event.actor === me) return 'You';
  const member = members.find((item) => item.userId === event.actor);
  const id = event.actor.slice(0, 8);
  return member ? `${capitalise(member.role)} ${id}` : `Member ${id}`;
}

/** The latest workspace events in plain words: what happened, to what, by whom, and when. */
export function RecentActivity({ className }: { className?: string }) {
  const audit = useAudit();
  const channels = useChannels();
  const me = useMe();
  const members = useMembers();
  const access = useWorkspaceAccess();
  const canOpenLog = checkAccess(access, { role: 'admin' });
  const now = Date.now() / 1000;
  const events = audit.data?.events ?? [];
  const lookups: Lookups = { channels: channels.data?.channels ?? [], providers: channels.data?.providers ?? [] };
  const memberList = members.data?.members ?? [];

  return (
    <Card data-tour='overview-activity' className={className}>
      <CardHeader>
        <CardTitle>Recent activity</CardTitle>
        <CardDescription>Content-free audit trail of what happened in this workspace.</CardDescription>
      </CardHeader>
      <CardContent>
        {audit.isError ? (
          <SectionUnavailable message='Activity is unavailable right now.' query={audit} />
        ) : !audit.data ? (
          <Skeleton className='h-32 w-full' />
        ) : events.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No activity recorded yet.</p>
        ) : (
          <ul className='divide-y'>
            {events.slice(0, SHOWN).map((event, index) => {
              const subject = subjectOf(event, lookups);
              const actor = actorOf(event, me.data?.userId, memberList);
              const detail = [subject, actor].filter(Boolean).join(' · ');
              return (
                <li
                  key={event.id ?? `${event.kind}-${event.at}-${index}`}
                  // First paint only: a line that is already on screen keeps its key and does not replay.
                  className='t-stagger-line flex items-start justify-between gap-3 py-2 text-sm'
                  style={{ '--stagger-i': index } as CSSProperties}
                >
                  <div className='min-w-0'>
                    <p className='font-medium'>{kindLabel(event)}</p>
                    {detail && <p className='text-muted-foreground truncate text-xs'>{detail}</p>}
                  </div>
                  <time
                    dateTime={new Date(event.at * 1000).toISOString()}
                    title={formatDateTime(event.at)}
                    className='text-muted-foreground shrink-0 pt-0.5 text-xs whitespace-nowrap'
                  >
                    {relativeTime(event.at, now)}
                  </time>
                </li>
              );
            })}
          </ul>
        )}
        {canOpenLog ? (
          <Link href='/app/workspace/audit' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), 'mt-2 w-fit')}>
            Full audit log <LearnMoreChevron />
          </Link>
        ) : (
          <p className='text-muted-foreground mt-2 text-xs'>The full log is open to admins; ask one if you need it.</p>
        )}
      </CardContent>
    </Card>
  );
}
