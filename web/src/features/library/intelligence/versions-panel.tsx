'use client';

import { useRef, useState } from 'react';
import Image from 'next/image';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { DialogButton as Button } from '../ui/controls';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import type { AffectedDependent, AssetRef, ComparisonResult, ComparisonSide, VersionStackEntry } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey } from '@/lib/library/batch';
import { assetRefFor, normalizeKey } from '@/lib/library/url-state';
import { comparisonHeadline, diffRows, linkVersionEnvelope, relationLabel, replacementEnvelope, replacementPlan, type ReplacementPlan } from '@/lib/library/versions';
import { formatClock, locatorLabel } from '@/lib/library/wording';
import { formatBytes, formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useAssetImage } from '../asset-card';
import { OriginBadge } from './detail-sections';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
  return String(value);
}

function metadataValue(field: string, value: unknown): string {
  if (field === 'bytes' && typeof value === 'number') return formatBytes(value);
  if (field === 'durationMs' && typeof value === 'number') return formatClock(value);
  if (field === 'sha256' && typeof value === 'string') return `${value.slice(0, 12)}…`;
  return show(value);
}

const FIELD_WORDS: Record<string, string> = { title: 'Title', filename: 'File name', kind: 'Type', mime: 'Format', bytes: 'Size', sha256: 'Fingerprint', tags: 'Tags', durationMs: 'Length', width: 'Width', height: 'Height' };

function SideHeader({ side, label }: { side: ComparisonSide; label: string }) {
  return (
    <div className='bg-card flex min-w-0 flex-col gap-0.5 rounded-[var(--rafii-radius-control)] p-3 text-sm' data-version-id={side.assetRef.versionId}>
      <span className='rafii-eyebrow'>{label}</span>
      <span className='font-medium'>
        Version {side.versionNo} · {side.title}
      </span>
      <span className='text-muted-foreground text-xs' title={formatDateTime(side.createdAt)}>
        {relativeTime(side.createdAt)} · {side.approval.label}
      </span>
      <span className='text-muted-foreground text-xs'>{side.usage.count ? `Used ${side.usage.count} ${side.usage.count === 1 ? 'time' : 'times'}` : 'Not used yet'}</span>
    </div>
  );
}

function VersionPicture({ assetRef, label }: { assetRef: AssetRef; label: string }) {
  const image = useAssetImage(assetRef.versionId || assetRef.assetId);
  return image.data ? (
    <Image src={image.data} alt={label} width={400} height={400} unoptimized className='rafii-quiet aspect-square w-full rounded-[var(--rafii-radius-control)] object-contain' />
  ) : (
    <div className='rafii-quiet text-muted-foreground flex aspect-square w-full items-center justify-center rounded-[var(--rafii-radius-control)] text-xs'>{image.isError ? 'Preview unavailable' : 'Loading preview…'}</div>
  );
}

