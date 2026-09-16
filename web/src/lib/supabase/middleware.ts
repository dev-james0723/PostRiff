import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import type { User } from '@supabase/supabase-js';
import { getSupabaseEnv, hasSupabaseEnv } from './env';

/**
 * Refresh the Supabase session on every matched request and forward the
 * refreshed cookies to both the request (for Server Components) and the
 * response (for the browser). Mirrors the Supabase SSR reference helper.
 */
export async function updateSession(
  request: NextRequest
): Promise<{ response: NextResponse; user: User | null }> {
  let supabaseResponse = NextResponse.next({ request });

  if (!hasSupabaseEnv()) {
    return { response: supabaseResponse, user: null };
  }

  const { url, key } = getSupabaseEnv();

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        supabaseResponse = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          supabaseResponse.cookies.set(name, value, options)
        );
      }
    }
  });

  // Do not run code between createServerClient and getUser(): doing so can
  // make session refresh race and log users out unexpectedly.
  const {
    data: { user }
  } = await supabase.auth.getUser();

  return { response: supabaseResponse, user };
}
