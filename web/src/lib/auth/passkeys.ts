import type { SupabaseClient } from '@supabase/supabase-js';
import { passkeyError } from '@/lib/auth/mfa';
import { createPasskeyProofClient } from '@/lib/supabase/client';

/**
 * Passkeys as the sign-in itself (Supabase's experimental passkey feature): one Face ID / Touch ID
 * prompt instead of an email code. These are separate from the WebAuthn second factor in `mfa.ts`;
 * a passkey sign-in is still AAL1, so an account with two-factor on confirms that afterwards.
 *
 * Off unless NEXT_PUBLIC_PASSKEY_SIGN_IN=true, because the Supabase project must have passkeys
 * enabled too; an enabled button against a project without them would only ever fail.
 */

export interface SignInPasskey {
  id: string;
  name: string;
  createdAt: string;
  lastUsedAt?: string;
}

export function passkeySignInEnabled(): boolean {
  return process.env.NEXT_PUBLIC_PASSKEY_SIGN_IN === 'true';
}

export async function listSignInPasskeys(client: SupabaseClient): Promise<SignInPasskey[]> {
  const { data, error } = await client.auth.passkey.list();
  if (error) throw error;
  return (data ?? []).map((item) => ({
    id: item.id,
    name: item.friendly_name || 'Passkey',
    createdAt: item.created_at,
    lastUsedAt: item.last_used_at
  }));
}

/** Runs the whole registration ceremony; the device names the authenticator, we store only the public key. */
export async function registerSignInPasskey(client: SupabaseClient): Promise<void> {
  const { error } = await client.auth.registerPasskey();
  if (error) throw passkeyError(error);
}

export async function renameSignInPasskey(client: SupabaseClient, id: string, name: string): Promise<void> {
  const { error } = await client.auth.passkey.update({ passkeyId: id, friendlyName: name.trim() });
  if (error) throw error;
}

export async function deleteSignInPasskey(client: SupabaseClient, id: string): Promise<void> {
  const { error } = await client.auth.passkey.delete({ passkeyId: id });
  if (error) throw error;
}

/** Sign-in page: one prompt, then a normal session. */
export async function signInWithPasskey(client: SupabaseClient): Promise<void> {
  const { data, error } = await client.auth.signInWithPasskey();
  if (error) throw passkeyError(error);
  if (!data?.session) throw new Error('The passkey did not start a session. Try again or use your email.');
}

/**
 * Ask for Face ID / Touch ID and lend the resulting session to exactly one callback. The session
 * is memory-only and is revoked in `finally`; only its access token reaches the requested action.
 */
export async function withPasskeyProof<T>(run: (accessToken: string) => Promise<T>, signal?: AbortSignal): Promise<T> {
  const client = createPasskeyProofClient();
  const { data, error } = await client.auth.signInWithPasskey({ options: { signal } });
  if (error) throw passkeyError(error);
  if (!data?.session?.access_token) throw new Error('The passkey did not create an identity proof. Try again.');
  try {
    return await run(data.session.access_token);
  } finally {
    // Cleanup cannot change the inspected action result. No refresh token is persisted either way.
    await client.auth.signOut({ scope: 'local' }).catch(() => undefined);
  }
}
