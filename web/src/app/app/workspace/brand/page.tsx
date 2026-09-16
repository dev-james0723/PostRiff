import type { Metadata } from 'next';
import { BrandView } from '@/features/workspace/brand-view';

export const metadata: Metadata = { title: 'Brand & voice' };

export default function Page() {
  return <BrandView />;
}
