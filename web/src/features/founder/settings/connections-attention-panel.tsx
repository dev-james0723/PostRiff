'use client';

import { useQuery } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { founderFetch } from '@/lib/founder/api';
import type { Envelope } from '@/lib/founder/types';
import { failureOf, useFounderScope } from '../customers/kit/api';
import { Panel, RetryAction } from '../customers/kit/page-frame';

type Count = { value: number | null; countState: 'exact' | 'estimated' | 'lower_bound' | 'unknown' };
type Freshness = { freshness: 'fresh' | 'stale' | 'unknown' | 'not_applicable'; coverage?: string | null; observedAt: string | null; lastCheckedAt: string | null; reason: string | null };
type Item = {
  id: string; priority: string; category: string; state: string; title: string; summary: string; launchBlocker: boolean;
  affected: { users: Count; tenants: Count; connections: Count; jobs: Count };
  owner: { lane: string; label: string | null };
  nextAction: { label?: string; requiresHuman?: boolean } | null;
  freshness: Freshness;
};
type Requirement = { kind: string; standing: string; blockers: string[]; freshness: Freshness };
type App = { provider: string; appRef: string; environment: string; readiness: string; launchScope: boolean; requirements: Requirement[] };
type Attention = {
  items: Item[]; truncated: boolean; total: number;
  summary: { tenants: Count; unassigned: number; launchBlockers: number };
  registry: App[];
  sources: { connectionHealth: { state: string; freshness: Freshness }; incidents: { state: string } };
};

/** A count as the operator must read it: unknown is never shown as 0, a lower bound says "at least". */
export function formatCount(count: Count, noun: string): string {
  if (count.countState === 'unknown' || count.value === null) return `${noun}: unknown`;
  const prefix = count.countState === 'lower_bound' ? 'at least ' : count.countState === 'estimated' ? '~' : '';
  return `${noun}: ${prefix}${count.value}`;
}

/** Green only for fresh evidence; stale shows the last-known time, unknown asks for a check. */
export function freshnessLabel(envelope: Freshness): string {
  if (envelope.freshness === 'fresh') return envelope.coverage === 'complete' ? 'Current' : 'Current (partial coverage)';
  if (envelope.freshness === 'stale') return envelope.observedAt ? `Stale · last good ${new Date(envelope.observedAt).toLocaleString()}` : 'Stale';
  if (envelope.freshness === 'not_applicable') return 'Episode record';
  return 'Check required';
}

/** Sources the queue could not read: their impact is unknown, so the panel says so instead of looking clear. */
export function degradedSources(sources: Attention['sources']): string[] {
  const out: string[] = [];
  if (sources.connectionHealth.state !== 'connected') out.push(`connection health (${sources.connectionHealth.state.replaceAll('_', ' ')})`);
  if (sources.incidents.state !== 'connected') out.push(`incidents (${sources.incidents.state.replaceAll('_', ' ')})`);
  return out;
}

export function ConnectionsAttentionPanel() {
  const scope = useFounderScope();
  const query = useQuery({
    queryKey: scope.key('connections-attention'),
    enabled: scope.ready,
    queryFn: async ({ signal }) => (await founderFetch<Envelope<Attention>>(`/connections/attention?mode=${scope.mode}`, { signal })).data
  });
  return (
    <Panel title='Connections needing attention' description='What is wrong, who is affected, who owns it and what happens next. Health is the last hourly observation, not live token validity.'>
      {query.isPending ? <p className='text-muted-foreground text-sm'>Loading connections…</p> : query.isError ? (
        failureOf(query.error).status === 403 ? (
          <StateMessage kind='permission' layout='inline' title='Connections are not available to this operator' description='Reading the attention queue needs the control.read capability.' />
        ) : (
          <StateMessage kind='error' layout='inline' title='Connections unavailable' description='The attention queue could not be read. Nothing has been counted as healthy.'
            action={<RetryAction onRetry={() => void query.refetch()} />} />
        )
      ) : query.data ? (
        <div className='flex flex-col gap-3'>
          <p className='text-muted-foreground text-sm'>
            {formatCount(query.data.summary.tenants, 'Workspaces affected')} · {query.data.summary.launchBlockers} launch blocker(s) · {query.data.summary.unassigned} unassigned ·
            Connection health: {freshnessLabel(query.data.sources.connectionHealth.freshness)}
          </p>
          {degradedSources(query.data.sources).length > 0 && (
            <p role='status' className='text-sm'>Not readable: {degradedSources(query.data.sources).join(', ')}. Their impact is unknown, not zero.</p>
          )}
          {query.data.items.length === 0 && <p className='text-sm'>No open items from the observed sources.</p>}
          {query.data.items.map((item) => (
            <details key={item.id} className='rafii-quiet rounded-lg p-3'>
              <summary className='cursor-pointer text-sm'>
                {item.priority} · {item.title}{item.launchBlocker ? ' · Launch blocker' : ''}{item.state !== 'open' ? ` · ${item.state.replaceAll('_', ' ')}` : ''}
              </summary>
              <p className='text-muted-foreground mt-2 text-sm'>{item.summary}</p>
              <p className='text-muted-foreground mt-1 text-xs'>
                {formatCount(item.affected.tenants, 'Workspaces')} · {formatCount(item.affected.connections, 'Connections')} · {formatCount(item.affected.jobs, 'Jobs')} · {formatCount(item.affected.users, 'Users')}
              </p>
              <p className='text-muted-foreground mt-1 text-xs'>Owner: {item.owner.label ?? item.owner.lane} · {freshnessLabel(item.freshness)}</p>
              {item.nextAction?.label && <p className='mt-1 text-sm'>Next: {item.nextAction.label}{item.nextAction.requiresHuman ? ' (needs a person)' : ''}</p>}
            </details>
          ))}
          {query.data.truncated && <p className='text-muted-foreground text-xs'>Showing the first {query.data.items.length} of {query.data.total} items.</p>}
          <details className='rafii-quiet rounded-lg p-3'>
            <summary className='cursor-pointer text-sm'>Provider approvals ({query.data.registry.filter((app) => app.readiness === 'ready').length} of {query.data.registry.length} apps evidenced)</summary>
            <ul className='mt-2 flex flex-col gap-2 text-xs'>
              {query.data.registry.map((app) => (
                <li key={`${app.provider}:${app.appRef}:${app.environment}`}>
                  <span className='font-medium'>{app.provider}</span> · {app.readiness.replaceAll('_', ' ')}{app.launchScope ? ' · launch scope' : ''}
                  <span className='text-muted-foreground'> — {app.requirements.map((req) => `${req.kind.replaceAll('_', ' ')}: ${req.standing.replaceAll('_', ' ')}`).join('; ')}</span>
                </li>
              ))}
            </ul>
          </details>
        </div>
      ) : null}
    </Panel>
  );
}
