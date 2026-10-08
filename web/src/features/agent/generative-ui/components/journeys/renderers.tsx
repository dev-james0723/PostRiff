'use client';
/**
 * Consumer journey renderers (lane E), keyed by component name. Lane C's `library.tsx` attaches them to the specs in
 * `specs.ts`; the founder renderers live in `founder-renderers.tsx` so founder components never ship in the consumer
 * chunk. Every renderer shows bound data only and safe-parses its own literal props.
 */
import { CalendarAgenda, ProposalList, QueueStatus, RescheduleForm, SlotCheck } from './calendar';
import { Commentary } from './commentary';
import { DraftCompare, DraftDetail, DraftEditor, DraftEvidence, DraftList } from './drafts';
import type { JourneyRenderers } from './types';

export const JOURNEY_RENDERERS: JourneyRenderers = {
  Commentary,
  DraftList,
  DraftCompare,
  DraftDetail,
  DraftEvidence,
  DraftEditor,
  CalendarAgenda,
  QueueStatus,
  SlotCheck,
  RescheduleForm,
  ProposalList,
};
