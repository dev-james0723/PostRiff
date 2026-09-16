import type { Metadata } from 'next';
import { AuthProvider } from '@/lib/auth/session';
import { Wordmark } from '@/components/marketing/wordmark';
import { AcceptInvitation } from './accept-invitation';

export const metadata: Metadata = {
  title: 'Accept invitation',
  robots: { index: false }
};

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthProvider>
      <div className='flex min-h-svh flex-col'>
        <div className='mx-auto flex h-14 w-full max-w-6xl items-center px-4 sm:px-6'>
          <Wordmark />
        </div>
        <main className='flex flex-1 items-center justify-center px-4 py-10 sm:px-6'>
          <div className='w-full max-w-md'>
            <AcceptInvitation token={token} />
          </div>
        </main>
      </div>
    </AuthProvider>
  );
}
