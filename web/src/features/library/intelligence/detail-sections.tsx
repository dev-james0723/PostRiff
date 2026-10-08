'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import type { Annotation, CapabilityState, ContentSegment, Locator, UnderstandingCard, UsageEntry } from '@/lib/api/library-intelligence-types';
import { normalizeKey } from '@/lib/library/url-state';
import { countLabel, locatorLabel, originLabel, purposeLines } from '@/lib/library/wording';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { LibraryAsset } from '../use-library';

/**
 * Library understanding for one item. Each read is optional: until a capability is in this build (or allowed for this
 * item) the detail keeps showing the deterministic facts, never a placeholder that pretends to be analysis.
 */
export function useAssetIntelligence(asset: LibraryAsset | null, reachable: boolean) {
  const { api, workspaceId } = useWorkspaceApi();
  const key = asset ? normalizeKey(asset.id) : '';
  const enabled = Boolean(workspaceId && key && reachable);
  const shared = { enabled, retry: false, staleTime: 30_000, refetchOnWindowFocus: false } as const;
  const card = useQuery({ queryKey: ['library-card', workspaceId, key], queryFn: () => api.libraryCard(workspaceId, key), ...shared });
  const segments = useQuery({ queryKey: ['library-segments', workspaceId, key], queryFn: () => api.librarySegments(workspaceId, key), ...shared });
  const related = useQuery({ queryKey: ['library-related', workspaceId, key], queryFn: () => api.libraryRelated(workspaceId, key), ...shared });
  const usage = useQuery({ queryKey: ['library-usage', workspaceId, key], queryFn: () => api.libraryUsage(workspaceId, key), ...shared });
  return { key, card, segments, related, usage };
}

export type AssetIntelligence = ReturnType<typeof useAssetIntelligence>;

/* --- provenance ------------------------------------------------------------------------------------------------- */

const ORIGIN_ICON = { extracted: Icons.page, ai_suggested: Icons.sparkles, user_confirmed: Icons.circleCheck } as const;

/** Where a statement came from, in words and an icon; the border style differs too. Never colour alone. */
export function OriginBadge({ origin }: { origin: Annotation['origin'] | string }) {
  const Icon = ORIGIN_ICON[origin as keyof typeof ORIGIN_ICON] ?? Icons.page;
  return (
    <span
      data-origin={origin}
      className={cn(
        'text-muted-foreground inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
        origin === 'ai_suggested' ? 'border border-dashed border-current' : origin === 'user_confirmed' ? 'border border-current' : 'bg-foreground/[0.06]'
      )}
    >
      <Icon className='size-3' aria-hidden />
      {originLabel(origin)}
    </span>
  );
}

function annotationText(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    const parts = value.map(annotationText).filter((part): part is string => Boolean(part));
    return parts.length ? parts.join(', ') : null;
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return annotationText(record.text ?? record.label ?? record.value ?? null);
  }
  return null;
}

/* --- section frame and navigation ------------------------------------------------------------------------------- */

export const DETAIL_SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'content', label: 'Content' },
  { id: 'related', label: 'Related' },
  { id: 'usage', label: 'Usage' }
] as const;

export function DetailSection({ prefix, id, title, children }: { prefix: string; id: string; title: string; children: ReactNode }) {
  return (
    <section id={`${prefix}-${id}`} aria-labelledby={`${prefix}-${id}-title`} className='flex scroll-mt-16 flex-col gap-3'>
      <h3 id={`${prefix}-${id}-title`} className='text-foreground text-base font-medium'>
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Jump links inside the panel: every section stays in the document, so nothing is hidden behind a tab. */
export function SectionNav({ prefix }: { prefix: string }) {
  const reduce = useReducedMotion();
  return (
    <nav aria-label='Detail sections' className='rafii-panel sticky top-0 z-10 -mx-4 flex gap-1 overflow-x-auto px-4 py-1.5'>
      {DETAIL_SECTIONS.map((section) => (
        <button
          key={section.id}
          type='button'
          className='rafii-focus text-muted-foreground hover:text-foreground min-h-11 shrink-0 rounded-[var(--rafii-radius-control)] px-3 text-sm font-medium'
          onClick={() => document.getElementById(`${prefix}-${section.id}`)?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })}
        >
          {section.label}
        </button>
      ))}
    </nav>
  );
}

/* --- overview --------------------------------------------------------------------------------------------------- */

