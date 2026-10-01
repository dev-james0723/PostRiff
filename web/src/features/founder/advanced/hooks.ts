'use client';

import { useQuery } from '@tanstack/react-query';
import { founderFetch } from '@/lib/founder/api';
import { useFounderScope } from '../customers/kit/api';
import type { EvidenceEnvelope, SnapshotsEnvelope } from './types';

/**
 * Local reads for Advanced → Engineering (CONTRACTS §8.D). Engineering evidence is Live data behind `engineering.read`:
 * Demo and operators without the capability never ask, so the tab cannot cause a 4xx on load. Both are plain GETs;
 * nothing here dispatches, re-runs or writes.
 */
function useEngineeringAllowed(): boolean {
  const scope = useFounderScope();
  return scope.ready && scope.mode === 'live' && scope.capabilities.includes('engineering.read');
}

/** `GET /engineering`: the latest 200 evidence rows (kind, provider, exact SHA, conclusion, attested, required, observed). */
export function useEngineeringEvidence() {
  const scope = useFounderScope();
  const allowed = useEngineeringAllowed();
  return useQuery({
    queryKey: scope.key('engineering', 'evidence'),
    enabled: allowed,
    retry: false,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const result = await founderFetch<EvidenceEnvelope>('/engineering', { signal });
      return { ...result, evidence: Array.isArray(result.data?.evidence) ? result.data.evidence : [] };
    }
  });
}

/** `GET /engineering/checks`: captured required-check manifests (exact SHA → how many checks are required). */
export function useCheckSnapshots() {
  const scope = useFounderScope();
  const allowed = useEngineeringAllowed();
  return useQuery({
    queryKey: scope.key('engineering', 'snapshots'),
    enabled: allowed,
    retry: false,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const result = await founderFetch<SnapshotsEnvelope>('/engineering/checks', { signal });
      return { ...result, snapshots: Array.isArray(result.data?.snapshots) ? result.data.snapshots : [] };
    }
  });
}
