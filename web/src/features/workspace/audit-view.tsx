'use client';

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { Icons } from '@/components/icons';
import PageContainer from '@/components/layout/page-container';
import { ActionSwapIcon } from '@/components/motion/action-swap';
import { Button } from '@/components/ui/button';
import { InfoButton } from '@/components/ui/info-button';
import type { InfobarContent } from '@/components/ui/infobar';
import { useAudit, useChannels, useMe, useMembers, useInvitations } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatNumber } from '@/lib/time';
import { AuditDetailSheet } from './audit/audit-detail-sheet';
import { AuditFilters, type ActorOption } from './audit/audit-filters';
import {
  AUDIT_API_LIMIT,
  FAMILIES,
  actorKey,
  dayLabel,
  eventKey,
  familyOf,
  groupByDay,
  inFamily,
  personOf,
  providersBySubject,
  type AuditLookup,
  type Family
} from './audit/audit-model';
import { AuditRow } from './audit/audit-row';
import { AuditCoverage, AuditEmpty, AuditFilterEmpty, AuditListSkeleton, AuditLoadError } from './audit/audit-states';

const infoContent: InfobarContent = {
  title: 'About the audit log',
  sections: [
    {
      title: 'What it records',
      description:
        'People joining, leaving and changing roles; ownership transfers; invitations; channels connected, re-checked and disconnected; data exports; the cloud memory and web research choices; billing checkouts; and approved replies. Each row says who, what and when.'
    },
    {
      title: 'Not recorded here yet',
      description: 'Post approvals, cancellations and publishing results. The Queue shows where each post stands.'
    },
    {
      title: 'Content-free by design',
      description: 'Events carry ids, kinds, counts and times — never post text, prompts, access tokens or email addresses. They cannot be edited.'
    },
    {
      title: 'How much this page shows',
      description: `The newest ${AUDIT_API_LIMIT} events. Counts and filters cover what is loaded, and the line under the filters says how far back that reaches.`
    },
    {
      title: 'People',
      description:
        '"You" marks your own actions. Other members appear by the name on their profile, or by their role and the start of their id if they have not set one. The log itself stores ids; names and roles come from today’s member list. Sign-ins and two-factor changes stay on each person’s own Profile page.'
    },
    {
      title: 'Retention',
      description: 'Kept for the life of the workspace. Deleting the workspace deletes its log.'
    }
  ]
};

