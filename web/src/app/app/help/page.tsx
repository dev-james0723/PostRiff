import type { Metadata } from 'next';
import { HelpIndexView } from '@/features/help/help-view';

export const metadata: Metadata = { title: 'Help' };

export default function Page() {
  return <HelpIndexView />;
}
