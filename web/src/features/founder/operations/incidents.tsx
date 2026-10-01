'use client';

import { useMemo } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { count, stateLabel, timeValue, whenDateTime } from '../customers/kit/format';
import type { Incident, IncidentEvent } from '../customers/kit/types';

/**
 * Incident list and timeline (PRD §7.2 Operations). Rows show detector, scope, severity, state, affected count
 * and age; Ack posts the incident's version so a stale click is refused by the server rather than silently
 * applied. The timeline is the server's events plus the opened / acknowledged / resolved stamps it recorded.
 */
export const OPEN_STATES = new Set(['open', 'investigating', 'mitigated']);

export function incidentTitle(incident: Incident): string {
  return incident.title ?? `${stateLabel(incident.detector)} · ${stateLabel(incident.scope)}`;
}

/** The server's events in time order, with the lifecycle stamps added when no event already names them. */
export function timelineOf(incident: Incident): IncidentEvent[] {
  const events = [...(incident.events ?? incident.timeline ?? [])];
  const has = (kind: string) => events.some((event) => event.kind === kind);
  if (incident.openedAt && !has('opened')) events.push({ kind: 'opened', at: incident.openedAt });
  if (incident.acknowledgedAt && !has('acknowledged')) events.push({ kind: 'acknowledged', at: incident.acknowledgedAt });
  if (incident.resolvedAt && !has('resolved')) events.push({ kind: 'resolved', at: incident.resolvedAt });
  // Stamps arrive as ISO strings (Demo payload) or epoch seconds (founder_incidents); order them as instants, never as text.
  return events.filter((event) => timeValue(event.at) !== null).toSorted((a, b) => (timeValue(a.at) ?? 0) - (timeValue(b.at) ?? 0));
}

function SeverityChip({ severity }: { severity: Incident['severity'] }) {
  return (
    <StatusChip status={severity === 'critical' ? 'danger' : 'warning'} tone='attention'>
      {stateLabel(severity)}
    </StatusChip>
  );
}

export function IncidentList({ incidents, selectedId, onSelect, onAck, acking, canAck, ackDisabledReason }: { incidents: Incident[]; selectedId: string | null; onSelect: (id: string) => void; onAck: (incident: Incident) => void; acking: string | null; canAck: boolean; ackDisabledReason?: string }) {
  const ordered = useMemo(() => incidents.toSorted((a, b) => Number(OPEN_STATES.has(b.state)) - Number(OPEN_STATES.has(a.state)) || (timeValue(b.openedAt) ?? 0) - (timeValue(a.openedAt) ?? 0)), [incidents]);
  if (ordered.length === 0) return <StateMessage kind='success' title='No incidents' description='No detector has opened an episode in this environment. Source health below says whether the detectors themselves are running.' />;
  return (
    <ul className='flex flex-col gap-2' aria-label='Incidents'>
      {ordered.map((incident) => {
        const selected = incident.id === selectedId;
        const open = OPEN_STATES.has(incident.state);
        return (
          <li key={incident.id} className={cn('rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3 sm:flex-row sm:items-center sm:justify-between', selected && 'rafii-glass-selected')}>
            <button type='button' onClick={() => onSelect(incident.id)} aria-pressed={selected} className='rafii-focus flex min-w-0 flex-1 flex-col items-start gap-1 rounded-md text-left'>
              <span className='flex flex-wrap items-center gap-2'>
                <SeverityChip severity={incident.severity} />
                <StatusChip icon={open ? 'bolt' : 'check'}>{stateLabel(incident.state)}</StatusChip>
                <span className='text-foreground text-sm font-medium'>{incidentTitle(incident)}</span>
              </span>
              <span className='text-muted-foreground text-xs'>
                Opened {whenDateTime(incident.openedAt)}
                {typeof incident.affectedCount === 'number' && ` · ${count(incident.affectedCount)} affected`}
                {incident.resolvedAt && ` · resolved ${whenDateTime(incident.resolvedAt)}`}
              </span>
            </button>
            <div className='flex shrink-0 items-center gap-2'>
              {incident.state === 'open' && (
                <Button variant='action' size='sm' disabled={!canAck || acking === incident.id} onClick={() => onAck(incident)} title={canAck ? `Acknowledge this episode (version ${incident.version})` : (ackDisabledReason ?? 'Needs the incidents.ack capability')}>
                  {acking === incident.id ? <Icons.spinner className='animate-spin' /> : <Icons.check />} Ack
                </Button>
              )}
              <Button variant='quiet' size='sm' onClick={() => onSelect(incident.id)} aria-label={`Open timeline for ${incidentTitle(incident)}`}>
                Timeline <Icons.chevronRight />
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function IncidentTimeline({ incident }: { incident: Incident | null }) {
  if (!incident) return <StateMessage kind='empty' layout='inline' title='Select an incident' description='Its events, evidence and lifecycle stamps show here.' />;
  const events = timelineOf(incident);
  const evidence = incident.evidence ? Object.entries(incident.evidence).filter(([, value]) => value !== null && typeof value !== 'object') : [];
  return (
    <div className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <SeverityChip severity={incident.severity} />
        <StatusChip icon={null}>{stateLabel(incident.state)}</StatusChip>
        <span className='text-muted-foreground font-mono text-xs'>v{incident.version} · {incident.id}</span>
      </div>
      <ol className='relative flex flex-col gap-3 border-l pl-4' aria-label='Incident timeline'>
        {events.length === 0 && <li className='text-muted-foreground text-sm'>No events recorded yet.</li>}
        {events.map((event, index) => (
          <li key={`${event.kind}-${event.at}-${index}`} className='relative'>
            <span aria-hidden className='bg-foreground absolute top-1.5 -left-[1.3125rem] size-2 rounded-full' />
            <p className='text-foreground text-sm font-medium'>{stateLabel(event.kind)}</p>
            <p className='text-muted-foreground text-xs'>{whenDateTime(event.at)}</p>
            {event.body && Object.keys(event.body).length > 0 && <p className='text-muted-foreground mt-0.5 text-xs'>{Object.entries(event.body).filter(([, value]) => typeof value !== 'object').map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}</p>}
          </li>
        ))}
      </ol>
      {evidence.length > 0 && (
        <dl className='grid grid-cols-[minmax(7rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs'>
          {evidence.map(([key, value]) => (
            <div key={key} className='contents'>
              <dt className='text-muted-foreground'>{stateLabel(key)}</dt>
              <dd className='font-mono break-all'>{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className='text-muted-foreground text-xs'>Release markers are a hypothesis, not evidence; this release draws none.</p>
    </div>
  );
}
