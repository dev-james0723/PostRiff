import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Start free trial',
  description: 'Create your PostRiff workspace.',
  robots: { index: false }
};

// Placeholder until Phase B wires Supabase auth.
export default function SignUpPage() {
  return (
    <div className='flex flex-col gap-2 text-center'>
      <h1 className='text-2xl font-semibold tracking-tight'>Start free trial</h1>
      <p className='text-muted-foreground text-sm'>Sign up coming in Phase B.</p>
    </div>
  );
}
