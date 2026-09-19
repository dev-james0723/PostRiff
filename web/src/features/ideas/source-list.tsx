'use client';

import { useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Badge } from '@/components/ui/badge';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { useSnapshot } from '@/lib/api/hooks';
import type { SnapshotState } from '@/lib/api/types';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { formatDate } from '@/lib/time';
import { cn } from '@/lib/utils';
import { FILTERS, ideaSources, kindLabel, plural, POLICIES, sortSources, toEpoch, variantsUsing, type FilterId, type IdeaSource, type UseState } from './use-sources';

interface SourceListProps {
  selectedId: string | null;
  onSelect: (sourceId: string) => void;
  /** Whether each rewrite-approval source's current facts carry a public-use approval. */
  useApprovals: Record<string, UseState>;
}

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
        <h2 id='ideas-sources-heading' className='text-base font-semibold'>
          Idea bank
        </h2>
        <div className='scrollbar-hide -mx-1 overflow-x-auto px-1' data-tour='ideas-filters'>
          <Tabs value={filter} onValueChange={(value) => setFilter(value as FilterId)} variant='pill'>
            <TabsList aria-label='Filter sources' className='bg-muted/60 w-max'>
              {FILTERS.map((item) => (
                <TabsTrigger key={item.id} value={item.id} className='h-7 gap-1.5 px-2.5 py-0 text-xs'>
                  {item.label}
                  <span className='tabular-nums opacity-70'>{loading ? '…' : <DigitSwap value={counts[item.id]} />}</span>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
      </div>

      {loading ? (
        <div className='bg-card ring-foreground/10 flex flex-col gap-3 rounded-xl p-4 ring-1' aria-busy='true' aria-label='Loading sources'>
          {[0, 1, 2].map((i) => (
            <div key={i} className='flex flex-col gap-2'>
              <Skeleton className='h-4 w-2/3' />
              <Skeleton className='h-3 w-1/2' />
            </div>
          ))}
        </div>
      ) : sources.length === 0 ? (
        <Empty className='bg-card ring-foreground/10 rounded-xl ring-1'>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <Icons.paperclip />
            </EmptyMedia>
            <EmptyTitle>Nothing captured yet</EmptyTitle>
            <EmptyDescription>
              Save a thought, paste text or add a link above. Nothing here is sent to a model or published on its own: you approve the facts, how each source may be used, and every draft.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : rows.length === 0 ? (
        <p className='bg-card ring-foreground/10 text-muted-foreground rounded-xl p-4 text-sm ring-1'>{current.empty}</p>
      ) : (
        // Keyed by filter so a switch replays the entrance; rows added later pop in instead.
        <Rows key={filter} rows={rows} state={state} selectedId={selectedId} onSelect={onSelect} useApprovals={useApprovals} />
      )}
    </section>
  );
}

function Rows({ rows, state, selectedId, onSelect, useApprovals }: { rows: IdeaSource[]; state: SnapshotState | undefined } & SourceListProps) {
  const reduce = useReducedMotion();
  // Rows present at mount stagger in; anything that appears afterwards is new and pops.
  const initial = useRef<Set<string> | null>(null);
  if (initial.current === null) initial.current = new Set(rows.map((r) => r.id));

  return (
    <ul className='bg-card ring-foreground/10 relative flex flex-col divide-y overflow-hidden rounded-xl ring-1'>
      <AnimatePresence mode='popLayout'>
        {rows.map((source, index) => {
          const fresh = !initial.current?.has(source.id);
          return (
            <motion.li
              key={source.id}
              layout={reduce ? false : 'position'}
              initial={fresh ? { opacity: 0, scale: 0.96 } : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96, transition: { duration: reduce ? 0 : 0.15, ease: EASE_OUT } }}
              transition={
                reduce
                  ? { duration: 0 }
                  : { duration: 0.24, ease: EASE_OUT, delay: fresh ? 0 : Math.min(index * 0.04, 0.2), layout: SPRING_LAYOUT }
              }
              className='bg-card'
            >
              <SourceRow source={source} state={state} selected={source.id === selectedId} first={index === 0} onSelect={onSelect} useApproved={useApprovals[source.id]} />
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ul>
  );
}

function PolicyBadge({ source }: { source: IdeaSource }) {
  if (!source.sourcePolicy) {
    return (
      <AnimatedBadge size='sm' status='warning' contentKey='policy-needed'>
        Policy needed
      </AnimatedBadge>
    );
  }
  const policy = POLICIES.find((p) => p.id === source.sourcePolicy);
  return (
    <Badge variant='outline' className='font-normal'>
      {policy?.badge ?? source.sourcePolicy}
    </Badge>
  );
}

function SourceRow({ source, state, selected, first, onSelect, useApproved }: { source: IdeaSource; state: SnapshotState | undefined; selected: boolean; first: boolean; onSelect: (id: string) => void; useApproved: UseState }) {
  const approved = source.facts.filter((f) => f.approved).length;
  const drafts = variantsUsing(state, source.id);
  const used = drafts.length;
  const blocked = drafts.filter((v) => v.blockedByRetraction).length;
  const cloud = (source.egressConsent ?? []).includes('cloud');
  const web = source.origin?.kind === 'web_research';
  const factLine = source.kind === 'idea' || source.kind === 'link' ? 'No facts · brief only' : `${approved}/${source.facts.length} facts approved`;

  return (
    <button
      type='button'
      onClick={() => onSelect(source.id)}
      aria-pressed={selected}
      data-tour={first ? 'ideas-source-row' : undefined}
      className={cn(
        'hover:bg-muted/50 focus-visible:ring-ring/50 flex w-full flex-col gap-1.5 px-4 py-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset',
        selected && 'bg-muted/70 hover:bg-muted/70'
      )}
    >
      <span className='flex min-w-0 items-center gap-2'>
        <span className={cn('min-w-0 truncate text-sm font-medium', !source.active && 'text-muted-foreground')}>{source.title || kindLabel(source)}</span>
        <Badge variant='secondary' className='font-normal'>
          {kindLabel(source)}
        </Badge>
      </span>
      {source.active ? (
        <span className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs'>
          <span className='tabular-nums'>{factLine}</span>
          <PolicyBadge source={source} />
          {source.sourcePolicy === 'rewrite_approval' && approved > 0 && useApproved === false && (
            <AnimatedBadge size='sm' status='warning' showIcon={false} contentKey='use-needed'>
              Public use not approved
            </AnimatedBadge>
          )}
          <span className='inline-flex items-center gap-1'>
            <span aria-hidden='true' className={cn('size-1.5 rounded-full', cloud ? 'bg-emerald-500' : 'bg-muted-foreground/40')} />
            {cloud ? 'Cloud on' : 'Cloud off'}
          </span>
          {web && source.origin?.host && (
            <span className='inline-flex min-w-0 items-center gap-1'>
              <Icons.externalLink className='size-3 shrink-0' />
              <span className='truncate'>{source.origin.host}</span>
            </span>
          )}
          <span>{used > 0 ? `Used in ${plural(used, 'draft')}` : 'Not used yet'}</span>
        </span>
      ) : (
        <span className='text-muted-foreground flex flex-wrap items-center gap-x-2 text-xs'>
          <span>Withdrawn {formatDate(toEpoch(source.withdrawnAt))}</span>
          {blocked > 0 && <span>· {plural(blocked, 'draft')} blocked until regenerated</span>}
        </span>
      )}
    </button>
  );
}
