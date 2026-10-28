'use client';

import { usePreferences } from '@/lib/preferences';
import { discordCopy, discordSenderLabel } from '@/lib/channels/discord-copy';
import { botNicknameView } from '@/lib/channels/discord-sender-name';
import { DiscordMessagePreview } from '@/features/channels/discord-message-preview';
import { cn } from '@/lib/utils';
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
  const { locale } = usePreferences();
  const copy = discordCopy(locale);
  const destination = manifest.discord?.target;
  const webhook = manifest.senderKind === 'webhook';
  const botNickname = botNicknameView(manifest.discordBotNickname, 'manifest');
  const discordMedia = post.media.flatMap((item) => (item.kind === 'image' && item.status === 'ready' && item.url ? [{ url: item.url, alt: item.alt }] : []));
  return <>
    {manifest.platform === 'Discord' && <p className='text-muted-foreground mb-2 text-sm' data-discord-sender>
      {discordSenderLabel(copy, manifest.senderKind, manifest.discordSenderName)}<br />{copy.senderNotice}
    </p>}
    {manifest.platform === 'Discord' && <p className='text-muted-foreground mb-2 text-xs' data-discord-frozen-target>
      {destination ? `Frozen target: ${destination.guildName} (${destination.guildId}) · ${destination.channelName} (${destination.channelId})` : 'Legacy Discord approval: a new server and channel preview is required before publication.'}
    </p>}
    {manifest.platform === 'Discord' ? (
      // Drawn as Discord lays out a message, with the APP tag and the sender the post will really show. A bot's name is
      // its shared server nickname: Discord cannot freeze it per post, so the approval records the nickname that was
      // shown and the post is held if Discord shows another one when it is due (nothing recorded: nothing is claimed).
      <DiscordMessagePreview
        kind={webhook ? 'webhook' : 'bot'}
        name={webhook ? manifest.discordSenderName ?? null : botNickname.name}
        nameSource={webhook ? (manifest.discordSenderName ? 'saved' : 'unknown') : botNickname.source}
        botHold={webhook ? undefined : botNickname.hold}
        text={manifest.payload.text}
        publishAt={post.publishAt}
        timeZone={timeZone}
        media={discordMedia}
        copy={copy}
        locale={locale}
        heading={copy.previewHeading}
        headingLevel='h4'
        compact
        className={cn('w-full max-w-[22rem]', className)}
      />
    ) : (
      <PostPreview post={post} scale={scale} className={className} />
    )}
  </>;
}
