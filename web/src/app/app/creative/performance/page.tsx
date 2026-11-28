import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { VideoPerformance } from '@/features/creative-video/performance';

export const metadata: Metadata = { title: 'Video performance' };

export default async function Page({ searchParams }: {
  searchParams: Promise<{ project?: string | string[]; revision?: string | string[] }>;
}) {
  const { project, revision } = await searchParams;
  if (typeof project !== 'string' || !project || project.length > 128 ||
      typeof revision !== 'string' || !/^[1-9]\d{0,8}$/.test(revision)) notFound();
  return <VideoPerformance projectId={project} revision={Number(revision)} />;
}
