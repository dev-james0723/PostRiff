'use client';

import { createContext, useContext, useId, type ReactNode } from 'react';
import Image from 'next/image';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import type { Asset } from '@/lib/api/types';
import type {
  AssetCandidateCardProps,
  CollectionProposalProps,
  DraftWorkspaceProps,
  LibraryAssetRef,
  LibraryLocator,
  ProcessingStatusProps,
  ProposedAction,
  SourceCitationProps,
  SourcePackReviewProps,
  SourceScopeProps,
  SuggestionReviewProps,
  VersionComparisonProps
} from '@/lib/library/openui-schemas';
import { resolveActionHandler, type DispatchOutcome } from '@/lib/library/openui-policy';
import { countLabel, formatCount, scopeLabel } from '@/lib/library/wording';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useAssetImage } from '../../asset-card';
import { AssetFileThumbnail } from '../../asset-thumbnail';
import { CapabilityList } from '../detail-sections';

/**
 * Library task components for generated (OpenUI) results (UI spec §7). They render validated server data with the
 * Library's own pieces, and every control only calls the injected onAction handler (action id and inputs): nothing writes on
 * mount, render or effect. Selection and drafts belong to the host (LibraryTaskSurface or the runtime's adapter),
 * so a streamed update never resets them.
 */

export type LibraryOnAction = (actionId: string, inputs: Record<string, unknown>) => void;
export interface HostInjected {
  /** Injected by the host (the runtime's bridge or LibraryTaskSurface). Missing: controls render disabled. */
  onAction?: LibraryOnAction | null;
}
type ActionHandle = ReturnType<typeof resolveActionHandler<LibraryOnAction>>;

/** Shown when no action handler was injected: the content stays readable, nothing can be pressed. */
function Unavailable({ act }: { act: ActionHandle }) {
  return act.available ? null : <p className='text-muted-foreground text-xs'>Actions aren’t available in this view.</p>;
}

export interface LibraryTaskHost {
  isSelected: (ref: LibraryAssetRef) => boolean;
  /** False while streaming, hydrating or replaying: controls stay visible but cannot write. */
  writesEnabled: boolean;
  busyActionId: string | null;
  outcomeOf: (actionId: string) => DispatchOutcome | undefined;
  draft: (key: string, initial: string) => string;
  setDraft: (key: string, value: string) => void;
}

const DEFAULT_HOST: LibraryTaskHost = {
  isSelected: () => false,
  writesEnabled: false,
  busyActionId: null,
  outcomeOf: () => undefined,
  draft: (_key, initial) => initial,
  setDraft: () => undefined
};

export const LibraryTaskHostContext = createContext<LibraryTaskHost>(DEFAULT_HOST);

export function useLibraryTaskHost() {
  return useContext(LibraryTaskHostContext);
}

const OUTCOME_WORDS: Record<DispatchOutcome['status'], string> = {
  applied: 'Done',
  requires_confirmation: 'Needs your confirmation',
  conflict: 'Changed since this result',
  denied: 'Not allowed',
  failed: 'Didn’t finish',
  busy: 'Another change is saving',
  refused: 'Not sent'
};

function Frame({ title, eyebrow, children, className }: { title: ReactNode; eyebrow?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('rafii-quiet flex min-w-0 flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4', className)}>
      <div className='flex min-w-0 flex-col gap-0.5'>
        {eyebrow ? <span className='rafii-eyebrow'>{eyebrow}</span> : null}
        <h3 className='text-foreground min-w-0 text-sm font-medium break-words'>{title}</h3>
      </div>
      {children}
    </section>
  );
}

