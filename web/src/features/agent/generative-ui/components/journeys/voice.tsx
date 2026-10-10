'use client';
/**
 * J04 — Brand Brain / Learn My Voice (lane E), from lane D's voice bindings over the real services: writing samples with
 * their exact use grants and eligibility, the approved voice next to the proposed one with evidence levels, learned vs
 * proposed preferences, every consent layer separately, and the learning status as the server derives it.
 *
 * Truth rules: nothing here says "trained" (Rafii trains no model); a proposed profile is not in effect until an owner
 * approves it; an eligibility exclusion names its reason; consent is shown per layer and changed only on the native
 * Memory/Brand pages. Writes are the original workspace commands behind lane D's action bridge.
 */
import { useState } from 'react';
import { z } from 'zod';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { formatInstant } from '../../journeys/format';
import { useBound, useJourneyEnvironment, useSelectionRecorder } from '../../journeys/runtime';
import type { VoiceSample } from '../../journeys/views';
import { InAppLink, CountValue, GuardedAction, Missing, Pill, QueryFrame, SelectToggle, toggleInOrder, Pager } from './shared';
import type { JourneyRendererProps } from './types';

export const MAX_SELECTED_SAMPLES = 50;
const SAMPLE_ID = /^[A-Za-z0-9_.:-]{1,120}$/;

function ids(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string' && SAMPLE_ID.test(v)) : [];
}

function epochOrIso(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) return new Date((value < 1e12 ? value * 1000 : value)).toISOString();
  return typeof value === 'string' ? value : null;
}

