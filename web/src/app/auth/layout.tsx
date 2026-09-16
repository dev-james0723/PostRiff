import { Wordmark } from '@/components/marketing/wordmark';
import { AuthProvider } from '@/lib/auth/session';

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className='flex min-h-svh flex-col'>
        <div className='mx-auto flex h-14 w-full max-w-6xl items-center px-4 sm:px-6'>
          <Wordmark />
        </div>
        <main className='flex flex-1 items-center justify-center px-4 py-10 sm:px-6'>
          <div className='w-full max-w-sm'>{children}</div>
        </main>
      </div>
    </AuthProvider>
  );
}
