'use client';

import { useMemo } from 'react';
import { useModels } from '@/lib/api/hooks';
import { draftableFrom } from '@/lib/creation/capabilities';

/** Platforms Rafii can draft for now (creation facet; the original five while it loads or if it is unavailable). */
export function useDraftPlatforms(): string[] {
  const models = useModels();
  const creation = models.data?.creation;
  return useMemo(() => draftableFrom(creation), [creation]);
}
