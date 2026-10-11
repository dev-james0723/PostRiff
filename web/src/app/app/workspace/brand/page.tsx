import { BRAND_BRAIN_V11 } from '@/features/workspace/brand/brain-types';
import type { Metadata } from 'next';
import { BrandView } from '@/features/workspace/brand-view';

export const metadata: Metadata = { title: BRAND_BRAIN_V11 ? 'Brand Brain' : 'Brand & voice' };

export default function Page() {
  return <BrandView />;
}
