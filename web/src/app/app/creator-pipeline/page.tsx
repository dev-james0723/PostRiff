import type { Metadata } from 'next';
import { CreatorPipeline } from '@/features/creator-pipeline/pipeline';
export const metadata: Metadata = { title: 'Creator Pipeline' };
export default function Page() { return <CreatorPipeline />; }
