'use client';

import { useQueries } from '@tanstack/react-query';
import { channelByPlatform } from '@/config/channels';
import type { Manifest } from '@/lib/api/types';
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
  const channel = channelByPlatform(manifest.platform);
  const avatarUrl = useAccountPicture(manifest.channelId);

  return {
    channel: channel?.slug ?? manifest.platform.toLowerCase().replace(/\s+/g, '-'),
    channelName: channel?.name ?? manifest.platform,
    account: manifest.account,
    avatarUrl,
    text: manifest.payload.text,
    media: assets.map((asset, index) => {
      const result = loaded[index];
      return {
        id: asset.id,
        kind: mediaKind(asset.mime),
        url: result?.data,
        alt: asset.alt,
        width: asset.width,
        height: asset.height,
        status: result?.isError ? 'error' : result?.data ? 'ready' : 'loading'
      };
    }),
    publishAt: new Date(manifest.timing.utc),
    timeZone
  };
}
