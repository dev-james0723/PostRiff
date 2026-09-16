import { NextResponse, type NextRequest } from 'next/server';
import { updateSession } from '@/lib/supabase/middleware';
import { hasSupabaseEnv } from '@/lib/supabase/env';

/** Set by the sign-in page when the API runs in dev-harness mode (no Supabase). */
const DEV_COOKIE = 'postriff_dev';

const SIGN_IN_PATH = '/auth/sign-in';

function isAppRoute(pathname: string) {
  return pathname === '/app' || pathname.startsWith('/app/');
}

/**
 * Next 16 proxy (formerly middleware). Refreshes the Supabase session and
 * gates /app/* behind sign-in. Marketing, auth and /api are left untouched;
 * /api is served by the Python service and never reaches this file.
 */
export async function proxy(request: NextRequest) {
  const { response, user } = await updateSession(request);
  const { pathname, search } = request.nextUrl;

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
