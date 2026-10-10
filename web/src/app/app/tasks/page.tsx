import type { Metadata } from 'next';
import { TaskCenter } from '@/features/agent-tasks/task-center';
export const metadata: Metadata = { title: 'Tasks' };
export default function Page() { return <TaskCenter />; }
