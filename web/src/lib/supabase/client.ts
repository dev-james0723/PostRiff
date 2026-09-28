'use client';

import { createBrowserClient } from '@supabase/ssr';
import { createClient as createSupabaseClient } from '@supabase/supabase-js';
import { getSupabaseEnv } from './env';

/**
 * Browser Supabase client. Throws a clear error when the public env is
 * missing, but only at call time so pages that never touch auth still build.
 * The experimental passkey flag only unlocks the `auth.passkey.*` methods;
 * whether they are offered is decided by NEXT_PUBLIC_PASSKEY_SIGN_IN.
 */
export function createClient() {
  const { url, key } = getSupabaseEnv();
  return createBrowserClient(url, key, { auth: { experimental: { passkey: true } } });
}

/**
 * Isolated client for a one-action passkey proof.  It never writes the passkey-created session to
 * cookies/localStorage and never broadcasts it to the app's signed-in client.  This matters when
 * the account's normal session is already AAL2 with TOTP: phone approval proves the passkey without
 * replacing or weakening that authorized session.
 */
export function createPasskeyProofClient() {
  const { url, key } = getSupabaseEnv();
  return createSupabaseClient(url, key, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
      detectSessionInUrl: false,
      experimental: { passkey: true }
    }
  });
}
