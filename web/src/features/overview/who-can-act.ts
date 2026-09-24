import type { WorkspacePermission } from '@/types';

/**
 * Who can act on an attention item: the permission its destination page asks for, from the same
 * client mirror of `permissions.py` the Roles and Members pages use (`features/workspace/access-model`).
 * Pure: an unknown destination returns null rather than a guess.
 */
export interface WhoCanAct {
  permission: WorkspacePermission;
  /** Short label for "Needs …". */
  label: string;
}

const BY_PATH: Record<string, WhoCanAct> = {
  '/app/workspace/brand': { permission: 'edit', label: 'edit access' },
  '/app/account/billing': { permission: 'owner', label: 'the owner' },
  '/app/channels': { permission: 'manage_connections', label: 'manage channels' },
  '/app/queue': { permission: 'approve', label: 'approve' }
};

export function whoCanAct(item: { id: string; href: string }): WhoCanAct | null {
  // Approving a proposed voice is an owner decision (permissions.py profile_decide), whatever page it opens.
  if (item.id === 'voice-proposal') return { permission: 'owner', label: 'the owner' };
  const path = item.href.split('?')[0].split('#')[0];
  return BY_PATH[path] ?? null;
}
