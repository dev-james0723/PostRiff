export interface DocSection {
  heading: string;
  paragraphs: string[];
  bullets?: string[];
}

export interface Doc {
  slug: string;
  title: string;
  summary: string;
  sections: DocSection[];
}

export const DOCS: Doc[] = [
  {
    slug: 'getting-started',
    title: 'Getting started',
    summary: 'From a new account to your first approved post.',
    sections: [
      { heading: 'Create your workspace', paragraphs: ['Sign up with Google or an email code and choose a trial plan. A workspace is created for you; you are its owner.'] },
      { heading: 'Add a source', paragraphs: ['Open Ideas, paste a thought or a paragraph, mark whether it is your own writing, and choose destinations and a language. Rafii drafts one candidate per destination.'] },
      { heading: 'Add candidates to your drafts', paragraphs: ['Pick the versions that sound like you and add them. This creates reviewable drafts — nothing is published yet.'] },
      { heading: 'Connect a channel', paragraphs: ['In Channels, connect the account you want to publish to. The card shows each capability’s verified level.'] },
      { heading: 'Approve and publish', paragraphs: ['Prepare a draft for a channel and time, then approve the exact review in the Queue. The worker publishes at the approved time and records a receipt. If the channel is Assisted, Rafii prepares the post and you complete the last step.'] }
    ]
  },
  {
    slug: 'channels-and-capabilities',
    title: 'Channels & capabilities',
    summary: 'Direct, Assisted, Local — and why a connection is not a permission.',
    sections: [
      { heading: 'Six capabilities', paragraphs: ['Identity, publish, schedule, analytics, read comments and reply are verified separately for every connected account.'] },
      { heading: 'Levels', paragraphs: ['Direct: Rafii acts through the official API after your approval. Assisted: Rafii prepares the post; a reviewed connector or you completes the final step. Local: a planned companion route; it is unavailable until the companion release is verified. Unsupported: not offered for this provider yet.'] },
      { heading: 'Provider reviews', paragraphs: ['LinkedIn, Threads and Instagram require Rafii to pass their app reviews before direct publishing is allowed. Until then their cards read “Assisted · review pending”. We never label a capability Direct before the review passes.'] }
    ]
  },
  {
    slug: 'approvals',
    title: 'Approvals',
    summary: 'Exact reviews, digests and receipts.',
    sections: [
      { heading: 'What a review contains', paragraphs: ['The text, the media (by hash), the account, the capability level and the time, frozen into a manifest with a digest.'] },
      { heading: 'Approving', paragraphs: ['Approving the digest creates a job. Changing anything — text, media, account, time — requires a new review. Approvers need the approve permission or the “can approve publications” grant.'] },
      { heading: 'Receipts', paragraphs: ['Every publication records the provider’s reference and confirmation. Uncertain outcomes are reconciled before any retry, and unresolved results require manual verification; do not resubmit an uncertain publication.'] }
    ]
  },
  {
    slug: 'usage-and-billing',
    title: 'Usage & billing',
    summary: 'Allowances, stop-lines and how plans work.',
    sections: [
      { heading: 'Allowances', paragraphs: ['Writing batches, media credits, connected accounts and storage are per plan. When an allowance is used up, the action stops and tells you; nothing is charged silently.'] },
      { heading: 'Trial', paragraphs: ['14 days, no card, no automatic conversion. You choose a plan yourself when you are ready.'] },
      { heading: 'Subscriptions', paragraphs: ['Proposed monthly billing through Stripe, available only when the plan and payment integration are activated. Payment method, plan changes, cancellation and invoices live in the billing portal (Account → Usage & plan → Manage billing).'] }
    ]
  },
  {
    slug: 'privacy-and-data',
    title: 'Privacy & data',
    summary: 'Export, diagnostics, retraction and deletion — all self-service.',
    sections: [
      { heading: 'Export', paragraphs: ['Account → Privacy & data → Export drafts downloads a zip and records a receipt with its SHA-256.'] },
      { heading: 'Retract or delete a source', paragraphs: ['Retraction blocks future use and dependent drafts; deletion removes the text and derived data.'] },
      { heading: 'Delete your account', paragraphs: ['Owners can delete the whole workspace and account from the same page. See the Data deletion page for what is removed and what is kept as content-free tombstones.'] }
    ]
  }
];

export function docBySlug(slug: string) {
  return DOCS.find((d) => d.slug === slug);
}
