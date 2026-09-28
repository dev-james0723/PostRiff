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

export class PasskeyEnrollmentUnavailableError extends Error {
  constructor() {
    super('Face ID / Touch ID isn’t available right now. Use an authenticator app instead.');
    this.name = 'PasskeyEnrollmentUnavailableError';
  }
}

export function isPasskeyEnrollmentUnavailable(error: unknown): error is PasskeyEnrollmentUnavailableError {
  return error instanceof PasskeyEnrollmentUnavailableError;
}

/** Cancelling the device prompt is not a failure worth a red banner. */
export function passkeyError(error: { name?: string; message?: string }): Error {
  const message = error.message ?? '';
  if (/MFA enroll is disabled for WebAuthn/i.test(message)) {
    return new PasskeyEnrollmentUnavailableError();
  }
  if (error.name === 'NotAllowedError' || /not allowed|cancel|abort/i.test(message)) {
    return new Error('The passkey prompt was cancelled. Nothing changed.');
  }
  return new Error(message || 'Your device did not complete the passkey step.');
}

/** Enrol, challenge and verify a new passkey in one ceremony; the session is AAL2 afterwards. */
export async function registerPasskey(client: SupabaseClient, friendlyName: string): Promise<void> {
  const { error } = await client.auth.mfa.webauthn.register({ friendlyName });
  if (error) throw passkeyError(error);
}

/** Prove possession of an enrolled passkey (Face ID / Touch ID prompt), upgrading to AAL2. */
export type BoundPasskey = {
  prepare: (factorId: string) => Promise<{ publicKey: Record<string, unknown> }>;
  approve: (credential: Record<string, unknown>) => Promise<{ session: { access_token: string; refresh_token: string } }>;
  signal?: AbortSignal;
};

function fromBase64url(value: string): ArrayBuffer {
  const text = value.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(text.padEnd(Math.ceil(text.length / 4) * 4, '=')), (c) => c.charCodeAt(0)).buffer;
}
function toBase64url(value: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function verifyPasskey(client: SupabaseClient, factorId?: string, bound?: BoundPasskey): Promise<void> {
  let id = factorId;
  if (!id) {
    const verified = (await listFactors(client)).find((factor) => factor.kind === 'webauthn' && factor.verified);
    if (!verified) throw new Error('No passkey is set up on this account.');
    id = verified.id;
  }
  if (bound) {
    // Supabase still creates and verifies the assertion. The phone API owns its exact call binding.
    const { publicKey } = await bound.prepare(id);
    const options = { ...publicKey, challenge: fromBase64url(String(publicKey.challenge)),
      allowCredentials: (publicKey.allowCredentials as { id: string; type: 'public-key'; transports?: AuthenticatorTransport[] }[] | undefined)?.map((item) => ({ ...item, id: fromBase64url(item.id) })),
      userVerification: 'required' as const } as PublicKeyCredentialRequestOptions;
    try {
      const credential = await navigator.credentials.get({ publicKey: options, signal: bound.signal }) as PublicKeyCredential | null;
      if (!credential) throw new Error('The passkey prompt was cancelled.');
      const response = credential.response as AuthenticatorAssertionResponse;
      const result = await bound.approve({ id: credential.id, rawId: toBase64url(credential.rawId), type: credential.type,
        response: { authenticatorData: toBase64url(response.authenticatorData), clientDataJSON: toBase64url(response.clientDataJSON),
          signature: toBase64url(response.signature), userHandle: response.userHandle ? toBase64url(response.userHandle) : undefined },
        clientExtensionResults: credential.getClientExtensionResults() });
      const { error } = await client.auth.setSession(result.session);
      if (error) throw new Error('The call was approved. Refresh Rafii to update this session.');
      return;
    } catch (error) { throw passkeyError(error as Error); }
  }
  const { error } = await client.auth.mfa.webauthn.authenticate({ factorId: id });
  if (error) throw passkeyError(error);
}

export async function unenrollFactor(client: SupabaseClient, factorId: string): Promise<void> {
  const { error } = await client.auth.mfa.unenroll({ factorId });
  if (error) throw error;
}
