import type { GrowthReadingWindow } from '@/lib/growth/types';

const STATES = {
  measured: { label: 'available', title: 'The reading is in. Find the useful part.', detail: 'Compare the exact published draft with this reading window. AI suggests a next step; you decide what becomes a lesson.' },
  pending_horizon: { label: 'not due yet', title: 'This reading window is still ahead.', detail: 'The reading window has not arrived. Missing data stays missing.' },
  scheduled: { label: 'scheduled', title: 'The reading is scheduled.', detail: 'The worker has not completed this reading yet. No outcome has been measured for this window.' },
  pending: { label: 'in progress', title: 'The reading is in progress.', detail: 'The worker is collecting the provider reading. No outcome is available yet.' },
  disabled: { label: 'collection disabled', title: 'Post readings are not enabled.', detail: 'Metric collection is disabled. Waiting will not create a reading for this window.' },
  unsupported: { label: 'provider unsupported', title: 'Native analytics are unavailable for this platform.', detail: 'This provider does not offer a qualified post measurement here.' },
  disconnected: { label: 'connection unavailable', title: 'The account connection is unavailable.', detail: 'Reconnect the account and confirm its analytics permissions before collecting new readings.' },
  rights_unavailable: { label: 'analytics permission unavailable', title: 'Analytics permission is unavailable.', detail: 'This account needs authorized native analytics access before Rafii can collect post readings.' },
  unscheduled: { label: 'not scheduled', title: 'This reading was not scheduled.', detail: 'There is no durable reading scheduled for this window. Waiting alone will not create one.' },
  unavailable: { label: 'unavailable', title: 'This reading is unavailable.', detail: 'The provider did not supply a usable reading for this window. Missing data stays missing.' }
} as const;

export function readingState(window?: GrowthReadingWindow) {
  if (window?.available) return STATES.measured;
  const state = window?.state;
  if (!state || state === 'measured') return STATES.unavailable;
  return STATES[state] ?? STATES.unavailable;
}
