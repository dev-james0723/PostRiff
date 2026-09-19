import type { NavGroup } from '@/types';

/**
 * App navigation (sidebar + Cmd+K), grouped per spec §5.
 *
 * `access` uses the PostRiff PermissionCheck shape:
 *   { permission?, role?, plan?, capability? }
 * All present keys must pass. Filtering happens in `@/hooks/use-nav`.
 */
export const navGroups: NavGroup[] = [
  {
    label: 'Create',
    items: [
      {
        title: 'Home',
        url: '/app',
        icon: 'sparkles',
        shortcut: ['h', 'h'],
        items: []
      },
      {
        title: 'Overview',
        url: '/app/overview',
        icon: 'dashboard',
        shortcut: ['o', 'o'],
        items: []
      },
      {
        title: 'Ideas',
        url: '/app/ideas',
        icon: 'post',
        shortcut: ['i', 'i'],
        items: [],
        access: { permission: 'edit' }
      },
      {
        title: 'Calendar',
        url: '/app/calendar',
        icon: 'calendar',
        shortcut: ['c', 'c'],
        items: []
      },
      {
        title: 'Pipeline',
        url: '/app/pipeline',
        icon: 'kanban',
        shortcut: ['p', 'p'],
        items: []
      },
      {
        title: 'Library',
        url: '/app/library',
        icon: 'media',
        shortcut: ['l', 'l'],
        items: []
      }
    ]
  },
  {
    label: 'Distribute',
    items: [
      {
        title: 'Channels',
        url: '/app/channels',
        icon: 'broadcast',
        shortcut: ['g', 'c'],
        items: []
      },
      {
        title: 'Queue',
        url: '/app/queue',
        icon: 'listDetails',
        shortcut: ['q', 'q'],
        items: []
      }
    ]
  },
  {
    label: 'Grow',
    items: [
      {
        title: 'Analytics',
        url: '/app/analytics',
        icon: 'trendingUp',
        shortcut: ['a', 'a'],
        items: []
      },
      {
        title: 'Inbox',
        url: '/app/inbox',
        icon: 'inbox',
        shortcut: ['n', 'n'],
        items: []
      }
    ]
  },
  {
    label: 'Workspace',
    items: [
      {
        title: 'Members',
        url: '/app/workspace/members',
        icon: 'teams',
        shortcut: ['m', 'm'],
        items: [],
        access: { permission: 'manage_members' }
      },
      {
        title: 'Roles',
        url: '/app/workspace/roles',
        icon: 'lock',
        items: []
      },
      {
        title: 'Audit log',
        url: '/app/workspace/audit',
        icon: 'history',
        items: [],
        access: { role: 'admin' }
      },
      {
        title: 'Brand',
        url: '/app/workspace/brand',
        icon: 'palette',
        items: [],
        access: { permission: 'edit' }
      },
      {
        title: 'Memory',
        url: '/app/workspace/memory',
        icon: 'page',
        items: [],
        access: { permission: 'edit' }
      }
    ]
  },
  {
    label: 'Account',
    items: [
      {
        title: 'Profile',
        url: '/app/account/profile',
        icon: 'profile',
        items: []
      },
      {
        title: 'Notifications',
        url: '/app/account/notifications',
        icon: 'notification',
        items: []
      },
      {
        title: 'Usage & plan',
        url: '/app/account/billing',
        icon: 'billing',
        shortcut: ['b', 'b'],
        items: []
      },
      {
        title: 'Privacy & data',
        url: '/app/account/privacy',
        icon: 'shieldCheck',
        items: []
      },
      {
        title: 'Models & providers',
        url: '/app/account/models',
        icon: 'adjustments',
        items: [],
        access: { permission: 'edit' }
      },
      {
        title: 'API & integrations',
        url: '/app/account/api',
        icon: 'key',
        items: [],
        access: { permission: 'manage_connections' }
      }
    ]
  }
];
