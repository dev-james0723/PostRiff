import type { Metadata } from 'next';
import { Suspense } from 'react';
import { VerifySession } from '@/components/auth/verify-session';
export const metadata: Metadata = { title: 'Confirm your sign-in', robots: { index: false } };
export default function VerifyPage() { return <Suspense fallback={null}><VerifySession /></Suspense>; }
