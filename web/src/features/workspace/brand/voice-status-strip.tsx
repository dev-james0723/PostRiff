'use client';

import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Surface } from '@/components/rafii';
import { StatusChip } from '@/features/workspace/rafii-parts';
import type { LearningSummary, SnapshotState } from '@/lib/api/types';
import { ApprovedDate, type Refetchable } from './brand-parts';
import { reasonLabel, voiceCounts, voiceStatus, type VoiceStatus } from './voice-model';

interface MemoryRead extends Refetchable {
  isLoading: boolean;
  isError: boolean;
  data?: { learning?: LearningSummary };
}

function badgeFor(status: VoiceStatus): { status: AnimatedBadgeStatus; label: string } {
  switch (status.kind) {
    case 'active':
      return { status: 'success', label: `Active · revision ${status.revision}` };
    case 'waiting':
      return { status: 'warning', label: 'Waiting for an owner' };
    case 'none':
      return { status: 'neutral', label: 'Not set up' };
    default:
      return { status: 'warning', label: 'Status unavailable' };
  }
}

function plural(count: number, one: string, many: string) {
  return count === 1 ? one : many;
}

/** One short line under the chip, only when there is something to do or watch. Rules are stated as what waits, never as what is blocked. */
function reminder(status: VoiceStatus, earlier: number | null, isOwner: boolean): string | null {
  switch (status.kind) {
    case 'active':
      if (status.waiting) return isOwner ? 'A new revision is waiting for your approval.' : 'A new revision is waiting for an owner.';
      if (earlier && earlier > 0) return `Redraft ${earlier === 1 ? 'the older draft' : `the ${earlier} older drafts`} with this voice to schedule ${plural(earlier, 'it', 'them')}.`;
      return null;
    case 'waiting':
      return isOwner ? 'A proposed voice is waiting for your approval. Check draft wording meanwhile.' : 'A proposed voice is waiting for an owner. Check draft wording meanwhile.';
    case 'none':
      return status.earlier > 0 ? 'No active voice. Check draft wording carefully.' : 'Set up a voice so drafts sound consistent.';
    default:
      return 'Couldn’t load the voice status.';
  }
}

/** A label and a number. The consequence behind it sits in a tooltip and the accessible description, not on screen. */
function Count({ label, value, hint }: { label: string; value: number | null | 'pending'; hint: string }) {
  return (
    <div className='flex min-w-0 flex-col gap-0.5' title={hint}>
      <span className='text-muted-foreground text-xs'>{label}</span>
      {value === 'pending' ? (
        <span className='text-muted-foreground text-xl font-semibold'>
          <span aria-hidden>—</span>
          <span className='sr-only'>Loading</span>
        </span>
      ) : value === null ? (
        <span className='text-muted-foreground text-sm font-medium'>Unavailable</span>
      ) : (
        <span className='text-foreground text-xl font-semibold tabular-nums'>
          <DigitSwap value={value} />
        </span>
      )}
      <span className='sr-only'>{hint}</span>
    </div>
  );
}

export function VoiceStatusStrip({ state, isOwner, memory }: { state: SnapshotState | undefined; isOwner: boolean; memory: MemoryRead }) {
  const status = voiceStatus(state);
  const counts = voiceCounts(state);
  const badge = badgeFor(status);
  const learning = memory.data?.learning;
  const note = reminder(status, counts.earlier, isOwner);
  const learned: number | null | 'pending' = memory.isLoading ? 'pending' : memory.isError || !learning || !Array.isArray(learning.items) ? null : learning.items.filter((item) => item.status === 'active').length;

  return (
    <Surface as='section' material='glass' aria-label='Voice status' data-tour='brand-status' className='flex flex-col gap-4'>
      <div className='flex min-w-0 flex-col gap-2'>
        <div className='flex flex-wrap items-center gap-x-3 gap-y-1'>
          <StatusChip status={badge.status}>{badge.label}</StatusChip>
          {status.kind === 'active' && status.record && (
            <span className='text-muted-foreground hidden text-xs md:inline'>
              Approved <ApprovedDate iso={status.record.approvedAt} />
              {reasonLabel(status.record.reason) ? ` · ${reasonLabel(status.record.reason)}` : ''}
            </span>
          )}
        </div>
        {note && <p className='text-muted-foreground max-w-prose text-sm leading-relaxed text-pretty'>{note}</p>}
      </div>
      <div className='grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4'>
        {status.kind === 'active' ? (
          <>
            <Count label='On this voice' value={counts.onVoice} hint='Drafts written with the active voice.' />
            <Count label='Older drafts' value={counts.earlier} hint='Edit and preview; redraft to schedule.' />
          </>
        ) : (
          <Count label='Drafts' value={counts.drafts} hint='Edit and preview any time.' />
        )}
        <Count label='Scheduled' value={counts.bound} hint='Approved or scheduled posts. Held if the voice changes.' />
        <Count label='Learned preferences' value={learned} hint='Accepted on the Memory page.' />
      </div>
    </Surface>
  );
}
