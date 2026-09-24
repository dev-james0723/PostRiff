'use client';

import { useId, useState } from 'react';
import { DigitSwap } from '@/components/motion/digit-swap';
import { SegmentedControl } from '@/components/rafii';
import { StatusChip } from '@/features/workspace/rafii-parts';
import type { LearnedItem, MemoryProposal, MemoryProposals } from '@/lib/api/types';
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
    const when = proposal.decidedAt ? `Decided ${formatDate(proposal.decidedAt)}` : proposal.status === 'expired' && proposal.expiresAt ? `Expired ${formatDate(proposal.expiresAt)}` : null;
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

function Row({ statement, meta, badge }: { statement: string; meta: string; badge?: string }) {
  return (
    <li className='flex flex-col gap-1.5 py-2.5'>
      <span className='text-foreground text-sm leading-snug'>{statement}</span>
      <span className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs'>
        {badge && <StatusChip icon={null}>{badge}</StatusChip>}
        {meta}
      </span>
    </li>
  );
}

function HistoryTabs({ data }: { data: MemoryProposals }) {
  const pending = data.pending ?? [];
  const decided = decidedRows(data);
  const retiredCount = (data.learning?.items ?? []).filter((item) => item.status === 'retired').length;
  const total = data.recentTotal === undefined ? null : data.recentTotal + retiredCount;
  const [tab, setTab] = useState<'waiting' | 'decided'>(pending.length > 0 ? 'waiting' : 'decided');
  const base = useId();
  const panelIds = [`${base}-waiting`, `${base}-decided`];

  return (
    <div className='flex flex-col gap-3'>
      <SegmentedControl
        pattern='tabs'
        label='Suggestions'
        size='sm'
        value={tab}
        onChange={setTab}
        panelIds={panelIds}
        className='w-full sm:w-fit'
        widths='equal'
        options={[
          {
            value: 'waiting',
            label: (
              <span className='inline-flex items-center gap-1.5'>
                Waiting <DigitSwap value={pending.length} />
              </span>
            )
          },
          {
            value: 'decided',
            label: <span className='inline-flex items-center gap-1.5'>Recent {total !== null && <DigitSwap value={total} />}</span>
          }
        ]}
      />
      {tab === 'waiting' ? (
        <div role='tabpanel' id={panelIds[0]} tabIndex={0} className='rafii-focus rounded-[var(--rafii-radius-control)]'>
          {pending.length === 0 ? (
            <p className='text-muted-foreground text-xs'>Nothing is waiting for a decision.</p>
          ) : (
            <div className='flex flex-col gap-2'>
              {pending.map((proposal) => (
                <ProposalCard key={proposal.id} proposal={proposal} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div role='tabpanel' id={panelIds[1]} tabIndex={0} className='rafii-focus rounded-[var(--rafii-radius-control)]'>
          {decided.length === 0 ? (
            <p className='text-muted-foreground text-xs'>No decisions yet. Suggestions an owner remembers, rewords or dismisses appear here, and so do retired preferences.</p>
          ) : (
            <div className='flex flex-col gap-3'>
              <ul className='flex flex-col'>
                {decided.map((row) => (
                  <Row key={row.key} statement={row.statement} badge={row.label} meta={[row.scope, row.when].filter(Boolean).join(' · ')} />
                ))}
              </ul>
              <p className='text-muted-foreground text-xs'>Newest first. {total !== null ? `Showing ${decided.length} of ${total} decisions and retired preferences.` : 'Showing the latest decisions and retired preferences. The total is unavailable.'}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * When each waiting suggestion expires and what was decided before: the proposals' `expiresAt`, the recent
 * decisions with `decidedAt`, and the retired preferences. If the proposals cannot be read, it says so.
 */
export function LearningHistory({ data }: { data: MemoryProposals }) {
  return (
    <section aria-labelledby='learning-history-title' className='flex flex-col gap-3 pt-1'>
      <h3 id='learning-history-title' className='text-foreground text-sm font-medium'>
        Suggestions and decisions
      </h3>
      <HistoryTabs data={data} />
    </section>
  );
}
