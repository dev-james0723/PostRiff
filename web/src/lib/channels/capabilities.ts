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
  { key: 'identity', label: 'Identity', meaning: 'The account you signed in with.' },
  { key: 'publish', label: 'Publish', meaning: 'Posts you approve.' },
  { key: 'schedule', label: 'Schedule', meaning: 'Approved posts go out at their time.' },
  { key: 'analytics', label: 'Analytics', meaning: 'Reach and engagement for your posts.' },
  { key: 'comments_read', label: 'Comments', meaning: 'Comments and replies on your posts.' },
  { key: 'reply', label: 'Reply', meaning: 'Replies you approve.' }
];

export function capabilityLabel(key: string) {
  return CAPABILITY_CHIPS.find((chip) => chip.key === key)?.label ?? key.replace(/_/g, ' ');
}

export interface ConnectCapabilityDef {
  key: ConnectCapability;
  label: string;
  /** What choosing it grants, before the API's own explanation arrives. Permission words stay explicit. */
  description: string;
}

/** The choices in the Connect sheet; a provider only lists the ones it offers. */
export const CONNECT_CAPABILITY_OPTIONS: readonly ConnectCapabilityDef[] = [
  { key: 'identity', label: 'Account only', description: 'Confirms the account. No posting.' },
  { key: 'posts_read', label: 'Read my posts', description: 'To learn your voice. You pick the posts and approve analysis. No posting.' },
  { key: 'publish', label: 'Publish', description: 'Posts only what you approve.' },
  { key: 'analytics', label: 'Analytics', description: 'Reads reach and engagement.' },
  { key: 'comments_read', label: 'Comments', description: 'Reads comments and replies.' },
  { key: 'reply', label: 'Reply', description: 'Replies only with your approval.' }
];

/** One line per capability level, for hover cards and InfoTips (never inline on the card). */
export const LEVEL_MEANING: Record<string, string> = {
  Direct: 'Direct: Rafii does it after your approval.',
  Assisted: 'Assisted: Rafii prepares it; you finish the last step.',
  Bridge: 'Local: runs on your own computer.',
  Unsupported: 'Not available for this platform yet.'
};
