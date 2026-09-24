/** Validate the browser's destination before a preview build can embed public auth configuration. */
export function assertPreviewEnvironment(env) {
  if (env.VERCEL_ENV !== 'preview') return;
  const staging = env.POSTRIFF_STAGING_PROJECT_REF || '';
  const production = env.POSTRIFF_PRODUCTION_PROJECT_REF || '';
  if (env.POSTRIFF_ENVIRONMENT !== 'staging' || !/^[a-z0-9]{20}$/.test(staging) || !/^[a-z0-9]{20}$/.test(production) || staging === production) {
    throw new Error('Preview requires distinct pinned staging and production projects.');
  }
  if ((env.NEXT_PUBLIC_SUPABASE_URL || '').replace(/\/$/, '') !== `https://${staging}.supabase.co`) {
    throw new Error('Preview browser identity must use the pinned staging project.');
  }
  if (env.POSTRIFF_API_ORIGIN) throw new Error('Preview API must use its own deployment.');
  if (env.NEXT_PUBLIC_APP_URL !== env.POSTRIFF_STAGING_PUBLIC_BASE_URL || !env.NEXT_PUBLIC_APP_URL?.startsWith('https://')) {
    throw new Error('Preview browser origin must match the approved staging origin.');
  }
}
