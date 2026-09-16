'use client';

import { useLocalTimeZone } from '@/hooks/use-local-time-zone';
import type { Manifest } from '@/lib/api/types';
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
  if (!zone) return null;
  return <ResolvedPreview manifest={manifest} timeZone={zone} scale={scale} className={className} />;
}

function ResolvedPreview({ manifest, timeZone, scale, className }: ManifestPreviewProps & { timeZone: string }) {
  const post = usePreviewPost(manifest, timeZone);
  return <PostPreview post={post} scale={scale} className={className} />;
}
