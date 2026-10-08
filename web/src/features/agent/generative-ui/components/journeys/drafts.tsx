'use client';
/**
 * J01 — Draft and platform studio (lane E). Lists, side-by-side comparison, a platform preview, evidence and the edit
 * form of an unscheduled draft, all from lane D's draft bindings (drafts_list, draft_read, draft_evidence).
 *
 * Selecting is interaction context only. Editing goes through `draft_edit` (author edit with the draft-revision check,
 * audited, leaves the draft needing review); rewrites and adaptations are follow-up turns in the conversation, never a
 * write from this view. A draft in the publishing queue is read-only here.
 */
import { useState } from 'react';
import { z } from 'zod';
import { Textarea } from '@/components/ui/textarea';
import { textAttributes } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { formatCount, formatInstant, textLength } from '../../journeys/format';
import { useBound, useJourneyEnvironment, useSelectionRecorder } from '../../journeys/runtime';
import type { DraftDetail as DraftDetailData, DraftRow } from '../../journeys/views';
import { CountLabel, GuardedAction, Missing, Pill, QueryFrame, SelectToggle, toggleInOrder, Pager } from './shared';
import type { JourneyRendererProps } from './types';

/** drafts_list accepts at most 10 ids; comparing more than four is not readable. */
export const MAX_SELECTED_DRAFTS = 10;
const titleProps = z.object({ title: z.string().max(120).optional() });

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string' && v.length > 0 && v.length <= 160) : [];
}

function DraftFlags({ draft }: { draft: DraftRow }) {
  const { copy } = useJourneyEnvironment();
  return (
    <span className='flex flex-wrap gap-1'>
      {draft.committed ? <Pill tone='good'>{copy.drafts.inQueue}</Pill> : null}
      {draft.needsReview ? <Pill tone='waiting'>{copy.drafts.needsReview}</Pill> : null}
      {draft.hasProposedUpdate ? <Pill tone='waiting'>{copy.drafts.rewriteWaiting}</Pill> : null}
      {draft.setAside ? <Pill tone='muted'>{copy.drafts.setAside}</Pill> : null}
      {draft.overLimit && draft.limit ? <Pill tone='attention'>{copy.drafts.overLimit(draft.limit)}</Pill> : null}
      {draft.fromAutomation ? <Pill tone='muted'>{copy.drafts.fromAutomation}</Pill> : null}
    </span>
  );
}

function Length({ characters, limit }: { characters: number; limit: number | null | undefined }) {
  const { copy, locale } = useJourneyEnvironment();
  const n = formatCount(characters, locale);
  return (
    <span className='tabular-nums'>
      {copy.drafts.characters}: {n}
      {limit ? ` / ${formatCount(limit, locale)}` : ''}
    </span>
  );
}

function DraftMeta({ draft }: { draft: DraftRow }) {
  const { copy } = useJourneyEnvironment();
  return (
    <span className='text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5 text-xs'>
      <span>{draft.platform ?? <Missing />}</span>
      {draft.account ? <span>{draft.account}</span> : null}
      <span>
        {copy.drafts.language}: {draft.language ?? <Missing />}
      </span>
      <Length characters={draft.characters} limit={draft.limit} />
      <span>
        <CountLabel value={draft.sourceCount} word={copy.drafts.sources} />
      </span>
      {draft.voice ? <span>{draft.voice === 'personalized' ? copy.drafts.voicePersonal : copy.drafts.voiceNeutral}</span> : null}
    </span>
  );
}

