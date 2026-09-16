import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Overview'
};

export default function AppOverviewPage() {
  return (
    <div className='flex flex-1 items-center justify-center p-4'>
      <p className='text-muted-foreground text-sm'>App shell coming in Phase B.</p>
    </div>
  );
}
