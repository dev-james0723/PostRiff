'use client';

/**
 * Workspace access context.
 *
 * Phase A ships a stub: every caller sees an owner on a trial workspace with
 * every permission. Phase B replaces `STUB_ACCESS` with data from the session
 * and `/api/workspaces/{id}` without changing this module's public surface.
 */

import { createContext, useContext, type ReactNode } from 'react';
import type { PermissionCheck, WorkspacePermission, WorkspacePlan, WorkspaceRole } from '@/types';

export const ALL_PERMISSIONS: WorkspacePermission[] = [
  'read',
  'edit',
  'approve',
  'reply',
  'moderate',
  'manage_connections',
  'manage_members',
  'owner'
];

/** Plans ordered by tier. A requirement of `studio` is satisfied by `assist`. */
const PLAN_ORDER: WorkspacePlan[] = ['trial', 'studio', 'assist'];

export interface WorkspaceAccess {
  role: WorkspaceRole;
  permissions: WorkspacePermission[];
  plan: WorkspacePlan;
  hasWorkspace: boolean;
  /** Workspace-level feature flags (for example reviewed hosted connectors). */
  capabilities: string[];
}

export const STUB_ACCESS: WorkspaceAccess = {
  role: 'owner',
  permissions: ALL_PERMISSIONS,
  plan: 'trial',
  hasWorkspace: true,
  capabilities: []
};

const WorkspaceAccessContext = createContext<WorkspaceAccess>(STUB_ACCESS);

export function WorkspaceAccessProvider({
  value,
  children
}: {
  value?: WorkspaceAccess;
  children: ReactNode;
}) {
  return (
    <WorkspaceAccessContext.Provider value={value ?? STUB_ACCESS}>
      {children}
    </WorkspaceAccessContext.Provider>
  );
}

export function useWorkspaceAccess(): WorkspaceAccess {
  return useContext(WorkspaceAccessContext);
}

/**
 * Pure check used by navigation filtering and `PageContainer` gating.
 * UI-only: real enforcement lives in the API.
 */
export function checkAccess(access: WorkspaceAccess, check?: PermissionCheck): boolean {
  if (!check) return true;

  if (!access.hasWorkspace) return false;

  if (check.permission && !access.permissions.includes(check.permission)) {
    return false;
  }

  // Owners see everything a narrower role would see.
  if (check.role && access.role !== check.role && access.role !== 'owner') {
    return false;
  }

  if (check.plan && PLAN_ORDER.indexOf(access.plan) < PLAN_ORDER.indexOf(check.plan)) {
    return false;
  }

  if (check.capability && !access.capabilities.includes(check.capability)) {
    return false;
  }

  return true;
}
