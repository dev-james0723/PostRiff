'use client';
/**
 * J03 — Universal Library (lane E): search results, one item with its text excerpt and consent, lineage, and the check
 * of a selection for the next drafting message — all from lane D's Library bindings over the production Library.
 *
 * Privacy: rows carry ids and an authenticated preview route, never a signed URL; this view fetches no bytes itself
 * (previews come from lane C's AssetPreview when available, otherwise a type cover). Selecting files only selects them:
 * photos travel as attachment chips and documents as source references on the person's next message, where the turn's
 * own consent checks apply. "Use as source" imports a document as a source that still needs review.
 */
import { z } from 'zod';
import { cn } from '@/lib/utils';
import { formatBytes, formatInstant } from '../../journeys/format';
import { useBound, useJourneyEnvironment, useSelectionRecorder } from '../../journeys/runtime';
import type { LibraryRow } from '../../journeys/views';
import { AssetPreviewView } from '../primitives/asset-preview';
import { InAppLink, GuardedAction, Missing, Pager, Pill, QueryFrame, SelectToggle, toggleInOrder } from './shared';
import type { JourneyRendererProps } from './types';

/** library_selection accepts at most 4 items for one message. */
export const MAX_SELECTED_ASSETS = 4;
const titleProps = z.object({ title: z.string().max(120).optional() });

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string' && /^[0-9a-f]{32}$/.test(v)) : [];
}

/** Preview through lane C's AssetPreviewView: only this workspace's own preview routes, never a signed URL. */
export function AssetCover({ row, size = 'card' }: { row: LibraryRow; size?: 'row' | 'card' | 'detail' }) {
  // The card prints the title itself; the preview keeps it only as the image's alternative text.
  return <AssetPreviewView item={{ ...row, alt: row.alt ?? row.title ?? null, title: null }} size={size} />;
}

function RowFlags({ row }: { row: LibraryRow }) {
  const { copy } = useJourneyEnvironment();
  const processing = [row.processing, row.indexingStatus, row.transcriptionStatus].some((s) => s && !['ready', 'done', 'complete', 'completed', 'indexed', 'not_needed'].includes(s));
  return (
    <span className='flex flex-wrap gap-1'>
      {row.hasSource ? <Pill tone='good'>{copy.library.alreadySource}</Pill> : null}
      {row.duplicateOf ? <Pill tone='muted'>{copy.library.duplicate}</Pill> : null}
      {row.extractionProblem ? <Pill tone='attention'>{copy.library.extractionProblem}</Pill> : null}
      {processing ? <Pill tone='waiting'>{copy.library.processing}</Pill> : null}
    </span>
  );
}

function refType(row: LibraryRow): string {
  return row.store === 'file' ? 'library_file' : 'media';
}

