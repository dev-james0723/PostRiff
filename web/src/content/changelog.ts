export interface ChangelogEntry {
  date: string;
  title: string;
  items: string[];
}

/** Implementation milestones; release verification is separate. Dates are ISO. */
export const CHANGELOG: ChangelogEntry[] = [
  {
    date: '2026-09-16',
    title: 'Public site, app shell and gated billing implementation',
    items: [
      'Implemented public pages: landing, pricing, channel directory, docs, and draft legal pages (privacy, terms, data deletion, security).',
      'Implemented app shell: sidebar navigation with Cmd+K, workspace switcher, and pages for Overview, Ideas, Calendar, Pipeline, Library, Channels, Queue, Analytics, Inbox, Members, Roles, Audit log, Brand, Profile, Notifications, Usage & plan, Privacy & data, API.',
      'Stripe checkout, portal and email adapters are implemented behind configuration gates. Live charging and real delivery have not been verified for this release.'
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
