import type { Metadata } from 'next';
import { MembersView } from '@/features/workspace/members-view';

export const metadata: Metadata = { title: 'Members' };

export default function Page() {
  return <MembersView />;
}
