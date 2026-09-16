import type { Metadata } from 'next';
import { RolesView } from '@/features/workspace/roles-view';

export const metadata: Metadata = { title: 'Roles' };

export default function Page() {
  return <RolesView />;
}
