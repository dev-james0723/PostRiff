/**
 * What the Roles and Members pages say about the access model. Every rule here is
 * derived from `@/lib/auth/permissions` (the UI mirror of `permissions.py`) or mirrors
 * a named line of the backend; the API still enforces every change.
 */
import { ApiError } from '@/lib/api/client';
import type { Membership } from '@/lib/api/types';
import { ALL_PERMISSIONS } from '@/lib/auth/access';
import { allows } from '@/lib/auth/permissions';
import type { WorkspacePermission, WorkspaceRole } from '@/types';

export type FlagKey = 'can_publish' | 'can_reply' | 'can_moderate' | 'can_manage_connections';
export type Flags = Record<FlagKey, boolean>;

export const ROLES: WorkspaceRole[] = ['owner', 'admin', 'editor', 'approver', 'viewer'];
/** `permissions.py` `validate_grant`: nobody grants `owner`; ownership moves by a separate action. */
export const ASSIGNABLE_ROLES: WorkspaceRole[] = ['admin', 'editor', 'approver', 'viewer'];

export const FLAGS: { key: FlagKey; label: string; short: string; explains: string }[] = [
  {
    key: 'can_publish',
    label: 'Can approve publications',
    short: 'Approve',
    explains: 'Review, approve and cancel exact publications without being an approver.'
  },
  {
    key: 'can_reply',
    label: 'Can reply to comments',
    short: 'Reply',
    explains: 'Send an approved reply to a comment on a connected channel.'
  },
  {
    key: 'can_moderate',
    label: 'Can moderate',
    short: 'Moderate',
    // No hosted action requires the `moderate` class yet (permissions.py ACTION_CLASSES).
    explains: 'Reserved for comment moderation. Nothing in the workspace uses it yet.'
  },
  {
    key: 'can_manage_connections',
    label: 'Can manage connections',
    short: 'Connections',
    explains: 'Connect, re-verify and disconnect channels without being an admin.'
  }
];

export const PERMISSION_LABELS: Record<WorkspacePermission, { label: string; short: string }> = {
  read: { label: 'Read drafts, schedule, analytics', short: 'Read' },
  edit: { label: 'Write and edit drafts', short: 'Edit drafts' },
  approve: { label: 'Approve exact publications', short: 'Approve' },
  reply: { label: 'Reply to comments', short: 'Reply' },
  moderate: { label: 'Moderate comments', short: 'Moderate' },
  manage_connections: { label: 'Connect and disconnect channels', short: 'Manage channels' },
  manage_members: { label: 'Invite and manage members', short: 'Manage members' },
  owner: { label: 'Billing, deletion, ownership', short: 'Billing and deletion' }
};

/**
 * Every action the API guards with `assert_fresh` (hosted.py: invite, update and remove member,
 * transfer ownership, revoke one or all other sessions, turn off two-factor authentication,
 * delete the account; oauth.py: disconnect). Revoking an invitation is not one of them.
 */
export const STEP_UP_ACTIONS: string[] = [
  'Invite someone',
  'Change a member’s role or grants',
  'Remove a member',
  'Transfer ownership',
  'Disconnect a channel',
  'Revoke a signed-in session',
  'Sign out every other session',
  'Turn off two-factor authentication',
  'Delete the account'
];

export const NO_FLAGS: Flags = { can_publish: false, can_reply: false, can_moderate: false, can_manage_connections: false };

export function flagsOf(membership: Membership | null | undefined): Flags {
  return {
    can_publish: Boolean(membership?.can_publish),
    can_reply: Boolean(membership?.can_reply),
    can_moderate: Boolean(membership?.can_moderate),
    can_manage_connections: Boolean(membership?.can_manage_connections)
  };
}

/** The flags that would lift `role` to `permission` on their own (empty when the role already has it). */
export function grantsFor(role: WorkspaceRole, permission: WorkspacePermission): FlagKey[] {
  if (allows({ role, ...NO_FLAGS }, permission)) return [];
  return FLAGS.filter((flag) => allows({ role, ...NO_FLAGS, [flag.key]: true }, permission)).map((flag) => flag.key);
}

