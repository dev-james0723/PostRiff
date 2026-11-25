import type { Metadata } from 'next';
import { Suspense } from 'react';
import { AuthForm } from '@/components/auth/auth-form';
import { PRICING_CATALOG } from '@/config/plans';
import { marketingCopy } from '@/config/pricing-copy';

const { signUp } = marketingCopy(PRICING_CATALOG);

export const metadata: Metadata = {
  title: signUp.metaTitle,
  description: signUp.metaDescription,
  robots: { index: false }
};

export default function SignUpPage() {
  return (
    <Suspense fallback={null}>
      <AuthForm intent='sign-up' signUp={signUp} />
    </Suspense>
  );
}
