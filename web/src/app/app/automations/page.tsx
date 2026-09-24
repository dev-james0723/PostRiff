import type { Metadata } from 'next';
import { AutomationsView } from '@/features/automations/automations-view';

export const metadata: Metadata = { title: 'Automations' };

export default function Page() {
  return <AutomationsView />;
}
