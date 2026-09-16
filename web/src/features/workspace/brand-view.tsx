'use client';

import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useSnapshot } from '@/lib/api/hooks';
import { downloadBlob } from '@/lib/download';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { toast } from 'sonner';

interface ProfileLike {
  tone?: string;
  writingExample?: string;
  observations?: string[];
  fields?: { id: string; label: string; value: string; section: string; privacy: string }[];
}

export function BrandView() {
  const snapshot = useSnapshot();
  const { api, workspaceId } = useWorkspaceApi();
  const state = snapshot.data?.state;
  const you = state?.you as { identitySentence?: string } | undefined;
  const profile = state?.profile as ProfileLike | undefined;
  const sources = state?.sources ?? [];

  async function exportProfile() {
    try {
      downloadBlob(await api.exportProfile(workspaceId), 'postriff-personal-voice.zip');
    } catch {
      toast.error('The voice profile could not be exported.');
    }
  }

  return (
    <PageContainer
      pageTitle='Brand & voice'
      pageDescription='What PostRiff knows about how you write. Every entry came from you and can be exported or deleted.'
      pageHeaderAction={
        <Button variant='outline' onClick={() => void exportProfile()}>
          Export voice profile
        </Button>
      }
    >
      {snapshot.isLoading ? (
        <Skeleton className='h-64 w-full' />
      ) : (
        <div className='grid gap-4 lg:grid-cols-2'>
          <Card>
            <CardHeader>
              <CardTitle>Identity</CardTitle>
              <CardDescription>The one-line summary drafts are checked against.</CardDescription>
            </CardHeader>
            <CardContent className='text-sm'>
              {you?.identitySentence ? <p>{you.identitySentence}</p> : <p className='text-muted-foreground'>Not set yet.</p>}
              {profile?.tone && (
                <p className='text-muted-foreground mt-2 text-xs'>
                  Tone: <span className='text-foreground'>{profile.tone}</span>
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Writing sample</CardTitle>
              <CardDescription>Used to match rhythm and vocabulary, never quoted publicly.</CardDescription>
            </CardHeader>
            <CardContent className='text-sm'>
              {profile?.writingExample ? (
                <blockquote className='border-l-2 pl-3 whitespace-pre-wrap'>{profile.writingExample}</blockquote>
              ) : (
                <p className='text-muted-foreground'>No sample yet. Paste one in Ideas and mark it as your own writing.</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Observations</CardTitle>
              <CardDescription>Patterns noticed across your approved drafts.</CardDescription>
            </CardHeader>
            <CardContent className='text-sm'>
              {profile?.observations?.length ? (
                <ul className='list-disc pl-5'>
                  {profile.observations.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className='text-muted-foreground'>Nothing recorded yet.</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Sources</CardTitle>
              <CardDescription>
                {sources.length} source{sources.length === 1 ? '' : 's'} in this workspace · {sources.filter((s) => s.active).length} active
              </CardDescription>
            </CardHeader>
            <CardContent className='flex flex-col gap-2 text-sm'>
              {sources.slice(0, 6).map((source) => (
                <div key={source.id} className='flex items-center justify-between gap-3'>
                  <span className='truncate'>{source.title || source.kind}</span>
                  <span className='text-muted-foreground shrink-0 text-xs'>{source.visibility}</span>
                </div>
              ))}
              <Link href='/app/ideas' className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
                Add a source in Ideas
              </Link>
            </CardContent>
          </Card>
        </div>
      )}
    </PageContainer>
  );
}
