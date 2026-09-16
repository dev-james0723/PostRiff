import { Icons } from '@/components/icons';

/** Workspace permissions mirror `permissions.py` on the API side. */
export type WorkspacePermission =
  | 'read'
  | 'edit'
  | 'approve'
  | 'reply'
  | 'moderate'
  | 'manage_connections'
  | 'manage_members'
  | 'owner';

export type WorkspaceRole = 'owner' | 'admin' | 'editor' | 'approver' | 'viewer';

/** Plan ids from migrations/postriff/007_consumer_web_billing.sql. */
export type WorkspacePlan = 'trial' | 'studio' | 'assist';

/**
 * Access requirements for a navigation item or page. All present keys must
 * pass. `capability` is a workspace-level feature flag (for example a hosted
 * connector that has cleared provider review).
 */
export interface PermissionCheck {
  permission?: WorkspacePermission;
  role?: WorkspaceRole;
  plan?: WorkspacePlan;
  capability?: string;
}

export interface NavItem {
  title: string;
  url: string;
  disabled?: boolean;
  external?: boolean;
  shortcut?: [string, string];
  icon?: keyof typeof Icons;
  label?: string;
  description?: string;
  isActive?: boolean;
  items?: NavItem[];
  access?: PermissionCheck;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export interface NavItemWithChildren extends NavItem {
  items: NavItemWithChildren[];
}

export interface NavItemWithOptionalChildren extends NavItem {
  items?: NavItemWithChildren[];
}

export interface FooterItem {
  title: string;
  items: {
    title: string;
    href: string;
    external?: boolean;
  }[];
}

export type MainNavItem = NavItemWithOptionalChildren;

export type SidebarNavItem = NavItemWithChildren;