export function VoiceSourcePicker({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const selection = useBound<string[]>(`${statementId ?? 'samples'}Selected`, props.selected);
  const selected = ids(selection.value);
  const record = useSelectionRecorder(statementId ?? 'samples');
  return (
    <QueryFrame value={props.data} binding='voice_sources' label={copy.voice.samplesTitle} title={copy.voice.samplesTitle}>
      {(data, result) => {
        const excluded = new Map((data.eligibility?.excluded ?? []).map((x) => [x.sourceId, x.reason]));
        const toggle = (sample: VoiceSample) => {
          const next = toggleInOrder(selected, sample.sourceId, MAX_SELECTED_SAMPLES);
          selection.set(next);
          const byId = new Map(data.samples.map((s) => [s.sourceId, s]));
          record(
            next.map((id) => ({ type: 'voice_sample', id, title: byId.get(id)?.title ?? undefined })),
            data.samples.map((s) => ({ type: 'voice_sample', id: s.sourceId })),
          );
        };
        return (
          <>
          <div className='flex flex-col gap-2'>
            {data.eligibility ? (
              <p className='text-muted-foreground text-xs'>
                {copy.voice.eligibility(data.eligibility.purpose, data.eligibility.route)} · {data.eligibility.rule}
              </p>
            ) : null}
            <ul className='flex flex-col divide-y divide-border rounded-[var(--rafii-radius-card)] border'>
              {data.samples.map((sample) => {
                const isSelected = selected.includes(sample.sourceId);
                const reason = excluded.get(sample.sourceId);
                return (
                  <li key={sample.ref} className={cn('flex items-start gap-3 p-2.5', isSelected && 'bg-muted/40')}>
                    <SelectToggle
                      selected={isSelected}
                      label={sample.title ?? sample.excerpt ?? sample.sourceId}
                      disabled={!sample.active || Boolean(sample.revoked) || Boolean(reason)}
                      onToggle={() => toggle(sample)}
                    />
                    <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
                      <span className='text-sm font-medium break-words' dir='auto'>
                        {sample.title ?? sample.excerpt ?? <Missing />}
                      </span>
                      <span className='text-muted-foreground text-xs'>{[sample.platform, sample.language, sample.label, sample.origin].filter(Boolean).join(' · ')}</span>
                      <span className='flex flex-wrap gap-1'>
                        {!sample.active || sample.revoked ? <Pill tone='attention'>{copy.voice.revoked}</Pill> : null}
                        <Pill tone={sample.selected ? 'good' : 'muted'}>{sample.selected ? copy.voice.selected : copy.voice.notSelected}</Pill>
                        {reason ? <Pill tone='waiting'>{copy.voice.excluded[reason] ?? reason}</Pill> : null}
                      </span>
                      <span className='text-muted-foreground text-xs'>
                        {sample.useGrants.length
                          ? `${copy.voice.grants}: ${sample.useGrants.map((g) => [g.purpose, g.route].filter(Boolean).join(' · ')).join('; ')}`
                          : copy.voice.noGrants}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
            {selected.length ? <p className='text-muted-foreground text-xs'>{copy.common.selected(selected.length)} · {copy.common.selectionHint}</p> : null}
          </div>
            <Pager result={result} cursor={props.cursor} statementId={statementId} />
          </>
        );
      }}
    </QueryFrame>
  );
}

const analyzeProps = z.object({ actionId: z.literal('voice_profile_analyze_local') });

export function VoiceAnalyzeLocal({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = analyzeProps.safeParse(props);
  const selection = useBound<string[]>(`${statementId ?? 'analyze'}Samples`, props.samples);
  const picked = ids(selection.value);
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  return (
    <section aria-label={copy.voice.profileTitle} className='flex flex-col gap-1.5'>
      <p className='text-muted-foreground text-xs'>{copy.voice.analyzeHint}</p>
      <GuardedAction
        actionId={literal.data.actionId}
        controlId={statementId}
        ready={picked.length > 0 && picked.length <= MAX_SELECTED_SAMPLES}
        notReadyHint={copy.voice.pickSamples}
        inputs={picked.length ? { sourceIds: picked } : null}
      />
    </section>
  );
}

function Dimensions({ dims }: { dims: { id?: string | null; observation: string; evidenceLevel?: string | null; support?: number | null; counterEvidence?: number | null }[] }) {
  const { copy } = useJourneyEnvironment();
  if (dims.length === 0) return <Missing word='none' />;
  return (
    <ul className='flex flex-col gap-1 text-sm'>
      {dims.map((d, i) => (
        <li key={d.id ?? i} className='flex flex-col gap-0.5'>
          <span dir='auto'>{d.observation}</span>
          <span className='text-muted-foreground flex flex-wrap gap-2 text-xs'>
            <span>{d.evidenceLevel ? copy.voice.evidence[d.evidenceLevel] ?? d.evidenceLevel : copy.common.unknown}</span>
            {typeof d.support === 'number' ? <span>{copy.voice.supports(d.support)}</span> : null}
            {typeof d.counterEvidence === 'number' && d.counterEvidence > 0 ? <span>{copy.voice.against(d.counterEvidence)}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

const reviewProps = z.object({ actionId: z.literal('voice_profile_approve').optional().nullable() });

export function VoiceProfileReview({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  const literal = reviewProps.safeParse(props);
  const actionId = literal.success ? literal.data.actionId ?? undefined : undefined;
  return (
    <QueryFrame value={props.data} binding='voice_profile_state' label={copy.voice.profileTitle} title={copy.voice.profileTitle}>
      {(data) => (
        <div className='flex flex-col gap-3'>
          <div className='@container'>
            <div className='grid gap-3 @[34rem]:grid-cols-2'>
              <article className='flex flex-col gap-1.5 rounded-[var(--rafii-radius-card)] border p-3' aria-label={copy.voice.approved}>
                <h4 className='flex items-center gap-2 text-sm font-semibold'>
                  <Pill tone='good'>{copy.voice.approved}</Pill>
                  {data.approved?.stale ? <Pill tone='waiting'>{copy.voice.stale}</Pill> : null}
                </h4>
                {data.approved ? (
                  <>
                    {data.approved.approvedAt ? <span className='text-muted-foreground text-xs'>{formatInstant(epochOrIso(data.approved.approvedAt), timeZone, locale)}</span> : null}
                    {data.approved.tone ? <p className='text-sm' dir='auto'>{data.approved.tone}</p> : null}
                    <Dimensions dims={data.approved.dimensions} />
                  </>
                ) : (
                  <p className='text-muted-foreground text-sm'>{copy.voice.noneApproved}</p>
                )}
              </article>
              <article className='flex flex-col gap-1.5 rounded-[var(--rafii-radius-card)] border border-dashed p-3' aria-label={copy.voice.proposed}>
                <h4 className='flex items-center gap-2 text-sm font-semibold'>
                  <Pill tone='waiting'>{copy.voice.proposed}</Pill>
                  {data.proposed?.method ? <span className='text-muted-foreground text-xs font-normal'>{copy.voice.method[data.proposed.method] ?? data.proposed.method}</span> : null}
                </h4>
                {data.proposed ? (
                  <>
                    {data.proposed.proposedAt ? <span className='text-muted-foreground text-xs'>{formatInstant(epochOrIso(data.proposed.proposedAt), timeZone, locale)}</span> : null}
                    <Dimensions dims={data.proposed.dimensions} />
                    {data.proposed.unknowns && data.proposed.unknowns.length > 0 ? (
                      <ul className='text-muted-foreground list-disc pl-5 text-xs'>
                        {data.proposed.unknowns.map((u) => (
                          <li key={u}>{u}</li>
                        ))}
                      </ul>
                    ) : null}
                  </>
                ) : (
                  <p className='text-muted-foreground text-sm'>{copy.voice.noneProposed}</p>
                )}
              </article>
            </div>
          </div>
          {data.derived ? (
            <p className='text-muted-foreground text-xs'>
              {copy.voice.affects(data.derived.draftsOnVoice, data.derived.scheduledPostsOnVoice)} ({copy.common.rule}: {data.derived.rule})
            </p>
          ) : null}
          {data.note ? <p className='text-muted-foreground text-xs'>{data.note}</p> : null}
          {actionId && data.proposed ? (
            <InAppLink href='/app/workspace/brand?section=teach&step=review'>{copy.common.open} · Brand Brain</InAppLink>
          ) : null}
        </div>
      )}
    </QueryFrame>
  );
}

const prefProps = z.object({ actionId: z.literal('preference_decide').optional().nullable() });

export function VoicePreferenceList({ props, statementId }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  const literal = prefProps.safeParse(props);
  const actionId = literal.success ? literal.data.actionId ?? undefined : undefined;
  return (
    <QueryFrame value={props.data} binding='voice_preferences' label={copy.voice.prefsTitle} title={copy.voice.prefsTitle}>
      {(data) => (
        <div className='flex flex-col gap-3'>
          <div className='flex flex-col gap-1'>
            <h4 className='text-xs font-semibold'>{copy.voice.pending}</h4>
            {data.pending.length === 0 ? (
              <p className='text-muted-foreground text-xs'>{copy.voice.noPending}</p>
            ) : (
              <ul className='flex flex-col gap-1.5'>
                {data.pending.map((p) => (
                  <li key={p.id} className='flex flex-col gap-1 rounded-md border border-dashed p-2 text-sm'>
                    <span dir='auto'>{p.statement ?? <Missing />}</span>
                    {p.why ? (
                      <span className='text-muted-foreground text-xs' dir='auto'>
                        {copy.voice.why}: {p.why}
                      </span>
                    ) : null}
                    <span className='text-muted-foreground text-xs'>
                      {[p.scopeLabel, p.expiresAt ? `${copy.calendar.proposalExpires}: ${formatInstant(epochOrIso(p.expiresAt), timeZone, locale)}` : null].filter(Boolean).join(' · ')}
                    </span>
                    {actionId ? (
                      <span className='flex flex-wrap gap-2'>
                        <GuardedAction actionId={actionId} controlId={`${statementId ?? 'prefs'}:${p.id}:remember`} ready inputs={{ proposalId: p.id, decision: 'remember' }} label={copy.voice.remember} quiet />
                        <GuardedAction actionId={actionId} controlId={`${statementId ?? 'prefs'}:${p.id}:dismiss`} ready inputs={{ proposalId: p.id, decision: 'dismiss' }} label={copy.voice.dismiss} quiet />
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className='flex flex-col gap-1'>
            <h4 className='text-xs font-semibold'>{copy.voice.learned}</h4>
            {data.learned.length === 0 ? (
              <p className='text-muted-foreground text-xs'>{copy.voice.noLearned}</p>
            ) : (
              <ul className='flex flex-col gap-1 text-sm'>
                {data.learned.map((item, i) => (
                  <li key={item.id ?? i} className='flex flex-wrap items-center gap-2'>
                    <span dir='auto'>{item.statement ?? <Missing />}</span>
                    {item.status && item.status !== 'active' ? <Pill tone='muted'>{item.status}</Pill> : null}
                    {item.evidenceSummary ? <span className='text-muted-foreground text-xs'>{item.evidenceSummary}</span> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {data.rule ? <p className='text-muted-foreground text-xs'>{data.rule}</p> : null}
        </div>
      )}
    </QueryFrame>
  );
}

function OnOff({ value }: { value: boolean | null | undefined }) {
  const { copy } = useJourneyEnvironment();
  if (typeof value !== 'boolean') return <Missing />;
  return <Pill tone={value ? 'good' : 'muted'}>{value ? copy.voice.on : copy.voice.off}</Pill>;
}

export function VoiceConsentPanel({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='voice_consent' label={copy.voice.consentTitle} title={copy.voice.consentTitle}>
      {(data) => {
        const cloud = data.cloudMemory && typeof data.cloudMemory.cloud === 'boolean' ? (data.cloudMemory.cloud as boolean) : null;
        const web = data.webResearch && typeof data.webResearch.web === 'boolean' ? (data.webResearch.web as boolean) : null;
        return (
          <div className='flex flex-col gap-2'>
            <dl className='grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5 text-sm'>
              <dt>{copy.voice.layer.samples}</dt>
              <dd className='text-muted-foreground text-xs'>{copy.voice.samplesGranted(data.samples.grantedForAnalysis, data.samples.grantedForGeneration, data.samples.total)}</dd>
              <dt>{copy.voice.layer.cloudMemory}</dt>
              <dd>
                <OnOff value={cloud} />
              </dd>
              <dt>{copy.voice.layer.cloudExtraction}</dt>
              <dd>
                <OnOff value={data.learning.cloudExtraction} />
              </dd>
              <dt>{copy.voice.layer.media}</dt>
              <dd>
                <OnOff value={data.media.cloud} />
              </dd>
              <dt>{copy.voice.layer.webResearch}</dt>
              <dd>
                <OnOff value={web} />
              </dd>
            </dl>
            <p className='text-muted-foreground text-xs'>{data.rule}</p>
            {!data.owner ? <p className='text-muted-foreground text-xs'>{copy.voice.ownerDecides}</p> : null}
            {data.href ? (
              <InAppLink href={data.href}>
                {copy.common.open}
              </InAppLink>
            ) : null}
          </div>
        );
      }}
    </QueryFrame>
  );
}

export function VoiceLearningStatus({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='voice_learning_status' label={copy.voice.learningTitle} title={copy.voice.learningTitle}>
      {(data) => (
        <div className='flex flex-col gap-1.5 text-sm'>
          <p>
            <Pill tone={data.enabled ? 'good' : 'muted'}>{data.enabled === true ? copy.voice.learningOn : data.enabled === false ? copy.voice.learningOff : copy.common.unknown}</Pill>
          </p>
          <dl className='grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm'>
            <dt className='text-muted-foreground'>{copy.voice.eventsWaiting}</dt>
            <dd>
              <CountValue value={data.eventsWaiting} />
            </dd>
            <dt className='text-muted-foreground'>{copy.voice.pendingProposals}</dt>
            <dd>
              <CountValue value={data.pendingProposals} />
            </dd>
            <dt className='text-muted-foreground'>{copy.voice.newestProposal}</dt>
            <dd>{formatInstant(data.newestProposalAt, timeZone, locale) ?? <Missing word='none' />}</dd>
          </dl>
          {data.lastRunNote ? <p className='text-muted-foreground text-xs'>{data.lastRunNote}</p> : null}
          <p className='text-muted-foreground text-xs'>{data.rule}</p>
        </div>
      )}
    </QueryFrame>
  );
}

const importProps = z.object({ actionId: z.literal('voice_samples_import'), name: z.string().regex(/^[A-Za-z][A-Za-z0-9_]{0,39}$/) });

export function VoiceSampleImport({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = importProps.safeParse(props);
  const name = literal.success ? literal.data.name : 'sample';
  const text = useBound<string>(name, undefined);
  const title = useBound<string>(`${name}Title`, undefined);
  const [confirmed, setConfirmed] = useState(false);
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  const value = typeof text.value === 'string' ? text.value : '';
  const titleValue = typeof title.value === 'string' ? title.value : '';
  const fieldId = `${statementId ?? name}-sample`;
  const ready = confirmed && value.trim().length >= 20 && value.length <= 8000;
  return (
    <section aria-label={copy.voice.importTitle} className='flex flex-col gap-2'>
      <h3 className='text-sm font-semibold'>{copy.voice.importTitle}</h3>
      <label className='flex flex-col gap-1 text-xs' htmlFor={fieldId}>
        {copy.voice.importText}
        <Textarea id={fieldId} rows={6} value={value} dir='auto' onChange={(e) => text.set(e.target.value)} />
      </label>
      <label className='flex flex-col gap-1 text-xs' htmlFor={`${fieldId}-title`}>
        {copy.voice.importTitleField}
        <Input id={`${fieldId}-title`} value={titleValue} maxLength={160} onChange={(e) => title.set(e.target.value)} />
      </label>
      <label className='flex items-start gap-2 text-xs' htmlFor={`${fieldId}-confirm`}>
        <input id={`${fieldId}-confirm`} type='checkbox' className='mt-0.5' aria-label={copy.voice.importConfirm} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        <span>{copy.voice.importConfirm}</span>
      </label>
      <p className='text-muted-foreground text-xs'>{copy.voice.importHint}</p>
      <GuardedAction
        actionId={literal.data.actionId}
        controlId={statementId}
        ready={ready}
        inputs={ready ? { text: value.trim(), ...(titleValue.trim() ? { title: titleValue.trim().slice(0, 160) } : {}), confirmed: true } : null}
      />
    </section>
  );
}
