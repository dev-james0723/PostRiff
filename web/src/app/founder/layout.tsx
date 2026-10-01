import type { Metadata } from 'next';
import { cookies, headers } from 'next/headers';
import { redirect } from 'next/navigation';
import { FounderShell } from '@/features/founder/shell/founder-shell';
import { CONTROL_COOKIE, FOUNDER_SIGN_IN_PATH } from '@/lib/founder/errors';

export const metadata: Metadata = {
  title: { default: 'Founder', template: '%s · Rafii Founder' },
  robots: { index: false, follow: false }
};

/**
 * Server layout for `/founder/*` (CONTRACTS §6). A browser without the `__Host-rafii-control` cookie is sent to
 * sign-in; the cookie's validity is proven by the shell's `GET /session`, never here. The sign-in page itself is
 * served bare: the proxy marks it with `x-founder-route: sign-in` so this layout neither gates nor wraps it.
 */
export default async function FounderLayout({ children }: { children: React.ReactNode }) {
  const route = (await headers()).get('x-founder-route');
  if (route === 'sign-in') return <>{children}</>;
  const cookieStore = await cookies();
  if (!cookieStore.has(CONTROL_COOKIE)) redirect(FOUNDER_SIGN_IN_PATH);
  const defaultOpen = cookieStore.get('sidebar_state')?.value !== 'false';
  return <FounderShell defaultOpen={defaultOpen}>{children}</FounderShell>;
}
