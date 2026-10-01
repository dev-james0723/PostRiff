import { NextRequest, NextResponse } from 'next/server';
import { admitted } from './boundary.mjs';

export function proxy(request: NextRequest) {
  if (!admitted(request.headers.get('host'), process.env)) return new NextResponse('Not found',{status:404,headers:{'Cache-Control':'no-store'}});
  if (request.nextUrl.pathname.startsWith('/control') && !request.cookies.get('__Host-rafii-control')) {
    return NextResponse.redirect(new URL('/sign-in', request.url));
  }
  const nonce = btoa(crypto.randomUUID());
  const identity = process.env.NEXT_PUBLIC_CONTROL_SUPABASE_URL;
  const source = identity && /^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(identity) ? identity : '';
  const csp = `default-src 'self'; script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${process.env.NODE_ENV==='development' ? " 'unsafe-eval'" : ''}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' ${source}; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'`;
  const headers = new Headers(request.headers);
  headers.set('x-nonce',nonce);
  headers.set('Content-Security-Policy',csp);
  const response = NextResponse.next({request:{headers}});
  response.headers.set('Content-Security-Policy',csp);
  response.headers.set('Cache-Control','private, no-store');
  return response;
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
