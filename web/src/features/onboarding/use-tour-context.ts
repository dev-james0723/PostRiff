'use client';

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
      hasVoice: snapshotReady ? Boolean(state?.speaker?.activeRevision) : null,
      voiceRevision: state?.speaker?.activeRevision ?? null,
      channelCount,
      draftCount: snapshotReady ? (state?.variants ?? []).length : null,
      jobCount: snapshotReady && state?.phase2 ? (state.phase2.jobs ?? []).length : null,
      needsReview: snapshotReady && state?.phase2 ? (state.phase2.reviews ?? []).filter((r) => r.status === 'needs_review').length : null,
      canEdit: checkAccess(access, { permission: 'edit' }),
      canManageConnections: checkAccess(access, { permission: 'manage_connections' }),
      canReply: checkAccess(access, { permission: 'reply' })
    };
  }, [settled, snapshotReady, state, channels.data, access]);

  return { ctx, ready: settled };
}
