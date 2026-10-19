'use client';

import { useLocalTimeZone } from '@/hooks/use-local-time-zone';
import type { Manifest } from '@/lib/api/types';
import { MastodonPollDetails } from '@/features/queue/mastodon-poll-details';
import { PostPreview } from './post-preview';
import { usePreviewPost } from './use-preview-post';

interface ManifestPreviewProps {
  manifest: Manifest;
  /** Defaults to this browser's zone; nothing renders until it is known (never on the server). */
  timeZone?: string;
  scale?: number;
  className?: string;
}

/** An approved or pending manifest drawn inside its destination app. */
export function ManifestPreview({ manifest, timeZone, scale, className }: ManifestPreviewProps) {
  const localZone = useLocalTimeZone();
  const zone = timeZone ?? localZone;
  return <div className='flex flex-col gap-2'>
    <MastodonPollDetails manifest={manifest} />
    {zone && <ResolvedPreview manifest={manifest} timeZone={zone} scale={scale} className={className} />}
  </div>;
}

function ResolvedPreview({ manifest, timeZone, scale, className }: ManifestPreviewProps & { timeZone: string }) {
  const post = usePreviewPost(manifest, timeZone);
  const destination = manifest.discord?.target;
  return <>
    {manifest.platform === 'Discord' && <p className='text-muted-foreground mb-2 text-xs' data-discord-frozen-target>
      {destination ? `Frozen target: ${destination.guildName} (${destination.guildId}) · ${destination.channelName} (${destination.channelId})` : 'Legacy Discord approval: a new server and channel preview is required before publication.'}
    </p>}
    <PostPreview post={post} scale={scale} className={className} />
  </>;
}
