import 'server-only';
import { cookies, headers } from 'next/headers';
import { hasSupabaseEnv } from '@/lib/supabase/env';
import { bootstrapOrigin, fetchWorkspaceBootstrap } from './bootstrap';

export async function loadWorkspaceBootstrap() {
  const incoming = process.env.VERCEL_ENV === 'preview' ? await headers() : null;
  const origin = bootstrapOrigin(process.env, incoming?.get('x-forwarded-host') ?? incoming?.get('host'));
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
    // Forward only existing deployment access to the pinned Preview origin.
    // Never persist it or expose it in the serialized bootstrap result.
    const preview = process.env.VERCEL_ENV === 'preview' ? {
      cookie: jar.get('_vercel_jwt') ? `_vercel_jwt=${jar.get('_vercel_jwt')!.value}` : undefined,
      bypass: incoming?.get('x-vercel-protection-bypass') ?? undefined
    } : {};
    // The visitor's own User-Agent: this prefetch is often a session's first API call, and the API records the
    // browser label then. Without it the session shows as "Unrecognized browser".
    const userAgent = (await headers()).get('user-agent') ?? undefined;
    // RAPv2 device registry: the browser's own opaque device hint (only ever issued while RAFII_DEVICE_TRUST_V2 is on),
    // so a returning browser is recognised on this first call too. Never minted or stored here.
    const device = jar.get('__Host-rafii_device')?.value;
    const deviceCookie = device && /^[A-Za-z0-9_-]{43}$/.test(device) ? `__Host-rafii_device=${device}` : undefined;
    const cookie = [preview.cookie, deviceCookie].filter(Boolean).join('; ') || undefined;
    const access = { ...preview, cookie, userAgent };
    return await fetchWorkspaceBootstrap(origin, token, mode, jar.get('postriff_workspace')?.value, fetch, access);
  } catch { return null; }
}
