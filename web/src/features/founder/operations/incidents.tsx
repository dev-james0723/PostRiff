'use client';

import { useMemo } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { count, timeValue, whenDate, whenDateTime } from '../customers/kit/format';
import { DETECTOR_LABELS, SWIMLANE_DAYS, detectorOf, humanize, swimlanes, timelineEvents, type OpsIncident } from './ops-model';

/**
 * Incidents (PRD §7.2 Operations, CONTRACTS §8.D): a swimlane per detector over the last seven days, the list with
 * Ack, and one incident's timeline. Ack posts the exact version the page showed, so a stale click is refused by the
 * server, and exists in Live only — Demo incidents are simulated and have no acknowledgement. The swimlane is a
 * picture of the same episodes the list holds (opened → resolved, or now while open); selecting happens in the list.
 */
export const OPEN_STATES = new Set(['open', 'acknowledged', 'investigating', 'mitigated']);

export function incidentTitle(incident: OpsIncident): string {
  if (incident.title) return incident.title;
  const detector = detectorOf(incident);
  return `${DETECTOR_LABELS[detector] ?? humanize(detector)} · ${humanize(incident.scope)}`;
}

function SeverityChip({ severity }: { severity: string | null | undefined }) {
  return (
    <StatusChip status={severity === 'critical' ? 'danger' : 'warning'} tone='attention'>
      {humanize(severity ?? 'warning')}
    </StatusChip>
  );
}

export interface IncidentListProps {
  incidents: readonly OpsIncident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAck: (incident: OpsIncident & { version: number }) => void;
  acking: string | null;
  /** Live data: incidents can be acknowledged at all. Demo incidents have no Ack. */
  ackable: boolean;
  /** The operator holds `incidents.ack`. */
  canAck: boolean;
}

