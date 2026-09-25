import type { Metadata } from 'next';
import { PersonalizationView } from '@/features/coworker/personalization/personalization-view';

export const metadata: Metadata = { title: 'Personalization' };

export default function PersonalizationPage() {
  return <PersonalizationView />;
}
