/**
 * Supabase binds every sign-in passkey to one Relying Party ID. While the app answers on more than one
 * domain, a ceremony on a host outside that RP ID can only fail, so offer passkeys there not at all.
 * Unset keeps the earlier behavior (every host).
 */
export function passkeyHostMatches(rpId: string | undefined, hostname = typeof window === 'undefined' ? undefined : window.location.hostname): boolean {
  const expected = rpId?.trim().toLowerCase();
  if (!expected) return true;
  if (!hostname) return false;
  const host = hostname.toLowerCase();
  return host === expected || host.endsWith(`.${expected}`);
}
