import { Wordmark } from '@/components/marketing/wordmark';
import { AuthProvider } from '@/lib/auth/session';

/**
 * Sign-in, sign-up, verification and help share one frame (Design DNA §21.16): the same
 * ambient canvas as the workspace, a restrained identity block, and one central surface.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className='relative isolate flex min-h-svh flex-col'>
        <div aria-hidden className='rafii-ambient' />
        <div className='mx-auto flex h-16 w-full max-w-6xl items-center px-4 sm:px-6'>
          <Wordmark />
        </div>
        <main className='flex flex-1 items-center justify-center px-4 pt-2 pb-[max(2.5rem,env(safe-area-inset-bottom))] sm:px-6'>
          <div className='w-full max-w-[26.5rem]'>{children}</div>
        </main>
      </div>
    </AuthProvider>
  );
}
