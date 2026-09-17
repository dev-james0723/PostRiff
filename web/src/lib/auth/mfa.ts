import type { SupabaseClient } from '@supabase/supabase-js';

/**
 * Supabase Auth MFA wrapped for the app: authenticator apps (TOTP) and passkeys (WebAuthn —
 * Face ID, Touch ID, Windows Hello, security keys) are both second factors.
 *
 * Enrolment and verification happen in the browser against Supabase. The API only learns the
 * outcome (`POST /api/auth/mfa`) and from then on refuses this user's sessions below AAL2, so
 * turning the feature on is a server-side decision, not a hidden button. A passkey stores a
 * public key with Supabase; the biometric itself never leaves the device.
 */

export type FactorKind = 'totp' | 'webauthn';

export interface SecondFactor {
  id: string;
  kind: FactorKind;
  name: string;
  createdAt: string;
  verified: boolean;
}

/** `pending`: a factor is enrolled but this session has not presented it yet. */
export type Assurance = 'aal1' | 'aal2' | 'pending';

export async function assurance(client: SupabaseClient): Promise<Assurance> {
  const { data, error } = await client.auth.mfa.getAuthenticatorAssuranceLevel();
  if (error || !data) return 'aal1';
  if (data.currentLevel === 'aal2') return 'aal2';
  return data.nextLevel === 'aal2' ? 'pending' : 'aal1';
}

/** Whether this browser can do WebAuthn at all; the device decides Face ID vs. key at prompt time. */
export function passkeysSupported(): boolean {
  return typeof window !== 'undefined' && 'PublicKeyCredential' in window;
}

export async function listFactors(client: SupabaseClient): Promise<SecondFactor[]> {
  const { data, error } = await client.auth.mfa.listFactors();
  if (error) throw error;
  return (data?.all ?? [])
    .filter((factor) => factor.factor_type === 'totp' || factor.factor_type === 'webauthn')
    .map((factor) => ({
      id: factor.id,
      kind: factor.factor_type as FactorKind,
      name: factor.friendly_name || (factor.factor_type === 'webauthn' ? 'Passkey' : 'Authenticator app'),
      createdAt: factor.created_at,
      verified: factor.status === 'verified'
    }));
}

/** Start enrolling an authenticator app. The factor stays unverified until `verifyTotp`. */
export async function enrollTotp(client: SupabaseClient, friendlyName: string) {
  const { data, error } = await client.auth.mfa.enroll({ factorType: 'totp', friendlyName });
  if (error) throw error;
  return { id: data.id, qrCode: data.totp.qr_code, secret: data.totp.secret, uri: data.totp.uri };
}

/**
 * Challenge and verify one code, upgrading the session to AAL2 with a fresh token. With no
 * `factorId` the first verified authenticator app is used, so any enrolled app works for step-up.
 */
export async function verifyTotp(client: SupabaseClient, code: string, factorId?: string): Promise<void> {
  let id = factorId;
  if (!id) {
    const verified = (await listFactors(client)).find((factor) => factor.kind === 'totp' && factor.verified);
    if (!verified) throw new Error('No authenticator app is set up on this account.');
    id = verified.id;
  }
  const { error } = await client.auth.mfa.challengeAndVerify({ factorId: id, code: code.trim() });
  if (error) throw error;
}

/** Cancelling the device prompt is not a failure worth a red banner. */
export function passkeyError(error: { name?: string; message?: string }): Error {
  if (error.name === 'NotAllowedError' || /not allowed|cancel|abort/i.test(error.message ?? '')) {
    return new Error('The passkey prompt was cancelled. Nothing changed.');
  }
  return new Error(error.message || 'Your device did not complete the passkey step.');
}

/** Enrol, challenge and verify a new passkey in one ceremony; the session is AAL2 afterwards. */
export async function registerPasskey(client: SupabaseClient, friendlyName: string): Promise<void> {
  const { error } = await client.auth.mfa.webauthn.register({ friendlyName });
  if (error) throw passkeyError(error);
}

/** Prove possession of an enrolled passkey (Face ID / Touch ID prompt), upgrading to AAL2. */
export async function verifyPasskey(client: SupabaseClient, factorId?: string): Promise<void> {
  let id = factorId;
  if (!id) {
    const verified = (await listFactors(client)).find((factor) => factor.kind === 'webauthn' && factor.verified);
    if (!verified) throw new Error('No passkey is set up on this account.');
    id = verified.id;
  }
  const { error } = await client.auth.mfa.webauthn.authenticate({ factorId: id });
  if (error) throw passkeyError(error);
}

export async function unenrollFactor(client: SupabaseClient, factorId: string): Promise<void> {
  const { error } = await client.auth.mfa.unenroll({ factorId });
  if (error) throw error;
}
