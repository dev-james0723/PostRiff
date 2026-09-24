import type { Metadata } from 'next';
import { cookies, headers } from 'next/headers';
import { loadWorkspaceBootstrap } from '@/lib/workspace/server-bootstrap';
import { AppShell } from '@/components/layout/app-shell';

export const metadata: Metadata = {
  title: { default: 'Workspace', template: '%s · Rafii' },
  robots: { index: false, follow: false }
};

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const defaultOpen = cookieStore.get('sidebar_state')?.value !== 'false';
  const initial = (await headers()).get('x-postriff-home-render') === '1' ? await loadWorkspaceBootstrap() : null;
  return <AppShell defaultOpen={defaultOpen} initial={initial}>{children}</AppShell>;
}
