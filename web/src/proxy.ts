import { NextResponse, type NextRequest } from 'next/server';
import { updateSession } from '@/lib/supabase/middleware';
import { hasSupabaseEnv } from '@/lib/supabase/env';
import { CONTROL_COOKIE, FOUNDER_SIGN_IN_PATH } from '@/lib/founder/errors';
import { legacyHostRedirect } from '@/lib/legacy-host';

/** Set by the sign-in page when the API runs in dev-harness mode (no Supabase). */
const DEV_COOKIE = 'postriff_dev';

const SIGN_IN_PATH = '/auth/sign-in';

function isAppRoute(pathname: string) {
  return pathname === '/app' || pathname.startsWith('/app/');
}

function isFounderRoute(pathname: string) {
  return pathname === '/founder' || pathname.startsWith('/founder/');
}

/**
 * The founder admin gate (CONTRACTS §6): `/founder/*` gets the same Supabase refresh as `/app`, but access is decided
 * by the `__Host-rafii-control` cookie alone. Without it the browser goes to `/founder/sign-in` (which stays open);
 * with it the request carries `x-founder-route` so the server layout knows whether to wrap the page in the shell.
 * The cookie's validity is the API's to judge: a stale one gets a 401 from `GET /session` and the client signs out.
 */
function founderGate(request: NextRequest, refreshed: NextResponse): NextResponse {
  const { pathname, search } = request.nextUrl;
  const signIn = pathname === FOUNDER_SIGN_IN_PATH;
  if (!signIn && !request.cookies.has(CONTROL_COOKIE)) {
    const url = request.nextUrl.clone();
    url.pathname = FOUNDER_SIGN_IN_PATH;
    url.search = '';
    url.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(url);
  }
  const headers = new Headers(request.headers);
  headers.set('x-founder-route', signIn ? 'sign-in' : 'shell');
  const response = NextResponse.next({ request: { headers } });
  // Keep the refreshed Supabase cookies the session helper set on its own response.
  for (const cookie of refreshed.cookies.getAll()) response.cookies.set(cookie);
  return response;
}

/**
 * Next 16 proxy (formerly middleware). Refreshes the Supabase session and
 * gates /app/* behind sign-in. Marketing, auth and /api are left untouched;
 * /api is served by the Python service and never reaches this file.
 */
export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const moved = legacyHostRedirect(
    { method: request.method, host: request.headers.get('host'), pathname, search },
    { mode: process.env.RAFII_LEGACY_HOST_REDIRECT, hosts: process.env.RAFII_LEGACY_HOSTS, canonical: process.env.NEXT_PUBLIC_APP_URL }
  );
  if (moved) return NextResponse.redirect(moved.location, moved.status);

  const { response, user } = await updateSession(request);

  if (isFounderRoute(pathname)) return founderGate(request, response);

  if (isAppRoute(pathname) && !user) {
    // Local dev harness: identity is simulated client-side; the API still verifies every token.
    if (!hasSupabaseEnv() && request.cookies.get(DEV_COOKIE)) return response;
    const url = request.nextUrl.clone();
    url.pathname = SIGN_IN_PATH;
    url.search = '';
    url.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(url);
  }

  return response;
}

export const config = {
  matcher: [
    // Skip Next.js internals, the Sentry tunnel, the Python API and static files.
    '/((?!_next/static|_next/image|api/|monitoring|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml|webmanifest|woff2?|ttf|css|js)$).*)'
  ]
};
