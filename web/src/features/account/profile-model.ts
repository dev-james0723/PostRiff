import type { Membership, MyChannel, SecurityEvent, WorkspaceListItem } from '@/lib/api/types';
import { ROLE_LABELS } from '@/lib/auth/permissions';
import type { WorkspaceRole } from '@/types';

/**
 * Pure helpers behind the profile page. Access rules mirror `permissions.py` (the API enforces
 * them); these only decide what the page shows and links to.
 */

/** Owner, staff (owner + admins) and members (everyone else): how the page explains a workspace. */
export function memberTiers(counts: Record<WorkspaceRole, number>) {
  const staff = counts.owner + counts.admin;
  const members = counts.editor + counts.approver + counts.viewer;
  return { owners: counts.owner, staff, members, total: staff + members };
}

/** Staff manage members, roles and connections; the page links them to the Members page. */
export function isStaff(role: WorkspaceRole) {
  return role === 'owner' || role === 'admin';
}

/** Anyone but the owner may leave; the owner transfers ownership first. */
export function canLeave(role: WorkspaceRole) {
  return role !== 'owner';
}

const PLAN_LABELS: Record<string, string> = { trial: 'Trial', studio: 'Studio', assist: 'Studio Assist' };

export function planLabel(item: Pick<WorkspaceListItem, 'plan' | 'trialPlan'>) {
  if (item.plan !== 'trial') return PLAN_LABELS[item.plan] ?? item.plan;
  return item.trialPlan ? `Trial · ${PLAN_LABELS[item.trialPlan] ?? item.trialPlan}` : 'Trial';
}

export const SIGN_IN_METHODS: Record<string, string> = { google: 'Google', email: 'Email code', phone: 'Phone' };

type Flag = 'can_publish' | 'can_reply' | 'can_moderate' | 'can_manage_connections';
const FLAG_LABELS: { key: Flag; label: string }[] = [
  { key: 'can_publish', label: 'approve publications' },
  { key: 'can_reply', label: 'reply to comments' },
  { key: 'can_moderate', label: 'moderate' },
  { key: 'can_manage_connections', label: 'manage connections' }
];
/** Rights a role already carries; a flag only counts as "extra" beyond these. Viewers gain nothing from flags. */
const ROLE_CARRIES: Record<WorkspaceRole, Flag[]> = {
  owner: ['can_publish', 'can_reply', 'can_moderate', 'can_manage_connections'],
  admin: ['can_manage_connections'],
  editor: [],
  approver: ['can_publish'],
  viewer: ['can_publish', 'can_reply', 'can_moderate', 'can_manage_connections']
};

export function extraGrants(membership: Membership): string[] {
  return FLAG_LABELS.filter((flag) => membership[flag.key] && !ROLE_CARRIES[membership.role].includes(flag.key)).map(
    (flag) => flag.label
  );
}

export { channelBadge, needsReconnect } from '@/lib/channels/state';

function roleLabel(value: unknown) {
  return typeof value === 'string' ? (ROLE_LABELS[value as WorkspaceRole] ?? value) : '';
}

/** One plain sentence per account event. `warning` marks the ones worth a second look. */
export function describeSecurityEvent(event: SecurityEvent): { label: string; tone: 'neutral' | 'warning' } {
  const ws = event.workspaceName || 'a workspace';
  const meta = event.meta ?? {};
  const role = roleLabel(meta.role);
  switch (event.kind) {
    case 'session.started':
      return { label: `Signed in on ${typeof meta.client === 'string' && meta.client ? meta.client : 'an unknown device'}`, tone: 'neutral' };
    case 'mfa.enabled':
      return { label: 'Two-factor authentication turned on', tone: 'neutral' };
    case 'mfa.disabled':
      return { label: 'Two-factor authentication turned off', tone: 'warning' };
    case 'session.revoked':
      return { label: 'A session was revoked', tone: 'neutral' };
    case 'session.revoked_others': {
      const count = Number(meta.count ?? 0);
      return { label: count === 1 ? '1 other session signed out' : `${count} other sessions signed out`, tone: 'neutral' };
    }
    case 'session.alerted':
      return meta.sent === false
        ? { label: 'New-device alert could not be emailed', tone: 'warning' }
        : { label: 'New-device alert emailed to you', tone: 'neutral' };
    case 'member.left':
      return { label: `Left ${ws}`, tone: 'neutral' };
    case 'invitation.accepted':
      return { label: `Joined ${ws}${role ? ` as ${role}` : ''}`, tone: 'neutral' };
    case 'invitation.declined':
      return { label: `Declined an invitation to ${ws}`, tone: 'neutral' };
    case 'workspace.created':
      return { label: `Created ${ws}`, tone: 'neutral' };
    case 'member.updated':
      return { label: `Your role in ${ws} changed${role ? ` to ${role}` : ''}`, tone: 'neutral' };
    case 'member.removed':
      return { label: `Removed from ${ws}`, tone: 'warning' };
    case 'data.exported':
      return { label: `Exported ${ws} data`, tone: 'neutral' };
    case 'data.diagnostics':
      return { label: `Shared a diagnostics package for ${ws}`, tone: 'neutral' };
    default:
      return { label: event.kind.replace(/[._]/g, ' '), tone: 'neutral' };
  }
}

/** Group channels by workspace, keeping the API's workspace order. */
export function groupByWorkspace(channels: MyChannel[]) {
  const groups = new Map<string, { workspaceId: string; workspaceName: string; channels: MyChannel[] }>();
  for (const channel of channels) {
    const group = groups.get(channel.workspaceId) ?? {
      workspaceId: channel.workspaceId,
      workspaceName: channel.workspaceName,
      channels: []
    };
    group.channels.push(channel);
    groups.set(channel.workspaceId, group);
  }
  return [...groups.values()];
}
