import type { Metadata } from 'next';
import { NotificationsView } from '@/features/account/notifications-view';

export const metadata: Metadata = { title: 'Notifications' };

export default function Page() {
  return <NotificationsView />;
}
