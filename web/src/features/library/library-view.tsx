'use client';

import { useRef, useState } from 'react';
import Image from 'next/image';
import { useQuery } from '@tanstack/react-query';
import { AnimatePresence, motion, useReducedMotion, type Variants } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger
} from '@/components/motion/context-menu';
import { TiltCard } from '@/components/motion/tilt-card';
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
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { formatBytes } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useFlash } from '@/hooks/use-flash';

const MAX_BYTES = 8 * 1024 * 1024;

// The grid staggers its first reveal; an asset added later (an upload) inherits the variants and animates in on its own.
const GRID_VARIANTS: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.035 } } };
const ASSET_VARIANTS: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  show: { opacity: 1, scale: 1, transition: { duration: 0.28, ease: EASE_OUT } }
};

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

async function copyHash(hash: string) {
  try {
    await navigator.clipboard.writeText(hash);
    toast.success('Copied to clipboard.');
  } catch {
    toast.error('Could not copy the hash.');
  }
}

export function LibraryView() {
  const snapshot = useSnapshot();
  const act = useAct();
  const access = useWorkspaceAccess();
  const reduce = useReducedMotion();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const input = useRef<HTMLInputElement>(null);
  const [pendingDelete, setPendingDelete] = useState<Asset | null>(null);
  // `act` also carries deletes, so the upload button tracks its own request rather than act.isPending.
  const [uploading, setUploading] = useState(false);
  const [uploadOutcome, flashUploadOutcome] = useFlash<'success' | 'error'>();
  const assets = (snapshot.data?.state.phase2?.assets ?? []).filter((a) => !a.deleted);
  const revision = snapshot.data?.revision ?? 0;

  async function upload(file: File) {
    if (file.size > MAX_BYTES) {
      toast.error('Choose an image up to 8 MB.');
      flashUploadOutcome('error');
      return;
    }
    setUploading(true);
    try {
      const data = await toBase64(file);
      act.mutate(
        { revision, action: 'p2_media_upload', payload: { data } },
        {
          onSuccess: () => {
            toast.success('Uploaded.');
            setUploading(false);
            flashUploadOutcome('success');
          },
          onError: (err) => {
            toast.error(err instanceof ApiError ? err.message : 'Upload failed.');
            setUploading(false);
            flashUploadOutcome('error');
          }
        }
      );
    } catch {
      toast.error('The file could not be read.');
      setUploading(false);
      flashUploadOutcome('error');
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
            <StatefulButton
              state={uploading ? 'loading' : (uploadOutcome ?? 'idle')}
              icon={<Icons.upload className='size-4' />}
              loadingText='Uploading…'
              successText='Uploaded'
              errorText='Upload failed'
              disabled={act.isPending}
              onClick={() => input.current?.click()}
            >
              Upload image
            </StatefulButton>
          </>
        ) : undefined
      }
    >
      {snapshot.isLoading ? (
        <Skeleton className='h-64 w-full' />
      ) : (
        // 'wait': deleting the last image lets it leave before the empty state arrives.
        <AnimatePresence mode='wait'>
          {assets.length === 0 ? (
            <motion.div
              key='empty'
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2, ease: EASE_OUT }}
              className='flex flex-1 flex-col'
            >
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant='icon'>
                    <Icons.media />
                  </EmptyMedia>
                  <EmptyTitle>No media yet</EmptyTitle>
                  <EmptyDescription>Upload images here or from a draft. Each one is stored with its hash and served privately.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            </motion.div>
          ) : (
            <motion.div
              key='grid'
              className='grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6'
              variants={GRID_VARIANTS}
              initial={reduce ? false : 'hidden'}
              animate='show'
              exit={{ opacity: 0, transition: { duration: 0.2, ease: EASE_OUT } }}
            >
              <AnimatePresence>
                {assets.map((asset) => (
                  <ContextMenu key={asset.id}>
                    <ContextMenuTrigger>
                      <motion.figure
                        layout={reduce ? false : 'position'}
                        variants={ASSET_VARIANTS}
                        exit={reduce ? { opacity: 0, transition: { duration: 0.15 } } : { opacity: 0, scale: 0.94, transition: { duration: 0.2, ease: EASE_OUT } }}
                        transition={{ layout: SPRING_LAYOUT }}
                        className='bg-card flex flex-col overflow-hidden rounded-lg border'
                      >
                        {/* Only the image tilts; the caption keeps the Delete button still. The figure clips the corners. */}
                        <TiltCard max={6} className='rounded-none'>
                          <AssetThumb asset={asset} />
                        </TiltCard>
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
                      </motion.figure>
                    </ContextMenuTrigger>
                    <ContextMenuContent ariaLabel='Image actions'>
                      <ContextMenuItem onSelect={() => void copyHash(asset.hash)}>
                        <Icons.copy className='text-muted-foreground size-4' aria-hidden />
                        Copy hash
                      </ContextMenuItem>
                      {canEdit && (
                        <>
                          <ContextMenuSeparator />
                          <ContextMenuItem tone='destructive' disabled={act.isPending} onSelect={() => setPendingDelete(asset)}>
                            <Icons.trash className='size-4' aria-hidden />
                            Delete…
                          </ContextMenuItem>
                        </>
                      )}
                    </ContextMenuContent>
                  </ContextMenu>
                ))}
              </AnimatePresence>
            </motion.div>
          )}
        </AnimatePresence>
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
