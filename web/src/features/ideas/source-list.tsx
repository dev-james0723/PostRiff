'use client';

import { useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { DigitSwap } from '@/components/motion/digit-swap';
import { SegmentedControl, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useSnapshot } from '@/lib/api/hooks';
import type { SnapshotState } from '@/lib/api/types';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { formatDate } from '@/lib/time';
import { cn } from '@/lib/utils';
import { FILTERS, ideaSources, kindIcon, kindLabel, plural, POLICIES, sortSources, toEpoch, variantsUsing, type FilterId, type IdeaSource, type UseState } from './use-sources';

interface SourceListProps {
  selectedId: string | null;
  onSelect: (sourceId: string) => void;
  /** Whether each rewrite-approval source's current facts carry a public-use approval. */
  useApprovals: Record<string, UseState>;
}

/**
 * A state that needs attention keeps its semantic tint (DNA §4.3) but loses the chip outline:
 * icon plus text, in line with the rest of the row's metadata.
 */
const ATTENTION_BADGE = 'h-auto border-transparent bg-transparent px-0';

/** Every source in the workspace with real counts per filter, newest first. */
export function SourceList({ selectedId, onSelect, useApprovals }: SourceListProps) {
  const snapshot = useSnapshot();
  const [filter, setFilter] = useState<FilterId>('all');
  const state = snapshot.data?.state;
  const sources = useMemo(() => sortSources(ideaSources(state)), [state]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.id, sources.filter(f.match).length])) as Record<FilterId, number>, [sources]);
  const current = FILTERS.find((f) => f.id === filter) ?? FILTERS[0];
  const rows = sources.filter(current.match);
  const loading = snapshot.isLoading;

  return (
    <section aria-labelledby='ideas-sources-heading' className='flex flex-col gap-3'>
      <div className='flex flex-col gap-2'>
        <h2 id='ideas-sources-heading' className='text-foreground text-base font-medium'>
          Idea bank
        </h2>
        {/* WHAT: one persistent-lens control; the counts are real (DNA §22.4). It scrolls sideways rather than widening the page. */}
        <div className='relative scrollbar-hide -mx-1 overflow-x-auto px-1 py-0.5' data-tour='ideas-filters'>
          <SegmentedControl
            label='Filter sources'
            value={filter}
            onChange={setFilter}
            widths='content'
            options={FILTERS.map((item) => ({
              value: item.id,
              label: (
                <>
                  {item.label}
                  <span className='text-muted-foreground tabular-nums'>{loading ? '…' : <DigitSwap value={counts[item.id]} />}</span>
                </>
              )
            }))}
          />
        </div>
      </div>

      {loading ? (
        <StateMessage kind='loading' title='Loading sources' />
      ) : sources.length === 0 ? (
        <StateMessage kind='empty' title='Nothing captured yet' />
      ) : rows.length === 0 ? (
        // No matches is not an empty bank (DNA §13.5): the other filters keep their sources.
        <StateMessage
          kind='empty'
          title={current.empty}
          action={
            filter === 'all' ? undefined : (
              <Button variant='quiet' size='lg' onClick={() => setFilter('all')}>
                Show all
              </Button>
            )
          }
        />
      ) : (
        <Rows key={filter} rows={rows} state={state} selectedId={selectedId} onSelect={onSelect} useApprovals={useApprovals} />
      )}
    </section>
  );
}

function Rows({ rows, state, selectedId, onSelect, useApprovals }: { rows: IdeaSource[]; state: SnapshotState | undefined } & SourceListProps) {
  const reduce = useReducedMotion();
  // Rows present at mount render in place (no staggered entrance, DNA §18.6); anything that appears afterwards is new and pops.
  const initial = useRef<Set<string> | null>(null);
  if (initial.current === null) initial.current = new Set(rows.map((r) => r.id));

  return (
    <Surface as='ul' material='quiet' radius='card' padding='none' className='relative flex flex-col gap-1 p-1.5'>
      <AnimatePresence mode='popLayout'>
        {rows.map((source, index) => {
          const fresh = !initial.current?.has(source.id);
          return (
            <motion.li
              key={source.id}
              layout={reduce ? false : 'position'}
              initial={fresh && !reduce ? { opacity: 0, scale: 0.96 } : false}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96, transition: { duration: reduce ? 0 : 0.15, ease: EASE_OUT } }}
              transition={reduce ? { duration: 0 } : { duration: 0.24, ease: EASE_OUT, layout: SPRING_LAYOUT }}
            >
              <SourceRow source={source} state={state} selected={source.id === selectedId} first={index === 0} onSelect={onSelect} useApproved={useApprovals[source.id]} />
            </motion.li>
          );
        })}
      </AnimatePresence>
    </Surface>
  );
}