export function DraftList({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = titleProps.safeParse(props);
  const selection = useBound<string[]>(`${statementId ?? 'draftList'}Selected`, props.selected);
  const selected = strings(selection.value);
  const record = useSelectionRecorder(statementId ?? 'drafts');
  return (
    <QueryFrame value={props.data} binding='drafts_list' label={copy.drafts.title} title={literal.success ? literal.data.title : null}>
      {(data, result) => {
        const titleOf = (d: DraftRow) => `${d.platform ?? ''} · ${d.excerpt.slice(0, 60)}`.trim();
        const toggle = (draft: DraftRow) => {
          const next = toggleInOrder(selected, draft.draftId, MAX_SELECTED_DRAFTS);
          selection.set(next);
          const byId = new Map(data.drafts.map((d) => [d.draftId, d]));
          record(
            next.map((id) => ({ type: 'draft', id, title: byId.get(id) ? titleOf(byId.get(id) as DraftRow) : undefined })),
            data.drafts.map((d) => ({ type: 'draft', id: d.draftId })),
          );
        };
        return (
          <>
        <div className='flex flex-col gap-2'>
          {selected.length > 0 ? (
            <p className='text-muted-foreground text-xs' role='status'>
              {copy.common.selected(selected.length)} · {copy.common.selectionHint}
            </p>
          ) : null}
          <ul className='flex flex-col divide-y divide-border rounded-[var(--rafii-radius-card)] border'>
            {data.drafts.map((draft) => {
              const isSelected = selected.includes(draft.draftId);
              return (
                <li key={draft.draftId} className={cn('flex items-start gap-3 p-3', isSelected && 'bg-muted/40')}>
                  <SelectToggle
                    selected={isSelected}
                    label={`${draft.platform ?? copy.drafts.title} · ${draft.excerpt.slice(0, 40)}`}
                    disabled={!isSelected && selected.length >= MAX_SELECTED_DRAFTS}
                    onToggle={() => toggle(draft)}
                  />
                  <div className='flex min-w-0 flex-1 flex-col gap-1'>
                    <DraftMeta draft={draft} />
                    <p className='text-foreground line-clamp-3 text-sm break-words' {...textAttributes(draft.language)}>
                      {draft.excerpt}
                    </p>
                    <DraftFlags draft={draft} />
                  </div>
                </li>
              );
            })}
          </ul>
          {data.missingIds && data.missingIds.length > 0 ? <p className='text-muted-foreground text-xs'>{copy.drafts.missingRequested}</p> : null}
        </div>
            <Pager result={result} cursor={props.cursor} statementId={statementId} />
          </>
        );
      }}
    </QueryFrame>
  );
}

export function DraftCompare({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = titleProps.safeParse(props);
  // Only drafts the person picked, in the order picked: an empty pick never falls back to "all drafts".
  const selection = useBound<string[]>(`${statementId ?? 'draftCompare'}Selected`, props.selected);
  const picked = strings(selection.value);
  return (
    <QueryFrame
      value={props.data}
      binding='drafts_list'
      label={copy.drafts.compareTitle}
      title={(literal.success ? literal.data.title : null) ?? copy.drafts.compareTitle}
      empty={() => <p className='text-muted-foreground text-sm'>{copy.drafts.compareNeedTwo}</p>}
    >
      {(data) => {
        const byId = new Map(data.drafts.map((d) => [d.draftId, d]));
        const drafts = picked.map((id) => byId.get(id)).filter((d): d is DraftRow => Boolean(d)).slice(0, 4);
        if (drafts.length < 2) return <p className='text-muted-foreground text-sm'>{copy.drafts.compareNeedTwo}</p>;
        return (
          <div className='@container'>
            <div className={cn('grid gap-3', drafts.length === 2 ? '@[34rem]:grid-cols-2' : '@[34rem]:grid-cols-2 @[56rem]:grid-cols-4')}>
              {drafts.map((draft, index) => (
                <article key={draft.draftId} className='flex min-w-0 flex-col gap-2 rounded-[var(--rafii-radius-card)] border p-3' aria-label={`${index + 1}. ${draft.platform ?? ''}`}>
                  <p className='text-muted-foreground text-xs font-medium'>
                    {index + 1}. {draft.platform ?? <Missing />}
                    {draft.account ? ` · ${draft.account}` : ''}
                  </p>
                  <dl className='grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs'>
                    <dt className='text-muted-foreground'>{copy.drafts.language}</dt>
                    <dd>{draft.language ?? <Missing />}</dd>
                    <dt className='text-muted-foreground'>{copy.drafts.characters}</dt>
                    <dd className='tabular-nums'>
                      <Length characters={draft.characters} limit={draft.limit} />
                    </dd>
                    <dt className='text-muted-foreground'>{copy.drafts.sourcesLabel}</dt>
                    <dd>
                      <CountLabel value={draft.sourceCount} word={copy.drafts.sources} />
                    </dd>
                    <dt className='text-muted-foreground'>{copy.drafts.voiceLabel}</dt>
                    <dd>{draft.voice ? (draft.voice === 'personalized' ? copy.drafts.voicePersonal : copy.drafts.voiceNeutral) : <Missing />}</dd>
                  </dl>
                  <p className='text-foreground text-sm break-words whitespace-pre-wrap' {...textAttributes(draft.language)}>
                    {draft.excerpt}
                  </p>
                  <DraftFlags draft={draft} />
                </article>
              ))}
            </div>
            {data.missingIds && data.missingIds.length > 0 ? <p className='text-muted-foreground mt-2 text-xs'>{copy.drafts.missingRequested}</p> : null}
          </div>
        );
      }}
    </QueryFrame>
  );
}

function ScheduledJobs({ draft }: { draft: DraftDetailData }) {
  const { copy, locale } = useJourneyEnvironment();
  if (!draft.scheduled || draft.scheduled.length === 0) return null;
  return (
    <ul className='flex flex-col gap-1 text-xs'>
      {draft.scheduled.map((job, i) => (
        <li key={job.jobId ?? i} className='flex flex-wrap items-center gap-2'>
          <Pill tone={job.verified ? 'good' : 'neutral'}>{job.title ?? job.state ?? copy.common.unknown}</Pill>
          <span>
            {copy.drafts.scheduledAt}: {formatInstant(null, job.timeZone, locale, job.publishAt) ?? <Missing />}
          </span>
          {job.demo ? <Pill tone='muted'>{copy.common.demo}</Pill> : null}
        </li>
      ))}
    </ul>
  );
}

export function DraftDetail({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='draft_read' label={copy.drafts.title}>
      {(draft) => (
        <article className='flex flex-col gap-3 rounded-[var(--rafii-radius-card)] border p-3'>
          <header className='flex flex-col gap-1'>
            <DraftMeta draft={draft} />
            <DraftFlags draft={draft} />
          </header>
          <p className='text-foreground text-sm break-words whitespace-pre-wrap' {...textAttributes(draft.language)}>
            {draft.text}
          </p>
          {draft.blockedByRetraction ? <p className='text-destructive text-xs'>{copy.drafts.blockedByRetraction}</p> : null}
          {draft.openings && draft.openings.length > 0 ? (
            <details className='text-sm'>
              <summary className='text-muted-foreground cursor-pointer text-xs'>{copy.drafts.openings}</summary>
              <ul className='mt-1 flex list-disc flex-col gap-1 pl-5'>
                {draft.openings.map((opening) => (
                  <li key={opening} {...textAttributes(draft.language)}>
                    {opening}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {draft.unknowns && draft.unknowns.length > 0 ? (
            <div className='text-xs'>
              <p className='font-medium'>{copy.drafts.unknowns(draft.unknowns.length)}</p>
              <ul className='text-muted-foreground list-disc pl-5'>
                {draft.unknowns.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {draft.warnings && draft.warnings.length > 0 ? (
            <div className='text-xs'>
              <p className='font-medium'>{copy.drafts.warnings(draft.warnings.length)}</p>
              <ul className='text-muted-foreground list-disc pl-5'>
                {draft.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <ScheduledJobs draft={draft} />
        </article>
      )}
    </QueryFrame>
  );
}

export function DraftEvidence({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='draft_evidence' label={copy.drafts.evidenceTitle} title={copy.drafts.evidenceTitle}>
      {(evidence) => (
        <div className='flex flex-col gap-3 text-sm'>
          {evidence.sources.length > 0 ? (
            <ul className='flex flex-col gap-1.5'>
              {evidence.sources.map((source) => (
                <li key={source.sourceId} className='flex flex-col gap-0.5 rounded-md border p-2'>
                  {source.available ? (
                    <>
                      <span className='font-medium break-words'>{source.title || <Missing />}</span>
                      <span className='text-muted-foreground flex flex-wrap gap-x-3 text-xs'>
                        {source.kind ? <span>{source.kind}</span> : null}
                        {source.host ? <span>{source.host}</span> : null}
                        {typeof source.approvedFacts === 'number' && typeof source.facts === 'number' ? (
                          <span>{copy.drafts.approvedFacts(source.approvedFacts, source.facts)}</span>
                        ) : null}
                        {source.retracted ? <Pill tone='attention'>{copy.drafts.blockedByRetraction}</Pill> : null}
                      </span>
                    </>
                  ) : (
                    <span className='text-muted-foreground text-xs'>{copy.drafts.sourceRemoved}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className='text-muted-foreground text-xs'>{copy.drafts.sources(0)}</p>
          )}
          {evidence.edges.length > 0 ? (
            <div className='flex flex-col gap-1'>
              <p className='text-xs font-medium'>{copy.drafts.relations}</p>
              <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
                {evidence.edges.map((edge) => (
                  <li key={`${edge.edge}:${edge.type}:${edge.id}`}>
                    {edge.edge.replaceAll('_', ' ')} · {edge.type}
                    {edge.title ? ` · ${edge.title}` : ''}
                    {edge.platform ? ` · ${edge.platform}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {evidence.voiceFit && evidence.voiceFit.findings && evidence.voiceFit.findings.length > 0 ? (
            <div className='flex flex-col gap-1'>
              <p className='text-xs font-medium'>{copy.drafts.voiceFit}</p>
              <ul className='flex flex-col gap-0.5 text-xs'>
                {evidence.voiceFit.findings.map((finding) => (
                  <li key={finding.trait} className='flex flex-wrap items-center gap-2'>
                    <Pill tone={finding.verdict === 'matches' ? 'good' : finding.verdict === 'differs' ? 'waiting' : 'muted'}>{finding.verdict}</Pill>
                    <span>{finding.trait}</span>
                    <span className='text-muted-foreground'>({finding.basis.replaceAll('_', ' ')})</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </QueryFrame>
  );
}

const editorProps = z.object({ actionId: z.literal('draft_edit'), name: z.string().regex(/^[A-Za-z][A-Za-z0-9_]{0,39}$/) });

function Editor({ draft, actionId, name, statementId }: { draft: DraftDetailData; actionId: string; name: string; statementId?: string }) {
  const { copy, locale } = useJourneyEnvironment();
  // Typed text and the revision it was based on live in the view's store, so a stream chunk, a patch or a refresh of the
  // draft never resets what the person wrote. The save carries the base revision; the server refuses it if the draft
  // changed meanwhile (no last-write-wins).
  const text = useBound<string>(name, undefined);
  const base = useBound<number>(`${name}Base`, undefined);
  const [touched, setTouched] = useState(false);
  const value = typeof text.value === 'string' ? text.value : draft.text;
  const baseRevision = typeof base.value === 'number' ? base.value : draft.revision ?? null;
  const changed = value.trim() !== draft.text.trim();
  const length = textLength(value.trim());
  const stale = typeof base.value === 'number' && typeof draft.revision === 'number' && base.value !== draft.revision;
  if (!draft.editable) {
    return <p className='text-muted-foreground text-sm'>{draft.editBlockedReason ?? copy.drafts.editBlocked}</p>;
  }
  const fieldId = `${statementId ?? name}-text`;
  return (
    <div className='flex flex-col gap-2'>
      <label htmlFor={fieldId} className='text-xs font-medium'>
        {copy.drafts.editLabel}
      </label>
      <Textarea
        id={fieldId}
        value={value}
        rows={8}
        aria-describedby={`${fieldId}-hint`}
        {...textAttributes(draft.language)}
        onChange={(event) => {
          if (!touched && typeof base.value !== 'number' && typeof draft.revision === 'number') base.set(draft.revision);
          setTouched(true);
          text.set(event.target.value);
        }}
      />
      <p id={`${fieldId}-hint`} className='text-muted-foreground text-xs'>
        <span className={cn('tabular-nums', draft.limit && length > draft.limit && 'text-destructive')}>
          {formatCount(length, locale)}
          {draft.limit ? ` / ${formatCount(draft.limit, locale)}` : ''}
        </span>{' '}
        · {copy.drafts.editHint}
      </p>
      {stale ? <p className='text-destructive text-xs'>{copy.states.stale}</p> : null}
      <GuardedAction
        actionId={actionId}
        controlId={statementId}
        ready={changed && value.trim().length > 0 && typeof baseRevision === 'number'}
        inputs={typeof baseRevision === 'number' ? { draftId: draft.draftId, revision: baseRevision, text: value.trim() } : null}
      />
    </div>
  );
}

export function DraftEditor({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = editorProps.safeParse(props);
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  return (
    <QueryFrame value={props.data} binding='draft_read' label={copy.drafts.editLabel}>
      {(draft) => <Editor draft={draft} actionId={literal.data.actionId} name={literal.data.name} statementId={statementId} />}
    </QueryFrame>
  );
}
