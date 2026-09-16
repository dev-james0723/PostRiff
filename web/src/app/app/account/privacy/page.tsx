import type { Metadata } from 'next';
import { PrivacyView } from '@/features/account/privacy-view';

export const metadata: Metadata = { title: 'Privacy & data' };

export default function Page() {
  return <PrivacyView />;
}
