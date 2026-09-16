import type { Metadata } from 'next';
import { WorkspaceAccessProvider } from '@/lib/auth/access';

export const metadata: Metadata = {
  robots: { index: false, follow: false }
};

// Placeholder shell. Phase B adds the sidebar, KBar and real workspace access.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceAccessProvider>
      <div className='flex min-h-svh flex-col'>{children}</div>
    </WorkspaceAccessProvider>
  );
}
