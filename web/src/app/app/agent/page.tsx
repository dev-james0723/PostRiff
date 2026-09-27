import { redirect } from 'next/navigation';

/** The chat home lives at /app; keep the bare agent entry point usable. */
export default function AgentIndexPage() {
  redirect('/app');
}
