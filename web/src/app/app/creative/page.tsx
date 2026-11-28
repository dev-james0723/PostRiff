import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { CreativeStudio } from '@/features/creative-video/studio';

export const metadata: Metadata = {
  title: 'Video Studio',
  description: 'Build an original brand video from a brief or reference, quote individual scenes in AI Credits and export your edit.'
};

export default async function Page({ searchParams }: {
  searchParams: Promise<{ project?: string | string[]; reference?: string | string[]; scene?: string | string[]; revision?: string | string[] }>;
}) {
  const { project, reference, revision, scene } = await searchParams;
  if (scene !== undefined && (typeof project !== 'string' || !project || typeof scene !== 'string' || !scene || scene.length > 128)) notFound();
  if (revision !== undefined && (typeof revision !== 'string' || !/^[1-9]\d{0,8}$/.test(revision) || typeof project !== 'string' || !project)) notFound();
  const selectedRevision = revision === undefined ? undefined : Number(revision);
  return <CreativeStudio projectId={typeof project === 'string' ? project : ''} referenceId={typeof reference === 'string' ? reference : ''} revision={selectedRevision} selectedSceneId={scene} />;
}
