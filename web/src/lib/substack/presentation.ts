import type { SubstackCapabilities, SubstackConnection, SubstackDraft, SubstackHandoff } from './types';

export const SUBSTACK_STATUS_LABELS: Record<string, string> = {
  available: 'Available',
  unsupported: 'Not supported',
  requires_official_approval: 'Official access required',
  requires_account_eligibility: 'Publication eligibility required',
  permission_missing: 'Permission required',
  temporarily_unavailable: 'Temporarily unavailable'
};

export const SUBSTACK_CAPABILITY_LABELS: Record<string, string> = {
  draft_create: 'Create a Rafii draft',
  draft_edit: 'Edit a Rafii draft',
  draft_preview: 'Preview a Rafii draft',
  draft_approval: 'Review and approve a draft',
  manual_handoff: 'Export for manual handoff',
  editorial_schedule: 'Set a target handoff time',
  public_feed_read: 'Read a public publication feed',
  public_feed_remove: 'Remove a saved feed',
  account_connect: 'Authorize a Substack account',
  account_reconnect: 'Reconnect an authorized account',
  account_disconnect: 'Revoke an authorized connection',
  publication_select: 'Select an authorized publication',
  publication_info: 'Read authorized publication details',
  publication_analytics: 'Read publication analytics',
  notes_create: 'Publish Notes',
  post_publish: 'Publish articles or newsletters',
  post_schedule: 'Schedule automatic publication',
  comments_read: 'Read community comments',
  subscribers_read: 'Read subscriber data'
};

export function isSubstackProvider(provider: { id: string; platform: string }): boolean {
  return provider.id.toLowerCase() === 'substack' || provider.platform.toLowerCase() === 'substack';
}

/** Presentation only. The hosted API independently checks grants, eligibility and workspace permissions. */
export function substackAvailable(capabilities: SubstackCapabilities, key: string): boolean {
  return capabilities[key]?.status === 'available';
}

export function activeSubstackConnection(connection: SubstackConnection): boolean {
  return connection.status === 'feed_added' || connection.status === 'connected';
}

/** A feed can never turn into authenticated proof merely because an inconsistent payload sets a boolean. */
export function substackConnectionClaims(connection: SubstackConnection) {
  const active = activeSubstackConnection(connection);
  const official = active && connection.mode !== 'public_feed';
  const authenticated = official && connection.accountAuthenticated === true;
  return [
    { label: 'Public Feed Added', verified: active && connection.mode === 'public_feed' },
    { label: 'Publication Ownership Verified', verified: authenticated && connection.ownershipVerified === true },
    { label: 'Account Authenticated', verified: authenticated },
    { label: 'Analytics Connected — Read Only', verified: authenticated && connection.analyticsConnected === true },
    { label: 'Publishing Authorized', verified: authenticated && connection.mode !== 'official_mcp_analytics' && connection.publishingAuthorized === true }
  ];
}

/** Limit outgoing feed links to the publication and the official Substack origin; never render a payload URL blindly. */
export function safeSubstackHref(value: unknown, publicationUrl?: string): string | null {
  if (typeof value !== 'string' || value.length > 2048) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
    if (url.hostname !== 'substack.com' && !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.substack\.com$/i.test(url.hostname)) return null;
    if (publicationUrl) {
      const publication = new URL(publicationUrl);
      if (url.hostname !== publication.hostname && url.hostname !== 'substack.com') return null;
    }
    return url.href;
  } catch {
    return null;
  }
}

export function approvedSubstackDraft(draft: SubstackDraft, connection: SubstackConnection | undefined): boolean {
  return Boolean(
    connection && connection.id === draft.connectionId && activeSubstackConnection(connection) &&
    (draft.status === 'approved' || draft.status === 'handoff_ready') &&
    /^[a-f0-9]{64}$/.test(draft.contentHash) && draft.approvedHash === draft.contentHash
  );
}

/** Keep receipt data outside the article so it cannot accidentally be pasted into a newsletter. */
export function substackHandoffMarkdown(handoff: SubstackHandoff, approvedHash: string): string {
  if (handoff.status !== 'manual_action_required' || handoff.autoPublished !== false || handoff.format !== 'markdown' ||
    !/^[a-f0-9]{64}$/.test(approvedHash) || handoff.contentHash !== approvedHash || !safeSubstackHref(handoff.publicationUrl)) {
    throw new Error('The handoff receipt did not match the approved draft. Reload the saved draft before trying again.');
  }
  return `${handoff.title.trim() ? `# ${handoff.title}\n\n` : ''}${handoff.body}\n`;
}

const padDatePart = (part: number) => String(part).padStart(2, '0');

export function toSubstackLocalDateTime(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}T${padDatePart(date.getHours())}:${padDatePart(date.getMinutes())}`;
}

export function fromSubstackLocalDateTime(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error('Choose a valid target handoff time.');
  return date.toISOString();
}
