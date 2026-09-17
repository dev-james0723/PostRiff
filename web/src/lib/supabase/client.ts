'use client';

import { createBrowserClient } from '@supabase/ssr';
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
