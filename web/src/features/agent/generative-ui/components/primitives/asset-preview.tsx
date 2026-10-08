'use client';
/**
 * Safe Library previews for generated views: `AssetPreviewView({item, size})` (exported for lane E's Library components)
 * and the `AssetPreview` primitive that wraps it.
 *
 * `item` is one bound Library row from lane D (`ui_domain/library.py`): {previewKind, previewRoute, title, mime?,
 * extension?, kind?, href?, alt?}. A preview is fetched ONLY through the existing authenticated route named by
 * `previewRoute` (an `/api/workspaces/{this workspace}/…` path; anything else is refused), with the message's transport
 * adding the person's auth. Media bytes become a short-lived blob URL; a JSON answer ({url}) is accepted only when the
 * returned URL is https or same-origin. URLs inside `item` are never used as sources. Nothing loads before the view is
 * server-accepted, while it is off screen, or after it unmounts (requests are aborted). Failures show a kind/extension
 * cover, never a broken image.
 */
import { type JSX, type RefObject, useEffect, useRef, useState } from 'react';
import { z } from 'zod';
import { cn } from '@/lib/utils';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { useGenUiLocale } from '../../core/locale';
import { safeProps } from '../../core/props';
import { useGenUiRuntime } from '../../core/runtime-context';
import { Unrenderable } from './shared';

export type AssetPreviewSize = 'row' | 'card' | 'detail';
export const PREVIEW_KINDS = ['image', 'video_poster', 'pdf_page', 'document_cover', 'server_page', 'audio_cover', 'file_cover'] as const;
export type PreviewKind = (typeof PREVIEW_KINDS)[number];

export interface AssetPreviewItem {
  previewKind?: PreviewKind | null;
  previewRoute?: string | null;
  title?: string | null;
  mime?: string | null;
  extension?: string | null;
  kind?: string | null;
  alt?: string | null;
}

const ROUTE = /^\/api\/workspaces\/[A-Za-z0-9_-]{1,80}\/(media\/[A-Za-z0-9_.:-]{1,128}(\/url)?|library\/files\/[A-Za-z0-9_.:-]{1,128}\/(preview|url))$/;
const MAX_BLOB_BYTES = 25 * 1024 * 1024;

/** The route is one of the existing preview routes of the workspace this message belongs to. */
export function previewRouteAllowed(route: unknown, workspacePrefix: string | null): route is string {
  if (typeof route !== 'string' || !ROUTE.test(route)) return false;
  return !workspacePrefix || route.startsWith(`${workspacePrefix}/`);
}

/** A URL returned by a preview route: https, or a same-origin path. */
export function previewUrlAllowed(url: unknown, origin: string | null): url is string {
  if (typeof url !== 'string' || url.length > 4096) return false;
  if (url.startsWith('/') && !url.startsWith('//')) return true;
  try {
    const parsed = new URL(url);
    if (parsed.username || parsed.password) return false;
    return parsed.protocol === 'https:' || (origin !== null && parsed.origin === origin);
  } catch {
    return false;
  }
}

function extensionOf(item: AssetPreviewItem): string {
  const ext = typeof item.extension === 'string' && item.extension ? item.extension : typeof item.mime === 'string' ? item.mime.split('/').pop() ?? '' : '';
  return ext.replace(/[^A-Za-z0-9]/g, '').slice(0, 6).toUpperCase();
}

/** What to fetch for a kind: images and rendered pages show as images, video posters as a paused video; others are covers. */
function fetchPlan(kind: PreviewKind | null | undefined, route: string): { path: string; as: 'image' | 'video' } | null {
  if (kind === 'image') return { path: route, as: 'image' };
  if (kind === 'server_page') return { path: route, as: 'image' };
  if (kind === 'video_poster') return { path: /\/media\/[^/]+$/.test(route) ? `${route}/url` : route, as: 'video' };
  return null;
}

const SIZE: Record<AssetPreviewSize, string> = {
  row: 'size-12 shrink-0 rounded-md',
  card: 'aspect-[4/3] w-full rounded-[var(--rafii-radius-card,0.875rem)]',
  detail: 'aspect-[4/3] w-full max-h-[60vh] rounded-[var(--rafii-radius-card,0.875rem)]',
};

function Cover(props: { item: AssetPreviewItem; size: AssetPreviewSize; state: 'cover' | 'loading' | 'failed' }): JSX.Element {
  const l = useGenUiLocale();
  const ext = extensionOf(props.item);
  return (
    <div
      data-genui-preview={props.state}
      className={cn('flex flex-col items-center justify-center gap-1 overflow-hidden bg-muted/60 text-muted-foreground', SIZE[props.size], props.state === 'loading' && 't-skel-pulse')}
    >
      <span aria-hidden="true" className={cn('font-semibold tracking-wide', props.size === 'row' ? 'text-[9px]' : 'text-xs')}>
        {ext || '•'}
      </span>
      {props.size !== 'row' && props.state === 'failed' ? <span className="text-[11px]">{l.t('previewUnavailable')}</span> : null}
    </div>
  );
}

/** Lazy: true once the element has been near the viewport (no IntersectionObserver → immediately). */
function useNearViewport<T extends Element>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    if (near) return;
    const element = ref.current;
    if (!element || typeof IntersectionObserver === 'undefined') {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setNear(true);
    }, { rootMargin: '200px' });
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);
  return [ref, near];
}

