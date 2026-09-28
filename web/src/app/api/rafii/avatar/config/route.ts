/** Phase 1 is a local development bridge; the worker must be bound to loopback or an SSH tunnel. */
export async function GET() {
  const enabled = process.env.NODE_ENV !== 'production' && process.env.AVATAR_MODE === 'soulx' && Boolean(process.env.SOULX_AVATAR_URL);
  return Response.json({ mode: enabled ? 'soulx' : 'disabled', url: enabled ? process.env.SOULX_AVATAR_URL : null },
    { headers: { 'Cache-Control': 'no-store' } });
}
