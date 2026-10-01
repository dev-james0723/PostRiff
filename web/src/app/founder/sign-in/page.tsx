import type { Metadata } from 'next';
import { Suspense } from 'react';
import { FounderSignInForm } from '@/features/founder/shell/sign-in-form';

export const metadata: Metadata = {
  title: 'Founder sign-in',
  description: 'Sign in to the Rafii founder admin.',
  robots: { index: false, follow: false }
};

/** Served without the founder shell (the proxy marks this route; the layout passes it through). */
export default function FounderSignInPage() {
  return (
    <div className='relative isolate flex min-h-svh flex-col'>
      <div aria-hidden className='rafii-ambient' />
      <main className='flex flex-1 items-center justify-center px-4 pt-10 pb-[max(2.5rem,env(safe-area-inset-bottom))] sm:px-6'>
        <div className='w-full max-w-[26.5rem]'>
          <Suspense fallback={null}>
            <FounderSignInForm />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
