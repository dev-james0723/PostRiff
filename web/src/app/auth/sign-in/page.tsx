import type { Metadata } from 'next';
import { Suspense } from 'react';
import { AuthForm } from '@/components/auth/auth-form';
import { PRICING_CATALOG } from '@/config/plans';
import { marketingCopy } from '@/config/pricing-copy';

export const metadata: Metadata = {
  title: 'Sign in',
  description: 'Sign in to your Rafii workspace.',
  robots: { index: false }
};

/** New prospects follow the Free signup path; existing account access remains unchanged. */
const { signUp } = marketingCopy(PRICING_CATALOG);

export default function SignInPage() {
  return (
    <Suspense fallback={null}>
      <AuthForm intent='sign-in' signUp={signUp} />
    </Suspense>
  );
}