/** The permissions a flag adds to at least one role that can carry it. */
export function unlockedBy(flag: FlagKey): WorkspacePermission[] {
  return ALL_PERMISSIONS.filter((permission) => ASSIGNABLE_ROLES.some((role) => grantsFor(role, permission).includes(flag)));
}

export function flagShort(key: FlagKey) {
  return FLAGS.find((flag) => flag.key === key)?.short ?? key;
}

/** Members have no display name in the API yet, so pages show the same short id the Members page does. */
export function shortId(userId: string | null | undefined) {
  return userId ? `${userId.slice(0, 8)}…` : '—';
}

const ASK = 'ask the owner or another admin';

/**
 * For each right this member lacks, one sentence on how to get it. A grant never lifts a viewer
 * (`Membership.allows`), and nobody can change their own access (hosted.py `update_member`).
 * `moderate` is left out: no action needs it yet.
 */
export function howToGetMore(membership: Membership): string[] {
  const { role } = membership;
  if (role === 'owner') return [];
  const lacks = (permission: WorkspacePermission) => !allows(membership, permission);
  if (role === 'viewer') {
    return [`Viewers only read. To write, approve, reply or manage channels, ${ASK} to change your role.`];
  }
  const lines: string[] = [];
  if (lacks('edit')) lines.push(`To write and edit drafts, ${ASK} to change your role.`);
  if (lacks('approve')) lines.push(`To approve publications, ${ASK} to add the Approve grant.`);
  if (lacks('reply')) lines.push(`To reply to comments, ${ASK} to add the Reply grant.`);
  if (lacks('manage_connections')) lines.push(`To connect or disconnect channels, ${ASK} to add the Connections grant.`);
  if (lacks('manage_members')) lines.push(`To invite or manage people, ${ASK} to make you an admin.`);
  lines.push('Billing and deleting the workspace stay with the owner.');
  return lines;
}

export interface GrantRule {
  /** The checkbox cannot be turned on by this actor. */
  cannotAdd: boolean;
  /** The member holds it, the actor does not: saving with it on is refused (`validate_grant`). */
  mustRemove: boolean;
}

/**
 * Mirrors `permissions.py` `validate_grant` for the person making the change:
 * a non-owner may only grant flags they hold themselves (the flag itself, not a
 * right their role already includes), and only an owner or an admin may make someone an admin.
 */
export function grantRules(actor: Membership | null, flags: Flags): Record<FlagKey, GrantRule> {
  const owner = actor?.role === 'owner';
  const result = {} as Record<FlagKey, GrantRule>;
  for (const flag of FLAGS) {
    const held = owner || Boolean(actor?.[flag.key]);
    result[flag.key] = { cannotAdd: !held, mustRemove: !held && flags[flag.key] };
  }
  return result;
}

export function canAssignRole(actor: Membership | null, role: WorkspaceRole) {
  if (role === 'owner') return false;
  if (role === 'admin') return actor?.role === 'owner' || actor?.role === 'admin';
  return true;
}

/**
 * What happens to work someone already approved once they can no longer approve: the worker
 * re-checks the approver at claim time and holds the job (hosted_worker.py, "Approval authority
 * changed; a new review is required"). A held job never resumes; it needs a new review.
 */
export const APPROVAL_HOLD_NOTE =
  'Anything they approved that has not published yet is held when it comes due, and needs a new review before it can go out.';

/** True when this change takes away the member's right to approve. */
export function losesApprove(before: Membership, after: Membership) {
  return allows(before, 'approve') && !allows(after, 'approve');
}

/**
 * `assert_fresh` answers 403 "Sign in again to confirm this sensitive action." The API has no
 * machine-readable code yet, so this matches the message; replace it once errors carry a code.
 */
export function needsFreshSignIn(error: unknown) {
  return error instanceof ApiError && error.status === 403 && /sign in again/i.test(error.message);
}
