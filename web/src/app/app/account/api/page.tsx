import type { Metadata } from 'next';
import { ApiView } from '@/features/account/api-view';

export const metadata: Metadata = { title: 'API & integrations' };

export default function Page() {
  return <ApiView />;
}
