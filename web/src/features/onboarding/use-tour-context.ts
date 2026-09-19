'use client';

import { useQuery } from '@tanstack/react-query';
import { useWorkspace } from '@/lib/workspace/provider';
import type { Usage } from '@/lib/api/types';
import { keys } from '@/lib/api/hooks';
import { useMemo } from 'react';
import { useChannels, useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { TourCtx } from './tours';

/**
 * The real workspace facts a tour reads: which steps apply, and what each step may claim.
 * A fact the API could not return is `null`, never 0, so a step's copy can say something
 * true without it ("each dot shows an account's state") instead of "nothing is connected".
 * `settled` turns true once every query has answered, successfully or not; tours wait for it.
 */
export function useTourContext(): { ctx: TourCtx; ready: boolean } {
  const { workspaceId, api } = useWorkspace();
  // Observe an existing usage result; tours must not cause a billing write transaction on every page.
  const usage = useQuery<Usage>({ queryKey: keys.usage(workspaceId ?? ''), queryFn: () => api.usage(workspaceId as string), enabled: false });
  const snapshot = useSnapshot();
  const channels = useChannels();
  const access = useWorkspaceAccess();
  const state = snapshot.data?.state;
  const snapshotReady = Boolean(snapshot.data);
  const settled = !snapshot.isLoading && !channels.isLoading;

  const ctx = useMemo<TourCtx>(() => {
    const channelCount = channels.data
      ? channels.data.channels.length
      : snapshotReady && state?.phase2
        ? (state.phase2.channels ?? []).length
        : null;
    return {
      settled,
      isOwner: checkAccess(access, { permission: 'owner' }),
      portalAvailable: usage.data?.billing?.portalAvailable ?? null,
      hasVoice: snapshotReady ? Boolean(state?.speaker?.activeRevision) : null,
      voiceRevision: state?.speaker?.activeRevision ?? null,
      channelCount,
      draftCount: snapshotReady ? (state?.variants ?? []).length : null,
      jobCount: snapshotReady && state?.phase2 ? (state.phase2.jobs ?? []).length : null,
      needsReview: snapshotReady && state?.phase2 ? (state.phase2.reviews ?? []).filter((r) => r.status === 'needs_review').length : null,
      assetCount: snapshotReady && state?.phase2 ? (state.phase2.assets ?? []).filter((a) => !a.deleted).length : null,
      canApprove: checkAccess(access, { permission: 'approve' }),
      canEdit: checkAccess(access, { permission: 'edit' }),
      canManageConnections: checkAccess(access, { permission: 'manage_connections' }),
      canReply: checkAccess(access, { permission: 'reply' })
    };
  }, [settled, snapshotReady, state, channels.data, access, usage.data]);

  return { ctx, ready: settled };
}
