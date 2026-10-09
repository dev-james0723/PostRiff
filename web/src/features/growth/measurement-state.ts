import type { GrowthReadingWindow } from '@/lib/growth/types';

// One honest label per reading window. A missed window stays missed (a late reading is never stored as it), an
// imported reading is a lifetime value at its age, and admission or rights problems never ask to reconnect.
const STATES = {
  measured: { label: 'available', mark: '●', title: 'The reading is in. Find the useful part.', detail: 'Compare the exact published draft with this reading window. AI suggests a next step; you decide what becomes a lesson.' },
  pending_horizon: { label: 'not due yet', mark: '○', title: 'This reading window is still ahead.', detail: 'The reading window has not arrived. Missing data stays missing.' },
  scheduled: { label: 'scheduled', mark: '◔', title: 'The reading is scheduled.', detail: 'The worker has not completed this reading yet. No outcome has been measured for this window.' },
  pending: { label: 'in progress', mark: '◑', title: 'The reading is in progress.', detail: 'The worker is collecting the provider reading. No outcome is available yet.' },
  missed: { label: 'missed', mark: '×', title: 'This reading window was missed.', detail: 'The window passed before a reading could be taken, so nothing was recorded for it. A later reading is never stored in its place. Missing data stays missing.' },
  backfill: { label: 'imported reading', mark: '◆', title: 'An imported lifetime reading.', detail: 'Read once, at the post’s age when it was imported. It is not a 1h, 24h or 7d window and is never compared with them.' },
  disabled: { label: 'collection disabled', mark: '–', title: 'Post readings are not enabled.', detail: 'Metric collection is disabled. Waiting will not create a reading for this window.' },
  not_entitled: { label: 'readings paused', mark: '–', title: 'Post readings are paused for this workspace.', detail: 'This workspace is not collecting post readings right now, so this window was not read. Missing data stays missing.' },
  unsupported: { label: 'provider unsupported', mark: '–', title: 'Native analytics are unavailable for this platform.', detail: 'This provider does not offer a qualified post measurement here.' },
  disconnected: { label: 'connection unavailable', mark: '–', title: 'The account connection is unavailable.', detail: 'Reconnect the account and confirm its analytics permissions before collecting new readings.' },
  rights_unavailable: { label: 'analytics permission unavailable', mark: '–', title: 'Analytics permission is unavailable.', detail: 'This account needs authorized native analytics access before Rafii can collect post readings.' },
  unscheduled: { label: 'not scheduled', mark: '–', title: 'This reading was not scheduled.', detail: 'There is no durable reading scheduled for this window. Waiting alone will not create one.' },
  unavailable: { label: 'unavailable', mark: '○', title: 'This reading is unavailable.', detail: 'The provider did not supply a usable reading for this window. Missing data stays missing.' }
} as const;

export type ReadingStateKey = keyof typeof STATES;

export function readingStateKey(window?: GrowthReadingWindow): ReadingStateKey {
  if (window?.available) return 'measured';
  const state = window?.state;
  if (!state || state === 'measured' || !Object.hasOwn(STATES, state)) return 'unavailable';
  return state as ReadingStateKey;
}

export function readingState(window?: GrowthReadingWindow) {
  return STATES[readingStateKey(window)];
}