export function AuditView() {
  const access = useWorkspaceAccess();
  const audit = useAudit();
  const members = useMembers();
  const channels = useChannels();
  const me = useMe();
  const canManageMembers = checkAccess(access, { permission: 'manage_members' });
  const invitations = useInvitations({ enabled: canManageMembers });

  const [params, setParams] = useQueryStates({
    cat: parseAsStringLiteral(FAMILIES).withDefault('all'),
    actor: parseAsString,
    event: parseAsString
  });

  const events = useMemo(() => audit.data?.events ?? [], [audit.data]);
  const loaded = audit.data !== undefined;

  const lookup = useMemo<AuditLookup>(
    () => ({
      members: new Map((members.data?.members ?? []).map((member) => [member.userId, member])),
      membersKnown: members.data !== undefined,
      youId: me.data?.userId ?? members.data?.members.find((member) => member.you)?.userId ?? null,
      invitations: new Map((invitations.data?.invitations ?? []).map((invitation) => [invitation.invitationId, invitation])),
      channels: new Map((channels.data?.channels ?? []).map((channel) => [channel.id, channel])),
      providers: channels.data?.providers ?? [],
      providerBySubject: providersBySubject(events)
    }),
    [members.data, me.data, invitations.data, channels.data, events]
  );

  const byActor = useMemo(() => events.filter((event) => params.actor === null || actorKey(event.actor) === params.actor), [events, params.actor]);
  const byFamily = useMemo(() => events.filter((event) => inFamily(event, params.cat)), [events, params.cat]);
  const shown = useMemo(() => byActor.filter((event) => inFamily(event, params.cat)), [byActor, params.cat]);

  // Pill counts honour the person filter; person counts honour the kind filter.
  const familyCounts = useMemo(() => {
    if (!loaded) return null;
    const counts = Object.fromEntries(FAMILIES.map((family) => [family, 0])) as Record<Family, number>;
    for (const event of byActor) {
      counts.all += 1;
      counts[familyOf(event.kind)] += 1;
    }
    return counts;
  }, [byActor, loaded]);

  const actorOptions = useMemo<ActorOption[] | null>(() => {
    if (!loaded) return null;
    const counts = new Map<string, { actor: string | null; count: number }>();
    for (const event of events) {
      const key = actorKey(event.actor);
      if (!counts.has(key)) counts.set(key, { actor: event.actor || null, count: 0 });
    }
    for (const event of byFamily) {
      const entry = counts.get(actorKey(event.actor));
      if (entry) entry.count += 1;
    }
    return [...counts.entries()]
      .map(([value, { actor, count }]) => ({ value, count, person: personOf(actor, lookup) }))
      .toSorted((a, b) => Number(b.person.kind === 'you') - Number(a.person.kind === 'you') || b.count - a.count);
  }, [events, byFamily, lookup, loaded]);

  // Rows on screen when the log first loaded stay still; rows a refresh brings in slide in.
  const [known, setKnown] = useState<Set<string> | null>(null);
  if (known === null && audit.data) setKnown(new Set(events.map(eventKey)));
  const freshKeys = useMemo(() => {
    if (!known) return new Map<string, number>();
    const fresh = new Map<string, number>();
    events.forEach((event, index) => {
      const key = eventKey(event, index);
      if (!known.has(key)) fresh.set(key, fresh.size);
    });
    return fresh;
  }, [events, known]);

  const now = audit.dataUpdatedAt ? Math.max(Date.now(), audit.dataUpdatedAt) / 1000 : Date.now() / 1000;
  const selected = params.event ? (events.find((event) => event.id === params.event) ?? null) : null;
  const groups = useMemo(() => groupByDay(shown), [shown]);
  const indexOf = useMemo(() => new Map(events.map((event, index) => [event, index])), [events]);

  const resetFilters = useCallback(() => void setParams({ cat: null, actor: null }), [setParams]);
  const refresh = () => {
    void audit.refetch();
    void members.refetch();
    void channels.refetch();
    if (canManageMembers) void invitations.refetch();
  };
  const lookupsFailed = members.isError || channels.isError;
  // Filters belong to a log with rows, or to one still loading (as skeletons); not to an empty or failed one.
  const showFilters = loaded ? events.length > 0 : !audit.isError;

  let body: ReactNode;
  if (!loaded && audit.isError) {
    body = <AuditLoadError error={audit.error} hasData={false} updatedAt={0} onRetry={() => audit.refetch()} />;
  } else if (!loaded) {
    body = <AuditListSkeleton />;
  } else if (events.length === 0) {
    body = <AuditEmpty />;
  } else if (shown.length === 0) {
    body = <AuditFilterEmpty loaded={events.length} onReset={resetFilters} />;
  } else {
    let first = true;
    body = (
      <div className='flex flex-col gap-6'>
        {groups.map((group) => {
          const label = dayLabel(group.at, now);
          const headingId = `audit-day-${group.key}`;
          return (
            <section key={group.key} aria-labelledby={headingId} className='flex flex-col gap-2'>
              <h3 id={headingId} className='flex flex-wrap items-baseline gap-x-2 text-sm font-medium'>
                {label.lead && <span>{label.lead}</span>}
                <span className={label.lead ? 'text-muted-foreground font-normal' : undefined}>{label.full}</span>
                <span className='text-muted-foreground text-xs font-normal tabular-nums'>
                  {formatNumber(group.events.length)} event{group.events.length === 1 ? '' : 's'}
                </span>
              </h3>
              <ol className='divide-y overflow-hidden rounded-lg border'>
                {group.events.map((event) => {
                  const key = eventKey(event, indexOf.get(event) ?? 0);
                  const order = freshKeys.get(key);
                  const tour = first;
                  first = false;
                  return (
                    <AuditRow
                      key={key}
                      event={event}
                      lookup={lookup}
                      now={now}
                      tour={tour}
                      // Only the first two new rows stagger (40ms), so the whole entrance stays under 300ms.
                      enterDelay={order === undefined ? null : Math.min(order, 1) * 0.04}
                      onOpen={() => void setParams({ event: event.id ?? null })}
                    />
                  );
                })}
              </ol>
            </section>
          );
        })}
      </div>
    );
  }

  return (
    <PageContainer access={canManageMembers}>
      <div className='mb-4 flex items-start justify-between gap-4'>
        <div className='min-w-0' data-tour='audit-title'>
          <div className='flex items-center gap-2'>
            <h2 className='text-3xl font-bold tracking-tight'>Audit log</h2>
            <div className='pt-1'>
              <InfoButton content={infoContent} data-tour='audit-info' />
            </div>
          </div>
          <p className='text-muted-foreground text-sm'>Who did what in this workspace, newest first. Never the content itself.</p>
        </div>
        <Button variant='outline' size='sm' className='shrink-0' onClick={refresh} disabled={!loaded && !audit.isError} aria-label='Refresh the audit log'>
          <ActionSwapIcon value={audit.isFetching ? 'busy' : 'idle'} className='size-3.5'>
            {audit.isFetching ? <Icons.spinner className='size-3.5 animate-spin' /> : <Icons.refresh className='size-3.5' />}
          </ActionSwapIcon>
          <span className='hidden sm:inline'>Refresh</span>
        </Button>
      </div>

      <div className='flex min-w-0 flex-col gap-4'>
        {showFilters ? (
          <AuditFilters
            family={params.cat}
            onFamily={(family) => void setParams({ cat: family === 'all' ? null : family })}
            actor={params.actor}
            onActor={(actor) => void setParams({ actor })}
            familyCounts={familyCounts}
            actorOptions={actorOptions}
            everyoneCount={loaded ? byFamily.length : null}
            onReset={resetFilters}
          />
        ) : null}
        {loaded && events.length > 0 && <AuditCoverage loaded={events.length} oldest={events[events.length - 1].at} showing={shown.length} />}
        {loaded && audit.isError && (
          <AuditLoadError error={audit.error} hasData updatedAt={audit.dataUpdatedAt} onRetry={() => audit.refetch()} />
        )}
        {loaded && lookupsFailed && (
          <p className='text-muted-foreground flex flex-wrap items-center gap-x-2 text-xs'>
            {members.isError && channels.isError
              ? 'Member names, roles and channel names could not be read, so some rows show less.'
              : members.isError
                ? 'Member names and roles could not be read, so people show as the start of their id.'
                : 'Channel names could not be read, so some channel rows name only the provider.'}
            <Button variant='link' size='xs' className='h-auto px-0' onClick={refresh}>
              Try again
            </Button>
          </p>
        )}
        {body}
      </div>

      <AuditDetailSheet event={selected} lookup={lookup} now={now} onClose={() => void setParams({ event: null })} />
    </PageContainer>
  );
}
