import type { Metadata } from 'next';
import { cookies } from 'next/headers';
import { AppShell } from '@/components/layout/app-shell';

export const metadata: Metadata = {
  title: { default: 'Workspace', template: '%s · PostRiff' },
  robots: { index: false, follow: false }
};

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const defaultOpen = cookieStore.get('sidebar_state')?.value !== 'false';
  return <AppShell defaultOpen={defaultOpen}>{children}</AppShell>;
}
