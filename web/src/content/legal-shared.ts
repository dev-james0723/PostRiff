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
  { data: 'Approval receipts', retention: 'Retained as records after publication', note: 'Content-free receipts survive account deletion as tombstones or hashes where required for audit.' },
  { data: 'Post metrics', retention: 'Plan-dependent, minimum 90 days', note: 'Native metric observations; never sold or aggregated across customers with content.' },
  { data: 'Audience comments', retention: 'Until the provider or you delete them', note: 'Tombstones are preserved when a provider requires deletion.' },
  { data: 'Logs and traces', retention: '30 days', note: 'Sanitised: no prompts, post bodies, tokens or files by default.' },
  { data: 'Backups', retention: '30-day rotation', note: 'Database backups; object storage is backed up separately.' }
];

export const SUBPROCESSORS = [
  { name: 'Vercel', purpose: 'Hosting and API runtime', region: 'Global edge; functions in US East', status: 'In use' },
  { name: 'Supabase', purpose: 'Authentication, PostgreSQL database, private object storage', region: 'us-east-1', status: 'In use' },
  { name: 'Stripe', purpose: 'Subscription billing and invoices (card details never touch PostRiff)', region: 'Global', status: 'When you subscribe' },
  { name: 'Resend', purpose: 'Transactional email (invitations, trial and billing notices)', region: 'US/EU', status: 'In use' },
  { name: 'Social providers (LinkedIn, Threads, Instagram)', purpose: 'Publishing and metrics for accounts you connect', region: 'Provider’s own', status: 'Only through your own OAuth grant' },
  { name: 'AI model provider', purpose: 'Drafting', region: 'To be announced', status: 'Not yet contracted; only the deterministic preview runs today' },
  { name: 'Exa (exa.ai)', purpose: 'Web search for facts when you ask for research: receives a search query derived from your message, never your sources, memory files or drafts', region: 'US', status: 'Only after the workspace owner turns web research on' },
  { name: 'Jina Reader (r.jina.ai)', purpose: 'Fetches the public pages found by that search, or a page whose link you paste, as plain text', region: 'US/EU', status: 'Only after the workspace owner turns web research on' }
];

export const RIGHTS = [
  'Export your workspace (drafts, sources, approvals, receipts) with a receipt',
  'Disconnect any provider at any time',
  'Retract or delete any source',
  'Delete your account and workspace',
  'Request a sanitised diagnostics package — only with your explicit consent'
];