/** A server comparison, as honest as the server: text diff, pictures side by side, timed passages, or "not supported". */
export function ComparisonView({ result }: { result: ComparisonResult }) {
  const headline = comparisonHeadline(result);
  const leftLabel = result.relationship.newer === 'left' ? 'Newer' : result.relationship.newer === 'right' ? 'Earlier' : 'First';
  const rightLabel = result.relationship.newer === 'right' ? 'Newer' : result.relationship.newer === 'left' ? 'Earlier' : 'Second';
  return (
    <section aria-label='Comparison' className='flex min-w-0 flex-col gap-3'>
      <div className='grid gap-2 sm:grid-cols-2'>
        <SideHeader side={result.left} label={leftLabel} />
        <SideHeader side={result.right} label={rightLabel} />
      </div>
      <p className={cn('text-sm', !headline.supported && 'font-medium')} data-comparison-supported={headline.supported ? 'true' : 'false'}>
        {headline.line}
      </p>
      {result.mode === 'text' && result.text ? (
        <ol aria-label='Text differences' className='flex max-h-80 flex-col gap-0.5 overflow-y-auto overscroll-contain font-mono text-xs'>
          {diffRows(result.text.hunks).map((row, index) =>
            row.type === 'same' ? (
              <li key={index} className='text-muted-foreground py-1 font-sans'>
                {row.count} unchanged {row.count === 1 ? 'line' : 'lines'}
              </li>
            ) : row.type === 'clipped' ? (
              <li key={index} className='text-muted-foreground py-1 font-sans'>
                Long change shortened
              </li>
            ) : (
              <li key={index} className={cn('flex gap-2 rounded px-2 py-0.5', row.type === 'added' ? 'bg-foreground/[0.06]' : 'line-through decoration-foreground/40')}>
                <span aria-hidden className='w-3 shrink-0'>
                  {row.type === 'added' ? '+' : '−'}
                </span>
                <span className='sr-only'>{row.type === 'added' ? 'Added: ' : 'Removed: '}</span>
                <span className='min-w-0 flex-1 break-words whitespace-pre-wrap'>{row.text}</span>
                {row.locator ? <span className='text-muted-foreground shrink-0 font-sans'>{locatorLabel(row.locator as Parameters<typeof locatorLabel>[0])}</span> : null}
              </li>
            )
          )}
        </ol>
      ) : null}
      {result.mode === 'image' && result.image ? (
        <div className='grid grid-cols-2 gap-2'>
          {[result.image.left, result.image.right].map((side, index) => (
            <figure key={side.assetRef.versionId} className='flex flex-col gap-1'>
              <VersionPicture assetRef={side.assetRef} label={index === 0 ? `${leftLabel} version` : `${rightLabel} version`} />
              <figcaption className='text-muted-foreground text-xs'>
                {side.width && side.height ? `${side.width}×${side.height}` : 'Size unknown'}
                {side.orientation ? ` · ${side.orientation}` : ''}
              </figcaption>
            </figure>
          ))}
        </div>
      ) : null}
      {result.mode === 'media' && result.media ? (
        <div className='grid gap-3 sm:grid-cols-2'>
          {[result.media.left, result.media.right].map((side, index) => (
            <div key={side.assetRef.versionId} className='flex min-w-0 flex-col gap-1 text-sm'>
              <p className='font-medium'>
                {index === 0 ? leftLabel : rightLabel}: {side.durationMs !== null ? formatClock(side.durationMs) : 'length unknown'}
              </p>
              {side.segments.length ? (
                <ul className='flex max-h-48 flex-col gap-1 overflow-y-auto text-xs'>
                  {side.segments.map((segment) => (
                    <li key={segment.segmentId}>
                      <span className='font-medium'>{locatorLabel(segment.locator as Parameters<typeof locatorLabel>[0])}</span> {segment.text}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className='text-muted-foreground text-xs'>No timed passages yet.</p>
              )}
            </div>
          ))}
        </div>
      ) : null}
      <table className='w-full text-left text-xs'>
        <caption className='sr-only'>Details of both versions</caption>
        <thead>
          <tr className='text-muted-foreground'>
            <th scope='col' className='py-1 pr-2 font-medium'>
              Detail
            </th>
            <th scope='col' className='py-1 pr-2 font-medium'>
              {leftLabel}
            </th>
            <th scope='col' className='py-1 pr-2 font-medium'>
              {rightLabel}
            </th>
            <th scope='col' className='py-1 font-medium'>
              <span className='sr-only'>Changed</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {result.metadata.map((row) => (
            <tr key={row.field}>
              <th scope='row' className='py-1 pr-2 font-normal'>
                {FIELD_WORDS[row.field] ?? row.field}
              </th>
              <td className='py-1 pr-2 break-words'>{metadataValue(row.field, row.left)}</td>
              <td className='py-1 pr-2 break-words'>{metadataValue(row.field, row.right)}</td>
              <td className='py-1'>{row.changed ? 'Changed' : 'Same'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.warnings.map((warning) => (
        <p key={warning} className='text-muted-foreground text-xs'>
          {warning}
        </p>
      ))}
      <p className='text-muted-foreground text-xs'>A comparison never means the newer version was approved; each version keeps its own approval.</p>
    </section>
  );
}

function useOrganizationRevision() {
  const { api, workspaceId } = useWorkspaceApi();
  return async () => (await api.libraryGrants(workspaceId)).revisions.organizationRevision;
}

/** "Link as a new version of…": pick the older item; the server restacks and flags what cites older versions. */
function LinkVersionDialog({ open, onOpenChange, current, onAnnounce }: { open: boolean; onOpenChange: (open: boolean) => void; current: AssetRef; onAnnounce: (message: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const organizationRevision = useOrganizationRevision();
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<{ id: string; title: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<{ target: string; key: string } | null>(null);
  const candidates = useQuery({
    queryKey: ['library-link-candidates', workspaceId, query.trim()],
    queryFn: () => api.library(workspaceId, query.trim(), 20, 0, { kind: 'all', tag: '', collection: '', sort: 'newest' }),
    enabled: open && Boolean(workspaceId),
    staleTime: 15_000
  });
  const options = (candidates.data?.assets ?? []).filter((asset) => !asset.deleted && normalizeKey(asset.id) !== normalizeKey(current.assetId));

  async function link() {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      const envelope = linkVersionEnvelope(current, assetRefFor(picked.id), await organizationRevision(), `link-${Date.now()}`);
      if (!envelope) throw new Error('Choose a different item.');
      if (!key.current || key.current.target !== picked.id) key.current = { target: picked.id, key: newIdempotencyKey('lib-link-version', randomKey) };
      const result = await api.libraryAction(workspaceId, { ...envelope, idempotencyKey: key.current.key });
      if (result.status !== 'applied') throw new Error(result.warnings?.[0] || (result.status === 'conflict' ? 'Library organization changed. Try again.' : 'Not allowed.'));
      key.current = null;
      await client.invalidateQueries({ queryKey: ['library-versions', workspaceId] });
      await client.invalidateQueries({ queryKey: ['library-related', workspaceId] });
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      onAnnounce(`Linked as a newer version of ${picked.title}. Anything citing older versions is flagged for review.`);
      onOpenChange(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The link wasn’t saved.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='sm'>
        <RafiiDialogHeader title='Link as a new version of…' intro='This item becomes the newest version of the one you pick. Drafts and packs that cite older versions are flagged for review; nothing is replaced automatically.' />
        <RafiiDialogBody className='flex flex-col gap-3'>
          <label htmlFor='library-link-version-search' className='flex flex-col gap-1.5 text-sm font-medium'>
            Find the earlier item
            <Input id='library-link-version-search' value={query} onChange={(event) => setQuery(event.target.value)} className='h-11 font-normal' />
          </label>
          <ul className='flex max-h-64 flex-col gap-1 overflow-y-auto' aria-label='Earlier item'>
            {options.map((asset) => {
              const title = asset.displayTitle || asset.originalFilename || 'Untitled item';
              const chosen = picked?.id === asset.id;
              return (
                <li key={asset.id}>
                  <Button variant='quiet' size='control' className='aria-pressed:bg-foreground/[0.07] aria-pressed:text-foreground w-full justify-start' aria-pressed={chosen} onClick={() => setPicked({ id: asset.id, title })}>
                    {chosen ? <Icons.check aria-hidden /> : null}
                    <span className='truncate'>{title}</span>
                  </Button>
                </li>
              );
            })}
            {!options.length && !candidates.isPending ? <li className='text-muted-foreground text-sm'>No other items match.</li> : null}
          </ul>
          {error ? (
            <p role='alert' className='text-destructive text-sm'>
              {error}
            </p>
          ) : null}
        </RafiiDialogBody>
        <RafiiDialogFooter className='flex-row justify-end'>
          <Button variant='glass' size='control' onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant='action' size='control' disabled={!picked || busy} onClick={() => void link()}>
            {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            {picked ? `Link to “${picked.title}”` : 'Link'}
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

/**
 * The Related section: the version stack with approvals, a comparison of any two versions, drafts that still cite an
 * older version (replaced one at a time, only after confirming), relations, and near-duplicate suggestions — which
 * are suggestions only, with nothing here that combines or removes items.
 */
export function VersionsPanel({ assetKey, canEdit, enabled, onOpenAsset, onAnnounce }: { assetKey: string; canEdit: boolean; enabled: boolean; onOpenAsset: (assetId: string) => void; onAnnounce: (message: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const organizationRevision = useOrganizationRevision();
  const shared = { enabled: Boolean(workspaceId && assetKey && enabled), retry: false, staleTime: 30_000 } as const;
  const versions = useQuery({ queryKey: ['library-versions', workspaceId, assetKey], queryFn: () => api.libraryVersions(workspaceId, assetKey), ...shared });
  const related = useQuery({ queryKey: ['library-related', workspaceId, assetKey], queryFn: () => api.libraryRelated(workspaceId, assetKey), ...shared });
  const [chosen, setChosen] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [plan, setPlan] = useState<ReplacementPlan | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [replaceMessage, setReplaceMessage] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);
  const replaceKey = useRef<{ plan: string; key: string } | null>(null);

  if (!enabled) return <p className='text-muted-foreground text-sm'>Versions and related items appear here once Library intelligence is available.</p>;
  if (versions.isPending || related.isPending) return <p className='text-muted-foreground text-sm'>Loading versions…</p>;
  if (versions.isError && related.isError) return <p className='text-muted-foreground text-sm'>Versions and related items couldn’t load.</p>;

  const stack: VersionStackEntry[] = versions.data?.versions ?? [];
  const affected: AffectedDependent[] = versions.data?.affected ?? [];
  const relations = related.data?.relations ?? [];
  const near = related.data?.nearDuplicates;
  const selfRef = versions.data?.assetRef ?? related.data?.assetRef ?? assetRefFor(assetKey);
  const defaultPair = stack.length >= 2 ? [stack[stack.length - 2].assetRef.versionId, stack[stack.length - 1].assetRef.versionId] : [];
  const pair = chosen.length === 2 ? chosen : defaultPair;

  async function compare() {
    const refs = pair.map((versionId) => stack.find((entry) => entry.assetRef.versionId === versionId)?.assetRef).filter((ref): ref is AssetRef => Boolean(ref));
    if (refs.length !== 2) return;
    setComparing(true);
    setCompareError(null);
    try {
      setComparison(await api.libraryCompare(workspaceId, refs));
    } catch (failure) {
      setCompareError(failure instanceof ApiError && failure.status === 503 ? 'Comparing versions isn’t available in this version yet.' : failure instanceof Error ? failure.message : 'The comparison didn’t finish.');
    } finally {
      setComparing(false);
    }
  }

  /** Runs only from the confirmation dialog's own button. */
  async function confirmReplacement(confirmed: ReplacementPlan) {
    setReplacing(true);
    setReplaceMessage(null);
    try {
      const expectedRevision = confirmed.revisionSource === 'source_pack' ? (await api.librarySourcePack(workspaceId, confirmed.payload.dependentKey)).revision : await organizationRevision();
      const envelope = replacementEnvelope(confirmed, { confirmed: true, expectedRevision, actionId: `replace-${Date.now()}` });
      if (!envelope) throw new Error('The replacement needs your confirmation.');
      const digest = JSON.stringify([confirmed.targetRefs, confirmed.payload]);
      if (!replaceKey.current || replaceKey.current.plan !== digest) replaceKey.current = { plan: digest, key: newIdempotencyKey('lib-replace', randomKey) };
      const result = await api.libraryAction<{ warnings?: string[] }>(workspaceId, { ...envelope, idempotencyKey: replaceKey.current.key });
      if (result.status !== 'applied') throw new Error(result.warnings?.[0] || (result.status === 'conflict' ? 'This changed since you opened it. Reload and try again.' : 'Not allowed.'));
      replaceKey.current = null;
      await client.invalidateQueries({ queryKey: ['library-versions', workspaceId, assetKey] });
      await client.invalidateQueries({ queryKey: ['library-related', workspaceId, assetKey] });
      const text = ['Replaced.', ...(result.warnings ?? [])].join(' ');
      setReplaceMessage(text);
      onAnnounce(text);
      setPlan(null);
    } catch (failure) {
      setReplaceMessage(failure instanceof Error ? failure.message : 'The replacement wasn’t saved.');
    } finally {
      setReplacing(false);
    }
  }

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        <p className='rafii-eyebrow'>Versions</p>
        {stack.length ? (
          <ol className='flex flex-col gap-1'>
            {stack.map((entry) => {
              const id = entry.assetRef.versionId;
              const checked = pair.includes(id);
              return (
                <li key={id} className='flex min-h-11 items-center gap-3 text-sm'>
                  {stack.length >= 2 ? (
                    <input
                      type='checkbox'
                      aria-label={`Compare version ${entry.versionNo}`}
                      checked={checked}
                      onChange={(event) => {
                        const base = chosen.length === 2 ? chosen : pair;
                        setChosen(event.target.checked ? [...base.filter((value) => value !== id), id].slice(-2) : base.filter((value) => value !== id));
                      }}
                      className='accent-foreground size-5'
                    />
                  ) : null}
                  <span className='flex min-w-0 flex-1 flex-col'>
                    <span>
                      Version {entry.versionNo}
                      {entry.current ? <span className='text-muted-foreground'> · current</span> : null}
                    </span>
                    <span className='text-muted-foreground text-xs' title={formatDateTime(entry.createdAt)}>
                      {relativeTime(entry.createdAt)} · {entry.approval.label}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className='text-muted-foreground text-sm'>One version.</p>
        )}
        <div className='flex flex-wrap gap-2'>
          {stack.length >= 2 ? (
            <Button variant='glass' size='control' className='h-11' disabled={comparing || pair.length !== 2} onClick={() => void compare()}>
              {comparing ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              Compare selected versions
            </Button>
          ) : null}
          {canEdit ? (
            <Button variant='quiet' size='control' className='h-11' onClick={() => setLinking(true)}>
              Link as a new version of…
            </Button>
          ) : null}
        </div>
        {compareError ? <p className='text-muted-foreground text-sm'>{compareError}</p> : null}
        {comparison ? <ComparisonView result={comparison} /> : null}
      </div>

      {affected.length ? (
        <div className='flex flex-col gap-2'>
          <p className='rafii-eyebrow'>Still citing an older version</p>
          <ul className='flex flex-col gap-2'>
            {affected.map((entry) => {
              const from = stack.find((version) => version.assetRef.versionId === entry.citesVersion.versionId)?.versionNo;
              return (
                <li key={`${entry.kind}:${entry.key}`} className='rafii-quiet flex flex-wrap items-center justify-between gap-2 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
                  <span className='flex min-w-0 flex-col'>
                    <span className='font-medium'>{entry.label}</span>
                    <span className='text-muted-foreground text-xs'>
                      Cites version {from ?? 'an older version'}
                      {entry.flagged ? '' : ' · not yet flagged'}
                    </span>
                  </span>
                  {canEdit ? (
                    <Button variant='glass' size='control' className='h-11' onClick={() => setPlan(replacementPlan(entry, stack))}>
                      Use the newer version…
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {replaceMessage ? <p className='text-muted-foreground text-xs'>{replaceMessage}</p> : null}
        </div>
      ) : null}

      {relations.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Relations</p>
          <ul className='flex flex-col gap-1 text-sm'>
            {relations.map((relation) => (
              <li key={relation.id} className='flex min-h-11 flex-wrap items-center justify-between gap-2'>
                <span className='min-w-0'>
                  {relationLabel(relation.relation, relation.direction)}{' '}
                  <span className='font-medium'>{relation.other.title ?? (relation.other.available === false ? 'an item that is no longer available' : relation.other.kind)}</span>
                  {relation.status === 'stale' ? <span className='text-muted-foreground'> · older version</span> : null}
                </span>
                {relation.other.assetRef ? (
                  <Button variant='quiet' size='lg' className='h-11' onClick={() => onOpenAsset(relation.other.assetRef!.assetId)}>
                    Open
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {near && near.available && near.suggestions.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Possible near-duplicates</p>
          <ul className='flex flex-col gap-1 text-sm'>
            {near.suggestions.map((suggestion) => (
              <li key={suggestion.id} className='flex min-h-11 flex-wrap items-center justify-between gap-2'>
                <span className='flex min-w-0 items-center gap-2'>
                  <span className='truncate'>{suggestion.other.title ?? 'Similar item'}</span>
                  <OriginBadge origin='ai_suggested' />
                </span>
                {suggestion.other.assetRef ? (
                  <Button variant='quiet' size='lg' className='h-11' onClick={() => onOpenAsset(suggestion.other.assetRef!.assetId)}>
                    Open to compare
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          <p className='text-muted-foreground text-xs'>{near.note}</p>
        </div>
      ) : null}
      {related.data?.exactDuplicates.count ? <p className='text-muted-foreground text-xs'>{related.data.exactDuplicates.note}</p> : null}
      {!stack.length && !relations.length && !(near?.suggestions.length) ? <p className='text-muted-foreground text-sm'>No versions or related items are recorded for this item.</p> : null}

      <AlertDialog open={plan !== null} onOpenChange={(open) => !open && !replacing && setPlan(null)}>
        <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-dialog)] p-5 ring-0 md:p-6'>
          <AlertDialogHeader>
            <AlertDialogTitle>{plan?.title}</AlertDialogTitle>
            <AlertDialogDescription render={<div className='flex flex-col gap-1.5' />}>
              {plan?.consequences.map((line) => (
                <span key={line} className='block'>
                  {line}
                </span>
              ))}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel variant='glass' size='control'>
              Keep the older version
            </AlertDialogCancel>
            <AlertDialogAction
              variant='action'
              size='control'
              disabled={replacing}
              onClick={() => {
                if (plan) void confirmReplacement(plan);
              }}
            >
              {replacing ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              Use the newer version
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {canEdit ? <LinkVersionDialog open={linking} onOpenChange={setLinking} current={selfRef} onAnnounce={onAnnounce} /> : null}
    </div>
  );
}
