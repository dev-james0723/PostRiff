'use client';

import { useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Badge } from '@/components/ui/badge';
import type { LearnedItem, MemoryProposal, MemoryProposals } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { formatDate } from '@/lib/time';
import { ProposalCard } from './proposal-card';

const DECISION_LABEL: Record<string, string> = {
  remembered: 'Remembered',
  edited: 'Remembered, reworded',
  dismissed: 'Dismissed',
  post_only: 'Only for that post',
  expired: 'Expired'
};

const RETIRED_LABEL: Record<string, string> = {
  replaced: 'Replaced',
  undone: 'Undone',
  retired: 'Retired'
};

/** Rows enter 40ms apart. The delay stops at 120ms so the last row settles by 300ms (120 + 180), however long the list is. */
const STAGGER = 0.04;
const MAX_STAGGERED = 3;
const ROW_DURATION = 0.18;

function scopeLabel(scope: LearnedItem['scope']) {
  const { platform, language, contentTypeId } = scope;
  const base = platform && language ? `${platform} · ${language}` : platform ? `${platform} · all languages` : language ? `All channels · ${language}` : 'All channels';
  return contentTypeId ? `${base} · ${contentTypeId}` : base;
}

function isoToEpoch(value: unknown) {
  if (typeof value !== 'string' || !value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms / 1000 : null;
}

interface DecidedRow {
  key: string;
  statement: string;
  label: string;
  scope: string;
  when: string | null;
  at: number | null;
}

function decidedRows(data: MemoryProposals): DecidedRow[] {
  const proposals = (data.recent ?? []).map((proposal: MemoryProposal): DecidedRow => {
    const label = DECISION_LABEL[proposal.status] ?? proposal.status.replace(/_/g, ' ');
    const when = proposal.decidedAt
      ? `Decided ${formatDate(proposal.decidedAt)}`
      : proposal.status === 'expired' && proposal.expiresAt
        ? `Expired ${formatDate(proposal.expiresAt)}`
        : null;
    return { key: `proposal-${proposal.id}`, statement: proposal.statement, label, scope: proposal.scopeLabel, when, at: proposal.decidedAt ?? (proposal.status === 'expired' ? proposal.expiresAt : null) };
  });
  const retired = (data.learning?.items ?? [])
    .filter((item) => item.status === 'retired')
    .map((item): DecidedRow => {
      const { validTo } = item as LearnedItem & { validTo?: string };
      const at = isoToEpoch(validTo);
      const label = RETIRED_LABEL[item.retiredReason ?? 'retired'] ?? 'Retired';
      return { key: `item-${item.id}`, statement: item.statement, label, scope: scopeLabel(item.scope), when: at ? `${label} ${formatDate(at)}` : null, at };
    });
  return [...proposals, ...retired].toSorted((a, b) => (b.at ?? -Infinity) - (a.at ?? -Infinity));
}

function Row({ index, statement, meta, badge }: { index: number; statement: string; meta: string; badge?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduce ? { duration: 0 } : { duration: ROW_DURATION, ease: EASE_OUT, delay: Math.min(index, MAX_STAGGERED) * STAGGER }}
      className='flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0'
    >
      <span className='text-sm leading-snug'>{statement}</span>
      <span className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs'>
        {badge && <Badge variant='outline'>{badge}</Badge>}
        {meta}
      </span>
    </motion.li>
  );
}

function HistoryTabs({ data }: { data: MemoryProposals }) {
  const pending = data.pending ?? [];
  const decided = decidedRows(data);
  const retiredCount = (data.learning?.items ?? []).filter((item) => item.status === 'retired').length;
  const total = data.recentTotal === undefined ? null : data.recentTotal + retiredCount;
  const [tab, setTab] = useState(pending.length > 0 ? 'waiting' : 'decided');

  return (
    <Tabs value={tab} onValueChange={setTab} variant='segment' className='flex flex-col'>
      <TabsList className='bg-muted grid w-full grid-cols-2 sm:inline-flex sm:w-fit' aria-label='Suggestions'>
        <TabsTrigger value='waiting' wrapperClassName='min-w-0' className='w-full gap-1.5 px-3 py-1 text-xs'>
          Waiting <DigitSwap value={pending.length} />
        </TabsTrigger>
        <TabsTrigger value='decided' wrapperClassName='min-w-0' className='w-full gap-1.5 px-3 py-1 text-xs'>
          Recent {total !== null && <DigitSwap value={total} />}
        </TabsTrigger>
      </TabsList>
      <TabsContent value='waiting' className='mt-3'>
        {pending.length === 0 ? (
          <p className='text-muted-foreground text-xs'>Nothing is waiting for a decision.</p>
        ) : (
          <div className='flex flex-col gap-2'>
            {pending.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} />)}
          </div>
        )}
      </TabsContent>
      <TabsContent value='decided' className='mt-3'>
        {decided.length === 0 ? (
          <p className='text-muted-foreground text-xs'>No decisions yet. Suggestions an owner remembers, rewords or dismisses appear here, and so do retired preferences.</p>
        ) : (
          <div className='flex flex-col gap-3'>
            <ul className='flex flex-col divide-y'>
              {decided.map((row, index) => (
                <Row key={row.key} index={index} statement={row.statement} badge={row.label} meta={[row.scope, row.when].filter(Boolean).join(' · ')} />
              ))}
            </ul>
            <p className='text-muted-foreground border-t pt-2 text-xs'>Newest first. {total !== null ? `Showing ${decided.length} of ${total} decisions and retired preferences.` : 'Showing the latest decisions and retired preferences. The total is unavailable.'}</p>
          </div>
        )}
      </TabsContent>
    </Tabs>
  );
}

/**
 * When each waiting suggestion expires and what was decided before: the proposals' `expiresAt`, the recent
 * decisions with `decidedAt`, and the retired preferences. If the proposals cannot be read, it says so.
 */
export function LearningHistory({ data }: { data: MemoryProposals }) {
  return (
    <section aria-labelledby='learning-history-title' className='flex flex-col gap-3 border-t pt-3'>
      <h2 id='learning-history-title' className='text-sm font-semibold'>Suggestions and decisions</h2>
      <HistoryTabs data={data} />
    </section>
  );
}
