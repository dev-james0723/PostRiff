import type { Membership } from '@/lib/api/types';
import { allows } from './permissions';

/** Only same-site paths; backslashes and control characters can change URL parsing. */
export function safeNext(value: string | null): string {
  // Reject control characters intentionally at this URL trust boundary.
  // oxlint-disable-next-line eslint/no-control-regex
  return value && value.startsWith('/') && !value.startsWith('//') && !/[\\\u0000-\u001f\u007f]/.test(value) && !/^\/auth\/verify(?:[/?#]|$)/.test(value) ? value : '/app';
}

export function verifyHref(next: string) {
  return `/auth/verify?next=${encodeURIComponent(safeNext(next))}`;
}

export function invitationLanding(membership: Membership): string {
  if (allows(membership, 'edit')) return '/app';
  if (allows(membership, 'approve')) return '/app/queue';
  return '/app/overview';
}
