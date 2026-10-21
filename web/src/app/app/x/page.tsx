import type { Metadata } from 'next';
import { XManagementView } from '@/features/x/management-view';
export const metadata: Metadata = { title: 'Manage X' };
export default function Page() { return <XManagementView />; }
