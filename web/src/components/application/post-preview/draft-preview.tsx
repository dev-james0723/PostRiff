'use client';

import { useState } from 'react';
import { channelByPlatform } from '@/config/channels';
import { useLocalTimeZone } from '@/hooks/use-local-time-zone';
import { PostPreview } from './post-preview';
import type { PreviewMedia, PreviewPost } from './types';
import { useAccountPicture } from './use-account-picture';

export interface DraftPreviewInput {
  /** API platform name, e.g. `LinkedIn`. */
  platform: string;
  text: string;
  /** The connected account for the platform, or how the workspace names its speaker. */
  account: string;
  /** The connection the draft would go out through, when one exists; its profile picture is drawn. */
  channelId?: string;
  /** The planned time when there is one; otherwise the preview reads as posting now. */
  publishAt?: Date | null;
  media?: PreviewMedia[];
}

/** A draft that has no manifest yet, in the shape the templates read. */
export function previewFromDraft(draft: DraftPreviewInput & { publishAt: Date; timeZone: string; avatarUrl?: string }): PreviewPost {
  const channel = channelByPlatform(draft.platform);
  return {
    channel: channel?.slug ?? draft.platform.toLowerCase().replace(/\s+/g, '-'),
    channelName: channel?.name ?? draft.platform,
    account: draft.account,
    avatarUrl: draft.avatarUrl,
    text: draft.text,
    media: draft.media ?? [],
    publishAt: draft.publishAt,
    timeZone: draft.timeZone
  };
}

/** A draft drawn inside its destination app while it is still being written. Renders nothing on the server. */
export function DraftPreview({ scale, className, ...draft }: DraftPreviewInput & { scale?: number; className?: string }) {
  const timeZone = useLocalTimeZone();
  // Without a planned time the phone shows the moment the preview opened; it does not tick.
  const [openedAt] = useState(() => new Date());
  const avatarUrl = useAccountPicture(draft.channelId);
  if (!timeZone) return null;
  const post = previewFromDraft({ ...draft, publishAt: draft.publishAt ?? openedAt, timeZone, avatarUrl });
  return <PostPreview post={post} scale={scale} className={className} />;
}
