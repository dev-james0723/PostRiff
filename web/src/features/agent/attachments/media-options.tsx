'use client';

/**
 * What tapping a chip opens (chat-context SPEC §4.4–§4.6). `MediaOptions` for a photo or video: the role (In the post /
 * Reference), what that means, reading (automatic, or a tap in credit mode) with "What Rafii noted", consent for owners
 * and the ask line for others, an inline player for videos, and Remove. `ChipOptions` for a post, template or source:
 * the post role and Remove. Every string is from SPEC §13.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Icons } from '@/components/icons';
import { SegmentedControl } from '@/components/rafii/segmented-control';
import { Button } from '@/components/ui/button';
import { useAct, useInvalidate, useMemory, useSnapshot } from '@/lib/api/hooks';
import type { Asset, AttachmentsCatalog } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useAssetImage } from '@/features/library/asset-card';
import { MediaConsentConfirm } from '@/features/memory/access-card';

import type { Chip, MediaRole, PostRole } from './chips';

function credits(milli: number | undefined): string {
  return String(Math.max(1, Math.round((milli ?? 0) / 1000)));
}

/** Why a reference can't be read here, or null when it can (SPEC §4.6, §13 "Media options: blocked"). */
export function readBlocker(opts: {
  catalog: AttachmentsCatalog | null | undefined;
  fixtureWriter: boolean;
  consent: { cloud: boolean; reconfirm: boolean } | null | undefined;
  isOwner: boolean;
}): { message: string; allow: boolean } | null {
  if (!opts.catalog?.notes.available)
    return { message: "Photo reading isn't available here.", allow: false };
  if (opts.fixtureWriter)
    return {
      message:
        "The free preview writer doesn't use photo notes. Choose another writer to use them.",
      allow: false
    };
  if (opts.consent?.cloud && opts.consent.reconfirm)
    return opts.isOwner
      ? { message: 'Allow Rafii to look at photos and videos first.', allow: true }
      : { message: 'The workspace owner needs to allow the new photo reader.', allow: false };
  if (!opts.consent?.cloud)
    return opts.isOwner
      ? { message: 'Allow Rafii to look at photos and videos first.', allow: true }
      : {
          message: 'Ask the workspace owner to allow photo reading on the Memory page.',
          allow: false
        };
  return null;
}

