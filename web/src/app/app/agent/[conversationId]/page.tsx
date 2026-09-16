import type { Metadata } from 'next';
import { ConversationView } from '@/features/agent/conversation-view';

export const metadata: Metadata = { title: 'Chat' };

export default async function ConversationPage({ params }: { params: Promise<{ conversationId: string }> }) {
  const { conversationId } = await params;
  return <ConversationView conversationId={conversationId} />;
}
