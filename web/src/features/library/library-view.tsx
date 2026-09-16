'use client';

import { useRef, useState } from 'react';
import Image from 'next/image';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Asset } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatBytes } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const MAX_BYTES = 8 * 1024 * 1024;

const infoContent = {
  title: 'Library',
  sections: [
    { title: 'Private by default', description: 'Media lives in private storage and is served only to members of this workspace, through the API.' },
    { title: 'Provenance', description: 'Every asset is stored with its hash; publications reference the exact hash they were approved with.' },
    { title: 'Limits', description: 'Images up to 8 MB. Storage counts toward your plan allowance.' }
  ]
};

function AssetThumb({ asset }: { asset: Asset }) {
  const { api, workspaceId } = useWorkspaceApi();
  const image = useQuery({
    queryKey: ['media', workspaceId, asset.id],
    queryFn: async () => URL.createObjectURL(await api.media(workspaceId, asset.id)),
    staleTime: Infinity
  });
  if (image.isLoading) return <Skeleton className='aspect-square w-full' />;
  if (!image.data) return <div className='bg-muted flex aspect-square w-full items-center justify-center text-xs'>Preview unavailable</div>;
  return <Image src={image.data} alt='' width={400} height={400} unoptimized className='aspect-square w-full object-cover' />;
}

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] ?? ''), { once: true });
    reader.addEventListener('error', () => reject(reader.error), { once: true });
    reader.readAsDataURL(file);
  });
}

export function LibraryView() {
  const snapshot = useSnapshot();
  const act = useAct();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const input = useRef<HTMLInputElement>(null);
  const [pendingDelete, setPendingDelete] = useState<Asset | null>(null);
  const assets = (snapshot.data?.state.phase2?.assets ?? []).filter((a) => !a.deleted);
  const revision = snapshot.data?.revision ?? 0;

  async function upload(file: File) {
    if (file.size > MAX_BYTES) {
      toast.error('Choose an image up to 8 MB.');
      return;
    }
    try {
      const data = await toBase64(file);
      act.mutate(
        { revision, action: 'p2_media_upload', payload: { data } },
        {
          onSuccess: () => toast.success('Uploaded.'),
          onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Upload failed.')
        }
      );
    } catch {
      toast.error('The file could not be read.');
    }
  }

  function remove(asset: Asset) {
    act.mutate(
      { revision, action: 'p2_media_delete', payload: { assetId: asset.id } },
      {
        onSuccess: () => toast.success('Deleted.'),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Delete failed.')
      }
    );
  }

  return (
    <PageContainer
      pageTitle='Library'
      pageDescription='Images you can attach to posts. Private to this workspace.'
      infoContent={infoContent}
      pageHeaderAction={
        canEdit ? (
          <>
            <input
              ref={input}
              type='file'
              accept='image/*'
              aria-label='Choose an image to upload'
              className='hidden'
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = '';
              }}
            />
            <Button disabled={act.isPending} onClick={() => input.current?.click()}>
              <Icons.upload className='size-4' /> Upload image
            </Button>
          </>
        ) : undefined
      }
    >
      {snapshot.isLoading ? (
        <Skeleton className='h-64 w-full' />
      ) : assets.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <Icons.media />
            </EmptyMedia>
            <EmptyTitle>No media yet</EmptyTitle>
            <EmptyDescription>Upload images here or from a draft. Each one is stored with its hash and served privately.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className='grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6'>
          {assets.map((asset) => (
            <figure key={asset.id} className='bg-card flex flex-col overflow-hidden rounded-lg border'>
              <AssetThumb asset={asset} />
              <figcaption className='flex flex-col gap-1 p-2 text-xs'>
                <span className='text-muted-foreground truncate font-mono' title={asset.hash}>
                  {asset.hash.slice(0, 10)}…
                </span>
                <span className='text-muted-foreground'>
                  {asset.mime}
                  {asset.width && asset.height ? ` · ${asset.width}×${asset.height}` : ''}
                  {asset.bytes ? ` · ${formatBytes(asset.bytes)}` : ''}
                </span>
                {canEdit && (
                  <Button variant='ghost' size='sm' className='text-destructive h-7 justify-start px-1' disabled={act.isPending} onClick={() => setPendingDelete(asset)}>
                    <Icons.trash className='size-3.5' /> Delete
                  </Button>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this image?</AlertDialogTitle>
            <AlertDialogDescription>Published posts keep their own copy; drafts referencing it will need a new image.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingDelete) remove(pendingDelete);
                setPendingDelete(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}
