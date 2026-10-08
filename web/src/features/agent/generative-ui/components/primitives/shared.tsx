'use client';
/**
 * Shared pieces of Rafii's generated-view primitives (lane C; lane E may use them in journey components).
 *
 *   <Children value={props.children} renderNode={renderNode} />  children keyed by statement id (never by array index
 *                                                                 alone), so inserting a statement keeps focus/selection
 *   <QueryStateNote view={readQuery(...)} />                      honest loading / waiting / empty / denied / unavailable /
 *                                                                 partial / stale notes (never a fake zero or empty list)
 *   <SourceMeta view={...} />                                     as-of time and coverage of bound data
 *   <Unrenderable />                                              quiet "this part can't be shown" (invalid props)
 */
import { Fragment, type JSX, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { useGenUiLocale } from '../../core/locale';
import { childKey } from '../../core/props';
import type { QueryView } from '../../core/query-data';

export function Children(props: { value: unknown; renderNode: (value: unknown) => ReactNode }): JSX.Element {
  const list = Array.isArray(props.value) ? props.value : props.value === null || props.value === undefined ? [] : [props.value];
  return (
    <>
      {list.map((child, index) => (
        <Fragment key={childKey(child, index)}>{props.renderNode(child)}</Fragment>
      ))}
    </>
  );
}

export function Unrenderable(props: { component?: string }): JSX.Element {
  const l = useGenUiLocale();
  return (
    <p className="text-xs text-muted-foreground" data-genui-invalid={props.component ?? ''}>
      {l.t('unknownComponent')}
    </p>
  );
}

/** Placeholder rows while a read is in flight; announced once by the message-level status, not per row. */
export function LoadingRows(props: { rows?: number; label?: string }): JSX.Element {
  const l = useGenUiLocale();
  const count = Math.max(1, Math.min(props.rows ?? 3, 6));
  return (
    <div className="grid gap-2" aria-busy="true">
      <span className="sr-only">{props.label ?? l.t('loading')}</span>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} aria-hidden="true" className="t-skel-pulse h-4 rounded-md bg-muted" style={{ width: `${92 - index * 14}%` }} />
      ))}
    </div>
  );
}

/** Notes for every non-data state, and for partial/stale data shown with a caveat. Returns null when data is complete. */
export function QueryStateNote(props: { view: QueryView; rows?: number; emptyText?: string }): JSX.Element | null {
  const l = useGenUiLocale();
  const { view } = props;
  switch (view.state) {
    case 'loading':
      return <LoadingRows rows={props.rows} />;
    case 'waiting':
      return <LoadingRows rows={props.rows} label={l.t('waitingForData')} />;
    case 'empty':
      return <p className="text-sm text-muted-foreground">{props.emptyText ?? l.t('empty')}</p>;
    case 'denied':
      return <p className="text-sm text-muted-foreground">{l.t('denied')}</p>;
    case 'unavailable':
      return <p className="text-sm text-muted-foreground">{l.t('unavailable')}</p>;
    case 'partial':
      return <p className="text-xs text-muted-foreground">{l.t('partial')}</p>;
    case 'stale':
      return <p className="text-xs text-muted-foreground">{l.t('stale')}</p>;
    default:
      return null;
  }
}

export function SourceMeta(props: { view: QueryView; className?: string }): JSX.Element | null {
  const l = useGenUiLocale();
  const { view } = props;
  if (!view.genuine) return null;
  const parts: string[] = [];
  if (view.asOf) parts.push(l.t('asOf', { time: l.formatDateTime(view.asOf) }));
  const known = view.coverage?.known;
  const total = view.coverage?.total;
  if (typeof known === 'number' && typeof total === 'number' && total > 0 && known < total) {
    parts.push(l.t('coverage', { known: l.formatNumber(known), total: l.formatNumber(total) }));
  }
  if (view.coverage?.note) parts.push(view.coverage.note);
  if (!parts.length) return null;
  return <p className={cn('text-xs text-muted-foreground', props.className)}>{parts.join(' · ')}</p>;
}

/** Status words exactly as the data says them, made readable ("needs_review" → "needs review"). */
export function statusText(value: unknown): string {
  if (typeof value !== 'string' || !value) return '';
  return value.replace(/[_-]+/g, ' ').trim();
}

const POSITIVE = new Set(['published', 'scheduled', 'saved', 'applied', 'done', 'complete', 'completed', 'active', 'connected', 'available', 'ok', 'healthy', 'trained', 'learned', 'approved']);
const NEGATIVE = new Set(['failed', 'error', 'rejected', 'disconnected', 'expired', 'denied', 'blocked', 'canceled', 'cancelled']);

export function StatusBadge(props: { value: unknown }): JSX.Element | null {
  const text = statusText(props.value);
  if (!text) return null;
  const key = text.toLowerCase().replace(/\s+/g, '_');
  const tone = POSITIVE.has(key) ? 'positive' : NEGATIVE.has(key) ? 'negative' : 'neutral';
  return (
    <span
      data-tone={tone}
      className={cn(
        'inline-flex h-5 items-center rounded-full border px-2 text-xs font-medium whitespace-nowrap',
        tone === 'positive' && 'border-transparent bg-emerald-500/12 text-emerald-700 dark:text-emerald-300 [.rafii-chat_&]:text-emerald-300',
        tone === 'negative' && 'border-transparent bg-destructive/12 text-destructive',
        tone === 'neutral' && 'border-border text-muted-foreground',
      )}
    >
      {text}
    </span>
  );
}
