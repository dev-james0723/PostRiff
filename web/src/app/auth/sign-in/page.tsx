import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Sign in',
  description: 'Sign in to your PostRiff workspace.',
  robots: { index: false }
};

// Placeholder until Phase B wires Supabase auth.
export default function SignInPage() {
  return (
    <div className='flex flex-col gap-2 text-center'>
      <h1 className='text-2xl font-semibold tracking-tight'>Sign in</h1>
      <p className='text-muted-foreground text-sm'>Sign in coming in Phase B.</p>
    </div>
  );
}
