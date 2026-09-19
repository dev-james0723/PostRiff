import type { ConnectCapability } from './state';

/**
 * Names and general-audience one-liners for the capabilities the Channels page shows.
 * The API's keys (`postriff_phase2/channels.py: CAPABILITIES`) stay as they are; only the
 * labels are ours. Evidence text always comes from the API, never from here.
 */

export interface CapabilityChipDef {
  key: string;
  label: string;
  /** What the capability means, for the hover card. */
  meaning: string;
}

/** The six chips on a channel card, in display order. */
export const CAPABILITY_CHIPS: readonly CapabilityChipDef[] = [
  { key: 'identity', label: 'Identity', meaning: 'PostRiff matched the account the provider returned.' },
  { key: 'publish', label: 'Publish', meaning: 'Posting to this account after your approval.' },
  { key: 'schedule', label: 'Schedule', meaning: 'Holding an approved post until its time, then publishing it.' },
  { key: 'analytics', label: 'Analytics', meaning: 'Reading reach and engagement for posts on this account.' },
  { key: 'comments_read', label: 'Comments', meaning: 'Reading comments and replies on this account.' },
  { key: 'reply', label: 'Reply', meaning: 'Replying to comments from this account after your approval.' }
];

export function capabilityLabel(key: string) {
  return CAPABILITY_CHIPS.find((chip) => chip.key === key)?.label ?? key.replace(/_/g, ' ');
}

export interface ConnectCapabilityDef {
  key: ConnectCapability;
  label: string;
  /** What choosing it asks the provider for, before the API's own explanation arrives. */
  description: string;
}

/** The choices in the Connect sheet; a provider only lists the ones it offers. */
export const CONNECT_CAPABILITY_OPTIONS: readonly ConnectCapabilityDef[] = [
  { key: 'publish', label: 'Publish', description: 'Post to this account after you approve each post.' },
  { key: 'analytics', label: 'Analytics', description: 'Read reach and engagement for this account.' },
  { key: 'comments_read', label: 'Comments', description: 'Read comments and replies on this account.' },
  { key: 'reply', label: 'Reply', description: 'Reply to comments from this account after you approve each reply.' }
];

/** Plain words for each capability level, shared with the badge component's colours. */
export const LEVEL_MEANING: Record<string, string> = {
  Direct: 'Direct: through the official API after your approval.',
  Assisted: 'Assisted: PostRiff prepares it and you finish the last step.',
  Bridge: 'Local: runs through the desktop companion on your own machine.',
  Unsupported: 'Not offered by this provider for this app.'
};
