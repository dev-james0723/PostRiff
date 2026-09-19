import type { Metadata } from 'next';
import { Suspense } from 'react';
import { SignInHelp } from '@/components/auth/sign-in-help';
export const metadata: Metadata = { title: 'Sign-in help', robots: { index: false } };
export default function ResetPage() { return <Suspense fallback={null}><SignInHelp /></Suspense>; }