const CAPABILITY_LABEL: Record<string, string> = {
  preview: 'Preview',
  extract: 'Text',
  transcribe: 'Transcript',
  visual: 'Visual description',
  embed_text: 'Meaning search',
  embed_visual: 'Visual search',
  understand: 'Summary'
};

const STATE_LABEL: Record<string, string> = {
  not_requested: 'not requested',
  queued: 'queued',
  processing: 'in progress',
  ready: 'ready',
  partial: 'partly ready',
  unsupported: 'not available for this file',
  failed: 'failed',
  cancelled: 'cancelled',
  blocked_permission: 'needs permission',
  blocked_budget: 'paused by the usage limit'
};

export function CapabilityList({ states }: { states: CapabilityState[] }) {
  if (!states.length) return null;
  return (
    <ul className='flex flex-col gap-1 text-sm'>
      {states.map((state) => (
        <li key={state.capability} className='flex items-baseline justify-between gap-3'>
          <span>{CAPABILITY_LABEL[state.capability] ?? state.capability}</span>
          <span className={cn('text-xs', state.state === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>
            {STATE_LABEL[state.state] ?? state.state.replaceAll('_', ' ')}
            {state.progress && state.progress.total > 0 ? ` · ${state.progress.done} of ${state.progress.total}` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function UnderstandingSummary({ asset, card }: { asset: LibraryAsset; card: UnderstandingCard | undefined }) {
  const summary = card?.summary ?? (asset.aiSummary ? { text: asset.aiSummary, origin: 'ai_suggested' as const } : null);
  const topics = card?.topics ?? [];
  return (
    <div className='flex flex-col gap-2'>
      {summary ? (
        <div className='flex flex-col gap-1.5'>
          <OriginBadge origin={summary.origin} />
          <p className='text-sm leading-relaxed'>{summary.text}</p>
        </div>
      ) : (
        <p className='text-muted-foreground text-sm'>No summary yet. The original stays useful as a file.</p>
      )}
      {topics.length ? (
        <ul aria-label='Topics' className='flex flex-wrap gap-1.5'>
          {topics.map((topic) => {
            const text = annotationText(topic.value);
            return text ? (
              <li key={topic.id} className='rafii-quiet inline-flex items-center gap-1.5 rounded-full py-1 pr-1 pl-2.5 text-xs'>
                {text}
                <OriginBadge origin={topic.origin} />
              </li>
            ) : null;
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function PurposeList({ card }: { card: UnderstandingCard | undefined }) {
  const lines = purposeLines(card?.sourceStatus);
  if (!lines.length) {
    return <p className='text-muted-foreground text-sm'>Private to this workspace. What Rafii may use it for appears here once Library understanding is available.</p>;
  }
  return (
    <ul className='flex flex-col gap-1.5'>
      {lines.map((line) => (
        <li key={line.purpose} className='flex items-start gap-2 text-sm'>
          {line.allowed ? <Icons.circleCheck className='mt-0.5 size-4 shrink-0' aria-hidden /> : <Icons.circleX className='text-muted-foreground mt-0.5 size-4 shrink-0' aria-hidden />}
          <span className='flex flex-col'>
            <span>{line.label}</span>
            <span className='text-muted-foreground text-xs'>{line.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function SuggestedUses({ card }: { card: UnderstandingCard | undefined }) {
  const uses = (card?.suggestedUses ?? []).map((use) => ({ use, text: annotationText(use.value) })).filter((entry) => entry.text);
  if (!uses.length) return null;
  return (
    <div className='flex flex-col gap-1.5'>
      <p className='rafii-eyebrow'>Suggested uses</p>
      <ul className='flex flex-col gap-1.5'>
        {uses.map(({ use, text }) => (
          <li key={use.id} className='flex items-start justify-between gap-2 text-sm'>
            <span>{text}</span>
            <OriginBadge origin={use.origin} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * "My voice" is a purpose with consequences, not a tag (UI spec §4, A048): it needs the owner, and the owner's
 * statement that they wrote or said this. No match scores or percentages — Rafii shows the sample, not a grade.
 */
export function VoiceControl({ assetKey, card, isOwner }: { assetKey: string; card: UnderstandingCard | undefined; isOwner: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const id = useId();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const status = card?.sourceStatus?.voice;
  if (!card || !status) return null;

  async function refresh() {
    await client.invalidateQueries({ queryKey: ['library-card', workspaceId, assetKey] });
    await client.invalidateQueries({ queryKey: ['library-grants', workspaceId] });
  }

  async function grant() {
    setBusy(true);
    try {
      await api.libraryGrant(workspaceId, { grantType: 'purpose', scope: { kind: 'asset', assetId: assetKey }, purpose: 'voice', attestation: { authoredByMe: true } });
      setConfirmed(false);
      await refresh();
      toast.success('Rafii may learn your voice from this item.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Couldn’t change this permission');
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    setBusy(true);
    try {
      const { grants } = await api.libraryGrants(workspaceId);
      const match = grants.find((entry) => entry.purpose === 'voice' && entry.scopeKind === 'asset' && normalizeKey(entry.scopeKey) === assetKey);
      if (!match) throw new Error('This item learns your voice through a wider permission. Change it in Memory.');
      await api.libraryRevokeGrant(workspaceId, match.id);
      await refresh();
      toast.success('Rafii will stop learning your voice from this item.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Couldn’t change this permission');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3'>
      <p className='text-sm font-medium'>My voice</p>
      {status.allowed ? (
        <>
          <p className='text-muted-foreground text-xs'>Rafii may learn how you write from this item. Withdrawing stops future use; it doesn’t change drafts already written.</p>
          {isOwner ? (
            <Button variant='glass' size='control' className='self-start' disabled={busy} onClick={() => void revoke()}>
              Stop using as my voice
            </Button>
          ) : null}
        </>
      ) : isOwner ? (
        <>
          <label htmlFor={`${id}-author`} className='flex min-h-11 items-start gap-3 text-sm'>
            <input id={`${id}-author`} type='checkbox' checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className='accent-foreground mt-1 size-5 shrink-0' />
            <span className='flex flex-col gap-0.5'>
              <span>I wrote or said this myself</span>
              <span className='text-muted-foreground text-xs'>Interviews, quotes and other people’s writing should not teach your voice.</span>
            </span>
          </label>
          <Button variant='glass' size='control' className='self-start' disabled={!confirmed || busy} onClick={() => void grant()}>
            Use as my voice
          </Button>
        </>
      ) : (
        <p className='text-muted-foreground text-xs'>Only the workspace owner can let Rafii learn a voice from Library items.</p>
      )}
    </div>
  );
}

/* --- content ---------------------------------------------------------------------------------------------------- */

function sameLocator(a: Locator | null | undefined, b: Locator | null | undefined) {
  return Boolean(a && b && JSON.stringify(a) === JSON.stringify(b));
}

/**
 * Transcript and structural text with their locators (page, slide, sheet, time). The passage a search result pointed
 * at is scrolled to and marked, in words as well as style.
 */
export function SegmentList({ segments, focus }: { segments: ContentSegment[]; focus?: Locator | null }) {
  const focused = useRef<HTMLLIElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    focused.current?.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
  }, [focus, reduce]);
  const text = segments.filter((segment) => segment.kind !== 'moment' && segment.text.trim());
  if (!text.length) return null;
  return (
    <ol className='flex max-h-96 flex-col gap-2 overflow-y-auto overscroll-contain'>
      {text.map((segment) => {
        const here = sameLocator(segment.locator, focus);
        return (
          <li key={segment.id} ref={here ? focused : undefined} className={cn('rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-control)] p-3', here && 'ring-foreground ring-2')}>
            <span className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
              <span className='font-medium'>{segment.locatorLabel || locatorLabel(segment.locator ?? null) || 'Text'}</span>
              {segment.speakerLabel ? <span>{segment.speakerLabel}</span> : null}
              {here ? <span className='text-foreground font-medium'>Search result</span> : null}
              <OriginBadge origin={segment.origin === 'user' ? 'user_confirmed' : segment.origin === 'ai_suggested' ? 'ai_suggested' : 'extracted'} />
            </span>
            <p className='text-sm leading-relaxed whitespace-pre-wrap'>{segment.text}</p>
          </li>
        );
      })}
    </ol>
  );
}

/* --- related ---------------------------------------------------------------------------------------------------- */

function labelOf(item: unknown): string | null {
  if (!item || typeof item !== 'object') return null;
  const record = item as Record<string, unknown>;
  const title = record.displayTitle ?? record.title ?? record.label;
  return typeof title === 'string' && title.trim() ? title.trim() : null;
}

export function RelatedList({ card, related }: { card: UnderstandingCard | undefined; related: { relations: unknown[]; nearDuplicates: unknown[]; versions: unknown[] } | undefined }) {
  const versions = card?.versions ?? [];
  const relations = (related?.relations ?? []).map(labelOf).filter((label): label is string => Boolean(label));
  const duplicates = (related?.nearDuplicates ?? []).map(labelOf).filter((label): label is string => Boolean(label));
  if (!versions.length && !relations.length && !duplicates.length) {
    return <p className='text-muted-foreground text-sm'>No versions or related items are recorded for this item.</p>;
  }
  return (
    <div className='flex flex-col gap-3'>
      {versions.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Versions</p>
          <ol className='flex flex-col gap-1 text-sm'>
            {versions.map((version) => (
              <li key={version.versionId} className='flex items-baseline justify-between gap-2'>
                <span>
                  Version {version.versionNo}
                  {version.current ? <span className='text-muted-foreground'> · current</span> : null}
                </span>
                <span className='text-muted-foreground text-xs' title={formatDateTime(version.createdAt)}>
                  {relativeTime(version.createdAt)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {relations.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Related</p>
          <ul className='flex flex-col gap-1 text-sm'>
            {relations.map((label, index) => (
              <li key={`${label}-${index}`}>{label}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {duplicates.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Possible near-duplicates</p>
          <ul className='flex flex-col gap-1 text-sm'>
            {duplicates.map((label, index) => (
              <li key={`${label}-${index}`} className='flex items-baseline justify-between gap-2'>
                <span>{label}</span>
                <OriginBadge origin='ai_suggested' />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/* --- usage ------------------------------------------------------------------------------------------------------ */

const USAGE_EVENT: Record<UsageEntry['eventType'], string> = {
  source_pack: 'Added to a source pack',
  draft_attached: 'Attached to a draft',
  post_scheduled: 'Scheduled in a post',
  post_published: 'Published in a post',
  agent_answer: 'Cited in a Rafii answer',
  downloaded: 'Downloaded'
};

/** Recorded uses and whatever metrics exist. A missing value says "unknown"; nothing here claims a cause. */
export function UsageEntries({ usage }: { usage: UsageEntry[] }) {
  if (!usage.length) return null;
  return (
    <ul className='flex flex-col gap-2'>
      {usage.map((entry, index) => (
        <li key={`${entry.eventType}-${entry.at}-${index}`} className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
          <span className='flex items-baseline justify-between gap-2'>
            <span>
              {USAGE_EVENT[entry.eventType] ?? entry.eventType}
              {entry.channel ? <span className='text-muted-foreground'> · {entry.channel}</span> : null}
            </span>
            <span className='text-muted-foreground text-xs' title={formatDateTime(entry.at)}>
              {relativeTime(entry.at)}
            </span>
          </span>
          {entry.metrics ? (
            <dl className='text-muted-foreground grid grid-cols-[auto_1fr] gap-x-3 text-xs'>
              {Object.entries(entry.metrics).map(([name, value]) => (
                <div key={name} className='contents'>
                  <dt>{name.replaceAll('_', ' ')}</dt>
                  <dd className='text-foreground tabular-nums'>{typeof value === 'number' ? value.toLocaleString('en-US') : 'unknown'}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <span className='text-muted-foreground text-xs'>Metrics: unknown</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/* --- danger ----------------------------------------------------------------------------------------------------- */

/** Delete sits apart from everything else, says what depends on the item, and keeps its own confirmation. */
export function DangerArea({ uses, recorded, publishing, deleting, onDelete }: { uses: number; recorded: number; publishing: boolean; deleting: boolean; onDelete: () => void }) {
  const impact = [
    uses > 0 ? `Used in ${countLabel(uses, 'post')}. Scheduled posts using it will need a new review; published posts aren’t affected.` : 'Not used in a post.',
    recorded > 0 ? `${countLabel(recorded, 'recorded use')} in drafts, source packs or answers will lose this source.` : null
  ].filter(Boolean);
  return (
    <section aria-labelledby='asset-danger-title' className='border-destructive/30 mt-2 flex flex-col gap-2 rounded-[var(--rafii-radius-card)] border border-dashed p-3'>
      <h3 id='asset-danger-title' className='text-destructive text-sm font-medium'>
        Delete
      </h3>
      {impact.map((line) => (
        <p key={line} className='text-muted-foreground text-xs'>
          {line}
        </p>
      ))}
      <Button
        variant='destructive'
        size='control'
        className='self-start rounded-[var(--rafii-radius-control)]'
        disabled={deleting || publishing}
        title={publishing ? 'A post using this asset is publishing' : undefined}
        onClick={onDelete}
      >
        {deleting ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : <Icons.trash aria-hidden />}
        {deleting ? 'Deleting…' : 'Delete…'}
      </Button>
    </section>
  );
}

