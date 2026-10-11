'use client';

import { useQueries } from '@tanstack/react-query';
import { channelByPlatform } from '@/config/channels';
import type { Asset, Manifest, RunMedia } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { PreviewMedia, PreviewPost } from './types';
import { useAccountPicture } from './use-account-picture';

function mediaKind(mime: string): PreviewMedia['kind'] {
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('video/')) return 'video';
  return 'file';
}

/**
 * A manifest as the preview templates read it. Media comes from the workspace's private storage through the
 * API, cached under the same key the Library uses.
 */
export function usePreviewPost(manifest: Manifest, timeZone: string): PreviewPost {
  const { api, workspaceId } = useWorkspaceApi();
  const assets = manifest.media.filter((asset) => !asset.deleted);
  const loaded = useQueries({
    queries: assets.map((asset) => ({
      queryKey: ['media', workspaceId, asset.id],
      queryFn: async () => URL.createObjectURL(await api.media(workspaceId, asset.id)),
      staleTime: Infinity
    }))
  });
  const players = useQueries({ queries: assets.map(asset => ({
    queryKey: ['media-url', workspaceId, asset.id],
    queryFn: async () => (await api.mediaUrl(workspaceId, asset.id)).url,
    enabled: asset.mime.startsWith('video/'), staleTime: 5 * 60 * 1000
  })) });
  const channel = channelByPlatform(manifest.platform);
  const avatarUrl = useAccountPicture(manifest.channelId);

  return {
    channel: channel?.slug ?? manifest.platform.toLowerCase().replace(/\s+/g, '-'),
    channelName: channel?.name ?? manifest.platform,
    account: manifest.account,
    avatarUrl,
    text: manifest.platform === 'YouTube' && typeof manifest.publishOptions?.description === 'string' ? manifest.publishOptions.description : manifest.payload.text,
    ...(manifest.platform === 'YouTube' ? { videoTitle: typeof manifest.publishOptions?.title === 'string' ? manifest.publishOptions.title : undefined,
      youtubeMode: manifest.publishOptions?.mode === 'short' ? 'short' as const : 'video' as const } : {}),
    media: assets.map((asset, index) => {
      const result = loaded[index];
      return {
        id: asset.id,
        kind: mediaKind(asset.mime),
        url: asset.mime.startsWith('video/') ? players[index]?.data : result?.data,
        poster: asset.mime.startsWith('video/') ? result?.data : undefined,
        alt: asset.alt,
        width: asset.width,
        height: asset.height,
        status: result?.isError || players[index]?.isError ? 'error' : (asset.mime.startsWith('video/') ? players[index]?.data : result?.data) ? 'ready' : 'loading'
      };
    }),
    publishAt: new Date(manifest.timing.utc),
    timeZone
  };
}

/**
 * A run's post media as preview media (chat-context SPEC §5.10): photos load through the private media route; a video
 * shows its poster (the same route serves a video's poster) and plays from a short-lived signed URL.
 */
export function useRunPreviewMedia(media: readonly RunMedia[] | null | undefined, assets?: readonly Asset[]): PreviewMedia[] {
  const { api, workspaceId } = useWorkspaceApi();
  // Without the Library at hand the run's own record is trusted for display; the server re-checks at scheduling.
  const items = (media ?? []).filter((item) => item.role === 'post' && (!assets || assets.some((asset) => asset.id === item.assetId && !asset.deleted)));
  const posters = useQueries({
    queries: items.map((item) => ({
      queryKey: ['media', workspaceId, item.assetId],
      queryFn: async () => URL.createObjectURL(await api.media(workspaceId, item.assetId)),
      staleTime: Infinity
    }))
  });
  const players = useQueries({
    queries: items.map((item) => ({
      queryKey: ['media-url', workspaceId, item.assetId],
      queryFn: async () => (await api.mediaUrl(workspaceId, item.assetId)).url,
      enabled: item.kind === 'video',
      staleTime: 5 * 60 * 1000
    }))
  });
  return items.map((item, index) => {
    const asset = assets?.find((candidate) => candidate.id === item.assetId);
    const video = item.kind === 'video';
    const url = video ? players[index]?.data : posters[index]?.data;
    const failed = video ? players[index]?.isError : posters[index]?.isError;
    return {
      id: item.assetId,
      kind: video ? 'video' : 'image',
      url,
      poster: video ? posters[index]?.data : undefined,
      alt: `${video ? 'Video' : 'Photo'} ${item.slot}`,
      width: asset?.width,
      height: asset?.height,
      status: failed ? 'error' : url ? 'ready' : 'loading'
    };
  });
}
