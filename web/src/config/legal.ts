/**
 * Legal review gate. Every legal page (/privacy, /terms, /data-deletion,
 * /security) renders a visible banner while this is 'draft'. Flip to
 * 'reviewed' only after qualified legal review has signed off.
 */
export type LegalReviewStatus = 'draft' | 'reviewed';

export const LEGAL_REVIEW_STATUS: LegalReviewStatus = 'draft';

export const LEGAL_REVIEW_BANNER = 'Draft — pending qualified legal review';

/** ISO date of the last edit to any legal page. Update when content changes. */
export const LEGAL_LAST_UPDATED = '2026-09-20';

/** Mailbox for privacy, deletion and security requests. TODO: confirm before general availability. */
export const LEGAL_CONTACT_EMAIL = 'privacy@postriff.app';

/** Governing-law placeholder used by the Terms until counsel confirms the jurisdiction. */
export const GOVERNING_LAW = '[Jurisdiction — to be confirmed by counsel]';
