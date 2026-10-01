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

/** The sign-up link under the form follows the active catalog (the trial today, Free under Pricing v2). */
const { signUp } = marketingCopy(PRICING_CATALOG);

export default function SignInPage() {
  return (
    <Suspense fallback={null}>
      <AuthForm intent='sign-in' signUp={signUp} />
    </Suspense>
  );
}