export function LibraryBrowser({ props, statementId }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  const literal = titleProps.safeParse(props);
  const selection = useBound<string[]>(`${statementId ?? 'library'}Selected`, props.selected);
  const selected = strings(selection.value);
  const record = useSelectionRecorder(statementId ?? 'library');
  return (
    <QueryFrame value={props.data} binding='library_search' label={copy.library.title} title={literal.success ? literal.data.title : null}>
      {(data, result) => {
        const toggle = (row: LibraryRow) => {
          const next = toggleInOrder(selected, row.assetId, MAX_SELECTED_ASSETS);
          selection.set(next);
          const byId = new Map(data.items.map((r) => [r.assetId, r]));
          record(
            next.map((id) => ({ type: refType(byId.get(id) as LibraryRow), id, title: byId.get(id)?.title ?? undefined })).filter((r) => byId.has(r.id)),
            data.items.map((r) => ({ type: refType(r), id: r.assetId })),
          );
        };
        return (
          <div className='@container flex flex-col gap-2'>
            <p className='text-muted-foreground text-xs' role={selected.length ? 'status' : undefined}>
              {selected.length ? `${copy.common.selected(selected.length)} · ` : ''}
              {copy.library.pickUpTo(MAX_SELECTED_ASSETS)}
            </p>
            <ul className='grid grid-cols-1 gap-2 @[26rem]:grid-cols-2 @[44rem]:grid-cols-3'>
              {data.items.map((row) => {
                const isSelected = selected.includes(row.assetId);
                return (
                  <li key={row.ref} className={cn('flex flex-col gap-1.5 rounded-[var(--rafii-radius-card)] border p-2', isSelected && 'ring-primary ring-2')}>
                    <AssetCover row={row} />
                    <div className='flex items-start gap-2'>
                      <SelectToggle
                        selected={isSelected}
                        label={row.title ?? copy.library.kind[row.kind ?? 'file'] ?? row.assetId}
                        disabled={!isSelected && selected.length >= MAX_SELECTED_ASSETS}
                        onToggle={() => toggle(row)}
                      />
                      <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
                        <span className='text-sm font-medium break-words' dir='auto'>
                          {row.title ?? <Missing />}
                        </span>
                        <span className='text-muted-foreground text-xs'>
                          {[copy.library.kind[row.kind ?? ''] ?? row.kind, formatBytes(row.bytes, locale), formatInstant(row.createdAt, timeZone, locale, null, { dateOnly: true, withZone: false })]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                        {row.tags && row.tags.length > 0 ? <span className='text-muted-foreground text-xs'>{row.tags.slice(0, 6).join(', ')}</span> : null}
                        <RowFlags row={row} />
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
            <Pager
              result={result}
              cursor={props.cursor}
              statementId={statementId}
              fallback={
                <InAppLink href='/app/library'>
                  {copy.common.more} · {copy.library.open}
                </InAppLink>
              }
            />
            {selected.length ? <p className='text-muted-foreground text-xs'>{copy.common.selectionHint}</p> : null}
          </div>
        );
      }}
    </QueryFrame>
  );
}

const cardProps = z.object({ actionId: z.literal('library_use_as_source').optional().nullable() });

export function LibraryAssetCard({ props, statementId }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  const literal = cardProps.safeParse(props);
  const actionId = literal.success ? literal.data.actionId ?? undefined : undefined;
  return (
    <QueryFrame value={props.data} binding='library_item' label={copy.library.title}>
      {(item) => (
        <article className='flex flex-col gap-2 rounded-[var(--rafii-radius-card)] border p-3'>
          <div className='grid gap-3 @[28rem]:grid-cols-[10rem_1fr]'>
            <AssetCover row={item} size='detail' />
            <div className='flex min-w-0 flex-col gap-1'>
              <h4 className='text-sm font-semibold break-words' dir='auto'>
                {item.title ?? <Missing />}
              </h4>
              <span className='text-muted-foreground text-xs'>
                {[copy.library.kind[item.kind ?? ''] ?? item.kind, item.mime, formatBytes(item.bytes, locale), formatInstant(item.createdAt, timeZone, locale)].filter(Boolean).join(' · ')}
              </span>
              <RowFlags row={item} />
              {item.summary ? (
                <p className='text-sm' dir='auto'>
                  {item.summary}
                </p>
              ) : null}
              {item.store === 'media' && item.mediaConsent ? (
                <p className='text-muted-foreground text-xs'>{item.mediaConsent.modelMayView ? copy.library.modelMayView : copy.library.modelMayNotView}</p>
              ) : null}
              {item.href ? (
                <InAppLink href={item.href}>
                  {copy.library.open}
                </InAppLink>
              ) : null}
            </div>
          </div>
          {item.excerpt ? (
            <details className='text-sm'>
              <summary className='text-muted-foreground cursor-pointer text-xs'>
                {copy.library.excerptTitle}
                {typeof item.chunkCount === 'number' ? ` · ${copy.library.chunks(item.chunkCount)}` : ''}
              </summary>
              <p className='mt-1 whitespace-pre-wrap break-words' dir='auto'>
                {item.excerpt}
                {item.excerptTruncated ? '…' : ''}
              </p>
            </details>
          ) : null}
          {actionId && item.store === 'file' && !item.hasSource ? (
            <>
              <p className='text-muted-foreground text-xs'>{copy.library.useAsSourceHint}</p>
              <GuardedAction actionId={actionId} controlId={statementId} ready={Boolean(item.excerpt)} inputs={{ assetId: item.assetId }} />
            </>
          ) : null}
        </article>
      )}
    </QueryFrame>
  );
}

export function LibraryLineage({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='library_lineage' label={copy.library.lineageTitle} title={copy.library.lineageTitle}>
      {(data) => (
        <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
          {data.edges.map((edge) => (
            <li key={`${edge.relation ?? edge.edge}:${edge.type}:${edge.id}`}>
              {(edge.relation ?? edge.edge ?? '').replaceAll('_', ' ')} · {edge.type}
              {edge.title ? ` · ${edge.title}` : ''}
              {edge.via ? <span className='opacity-70'> ({edge.via})</span> : null}
            </li>
          ))}
        </ul>
      )}
    </QueryFrame>
  );
}

export function LibrarySelectionCheck({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame
      value={props.data}
      binding='library_selection'
      label={copy.library.selectionTitle}
      title={copy.library.selectionTitle}
      empty={(result) => <p className='text-muted-foreground text-xs'>{result.coverage.note ?? copy.library.pickUpTo(MAX_SELECTED_ASSETS)}</p>}
    >
      {(data) => (
        <div className='flex flex-col gap-1.5 text-sm'>
          <p className='flex flex-wrap gap-2'>
            <Pill tone='neutral'>{copy.library.attachments(data.attachments.length)}</Pill>
            <Pill tone='neutral'>{copy.library.references(data.references.length)}</Pill>
          </p>
          {data.refused.length > 0 ? (
            <ul className='text-muted-foreground text-xs'>
              {data.refused.map((r) => (
                <li key={r.assetId}>{copy.library.refused[r.reason] ?? r.reason}</li>
              ))}
            </ul>
          ) : null}
          <p className='text-muted-foreground text-xs'>{copy.library.sendHint}</p>
        </div>
      )}
    </QueryFrame>
  );
}