export function IncidentList({ incidents, selectedId, onSelect, onAck, acking, ackable, canAck }: IncidentListProps) {
  const ordered = useMemo(() => incidents.toSorted((a, b) => Number(OPEN_STATES.has(b.state ?? '')) - Number(OPEN_STATES.has(a.state ?? '')) || (timeValue(b.openedAt ?? b.observedAt) ?? 0) - (timeValue(a.openedAt ?? a.observedAt) ?? 0)), [incidents]);
  if (ordered.length === 0) return <StateMessage kind='success' title='No incidents' description='No detector has opened an episode in this environment. Source health says whether the detectors themselves are running.' />;
  return (
    <ul className='flex flex-col gap-2' aria-label='Incidents'>
      {ordered.map((incident) => {
        const selected = incident.id === selectedId;
        const open = OPEN_STATES.has(incident.state ?? '');
        const version = typeof incident.version === 'number' ? incident.version : null;
        return (
          <li key={incident.id} className={cn('rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3 sm:flex-row sm:items-center sm:justify-between', selected && 'rafii-glass-selected')}>
            <button type='button' onClick={() => onSelect(incident.id)} aria-pressed={selected} className='rafii-focus flex min-w-0 flex-1 flex-col items-start gap-1 rounded-md text-left'>
              <span className='flex flex-wrap items-center gap-2'>
                <SeverityChip severity={incident.severity} />
                <StatusChip icon={open ? 'bolt' : 'check'}>{humanize(incident.state)}</StatusChip>
                <span className='text-foreground text-sm font-medium break-words'>{incidentTitle(incident)}</span>
              </span>
              <span className='text-muted-foreground text-xs'>
                Opened {whenDateTime(incident.openedAt ?? incident.observedAt)}
                {typeof incident.affectedCount === 'number' && ` · ${count(incident.affectedCount)} affected`}
                {incident.resolvedAt && ` · resolved ${whenDateTime(incident.resolvedAt)}`}
              </span>
            </button>
            <div className='flex shrink-0 items-center gap-2'>
              {ackable && incident.state === 'open' && version !== null && (
                <Button variant='action' size='sm' disabled={!canAck || acking === incident.id} onClick={() => onAck({ ...incident, version })} title={canAck ? `Acknowledge this episode (version ${version})` : 'Needs the incidents.ack capability'}>
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

/** One lane per detector; bars are the episodes of the last seven days. The list below is how an episode is opened. */
export function IncidentSwimlane({ incidents, selectedId, now }: { incidents: readonly OpsIncident[]; selectedId: string | null; now: number }) {
  const lanes = useMemo(() => swimlanes(incidents, now), [incidents, now]);
  if (lanes.length === 0) return <StateMessage kind='success' layout='inline' title={`No incident in the last ${SWIMLANE_DAYS} days`} description='Every detector stayed quiet over the window. Source health says whether the detectors ran.' />;
  return (
    <figure className='flex flex-col gap-2' aria-label={`Incidents of the last ${SWIMLANE_DAYS} days by detector`}>
      <ul className='flex flex-col gap-2'>
        {lanes.map((lane) => (
          <li key={lane.detector} className='grid gap-1 sm:grid-cols-[9rem_minmax(0,1fr)] sm:items-center sm:gap-3'>
            <span className='text-muted-foreground text-xs font-medium'>{lane.label}</span>
            <div
              role='img'
              aria-label={`${lane.label}: ${lane.episodes.map((episode) => `${incidentTitle(episode.incident)}, ${humanize(episode.severity)}, ${episode.open ? 'still open' : 'resolved'}, opened ${whenDateTime(episode.startMs)}`).join('; ')}`}
              className='bg-muted relative h-6 min-w-0 overflow-hidden rounded-md'
            >
              {lane.episodes.map((episode) => (
                <span
                  key={episode.id}
                  aria-hidden
                  className={cn('absolute inset-y-1 rounded-sm', episode.severity === 'critical' ? 'bg-destructive' : 'bg-foreground/60', !episode.open && 'opacity-45', episode.id === selectedId && 'ring-foreground ring-2')}
                  style={{ left: `${episode.left}%`, width: `${episode.width}%` }}
                />
              ))}
            </div>
          </li>
        ))}
      </ul>
      <figcaption className='text-muted-foreground flex justify-between gap-2 text-xs sm:ml-[9.75rem]'>
        <span>{whenDate(now - SWIMLANE_DAYS * 86_400_000)}</span>
        <span>Now</span>
      </figcaption>
    </figure>
  );
}

export function IncidentTimeline({ incident }: { incident: (OpsIncident & { evidence?: Record<string, unknown> | null }) | null }) {
  if (!incident) return <StateMessage kind='empty' layout='inline' title='Select an incident' description='Its events, evidence and lifecycle stamps show here.' />;
  const events = timelineEvents(incident);
  const evidence = incident.evidence ? Object.entries(incident.evidence).filter(([, value]) => value !== null && typeof value !== 'object') : [];
  return (
    <div className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <SeverityChip severity={incident.severity} />
        <StatusChip icon={null}>{humanize(incident.state)}</StatusChip>
        <span className='text-muted-foreground font-mono text-xs break-all'>
          {typeof incident.version === 'number' ? `v${incident.version} · ` : ''}
          {incident.id}
        </span>
      </div>
      <ol className='relative flex flex-col gap-3 border-l pl-4' aria-label='Incident timeline'>
        {events.length === 0 && <li className='text-muted-foreground text-sm'>No events recorded yet.</li>}
        {events.map((event, index) => (
          <li key={`${event.kind}-${String(event.at)}-${index}`} className='relative'>
            <span aria-hidden className='bg-foreground absolute top-1.5 -left-[1.3125rem] size-2 rounded-full' />
            <p className='text-foreground text-sm font-medium'>{humanize(event.kind)}</p>
            <p className='text-muted-foreground text-xs'>{whenDateTime(event.at)}</p>
            {event.body && Object.keys(event.body).length > 0 && (
              <p className='text-muted-foreground mt-0.5 text-xs break-words'>
                {Object.entries(event.body)
                  .filter(([, value]) => value !== null && typeof value !== 'object')
                  .map(([key, value]) => `${humanize(key)}: ${String(value)}`)
                  .join(' · ')}
              </p>
            )}
          </li>
        ))}
      </ol>
      {evidence.length > 0 && (
        <dl className='grid grid-cols-[minmax(7rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs'>
          {evidence.map(([key, value]) => (
            <div key={key} className='contents'>
              <dt className='text-muted-foreground'>{humanize(key)}</dt>
              <dd className='font-mono break-all'>{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className='text-muted-foreground text-xs'>Release markers would be a hypothesis, not evidence; this release draws none.</p>
    </div>
  );
}
