'use client';

import { useId, useState } from 'react';
import { Icons } from '@/components/icons';
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { SegmentedControl, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { isFeatureDisabled } from '@/lib/growth-v2/request';
import { useResultsSummary } from '@/lib/growth-v2/results-hooks';
import type { ResultProvenance, ResultsDataState, ResultsSummary } from '@/lib/growth-v2/results-types';
import { cn } from '@/lib/utils';
import { classView, stateSentence, type ClassView, type ResultsCopy } from './present';
import { ResultConnectionsView } from './results-connections';
import { ResultsLedger } from './results-ledger';
import { TrackingLinksView } from './results-links';
import { useResultsCopy } from './use-results-copy';

type Period = '30' | '90' | 'all';
type View = 'ledger' | 'connections' | 'links';

const ORDER: ResultProvenance[] = ['user_declared', 'first_party_reported', 'provider_native'];
const STATE_STATUS: Record<ResultsDataState, AnimatedBadgeStatus> = { available: 'success', partial: 'warning', unavailable: 'neutral', stale: 'warning' };

/**
 * Business results on Analytics (PRD R-OUT-01..03): what the person reported, what their connected tools reported and
 * platform metrics, side by side and never added together; the ledger, connections and tracking links below. Hidden
 * entirely while the deployment has business results switched off.
 */
export function BusinessResultsSection() {
  const { copy, lang, locale } = useResultsCopy();
  const [period, setPeriod] = useState<Period>('30');
  const [view, setView] = useState<View>('ledger');
  const summary = useResultsSummary(period === 'all' ? 'all' : Number(period));
  const id = useId();
  if (isFeatureDisabled(summary.error)) return null;
  const views: { value: View; label: string }[] = [
    { value: 'ledger', label: copy.tabs.ledger },
    { value: 'connections', label: copy.tabs.connections },
    { value: 'links', label: copy.tabs.links }
  ];
  const current = views.find((option) => option.value === view) ?? views[0];
  return (
    <Panel
      id='business-results'
      lang={lang}
      title={copy.title}
      titleId={`${id}-title`}
      description={copy.description}
      className='scroll-mt-24'
      actions={
        <SegmentedControl
          label={copy.periodLabel}
          options={[
            { value: '30', label: copy.periods.d30 },
            { value: '90', label: copy.periods.d90 },
            { value: 'all', label: copy.periods.all }
          ]}
          value={period}
          onChange={setPeriod}
          size='sm'
          widths='content'
        />
      }
    >
      {summary.isPending ? (
        <div className='grid gap-3 md:grid-cols-3' aria-hidden>
          {ORDER.map((provenance) => (
            <Skeleton key={provenance} className='h-32 w-full rounded-[var(--rafii-radius-card)]' />
          ))}
        </div>
      ) : summary.isError || !summary.data ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={copy.unavailableTitle}
          description={copy.unavailableDescription}
          action={
            <Button variant='glass' onClick={() => void summary.refetch()}>
              <Icons.refresh /> {copy.retry}
            </Button>
          }
        />
      ) : (
        <Summary data={summary.data} copy={copy} locale={locale} />
      )}
      <SegmentedControl
        pattern='tabs'
        label={copy.tabsLabel}
        options={views}
        value={view}
        onChange={setView}
        panelIds={views.map((option) => `${id}-${option.value}`)}
        size='sm'
        widths='content'
      />
      <section id={`${id}-${view}`} role='tabpanel' aria-label={current.label} className='flex min-w-0 flex-col gap-3'>
        {view === 'ledger' ? <ResultsLedger /> : view === 'connections' ? <ResultConnectionsView /> : <TrackingLinksView />}
      </section>
    </Panel>
  );
}

function Summary({ data, copy, locale }: { data: ResultsSummary; copy: ResultsCopy; locale: string }) {
  // Coverage tells "never set up" (Not connected / Nothing recorded yet) apart from "nothing in this period".
  const views = ORDER.map((provenance) => classView(provenance, data.classes[provenance], copy, locale, data.coverage));
  const hasMoney = views.some((view) => view.money.length > 0);
  return (
    <div className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-center gap-x-3 gap-y-2'>
        <StatusChip status={STATE_STATUS[data.dataState]}>{copy.stateChip[data.dataState]}</StatusChip>
        <p className='text-muted-foreground min-w-0 text-sm text-pretty'>{stateSentence(data.dataState, data.period.open, data.coverage.connections, copy)}</p>
      </div>
      <ul className='grid gap-3 md:grid-cols-3' aria-label={copy.title}>
        {views.map((view) => (
          <ClassCard key={view.provenance} view={view} />
        ))}
      </ul>
      {hasMoney && <p className='text-muted-foreground text-xs'>{copy.moneyNote}</p>}
      {data.clicks && (
        <p className='text-sm text-pretty'>
          <span className='text-foreground tabular-nums'>{copy.clicks(data.clicks.counted)}</span>
          <span className='text-muted-foreground'>
            {' · '}
            {copy.bots(data.clicks.likelyBot)}. {copy.clicksNotPeople}
          </span>
        </p>
      )}
      {data.testEvents > 0 && <p className='text-muted-foreground text-xs'>{copy.testEvents(data.testEvents)}</p>}
      {data.quarantined > 0 && <p className='text-muted-foreground text-xs'>{copy.quarantined(data.quarantined)}</p>}
    </div>
  );
}

function ClassCard({ view }: { view: ClassView }) {
  return (
    <li className='rafii-quiet flex min-w-0 flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4'>
      <h3 className='text-foreground text-sm font-medium'>{view.label}</h3>
      <p className={cn('text-base text-pretty', view.available ? 'text-foreground font-medium' : 'text-muted-foreground')}>{view.headline}</p>
      {view.money.length > 0 && (
        <ul className='flex flex-col gap-0.5'>
          {view.money.map((line) => (
            <li key={line.currency} className='text-foreground text-sm tabular-nums'>
              {line.text}
            </li>
          ))}
        </ul>
      )}
      {view.notes.length > 0 && (
        <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
          {view.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      <p className='text-muted-foreground mt-auto text-xs leading-relaxed text-pretty'>{view.hint}</p>
    </li>
  );
}
