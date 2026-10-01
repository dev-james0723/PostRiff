/** Local review only. No fixture identity or authority is embedded in browser code. */
export function localDemoAccessAllowed(host, env) {
  if (env.RAFII_CONTROL_LOCAL_PREVIEW !== '1' || !['1', 'true'].includes(env.RAFII_CONTROL_ENABLED) || env.RAFII_CONTROL_ENVIRONMENT !== 'local' || env.VERCEL || env.VERCEL_ENV) return false;
  if (typeof env.RAFII_CONTROL_LOCAL_PREVIEW_TOKEN !== 'string' || !env.RAFII_CONTROL_LOCAL_PREVIEW_TOKEN || env.RAFII_CONTROL_LOCAL_PREVIEW_TOKEN.length > 128) return false;
  try {
    const origin = new URL(env.RAFII_CONTROL_ORIGIN);
    return origin.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname) && !!origin.port && origin.origin === env.RAFII_CONTROL_ORIGIN && host === origin.host;
  } catch { return false; }
}
