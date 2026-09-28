import { Suspense } from 'react';
import type { Metadata } from 'next';
import { VerifyCall } from '@/features/rafii-phone/verify-call';
export const metadata: Metadata = { title: 'Verify your Rafii call', robots: { index: false, follow: false }, referrer: 'no-referrer' };
export default function Page() {
  return <Suspense fallback={<p role='status'>Loading call verification…</p>}><VerifyCall /></Suspense>;
}
