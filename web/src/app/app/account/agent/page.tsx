import type { Metadata } from 'next';
import { AgentPermissionsView } from '@/features/account/agent/agent-permissions-view';

export const metadata: Metadata = { title: 'Rafii Agent' };

export default function AgentPermissionsPage() {
  return <AgentPermissionsView />;
}
