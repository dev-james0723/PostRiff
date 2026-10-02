/**
 * Which first-week posts the person can write themselves (PRD R-FWR-02, "Free manual writing"). Type-only imports, so
 * `node --test web/tests/first-week-slots.test.mjs` loads it directly.
 *
 * The server's `write_slot` accepts the person's own words for any post that isn't in Queue yet, on any plan, for free:
 * writing needs no source, answer or AI. A post the planner couldn't draft (no approved source, or a question for the
 * person) is exactly the one they may want to write, so it is offered too, not only a `planned` one.
 */
import type { FirstWeekSlot } from './first-week-types';

const WRITABLE = new Set(['planned', 'needs_input', 'needs_source']);

/** "Write it yourself" is offered for a committed post that has no draft yet and isn't in Queue. */
export function canWriteYourself(slot: Pick<FirstWeekSlot, 'committed' | 'draft' | 'status'>): boolean {
  return slot.committed && !slot.draft && WRITABLE.has(slot.status);
}
