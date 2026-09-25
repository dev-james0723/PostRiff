'use client';

import { usePathname } from 'next/navigation';
import { useMemo } from 'react';

type BreadcrumbItem = {
  title: string;
  link: string;
};

const TITLES: Record<string, string> = {
  app: 'Home',
  overview: 'Overview',
  agent: 'Chat',
  memory: 'Memory',
  models: 'Models',
  ideas: 'Ideas',
  calendar: 'Calendar',
  pipeline: 'Pipeline',
  library: 'Library',
  channels: 'Channels',
  connect: 'Connect',
  queue: 'Queue',
  analytics: 'Analytics',
  inbox: 'Inbox',
  workspace: 'Workspace',
  members: 'Members',
  roles: 'Roles',
  audit: 'Audit log',
  brand: 'Brand',
  account: 'Account',
  profile: 'Profile',
  notifications: 'Notifications',
  billing: 'Usage & plan',
  privacy: 'Privacy & data',
  api: 'API & integrations'
};

/** Group segments without their own page point at the first child instead. */
const GROUP_LANDING: Record<string, string> = {
  '/app/workspace': '/app/workspace/members',
  '/app/account': '/app/account/profile'
};

export function useBreadcrumbs() {
  const pathname = usePathname();

  return useMemo<BreadcrumbItem[]>(() => {
    const segments = pathname.split('/').filter(Boolean);
    return segments.map((segment, index) => {
      const path = `/${segments.slice(0, index + 1).join('/')}`;
      // Record identifiers (e.g. /app/agent/<conversationId>) read as their kind, never as the raw id.
      const title = segments[index - 1] === 'agent' ? 'Conversation' : (TITLES[segment] ?? segment.charAt(0).toUpperCase() + segment.slice(1));
      return { title, link: GROUP_LANDING[path] ?? path };
    });
  }, [pathname]);
}
