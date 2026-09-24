import 'server-only';
import { cookies } from 'next/headers';
import { hasSupabaseEnv } from '@/lib/supabase/env';
import { bootstrapOrigin, fetchWorkspaceBootstrap } from './bootstrap';

export async function loadWorkspaceBootstrap() {
  const origin = bootstrapOrigin(process.env);
  if (!origin) return null;
  const jar = await cookies();
  let token: string | undefined;
  let mode: 'dev' | 'supabase' = 'supabase';
  try {
    if (hasSupabaseEnv()) {
      const { createClient } = await import('@/lib/supabase/server');
      const client = await createClient();
      const { data, error } = await client.auth.getSession();
      if (error || !data.session) return null;
      const assurance = await client.auth.mfa.getAuthenticatorAssuranceLevel();
      if (assurance.error || !assurance.data || (assurance.data.nextLevel === 'aal2' && assurance.data.currentLevel !== 'aal2')) return null;
      // getSession supplies credentials only. The API verifies identity and memberships independently.
      token = data.session.access_token;
    } else {
      if (process.env.POSTRIFF_DEV_SSR !== '1' || process.env.VERCEL) return null;
      const principal = jar.get('postriff_dev_principal')?.value;
      if (!principal || !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(principal)) return null;
      const response = await fetch(origin + '/api/catalog', { cache:'no-store', redirect:'error', signal:AbortSignal.timeout(2500) });
      if (!response.ok || (await response.json()).authMode !== 'dev') return null;
      mode = 'dev';token = `dev:${principal}`;
    }
    return await fetchWorkspaceBootstrap(origin, token, mode, jar.get('postriff_workspace')?.value);
  } catch { return null; }
}
