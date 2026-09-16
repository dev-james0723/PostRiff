import type { Metadata } from 'next';
import { ModelsView } from '@/features/account/models-view';

export const metadata: Metadata = { title: 'Models & providers' };

export default function ModelsPage() {
  return <ModelsView />;
}
