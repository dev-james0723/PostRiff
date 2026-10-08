'use client';

/**
 * The single mount point of lane C's `RafiiGenerativeMessage` (D-A29) for every F surface, loaded lazily so answers without a
 * generated view never download the renderer, OpenUI or the component library (D14). F never renders OpenUI source itself:
 * C's component draws the canonical source (or the untrusted preview while a first generation streams), owns the frame
 * markers `[data-rafii-generated][data-artifact-id][data-generation-state]`, the native status line, the dirty-field warning
 * and the action confirmation; F supplies the transport, the render model, the status line and the view-state bridge.
 */
import dynamic from 'next/dynamic';
import type { ReactNode } from 'react';
import type { UiPublicManifestV1, UiSurface } from '@/lib/agent-runtime/ui-contracts';
import type { ContinueRequest, UiTransport } from '@/features/agent/generative-ui/bridges/types';
import assets from '../generated/openui-assets.json';
import type { ArtifactRender, UiArtifactViewV1 } from '../state/artifact-machine';

const RafiiGenerativeMessage = dynamic(() => import('../renderer').then((module) => module.RafiiGenerativeMessage), { ssr: false, loading: () => null });

type LibraryName = 'consumer' | 'founder';

/** Library hashes this build renders (same rule as C's `supportedLibraryHashes`, read from the generated assets directly). */
export function bundledLibraryHashes(name: LibraryName): string[] {
  const entry = (assets.libraries as Record<string, { libraryHash?: string; compatibleLibraryHashes?: string[] }>)[name];
  return entry?.libraryHash ? [entry.libraryHash, ...(entry.compatibleLibraryHashes ?? [])] : [];
}

export interface GeneratedRendererProps {
  render: ArtifactRender;
  view: UiArtifactViewV1 | null;
  transport: UiTransport;
  surface: UiSurface;
  status: string | null;
  active: boolean;
  onContinue: (request: ContinueRequest) => void;
  onRetry?: (() => void) | null;
  onExpand?: (() => void) | null;
  onNavigate?: (path: string) => void;
  /** The native answer stays in the native layer above; pass it only where the surface has no other native rendering. */
  nativeResult?: ReactNode;
}

export function GeneratedRenderer({ render, view, transport, surface, status, active, onContinue, onRetry, onExpand, onNavigate, nativeResult }: GeneratedRendererProps): ReactNode {
  const artifact = render.mode === 'generated' ? render.artifact : render.mode === 'preview' ? render.artifact : (view?.artifact ?? null);
  const manifest: UiPublicManifestV1 | null = view?.manifest ?? null;
  return (
    <RafiiGenerativeMessage artifact={artifact} manifest={manifest} render={render} status={status} historical={Boolean(view?.access?.historical)} active={active}
      surface={surface} transport={transport} onContinue={onContinue} onRetry={onRetry ?? null} onExpand={onExpand ?? null} onNavigate={onNavigate}
      nativeResult={nativeResult} />
  );
}
