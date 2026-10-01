export function admitted(host, env) {
  if (!['1', 'true'].includes(env.RAFII_CONTROL_ENABLED)) return false;
  try {
    const origin = new URL(env.RAFII_CONTROL_ORIGIN);
    return origin.origin === env.RAFII_CONTROL_ORIGIN && host === origin.host;
  } catch { return false; }
}

export function localBackend(env) {
  if (env.VERCEL || env.VERCEL_ENV) throw new Error('Local forwarding is forbidden on Vercel');
  const url = new URL(env.RAFII_CONTROL_LOCAL_API || 'http://127.0.0.1:4450');
  if (url.protocol !== 'http:' || !['127.0.0.1','localhost'].includes(url.hostname) || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Exact loopback API required');
  return url.origin;
}
