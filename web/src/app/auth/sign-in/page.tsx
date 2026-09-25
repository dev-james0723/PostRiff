import type { Metadata } from 'next';
import { Suspense } from 'react';
import { AuthForm } from '@/components/auth/auth-form';

export const metadata: Metadata = {
  title: 'Sign in',
  description: 'Sign in to your Rafii workspace.',
  robots: { index: false }
};

export default function SignInPage() {
  return (
    <Suspense fallback={null}>
      <AuthForm intent='sign-in' />
    </Suspense>
  );
}
