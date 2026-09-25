/**
 * The one short word (or two) Raffi uses for each state a person sees. Every surface that shows
 * one of these states reads it from here, so "Connected" never becomes "Successfully connected"
 * on one page and "Currently connected" on another. Detail belongs in a tooltip or an
 * accessible name, not in the label.
 */
export const STATUS = {
  connected: 'Connected',
  readOnly: 'Read only',
  disconnected: 'Disconnected',
  reconnect: 'Needs reconnect',
  expiringSoon: 'Expiring soon',
  missingPermissions: 'Missing permissions',
  accountOnly: 'Account only',
  draft: 'Draft',
  needsReview: 'Needs review',
  changesRequested: 'Changes requested',
  approved: 'Approved',
  scheduled: 'Scheduled',
  publishing: 'Publishing',
  published: 'Published',
  failed: 'Failed',
  paused: 'Paused',
  active: 'Active',
  expired: 'Expired',
  trial: 'Trial',
  saved: 'Saved',
  saving: 'Saving…'
} as const;

export type StatusKey = keyof typeof STATUS;
