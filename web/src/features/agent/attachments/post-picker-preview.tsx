'use client';

import { useMemo, useState } from 'react';

import {
  ExpandedPreviewDialog,
  type DeckItem
} from '@/components/application/post-preview/expanded-preview-dialog';
import { previewFromDraft } from '@/components/application/post-preview/draft-preview';
import { useAccountPicture } from '@/components/application/post-preview/use-account-picture';
import {
  usePreviewPost,
  useRunPreviewMedia
} from '@/components/application/post-preview/use-preview-post';
import { useLocalTimeZone } from '@/hooks/use-local-time-zone';
import type { Manifest, Snapshot, SnapshotVariant } from '@/lib/api/types';

import type { PickerItem } from './picker-items';

function latestManifest(snapshot: Snapshot, variantId: string): Manifest | null {
  const phase2 = snapshot.state.phase2;
  if (!phase2) return null;
  for (let index = phase2.jobs.length - 1; index >= 0; index -= 1) {
    if (phase2.jobs[index].manifest.variantId === variantId) return phase2.jobs[index].manifest;
  }
  for (let index = phase2.reviews.length - 1; index >= 0; index -= 1) {
    if (phase2.reviews[index].manifest.variantId === variantId) return phase2.reviews[index].manifest;
  }
  return null;
}

function PreviewDialog({
  post,
  item,
  open,
  onOpenChange
}: {
  post: DeckItem['post'];
  item: PickerItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const items = useMemo<DeckItem[]>(() => [{ key: item.id, post }], [item.id, post]);
  return (
    <ExpandedPreviewDialog
      open={open}
      onOpenChange={onOpenChange}
      items={items}
      activeKey={item.id}
      onChange={() => undefined}
      eyebrow='Post preview'
      description={'How this post may look inside ' + post.channelName + ' on iPhone.'}
      tools={false}
    />
  );
}

function ManifestPostPreview({
  manifest,
  item,
  open,
  onOpenChange
}: {
  manifest: Manifest;
  item: PickerItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const localZone = useLocalTimeZone();
  const post = usePreviewPost(manifest, localZone || manifest.timing.timeZone);
  return <PreviewDialog post={post} item={item} open={open} onOpenChange={onOpenChange} />;
}

function DraftPostPreview({
  variant,
  item,
  snapshot,
  open,
  onOpenChange
}: {
  variant: SnapshotVariant;
  item: PickerItem;
  snapshot: Snapshot;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const localZone = useLocalTimeZone();
  const [openedAt] = useState(() => new Date());
  const media = useRunPreviewMedia(variant.media, snapshot.state.phase2?.assets);
  const avatarUrl = useAccountPicture(variant.channelId);
  const channel = snapshot.state.phase2?.channels.find((candidate) => candidate.id === variant.channelId);
  if (!localZone) return null;

  const post = previewFromDraft({
    platform: variant.platform,
    text: variant.text,
    account: channel?.account || snapshot.state.workspace?.name || 'Your account',
    channelId: variant.channelId,
    publishAt: openedAt,
    media,
    timeZone: localZone,
    avatarUrl
  });
  return <PreviewDialog post={post} item={item} open={open} onOpenChange={onOpenChange} />;
}

export function PostPickerPreview({
  item,
  snapshot,
  open,
  onOpenChange
}: {
  item: PickerItem | null;
  snapshot: Snapshot | null | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!item || item.kind !== 'post' || !snapshot) return null;
  const variant = snapshot.state.variants?.find((candidate) => candidate.id === item.id);
  if (!variant) return null;
  const manifest = latestManifest(snapshot, variant.id);
  return manifest ? (
    <ManifestPostPreview
      manifest={manifest}
      item={item}
      open={open}
      onOpenChange={onOpenChange}
    />
  ) : (
    <DraftPostPreview
      variant={variant}
      item={item}
      snapshot={snapshot}
      open={open}
      onOpenChange={onOpenChange}
    />
  );
}
