import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { listFactors, verifyPasskey, verifyTotp } from '@/lib/auth/mfa';
import { getSupabaseEnv } from '@/lib/supabase/env';
import { CONTROL_EXCHANGE_HEADER, FOUNDER_API_BASE } from './api';
import { founderErrorMessage } from './errors';

/** Primary passkeys and WebAuthn MFA are different ceremonies. Only the existing server exchange grants Founder access. */
export type FounderIdentity = {
  client: SupabaseClient;
  userId: string;
  email: string;
  method: 'password' | 'passkey';
  totpFactorId?: string;
  passkeyFactorId?: string;
};

type SignInInput = { method: 'password'; email: string; password: string } | { method: 'passkey' };
export type FounderFactor = { kind: 'totp'; code: string } | { kind: 'webauthn' };

export class FounderSignInError extends Error {
  constructor(message: string, readonly kind: 'cancelled' | 'unavailable' | 'failed' = 'failed') {
    super(message);
    this.name = 'FounderSignInError';
  }
}

const COPY = {
  identity: 'Sign-in could not be verified. Use your existing Rafii account and try again.',
  factor: 'Second-factor verification failed. Try again or use your authenticator app.',
  noFactor: 'A verified second factor is required. Set up an authenticator app in Account security, then return here.',
  noToken: 'The verified session is unavailable. Start over to sign in again.',
  setup: 'Passkey setup could not be completed. You can continue to Founder and try again later.',
  cancelled: 'The passkey prompt was cancelled. Nothing changed.',
  unavailable: 'Passkey sign-in is unavailable here. Use your password and authenticator app instead.'
};

function cancelled(name?: string): boolean {
  return name === 'NotAllowedError' || name === 'AbortError';
}

function passkeyFailure(error: unknown, fallback = COPY.identity): FounderSignInError {
  const value = error as { name?: string; code?: string; cause?: { name?: string } } | null;
  if (cancelled(value?.name) || value?.code === 'ERROR_CEREMONY_ABORTED' || (value?.code === 'ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY' && cancelled(value.cause?.name))) {
    return new FounderSignInError(COPY.cancelled, 'cancelled');
  }
  if (['passkey_disabled', 'webauthn_not_supported'].includes(value?.code ?? '')) {
    return new FounderSignInError(COPY.unavailable, 'unavailable');
  }
  return new FounderSignInError(fallback);
}

export async function discardFounderIdentity(identity: Pick<FounderIdentity, 'client'>): Promise<void> {
  // Never call this after successful exchange: the Control cookie is bound to that upstream session.
  await identity.client.auth.signOut({ scope: 'local' }).catch(() => undefined);
}

/** A new memory-only client per attempt. It neither reads nor overwrites the consumer account's persistent session. */
export async function beginFounderSignIn(input: SignInInput, signal?: AbortSignal): Promise<FounderIdentity> {
  const { url, key } = getSupabaseEnv();
  const client = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false, storageKey: 'rafii-founder-identity', experimental: { passkey: true } }
  });
  try {
    if (signal?.aborted) throw new FounderSignInError(COPY.cancelled, 'cancelled');
    const signed = input.method === 'passkey'
      ? await client.auth.signInWithPasskey({ options: { signal } })
      : await client.auth.signInWithPassword({ email: input.email.trim(), password: input.password });
    if (signed.error) throw input.method === 'passkey' ? passkeyFailure(signed.error) : new FounderSignInError(COPY.identity);
    if (signal?.aborted) throw new FounderSignInError(COPY.cancelled, 'cancelled');
    const verified = await client.auth.getUser();
    const user = verified.data.user;
    if (verified.error || !user?.id || !user.email || !user.email_confirmed_at || user.is_anonymous || user.id !== signed.data.session?.user.id) {
      throw new FounderSignInError(COPY.identity);
    }
    const factors = (await listFactors(client)).filter((factor) => factor.verified);
    const totpFactorId = factors.find((factor) => factor.kind === 'totp')?.id;
    const passkeyFactorId = factors.find((factor) => factor.kind === 'webauthn')?.id;
    if (!totpFactorId && !passkeyFactorId) throw new FounderSignInError(COPY.noFactor);
    if (signal?.aborted) throw new FounderSignInError(COPY.cancelled, 'cancelled');
    return { client, userId: user.id, email: user.email, method: input.method, totpFactorId, passkeyFactorId };
  } catch (error) {
    await discardFounderIdentity({ client });
    throw error instanceof FounderSignInError ? error : new FounderSignInError(COPY.identity);
  }
}

/** Always prove a fresh, enrolled second factor, even after a successful primary passkey sign-in. */
export async function verifyFounderFactor(identity: FounderIdentity, factor: FounderFactor): Promise<string> {
  try {
    if (factor.kind === 'totp') {
      if (!identity.totpFactorId) throw new FounderSignInError(COPY.noFactor);
      await verifyTotp(identity.client, factor.code, identity.totpFactorId);
    } else {
      if (!identity.passkeyFactorId) throw new FounderSignInError(COPY.noFactor);
      await verifyPasskey(identity.client, identity.passkeyFactorId);
    }
  } catch (error) {
    if (error instanceof FounderSignInError) throw error;
    throw new FounderSignInError(COPY.factor);
  }
  const { data, error } = await identity.client.auth.getSession();
  if (error || !data.session?.access_token || data.session.user.id !== identity.userId) throw new FounderSignInError(COPY.noToken);
  return data.session.access_token;
}

/** Called only by the optional post-exchange setup screen; Supabase validates the registration ceremony. */
export async function registerFounderPasskey(identity: FounderIdentity): Promise<void> {
  const [verified, assurance] = await Promise.all([identity.client.auth.getUser(), identity.client.auth.mfa.getAuthenticatorAssuranceLevel()]);
  if (verified.error || verified.data.user?.id !== identity.userId || assurance.error || assurance.data?.currentLevel !== 'aal2') {
    throw new FounderSignInError('Fresh account verification is required before adding a passkey. Sign in again.');
  }
  try {
    const { error } = await identity.client.auth.registerPasskey();
    if (error) throw error;
  } catch (error) {
    throw passkeyFailure(error, COPY.setup);
  }
}

export async function exchangeFounderToken(accessToken: string): Promise<void> {
  const response = await fetch(`${FOUNDER_API_BASE}/session/exchange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}`, ...CONTROL_EXCHANGE_HEADER },
    body: '{}', cache: 'no-store', credentials: 'same-origin'
  });
  if (!response.ok) {
    const safe = (await response.json().catch(() => ({}))) as { code?: string };
    const error = new Error(founderErrorMessage(response.status, safe.code)) as Error & { code?: string };
    error.name = response.status === 401 || response.status === 403 ? 'ExchangeRefused' : 'ExchangeFailed';
    error.code = typeof safe.code === 'string' ? safe.code : undefined;
    throw error;
  }
}

export function notYetFounder(error: unknown): boolean {
  return error instanceof Error && error.name === 'ExchangeRefused' && (error as Error & { code?: string }).code === 'FOUNDER_REQUIRED';
}