function InlineVideo({ assetId }: { assetId: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const poster = useAssetImage(assetId);
  const playback = useQuery({
    queryKey: ['media-url', workspaceId, assetId],
    queryFn: async () => (await api.mediaUrl(workspaceId, assetId)).url,
    enabled: Boolean(workspaceId),
    staleTime: 5 * 60 * 1000
  });
  if (!playback.data) return null;
  return (
    <div className='rafii-quiet flex max-h-56 items-center justify-center overflow-hidden rounded-[var(--rafii-radius-card)]'>
      {/* The person's own upload: no caption file exists for it, and an empty <track> would claim one. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video
        src={playback.data}
        poster={poster.data}
        controls
        playsInline
        preload='metadata'
        aria-label='Play video'
        className='h-auto max-h-56 w-auto max-w-full'
      />
    </div>
  );
}

export interface MediaOptionsProps {
  chip: Chip;
  asset?: Asset | null;
  catalog: AttachmentsCatalog | null | undefined;
  creditMode: boolean;
  fixtureWriter: boolean;
  isOwner: boolean;
  onRole: (role: MediaRole) => void;
  onRead: () => void;
  onRetry: () => void;
  onRemove: () => void;
}

export function MediaOptions({
  chip,
  asset,
  catalog,
  creditMode,
  fixtureWriter,
  isOwner,
  onRole,
  onRead,
  onRetry,
  onRemove
}: MediaOptionsProps) {
  const video = chip.kind === 'video';
  const role: MediaRole = chip.role === 'reference' ? 'reference' : 'post';
  const memory = useMemory();
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const [asking, setAsking] = useState(false);
  const consent = memory.data?.media;
  const blocked =
    role === 'reference' ? readBlocker({ catalog, fixtureWriter, consent, isOwner }) : null;
  const estimate = catalog?.notes[video ? 'video' : 'photo'];

  function allow() {
    act.mutate(
      {
        revision: snapshot.data?.revision ?? 0,
        action: 'media_egress',
        payload: { cloud: true, confirmed: true }
      },
      {
        onSettled: () => setAsking(false),
        onSuccess: () => {
          invalidate('memory');
          if (chip.read?.status !== 'read' && !creditMode) onRead();
        }
      }
    );
  }

  return (
    <div className='flex flex-col gap-3 text-sm'>
      <SegmentedControl
        label='Media options'
        value={role}
        onChange={(next) => onRole(next)}
        options={[
          { value: 'post', label: 'In the post' },
          { value: 'reference', label: 'Reference' }
        ]}
      />
      {role === 'post' ? (
        <p className='text-muted-foreground'>
          {video
            ? "Shown with the draft preview. Video posts can't be scheduled from Rafii yet."
            : "Shown with the draft. Rafii doesn't look at it."}
        </p>
      ) : (
        <div className='flex flex-col gap-2'>
          <p className='text-muted-foreground'>
            {video
              ? 'Rafii looks at 4 frames once and writes from what it sees.'
              : 'Rafii looks at it once and writes from what it sees.'}
            {creditMode && estimate
              ? ` About ${credits(estimate.typicalMilliCredits)} credits, once per ${video ? 'video' : 'photo'}.`
              : ''}
          </p>
          {creditMode ? (
            <p className='text-muted-foreground'>
              Rafii looks at it with a paid AI model before writing.
            </p>
          ) : null}
          {blocked ? (
            <div className='flex flex-col items-start gap-2'>
              <p>{blocked.message}</p>
              {blocked.allow ? (
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => setAsking(true)}
                  disabled={!consent}
                >
                  Review and allow
                </Button>
              ) : null}
            </div>
          ) : chip.read?.status === 'reading' ? (
            <p className='inline-flex items-center gap-2' role='status'>
              <Icons.spinner aria-hidden className='size-4 motion-safe:animate-spin' />
              Reading…
            </p>
          ) : chip.read?.status === 'read' ? (
            <div className='flex flex-col gap-1'>
              <h4 className='rafii-eyebrow'>What Rafii noted</h4>
              <p className='text-foreground whitespace-pre-line'>{chip.read.note}</p>
            </div>
          ) : chip.read?.status === 'failed' ? (
            <div className='flex flex-col items-start gap-2'>
              <p>Couldn&apos;t read this. Try again.</p>
              <Button variant='outline' size='sm' onClick={onRetry}>
                Try again
              </Button>
            </div>
          ) : creditMode ? (
            <Button variant='outline' size='sm' className='self-start' onClick={onRead}>
              Read · about {credits(estimate?.typicalMilliCredits)} credits
            </Button>
          ) : null}
        </div>
      )}
      {video ? <InlineVideo assetId={chip.id} /> : null}
      {asset?.verified?.locationCleared ? (
        <p className='text-muted-foreground'>Location tags removed.</p>
      ) : null}
      <div className='border-foreground/10 flex flex-col items-start gap-1 border-t pt-3'>
        <Button variant='quiet' size='sm' onClick={onRemove}>
          Remove from message
        </Button>
        <p className='text-muted-foreground text-xs'>It stays in your Library.</p>
      </div>
      {isOwner && consent ? (
        <MediaConsentConfirm
          open={asking}
          allow
          pending={act.isPending}
          media={consent}
          creditMode={creditMode}
          onConfirm={allow}
          onClose={() => setAsking(false)}
        />
      ) : null}
    </div>
  );
}

export function ChipOptions({
  chip,
  onRole,
  onRemove
}: {
  chip: Chip;
  onRole: (role: PostRole) => void;
  onRemove: () => void;
}) {
  return (
    <div className='flex flex-col gap-3 text-sm'>
      {chip.kind === 'post' ? (
        <>
          <SegmentedControl
            label='Post options'
            value={chip.role === 'rework' ? 'rework' : 'inspire'}
            onChange={(next) => onRole(next)}
            options={[
              { value: 'rework', label: 'Rework this post' },
              { value: 'inspire', label: 'Use it for ideas' }
            ]}
          />
          <p className='text-muted-foreground'>Only one post can be reworked.</p>
        </>
      ) : null}
      <Button variant='quiet' size='sm' className='self-start' onClick={onRemove}>
        Remove from message
      </Button>
    </div>
  );
}