function PolicyState({ source }: { source: IdeaSource }) {
  if (!source.sourcePolicy) {
    return (
      <AnimatedBadge size='sm' status='warning' contentKey='policy-needed' className={ATTENTION_BADGE}>
        Policy needed
      </AnimatedBadge>
    );
  }
  const policy = POLICIES.find((p) => p.id === source.sourcePolicy);
  return <span>{policy?.badge ?? source.sourcePolicy}</span>;
}

/**
 * List row anatomy (DNA §13.3, §21.10): compact semantic mark | title + type | inclusion and
 * processing state. The whole row is the one open control; its selected state is a glass lens.
 */
function SourceRow({ source, state, selected, first, onSelect, useApproved }: { source: IdeaSource; state: SnapshotState | undefined; selected: boolean; first: boolean; onSelect: (id: string) => void; useApproved: UseState }) {
  const approved = source.facts.filter((f) => f.approved).length;
  const drafts = variantsUsing(state, source.id);
  const used = drafts.length;
  const blocked = drafts.filter((v) => v.blockedByRetraction).length;
  const cloud = (source.egressConsent ?? []).includes('cloud');
  const web = source.origin?.kind === 'web_research';
  const factLine = source.kind === 'idea' || source.kind === 'link' ? 'No facts · brief only' : `${approved}/${source.facts.length} facts approved`;
  const Mark = Icons[kindIcon(source)];

  return (
    <button
      type='button'
      onClick={() => onSelect(source.id)}
      aria-pressed={selected}
      data-tour={first ? 'ideas-source-row' : undefined}
      className={cn(
        'rafii-focus flex w-full min-h-14 items-center gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2.5 text-left transition-colors',
        selected ? 'rafii-glass-selected' : 'hover:rafii-quiet'
      )}
    >
      <span aria-hidden className={cn('rafii-quiet flex size-9 shrink-0 items-center justify-center rounded-full', source.active ? 'text-foreground' : 'text-muted-foreground')}>
        <Mark className='size-4' />
      </span>
      <span className='flex min-w-0 flex-1 flex-col gap-1'>
        <span className='flex min-w-0 items-baseline gap-2'>
          <span className={cn('min-w-0 truncate text-sm font-medium', !source.active && 'text-muted-foreground')}>{source.title || kindLabel(source)}</span>
          <span className='text-muted-foreground shrink-0 text-xs'>{kindLabel(source)}</span>
        </span>
        {source.active ? (
          <span className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs'>
            <span className='tabular-nums'>{factLine}</span>
            <PolicyState source={source} />
            {source.sourcePolicy === 'rewrite_approval' && approved > 0 && useApproved === false && (
              <AnimatedBadge size='sm' status='warning' showIcon={false} contentKey='use-needed' className={ATTENTION_BADGE}>
                Public use not approved
              </AnimatedBadge>
            )}
            {/* Secondary metadata stays off phones; the inspector has all of it. */}
            <span className='hidden items-center gap-1 md:inline-flex'>
              <Icons.cloudUpload aria-hidden className={cn('size-3.5', cloud ? 'text-foreground' : 'opacity-60')} />
              {cloud ? 'Cloud on' : 'Cloud off'}
            </span>
            {web && source.origin?.host && (
              <span className='hidden min-w-0 items-center gap-1 md:inline-flex'>
                <Icons.externalLink className='size-3 shrink-0' />
                <span className='truncate'>{source.origin.host}</span>
              </span>
            )}
            {used > 0 && <span className='hidden md:inline'>Used in {plural(used, 'draft')}</span>}
          </span>
        ) : (
          <span className='text-muted-foreground flex flex-wrap items-center gap-x-2 text-xs'>
            <span>Withdrawn {formatDate(toEpoch(source.withdrawnAt))}</span>
            {blocked > 0 && <span>· {plural(blocked, 'draft')} blocked</span>}
          </span>
        )}
      </span>
    </button>
  );
}