export function AssetPreviewView(props: { item: AssetPreviewItem; size?: AssetPreviewSize; className?: string }): JSX.Element {
  const size = props.size ?? 'card';
  const runtime = useGenUiRuntime();
  const l = useGenUiLocale();
  const [ref, near] = useNearViewport<HTMLDivElement>();
  const [loaded, setLoaded] = useState<{ url: string; as: 'image' | 'video'; revoke: boolean } | null>(null);
  const [failed, setFailed] = useState(false);
  const route = props.item.previewRoute;
  const kind = props.item.previewKind;
  const title = typeof props.item.title === 'string' && props.item.title ? props.item.title : '';
  // The route shape is checked here; the renderer's fetchPreview also refuses any path outside this message's workspace.
  const plan = runtime.fetchPreview && previewRouteAllowed(route, null) ? fetchPlan(kind, route) : null;

  useEffect(() => {
    if (!plan || !near || !runtime.fetchPreview || !runtime.accepted) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setFailed(false);
    (async () => {
      try {
        const response = await runtime.fetchPreview!(plan.path, controller.signal);
        if (!response.ok) throw new Error('preview_status');
        const type = response.headers.get('content-type') ?? '';
        if (type.includes('application/json')) {
          const body = (await response.json()) as { url?: unknown };
          const origin = typeof window !== 'undefined' ? window.location.origin : null;
          if (!previewUrlAllowed(body?.url, origin)) throw new Error('preview_url');
          if (!controller.signal.aborted) setLoaded({ url: body.url as string, as: plan.as, revoke: false });
          return;
        }
        if (!/^(image|video)\//.test(type)) throw new Error('preview_type');
        const length = Number(response.headers.get('content-length') ?? '0');
        if (length > MAX_BLOB_BYTES) throw new Error('preview_size');
        const blob = await response.blob();
        if (blob.size > MAX_BLOB_BYTES) throw new Error('preview_size');
        objectUrl = URL.createObjectURL(blob);
        if (!controller.signal.aborted) setLoaded({ url: objectUrl, as: type.startsWith('video/') ? 'video' : 'image', revoke: true });
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setLoaded(null);
    };
    // The plan is derived from route + kind; re-run only when those or access change.
  }, [route, kind, near, runtime.fetchPreview, runtime.accepted]); // eslint-disable-line react-hooks/exhaustive-deps

  const alt = typeof props.item.alt === 'string' && props.item.alt ? props.item.alt : title;
  let body: JSX.Element;
  if (loaded && !failed && loaded.as === 'image') {
    body = (
      // eslint-disable-next-line @next/next/no-img-element -- blob/signed preview URLs are not optimizable
      <img
        src={loaded.url}
        alt={alt}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className={cn('object-cover', SIZE[size])}
      />
    );
  } else if (loaded && !failed && loaded.as === 'video') {
    body = (
      <video
        src={loaded.url}
        preload="metadata"
        muted
        playsInline
        controls={size !== 'row'}
        aria-label={alt || undefined}
        onError={() => setFailed(true)}
        className={cn('bg-black object-cover', SIZE[size])}
      />
    );
  } else {
    body = <Cover item={props.item} size={size} state={plan && !failed ? 'loading' : failed ? 'failed' : 'cover'} />;
  }
  return (
    <div ref={ref} data-genui-asset-preview={kind ?? 'none'} className={cn('min-w-0', props.className)} title={title || undefined}>
      {body}
      {size !== 'row' && title ? (
        <p dir="auto" className="mt-1 truncate text-xs text-foreground">
          {title}
        </p>
      ) : null}
      {size === 'row' ? <span className="sr-only">{title || l.t('previewUnavailable')}</span> : null}
    </div>
  );
}

const itemSchema = z.object({
  previewKind: z.enum(PREVIEW_KINDS).optional(),
  previewRoute: z.string().max(300).optional(),
  title: z.string().max(300).optional(),
  mime: z.string().max(120).optional(),
  extension: z.string().max(20).optional(),
  kind: z.string().max(40).optional(),
  alt: z.string().max(300).optional(),
});
const previewProps = z.object({ item: z.record(z.string(), z.unknown()), size: z.enum(['row', 'card', 'detail']).optional() });

function cleanItem(raw: Record<string, unknown>): AssetPreviewItem {
  const picked: Record<string, unknown> = {};
  for (const key of ['previewKind', 'previewRoute', 'title', 'mime', 'extension', 'kind', 'alt']) {
    if (typeof raw[key] === 'string') picked[key] = raw[key];
  }
  const parsed = itemSchema.safeParse(picked);
  return parsed.success ? parsed.data : {};
}

export const AssetPreview: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(previewProps, props);
  const runtime = useGenUiRuntime();
  if (!p.ok) return <Unrenderable component="AssetPreview" />;
  const item = runtime.accepted ? cleanItem(p.value.item) : {};
  return (
    <div data-genui="AssetPreview" data-statement-id={statementId} className={p.value.size === 'row' ? 'inline-flex' : 'block'}>
      <AssetPreviewView item={item} size={p.value.size ?? 'card'} />
    </div>
  );
};
