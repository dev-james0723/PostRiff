export interface ChangelogEntry {
  date: string;
  title: string;
  items: string[];
}

/** Only shipped, verifiable changes. Dates are ISO. */
export const CHANGELOG: ChangelogEntry[] = [
  {
    date: '2026-09-16',
    title: 'Public site, app shell and live billing',
    items: [
      'New public site: landing, pricing, channel directory, docs, and draft legal pages (privacy, terms, data deletion, security).',
      'New app shell: sidebar navigation with Cmd+K, workspace switcher, and pages for Overview, Ideas, Calendar, Pipeline, Library, Channels, Queue, Analytics, Inbox, Members, Roles, Audit log, Brand, Profile, Notifications, Usage & plan, Privacy & data, API.',
      'Stripe checkout and billing portal behind the plan-availability gate; transactional email for invitations, welcome, trial reminders and billing notices.'
    ]
  },
  {
    date: '2026-09-15',
    title: 'Private alpha: hosted workspace',
    items: [
      'Tenancy with five roles and invitations, Ideas conversations with source policy, per-capability OAuth connections, entitlements and usage ledger, privacy requests, limited analytics and audience surfaces.'
    ]
  }
];
