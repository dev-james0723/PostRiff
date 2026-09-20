'use client';

import { useQuery } from '@tanstack/react-query';
import { useChannels } from '@/lib/api/hooks';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/**
 * The connected account's profile picture as an object URL, when PostRiff stored one at connect or re-verify.
 * Undefined for accounts without one (every channel not connected through OAuth): previews then draw a monogram.
 */
export function useAccountPicture(channelId: string | undefined) {
  const { api, workspaceId } = useWorkspaceApi();
  const channels = useChannels();
  const digest = channelId ? channels.data?.channels.find((channel) => channel.id === channelId)?.pictureDigest : undefined;
  const picture = useQuery({
    queryKey: ['channel-picture', workspaceId, channelId, digest],
    queryFn: async () => URL.createObjectURL(await api.channelPicture(workspaceId, channelId ?? '', digest ?? '')),
    enabled: Boolean(channelId && digest),
    staleTime: Infinity
  });
  return picture.data;
}
