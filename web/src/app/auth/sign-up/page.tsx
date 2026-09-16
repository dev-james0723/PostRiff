import type { Metadata } from 'next';
import { Suspense } from 'react';
import { AuthForm } from '@/components/auth/auth-form';

export const metadata: Metadata = {
  title: 'Start your free trial',
  description: 'Create a PostRiff workspace. 14-day trial, no card required.',
  robots: { index: false }
};

export default function SignUpPage() {
  return (
    <Suspense fallback={null}>
      <AuthForm intent='sign-up' />
    </Suspense>
  );
}
