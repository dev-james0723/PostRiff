/**
 * Mirror of `src/postriff_phase2/permissions.py` CLASSES. UI-only: the API
 * enforces every action. Keep the two in sync when a class changes.
 */
import type { Membership } from '@/lib/api/types';
import type { WorkspacePermission, WorkspaceRole } from '@/types';

const CLASSES: Record<
  WorkspacePermission,
  { roles: WorkspaceRole[]; flag: keyof Omit<Membership, 'role'> | null }
> = {
  read: { roles: ['owner', 'admin', 'editor', 'approver', 'viewer'], flag: null },
  edit: { roles: ['owner', 'admin', 'editor'], flag: null },
  approve: { roles: ['owner', 'approver'], flag: 'can_publish' },
  reply: { roles: ['owner'], flag: 'can_reply' },
  moderate: { roles: ['owner'], flag: 'can_moderate' },
  manage_connections: { roles: ['owner', 'admin'], flag: 'can_manage_connections' },
  manage_members: { roles: ['owner', 'admin'], flag: null },
  owner: { roles: ['owner'], flag: null }
};

export function allows(membership: Membership, requirement: WorkspacePermission): boolean {
  const spec = CLASSES[requirement];
  if (membership.role === 'owner' || spec.roles.includes(membership.role)) return true;
  return Boolean(spec.flag) && membership.role !== 'viewer' && Boolean(membership[spec.flag as keyof Membership]);
}

export function permissionsFor(membership: Membership): WorkspacePermission[] {
  return (Object.keys(CLASSES) as WorkspacePermission[]).filter((p) => allows(membership, p));
}

export const ROLE_LABELS: Record<WorkspaceRole, string> = {
  owner: 'Owner',
  admin: 'Admin',
  editor: 'Editor',
  approver: 'Approver',
  viewer: 'Viewer'
};

export const ROLE_DESCRIPTIONS: Record<WorkspaceRole, string> = {
  owner: 'Everything, including billing, deletion and member roles.',
  admin: 'Edit content, manage members and connections. No billing.',
  editor: 'Write and edit drafts. Cannot approve or publish.',
  approver: 'Review and approve exact publications. Cannot edit drafts.',
  viewer: 'Read-only access to drafts, schedule and analytics.'
};
