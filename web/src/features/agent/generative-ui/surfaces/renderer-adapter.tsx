'use client';

/**
 * The single mount point of lane C's `RafiiGenerativeMessage` (D-A29) for every F surface. F never renders OpenUI source
 * itself: until C's renderer module is wired here, an accepted view renders nothing extra (the native answer above is complete
 * and every native control still works), and a streaming preview shows only the native progress line.
 */
import type { ReactNode } from 'react';
import type { UiArtifactV1, UiSurface } from '@/lib/agent-runtime/ui-contracts';
import type { ContinueRequest, UiTransport } from '@/features/agent/generative-ui/bridges/types';
import type { ArtifactRender } from '../state/artifact-machine';

export interface GeneratedRendererProps {
  render: ArtifactRender;
  transport: UiTransport;
  surface: UiSurface;
  onContinue: (request: ContinueRequest) => void;
  /** The native answer (text, warnings, proposals) — rendered by the native layer, passed for context only. */
  nativeResult?: ReactNode;
}

export function GeneratedRenderer({ render }: GeneratedRendererProps): ReactNode {
  if (render.mode !== 'generated' && render.mode !== 'preview') return null;
  const artifact: UiArtifactV1 | null = render.artifact;
  return <div data-rafii-renderer='pending' data-revision={artifact?.revision ?? 0} hidden />;
}