/** The server's offered actions. Labels and effects are the server's words; the outcome is shown as it came back. */
function ActionButtons({ actions, act }: { actions: readonly ProposedAction[]; act: ActionHandle }) {
  const host = useLibraryTaskHost();
  const id = useId();
  if (!actions.length) return null;
  return (
    <div className='flex flex-col gap-2'>
      <div className='flex flex-wrap gap-2'>
        {actions.map((action, index) => (
          <Button
            key={action.envelope.actionId}
            variant={index === 0 ? 'action' : 'glass'}
            size='control'
            className='h-11'
            aria-describedby={`${id}-${index}`}
            disabled={!act.available || !host.writesEnabled || host.busyActionId !== null}
            onClick={() => act.call(action.envelope.actionType, { actionId: action.envelope.actionId })}
          >
            {host.busyActionId === action.envelope.actionId ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            {action.label}
          </Button>
        ))}
      </div>
      {actions.map((action, index) => {
        const outcome = host.outcomeOf(action.envelope.actionId);
        return (
          <p key={action.envelope.actionId} id={`${id}-${index}`} className='text-muted-foreground text-xs'>
            {action.effect}
            {outcome ? (
              <span className={cn('ml-1 font-medium', outcome.status === 'applied' ? 'text-foreground' : 'text-destructive')}>
                · {OUTCOME_WORDS[outcome.status]}
                {'message' in outcome && outcome.message ? `: ${outcome.message}` : ''}
              </span>
            ) : null}
          </p>
        );
      })}
      {act.available && !host.writesEnabled ? <p className='text-muted-foreground text-xs'>Actions unlock when the result has finished and been checked.</p> : null}
    </div>
  );
}

function OpenButton({ label, assetRef, locator, act }: { label: string; assetRef: LibraryAssetRef; locator?: LibraryLocator; act: ActionHandle }) {
  return (
    <Button variant='quiet' size='lg' className='h-11 self-start' disabled={!act.available} onClick={() => act.call('library.open', { assetRef, ...(locator ? { locator } : {}) })}>
      {label}
    </Button>
  );
}

function stubAsset(assetRef: LibraryAssetRef, title: string, kind: AssetCandidateCardProps['kind'], mime: string): Asset {
  return { id: assetRef.assetId, hash: assetRef.sha256, mime, assetKind: kind, displayTitle: title, deleted: false };
}

/** A candidate item: real preview, title, why it matched, and select/open — selection is the host's. */
export function AssetCandidateCard({ assetRef, title, kind, mime, snippet, locatorLabel, matchReasons, onAction }: AssetCandidateCardProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  const host = useLibraryTaskHost();
  const selected = host.isSelected(assetRef);
  const media = kind === 'image' || kind === 'video';
  const image = useAssetImage(assetRef.assetId, media);
  return (
    <article className={cn('bg-card text-card-foreground flex min-w-0 flex-col overflow-hidden rounded-[var(--rafii-radius-card)] shadow-[var(--rafii-shadow-glass)]', selected && 'ring-foreground ring-2')}>
      {media ? (
        image.data ? (
          <Image src={image.data} alt='' width={400} height={400} unoptimized className='rafii-quiet aspect-square w-full object-contain' />
        ) : (
          <div className='rafii-quiet text-muted-foreground flex aspect-square w-full items-center justify-center text-xs'>{image.isError ? 'Preview unavailable' : 'Loading preview…'}</div>
        )
      ) : (
        <AssetFileThumbnail asset={stubAsset(assetRef, title, kind, mime)} size='gallery' loadPreview={false} />
      )}
      <div className='flex min-w-0 flex-col gap-1.5 p-3'>
        <h3 className='truncate text-sm font-medium'>{title}</h3>
        {matchReasons?.length ? <p className='text-muted-foreground text-xs'>Matched: {matchReasons.join(' · ')}</p> : null}
        {locatorLabel ? <p className='text-xs font-medium'>{locatorLabel}</p> : null}
        {snippet ? <p className='text-muted-foreground line-clamp-3 text-xs'>{snippet}</p> : null}
        <div className='flex flex-wrap gap-2'>
          <Button variant={selected ? 'action' : 'glass'} size='control' className='h-11' aria-pressed={selected} disabled={!act.available} onClick={() => act.call('library.select', { assetRef, selected: !selected })}>
            {selected ? <Icons.check aria-hidden /> : null}
            {selected ? 'Selected' : 'Select'}
          </Button>
          <OpenButton label='Open' assetRef={assetRef} act={act} />
        </div>
        <Unavailable act={act} />
      </div>
    </article>
  );
}

const SUPPORT: Record<SourceCitationProps['support'], { label: string; icon: keyof typeof Icons }> = {
  supported: { label: 'Supports the answer', icon: 'circleCheck' },
  conflicting: { label: 'Conflicts with another source', icon: 'warning' },
  insufficient: { label: 'Not enough evidence', icon: 'info' }
};

/** A citation that opens the original at its locator. Support is said in words and an icon, not colour. */
export function SourceCitation({ sourceRef, title, support, quote, locatorLabel, onAction }: SourceCitationProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  const word = SUPPORT[support];
  const Icon = Icons[word.icon];
  return (
    <Frame title={title} eyebrow='Source'>
      <p className='flex items-center gap-1.5 text-xs font-medium'>
        <Icon className='size-3.5' aria-hidden />
        {word.label}
      </p>
      {quote ? <blockquote className='border-foreground/20 border-l-2 pl-3 text-sm'>{quote}</blockquote> : null}
      <OpenButton label={locatorLabel ? `Open at ${locatorLabel}` : 'Open original'} assetRef={sourceRef.assetRef} locator={sourceRef.locator} act={act} />
      <Unavailable act={act} />
    </Frame>
  );
}

/** What was searched, in the same plain words as the Library's own scope line. */
export function SourceScope({ kind, selectedCount, description, collectionName, accessibleCount, pendingCount }: SourceScopeProps & HostInjected) {
  return (
    <p data-library-scope={kind} className='text-muted-foreground text-xs'>
      Searching <span className='text-foreground font-medium'>{scopeLabel({ kind, collectionName: collectionName ?? null, selectedCount })}</span>
      {kind === 'collection' && collectionName ? ` · ${collectionName}` : ''}
      {typeof accessibleCount === 'number' ? ` · ${countLabel(accessibleCount, 'permitted item')}` : ''}
      {pendingCount ? ` · ${formatCount(pendingCount)} still being indexed` : ''}
      {description ? <span className='sr-only'> ({description})</span> : null}
    </p>
  );
}

function approvalWord(approved: boolean | null) {
  return approved === null ? 'Approval unknown' : approved ? 'Approved' : 'Not approved';
}

/** Two specific versions side by side. Each keeps its own version identity; nothing is replaced from here silently. */
export function VersionComparison({ title, before, after, differences, affectedDrafts, actions, onAction }: VersionComparisonProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  return (
    <Frame title={title} eyebrow='Compare versions'>
      <div className='grid gap-3 sm:grid-cols-2'>
        {[before, after].map((side, index) => (
          <div key={side.ref.versionId} data-version-id={side.ref.versionId} className='bg-card flex flex-col gap-1 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
            <span className='rafii-eyebrow'>{index === 0 ? 'Earlier' : 'Newer'}</span>
            <span className='font-medium'>
              Version {side.versionNo}
              {side.current ? ' · current' : ''}
            </span>
            <span className='text-muted-foreground text-xs' title={formatDateTime(side.createdAt)}>
              {relativeTime(side.createdAt)} · {approvalWord(side.approved)}
            </span>
            <OpenButton label='Open this version' assetRef={side.ref} act={act} />
          </div>
        ))}
      </div>
      {differences.length ? (
        <table className='w-full text-left text-sm'>
          <thead>
            <tr className='text-muted-foreground text-xs'>
              <th scope='col' className='py-1 pr-3 font-medium'>
                What changed
              </th>
              <th scope='col' className='py-1 pr-3 font-medium'>
                Earlier
              </th>
              <th scope='col' className='py-1 font-medium'>
                Newer
              </th>
            </tr>
          </thead>
          <tbody>
            {differences.map((difference) => (
              <tr key={difference.field}>
                <th scope='row' className='py-1 pr-3 font-normal'>
                  {difference.field}
                </th>
                <td className='py-1 pr-3 break-words'>{difference.before}</td>
                <td className='py-1 break-words'>{difference.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className='text-muted-foreground text-sm'>No differences were reported for this type of item.</p>
      )}
      <p className='text-sm'>{affectedDrafts > 0 ? `${countLabel(affectedDrafts, 'draft')} ${affectedDrafts === 1 ? 'uses' : 'use'} the earlier version.` : 'No draft uses the earlier version.'}</p>
      <Unavailable act={act} />
      <ActionButtons actions={actions} act={act} />
    </Frame>
  );
}

/** A proposed collection, before and after: who joins, who leaves, and what saving does. */
export function CollectionProposal({ name, ruleSummary, before, after, effect, actions, onAction }: CollectionProposalProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  const was = new Set(before.map((item) => `${item.assetRef.assetId}:${item.assetRef.versionId}`));
  const will = new Set(after.map((item) => `${item.assetRef.assetId}:${item.assetRef.versionId}`));
  const joining = after.filter((item) => !was.has(`${item.assetRef.assetId}:${item.assetRef.versionId}`));
  const leaving = before.filter((item) => !will.has(`${item.assetRef.assetId}:${item.assetRef.versionId}`));
  const staying = after.length - joining.length;
  return (
    <Frame title={name} eyebrow='Collection proposal'>
      {ruleSummary ? <p className='text-sm'>{ruleSummary}</p> : null}
      <p className='text-muted-foreground text-xs'>
        Before {countLabel(before.length)} · after {countLabel(after.length)} · {formatCount(staying)} staying
      </p>
      <div className='grid gap-3 sm:grid-cols-2'>
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Joining ({joining.length})</p>
          {joining.length ? (
            <ul className='flex flex-col gap-1 text-sm'>
              {joining.map((item) => (
                <li key={`${item.assetRef.assetId}:${item.assetRef.versionId}`} className='flex items-center gap-1.5'>
                  <Icons.add className='size-3.5 shrink-0' aria-hidden />
                  <span className='min-w-0 truncate'>{item.title}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className='text-muted-foreground text-sm'>None</p>
          )}
        </div>
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Leaving ({leaving.length})</p>
          {leaving.length ? (
            <ul className='flex flex-col gap-1 text-sm'>
              {leaving.map((item) => (
                <li key={`${item.assetRef.assetId}:${item.assetRef.versionId}`} className='flex items-center gap-1.5'>
                  <Icons.minus className='size-3.5 shrink-0' aria-hidden />
                  <span className='min-w-0 truncate'>{item.title}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className='text-muted-foreground text-sm'>None</p>
          )}
        </div>
      </div>
      {effect ? <p className='text-sm'>{effect}</p> : null}
      <p className='text-muted-foreground text-xs'>Collections hold references, never copies of files.</p>
      <Unavailable act={act} />
      <ActionButtons actions={actions} act={act} />
    </Frame>
  );
}

/**
 * A source pack: evidence and style samples kept apart, with gaps and rights to check. It cannot approve a fact or
 * rights; the words below say so, and the schema refuses any action that would.
 */
export function SourcePackReview({ goal, evidence, style, gaps, rightsWarnings, actions, onAction }: SourcePackReviewProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  return (
    <Frame title={goal || 'Source pack'} eyebrow='Source pack'>
      <div className='flex flex-col gap-1'>
        <p className='rafii-eyebrow'>Evidence ({evidence.length})</p>
        {evidence.length ? (
          <ul className='flex flex-col gap-2'>
            {evidence.map((entry) => (
              <li key={`${entry.sourceRef.assetRef.assetId}-${entry.sourceRef.segmentId ?? ''}`} className='flex flex-col gap-0.5 text-sm'>
                <span className='font-medium'>{entry.title}</span>
                {entry.rationale ? <span className='text-muted-foreground text-xs'>{entry.rationale}</span> : null}
                {entry.rights ? <span className='text-muted-foreground text-xs'>Rights: {entry.rights}</span> : null}
                <OpenButton label='Open source' assetRef={entry.sourceRef.assetRef} locator={entry.sourceRef.locator} act={act} />
              </li>
            ))}
          </ul>
        ) : (
          <p className='text-muted-foreground text-sm'>No evidence selected.</p>
        )}
      </div>
      <div className='flex flex-col gap-1'>
        <p className='rafii-eyebrow'>Style samples ({style.length})</p>
        {style.length ? (
          <ul className='flex flex-col gap-2'>
            {style.map((entry) => (
              <li key={`${entry.sourceRef.assetRef.assetId}-${entry.sourceRef.segmentId ?? ''}`} className='flex flex-col gap-0.5 text-sm'>
                <span className='font-medium'>{entry.title}</span>
                {entry.rationale ? <span className='text-muted-foreground text-xs'>{entry.rationale}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className='text-muted-foreground text-sm'>No style samples. Drafts won’t imitate anyone’s voice.</p>
        )}
      </div>
      {gaps.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Missing</p>
          <ul className='flex list-disc flex-col gap-1 pl-5 text-sm'>
            {gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {rightsWarnings.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Rights to check</p>
          <ul className='flex list-disc flex-col gap-1 pl-5 text-sm'>
            {rightsWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className='text-muted-foreground text-xs'>Rafii can’t approve facts or rights. Check them yourself before anything is published.</p>
      <Unavailable act={act} />
      <ActionButtons actions={actions} act={act} />
    </Frame>
  );
}

/** A draft and its sources. The text is the person's to edit and is kept by the host while results update. */
export function DraftWorkspace({ title, body, sources, draftId, actions, onAction }: DraftWorkspaceProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  const host = useLibraryTaskHost();
  const id = useId();
  const key = draftId ?? `draft:${title}`;
  const value = host.draft(key, body);
  return (
    <Frame title={title} eyebrow='Draft'>
      <label htmlFor={id} className='flex flex-col gap-1.5 text-xs font-medium'>
        Draft text
        <textarea id={id} aria-label='Draft text' value={value} onChange={(event) => host.setDraft(key, event.target.value)} className='rafii-field rafii-focus min-h-48 w-full rounded-[var(--rafii-radius-control)] p-3 text-base font-normal md:text-sm' />
      </label>
      <p className='text-muted-foreground text-xs'>Your edits stay here while the result updates. Nothing is saved or posted from this box.</p>
      {sources.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Sources ({sources.length})</p>
          <ul className='flex flex-col gap-1'>
            {sources.map((source) => (
              <li key={`${source.sourceRef.assetRef.assetId}-${source.sourceRef.segmentId ?? ''}`} className='flex flex-wrap items-center justify-between gap-2 text-sm'>
                <span className='min-w-0 truncate'>{source.title}</span>
                <OpenButton label='Open' assetRef={source.sourceRef.assetRef} locator={source.sourceRef.locator} act={act} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Unavailable act={act} />
      <ActionButtons actions={actions ?? []} act={act} />
    </Frame>
  );
}

/** Processing as the server reports it, capability by capability; never a narrated guess. */
export function ProcessingStatus({ assetRef, title, capabilities, onAction }: ProcessingStatusProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  return (
    <Frame title={title} eyebrow='Processing'>
      {capabilities.length ? (
        <CapabilityList states={capabilities.map((state) => ({ capability: state.capability, state: state.state, progress: state.progress ?? null, retryable: state.retryable, detail: state.detail }))} />
      ) : (
        <p className='text-muted-foreground text-sm'>Nothing has been requested for this item.</p>
      )}
      <OpenButton label='Open item' assetRef={assetRef} act={act} />
      <Unavailable act={act} />
    </Frame>
  );
}

const CATEGORY: Record<SuggestionReviewProps['category'], string> = {
  outdated_source: 'A newer version exists',
  unused_relevant: 'Relevant and not used yet',
  missing_input: 'Something is missing',
  failed_processing: 'Processing failed',
  organization: 'Organizing suggestion',
  permission: 'Permission needed',
  source_integrity: 'Source check'
};

/** One suggestion with its reason. No urgency it doesn't have; dismiss and snooze come from the server's actions. */
export function SuggestionReview({ category, reason, state, critical, candidates, affected, actions, onAction }: SuggestionReviewProps & HostInjected) {
  const act = resolveActionHandler(onAction);
  return (
    <Frame title={CATEGORY[category]} eyebrow={critical ? 'Needs attention' : 'Suggestion'}>
      <p className='text-sm'>{reason}</p>
      {affected.length ? (
        <p className='text-muted-foreground text-xs'>
          Affects: {affected.map((entry) => entry.label).join(', ')}
        </p>
      ) : null}
      {candidates.length ? (
        <ul className='flex flex-col gap-1'>
          {candidates.map((candidate) => (
            <li key={`${candidate.sourceRef.assetRef.assetId}-${candidate.sourceRef.segmentId ?? ''}`} className='flex flex-wrap items-center justify-between gap-2 text-sm'>
              <span className='min-w-0 truncate'>{candidate.title}</span>
              <OpenButton label='Open' assetRef={candidate.sourceRef.assetRef} locator={candidate.sourceRef.locator} act={act} />
            </li>
          ))}
        </ul>
      ) : null}
      {state !== 'new' && state !== 'seen' ? <p className='text-muted-foreground text-xs'>Current state: {state}</p> : null}
      <Unavailable act={act} />
      <ActionButtons actions={actions} act={act} />
    </Frame>
  );
}
