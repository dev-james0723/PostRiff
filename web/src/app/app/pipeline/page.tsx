import type { Metadata } from 'next';
import { PipelineView } from '@/features/pipeline/pipeline-view';

export const metadata: Metadata = { title: 'Pipeline' };

export default function Page() {
  return <PipelineView />;
}
