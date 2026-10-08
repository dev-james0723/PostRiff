/**
 * Moving public pages off a former production host (e.g. postriff-phase2-private.vercel.app → rafii.io).
 *
 * Off unless RAFII_LEGACY_HOST_REDIRECT is `temporary` (307, while validating) or `permanent` (308, after
 * acceptance) and the request host is listed in RAFII_LEGACY_HOSTS. The target is the build-time canonical
 * origin, never the request's Host. Only GET/HEAD on public pages move: signed-in surfaces keep per-origin
 * sessions, unsent composer state (sessionStorage) and onboarding progress (localStorage), and auth, OAuth
 * return, invitation and service-worker paths must finish on the origin that started them. /api never
 * reaches the proxy, so webhooks, provider callbacks and Bluesky client metadata are untouched.
 */

const KEEP_PREFIXES = ['/app', '/founder', '/auth', '/channels', '/connectors', '/invite', '/sign-in', '/sign-up', '/monitoring'];
const KEEP_EXACT = new Set(['/sw.js', '/manifest.webmanifest']);

export type LegacyRedirectMode = 'off' | 'temporary' | 'permanent';

export function legacyRedirectMode(value: string | undefined): LegacyRedirectMode {
  return value === 'temporary' || value === 'permanent' ? value : 'off';
}

function canonicalOrigin(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || (url.pathname !== '/' && url.pathname !== '') || url.search || url.hash) return null;
    return url.origin;
  } catch {
    return null;
  }
}

function keeps(pathname: string): boolean {
  if (KEEP_EXACT.has(pathname)) return true;
  return KEEP_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

/** The redirect URL and status for a legacy-host request, or null to serve it unchanged. */
export function legacyHostRedirect(
  request: { method: string; host: string | null; pathname: string; search: string },
  env: { mode?: string; hosts?: string; canonical?: string }
): { location: string; status: 307 | 308 } | null {
  const mode = legacyRedirectMode(env.mode);
  if (mode === 'off' || (request.method !== 'GET' && request.method !== 'HEAD')) return null;
  const target = canonicalOrigin(env.canonical);
  const host = (request.host ?? '').split(':')[0].trim().toLowerCase();
  const legacy = (env.hosts ?? '').split(',').map((item) => item.trim().toLowerCase()).filter(Boolean);
  if (!target || !host || !legacy.includes(host) || new URL(target).hostname === host) return null;
  if (keeps(request.pathname)) return null;
  return { location: `${target}${request.pathname}${request.search}`, status: mode === 'permanent' ? 308 : 307 };
}
