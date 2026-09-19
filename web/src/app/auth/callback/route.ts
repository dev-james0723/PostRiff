import { safeNext, verifyHref } from '@/lib/auth/navigation';
import { NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase/server';

/** PKCE callback: exchange the code for a session cookie, then continue to `next`. */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get('code');
  const next = safeNext(searchParams.get('next'));
  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(`${origin}${verifyHref(next)}`);
  }
  return NextResponse.redirect(`${origin}/auth/sign-in?error=callback&next=${encodeURIComponent(next)}`);
}
