/**
 * Facts shared by the legal pages. Mirrors `src/postriff_phase2/privacy.py`
 * (RETENTION_CLASSES, SUBPROCESSORS, rights) so the public text and the
 * in-app notice never drift.
 */
export const RETENTION = [
  { data: 'Drafts and revision history', retention: 'Until you delete them', note: 'Revision history is kept with the draft.' },
  { data: 'Sources you add', retention: 'Until retraction or deletion', note: 'Retraction blocks future use and dependent drafts; deletion removes the text and derived chunks.' },
  { data: 'Generated media', retention: 'Until you delete it', note: 'Immutable renditions; provenance kept as hashes.' },
  { data: 'Provider tokens (OAuth)', retention: 'Until disconnect or revocation', note: 'Encrypted at rest; the ciphertext is wiped on disconnect.' },
  { data: 'Approval receipts', retention: 'Retained as records after publication', note: 'Limited deletion, trial and audit records remain after account deletion; workspace publication records are removed.' },
  { data: 'Post metrics', retention: 'Until workspace deletion; release policy pending review', note: 'Native metric observations; never sold or aggregated across customers with content.' },
  { data: 'Audience comments', retention: 'Until the provider or you delete them', note: 'Tombstones are preserved when a provider requires deletion.' },
  { data: 'Logs and traces', retention: '30 days — candidate', note: 'Sanitised: no prompts, post bodies, tokens or files by default.' },
  { data: 'Backups', retention: '30-day rotation — candidate', note: 'Database and object-storage backup coverage must be verified separately for the release environment.' }
];

export const SUBPROCESSORS = [
  { name: 'Vercel', purpose: 'Hosting and API runtime', region: 'Release region to be verified', status: 'Configured hosting provider' },
  { name: 'Supabase', purpose: 'Authentication, PostgreSQL database, private object storage', region: 'Release region to be verified', status: 'Configured identity, database and storage provider' },
  { name: 'Vercel Web Analytics; Sentry when configured', purpose: 'Website usage and sanitised error diagnostics', region: 'Release settings to be verified', status: 'Analytics is integrated; error delivery depends on configuration' },
  { name: 'Stripe', purpose: 'Subscription billing and invoices (card details never touch Rafii)', region: 'Global', status: 'When you subscribe' },
  { name: 'Resend', purpose: 'Transactional email (invitations, trial and billing notices)', region: 'To be verified', status: 'Only when a reviewed email sender is configured' },
  { name: 'Social providers (LinkedIn, Threads, Instagram)', purpose: 'Publishing and metrics for accounts you connect', region: 'Provider’s own', status: 'Only through your own OAuth grant' },
  { name: 'Vercel AI Gateway and the selected model provider; configured CLI provider', purpose: 'Drafting from the instruction and permitted context', region: 'Provider route and contract to be verified', status: 'Cloud routes require the applicable consent; deterministic preview makes no model call' },
  { name: 'Exa (exa.ai)', purpose: 'Web search for facts when you ask for research: receives a search query derived from your message, never your sources, memory files or drafts', region: 'To be verified for release', status: 'Only after the workspace owner turns web research on' },
  { name: 'Jina Reader (r.jina.ai)', purpose: 'Fetches the public pages found by that search, or a page whose link you paste, as plain text', region: 'To be verified for release', status: 'Only after the workspace owner turns web research on' }
];

export const RIGHTS = [
  'Export your workspace (drafts, sources, approvals, receipts) with a receipt',
  'Disconnect any provider at any time',
  'Retract or delete any source',
  'Delete your account and workspace',
  'Request a sanitised diagnostics package — only with your explicit consent'
];
