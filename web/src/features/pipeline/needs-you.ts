/**
 * What is stuck on the board, and why: the "Needs you" stack above the Pipeline. Pure, built only from the
 * unfiltered board and the channel capability matrix, so every count is a real count and an empty list renders
 * nothing.
 */
import type { Icons } from '@/components/icons';
import type { ChannelView } from '@/lib/api/types';
import { allCards, type Board, type ColumnKey } from './board';
import { jobNote } from './job-state';

export interface NeedsYouItem {
  id: string;
  icon: keyof typeof Icons;
  title: string;
  description: string;
  /** The stack's action label when this item leads. */
  action: string;
  /** A column on this board, or a page elsewhere. */
  target: { column: ColumnKey } | { href: string };
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function deriveNeedsYou(
  board: Board,
  options: {
    canApprove: boolean;
    /**
     * The channel capability matrix (`useChannels`). `undefined` while it loads or when it failed: the channel item
     * is left out rather than counted as zero, and never read from the blended `displayState`.
     */
    channels: ChannelView[] | undefined;
  }
): NeedsYouItem[] {
  const cards = allCards(board);
  const items: NeedsYouItem[] = [];

  const held = cards.filter((c) => c.jobGroup === 'held');
  if (held.length > 0) {
    items.push({
      id: 'held',
      icon: 'handStop',
      title: `${plural(held.length, 'job', 'jobs')} held`,
      description: (held[0].job && jobNote(held[0].job)) || 'Something changed after approval. Cancel the job, then prepare a new review.',
      action: 'Show the Queue column',
      target: { column: 'queue' }
    });
  }

  const uncertain = cards.filter((c) => c.jobGroup === 'uncertain');
  if (uncertain.length > 0) {
    items.push({
      id: 'uncertain',
      icon: 'hourglass',
      title: `${plural(uncertain.length, 'publication', 'publications')} uncertain`,
      description: (uncertain[0].job && jobNote(uncertain[0].job)) || 'The provider did not confirm. Nothing is retried until it is reconciled.',
      action: 'Show the Queue column',
      target: { column: 'queue' }
    });
  }

  // Only reviews inside their deadline: `store.py` refuses to approve an expired one, so it is never sent to the Queue.
  const reviews = cards.filter((c) => c.kind === 'review' && !c.footer);
  if (reviews.length > 0) {
    items.push({
      id: 'reviews',
      icon: 'listCheck',
      title: `${plural(reviews.length, 'review', 'reviews')} waiting for approval`,
      description: options.canApprove
        ? 'Each one freezes the exact text, account and time. Approve it in the Queue.'
        : 'An approver must approve each one in the Queue before it is scheduled.',
      action: options.canApprove ? 'Approve in the Queue' : 'Show Needs approval',
      target: options.canApprove ? { href: '/app/queue' } : { column: 'review' }
    });
  }

  // An expired review that is still its draft's latest try: nothing will be published unless the draft is scheduled
  // again (or set aside, which settles it). Stale reviews are not cards, and a newer try supersedes the expired one.
  const reviewKeys = new Set(cards.filter((c) => c.kind === 'review' && c.footer).map((c) => c.key));
  const expired = cards.filter(
    (c) => c.draft?.outcome === 'review expired' && c.draft.outcomeReviewId && reviewKeys.has(`review:${c.draft.outcomeReviewId}`) && !c.draft.setAside && !c.draft.retracted
  );
  if (expired.length > 0) {
    items.push({
      id: 'expired',
      icon: 'clock',
      title: `${plural(expired.length, 'review', 'reviews')} expired before approval`,
      description: options.canApprove
        ? 'They can no longer be approved. Schedule… the draft again to prepare a new review, or set it aside.'
        : 'They can no longer be approved. Someone who can approve schedules the draft again.',
      action: 'Show Drafts',
      target: { column: 'drafts' }
    });
  }

  const retracted = cards.filter((c) => c.draft?.retracted);
  if (retracted.length > 0) {
    items.push({
      id: 'retracted',
      icon: 'alertCircle',
      title: `${plural(retracted.length, 'draft', 'drafts')} blocked by a retracted source`,
      description: 'A source they drew on was withdrawn. Draft them again from current sources.',
      action: 'Show Drafts',
      target: { column: 'drafts' }
    });
  }

  if (options.channels) {
    // Per-capability honesty: what the publish capability itself says, with its evidence.
    const indirect = options.channels.filter((channel) => channel.capabilities.publish?.level !== 'Direct');
    if (indirect.length > 0) {
      items.push({
        id: 'channels',
        icon: 'broadcast',
        title: `${plural(indirect.length, 'channel cannot', 'channels cannot')} publish directly`,
        description: indirect
          .map((channel) => {
            const publish = channel.capabilities.publish;
            return publish
              ? `${channel.platform} ${channel.account}: publish ${publish.level}${publish.evidence ? ` (${publish.evidence})` : ''}`
              : `${channel.platform} ${channel.account}: no publish capability reported`;
          })
          .join(' · '),
        action: 'Open Channels',
        target: { href: '/app/channels' }
      });
    }
  }

  const unreviewed = cards.filter((c) => c.draft?.needsReview && !c.draft.setAside && !c.draft.retracted);
  if (unreviewed.length > 0) {
    items.push({
      id: 'needs-review',
      icon: 'eye',
      title: `${plural(unreviewed.length, 'draft needs', 'drafts need')} a review of unknowns`,
      description: 'Schedule… asks you to confirm unsupported details are left out.',
      action: 'Show Drafts',
      target: { column: 'drafts' }
    });
  }

  return items;
}
