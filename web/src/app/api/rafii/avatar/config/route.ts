/** Phase 1 is a local development bridge; the worker must be bound to loopback or an SSH tunnel. */
export async function GET() {
  let url: string | null = null;
  try {
    const parsed = new URL(process.env.SOULX_AVATAR_URL ?? '');
    if (parsed.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)
      && parsed.pathname === '/' && !parsed.username && !parsed.password && !parsed.search && !parsed.hash) {
      url = parsed.origin;
    }
  } catch { /* invalid worker configuration stays disabled */ }
  const enabled = process.env.NODE_ENV !== 'production' && process.env.AVATAR_MODE === 'soulx' && url !== null;
  return Response.json({ mode: enabled ? 'soulx' : 'disabled', url: enabled ? url : null },
    { headers: { 'Cache-Control': 'no-store' } });
}
