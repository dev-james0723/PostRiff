'use client';

/**
 * Proof revisions and the next-week decision inside the existing Growth Loop proof section (PRD R-PROOF-01/02).
 * Each figure shows its definition, data state (partial and unavailable are labelled, with the reason) and the evidence
 * it counts, plus where those records live; late data appears as a new revision with what changed, in words, and
 * earlier revisions stay listed. Weekly and monthly proofs are both reachable and paged. Owners can recompute a
 * completed period from stored records (the recomputed proof is shown and focused) and accept, edit, reject or revoke
 * a proposed next-week action. Hidden when the deployment has proof v2 off (the existing recap cards below keep
 * working). English and Traditional Chinese follow the person's language preference (D-022).
 */
import { useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { SegmentedControl, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { ToneChip } from '@/features/coworker/parts';
import { useChannels } from '@/lib/api/hooks';
import { usePreferences } from '@/lib/preferences';
import { formatDate, formatDateTime } from '@/lib/time';
import { useInlineForm } from '@/lib/growth-v2/inline-form';
import { idempotencyKey, isFeatureDisabled } from '@/lib/growth-v2/request';
import { useDecide, useProof, useProofs, useRefreshProof } from '@/lib/growth-v2/proof-hooks';
import {
  appliesFromText, correctionText, coverageReasons, decisionActions, evidenceGroups, evidenceLink, FIGURE_ORDER, figureState, figureText, linkedProofId,
  mergeProofPages, planningText, proofCopy, proofFailure, proofLocale, scopeText, serverText
} from '@/lib/growth-v2/proof-present';
import type { DecisionAction, ProofView, StrategyDecision } from '@/lib/growth-v2/proof-types';

type Copy = ReturnType<typeof proofCopy>;
type Lang = ReturnType<typeof proofLocale>;
type Frequency = 'weekly' | 'monthly';
type Failure = { code?: string; status?: number; message?: string };

export function ProofRevisions({ owner }: { owner: boolean }) {
  const { locale } = usePreferences();
  const lang = proofLocale(locale);
  const copy = proofCopy(locale);
  const [frequency, setFrequency] = useState<Frequency>('weekly');
  const proofs = useProofs(frequency);
  const refresh = useRefreshProof();
  const [notice, setNotice] = useState<string | null>(null);
  // A proof that must stay visible even before (or without) its page loading: the one just recomputed, or the one a
  // proof link named.
  const [pinned, setPinned] = useState<{ proof: ProofView; why: 'recomputed' | 'linked' } | null>(null);
  const [focusProof, setFocusProof] = useState<string | null>(null);
  const [linkedId] = useState(() => (typeof window === 'undefined' ? null : linkedProofId(window.location.search)));
  const linked = useProof(linkedId);
  const linkedShown = useRef(false);

  // A proof link opens that proof wherever it is: its frequency, kept visible, scrolled to and focused.
  useEffect(() => {
    const proof = linked.data?.proof;
    if (!proof || linkedShown.current) return;
    linkedShown.current = true;
    setFrequency(proof.frequency);
    setPinned({ proof, why: 'linked' });
    setFocusProof(proof.proofId);
  }, [linked.data]);

  const shownPinned = pinned && pinned.proof.frequency === frequency ? pinned : null;
  const list = mergeProofPages(proofs.data?.pages, shownPinned?.proof);

  useEffect(() => {
    if (!focusProof) return;
    const card = document.getElementById(`proof-${focusProof}`);
    if (!card) return;
    card.scrollIntoView({ block: 'start' });
    card.focus({ preventScroll: true });
    setFocusProof(null);
  }, [focusProof, list]);

  if (proofs.isError && isFeatureDisabled(proofs.error)) return null;

  async function recompute(next: Frequency) {
    setNotice(null);
    try {
      const result = await refresh.mutateAsync({ frequency: next });
      if (result.reason === 'period_in_progress') setNotice(copy.inProgress);
      else if (!result.verified) setNotice(copy.unverified);
      else setNotice(result.appended && result.revision ? copy.appended(result.revision) : copy.noChange);
      if (result.proof) {
        // Show the proof that was just recomputed: its frequency's list, pinned until its page has it, focused.
        setFrequency(result.proof.frequency);
        setPinned({ proof: result.proof, why: 'recomputed' });
        setFocusProof(result.proof.proofId);
      }
    } catch (error) {
      setNotice(proofFailure(error as Failure, copy, lang));
    }
  }

  return (
    <section aria-labelledby='proof-v2-title' className='flex flex-col gap-3' lang={lang}>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h3 id='proof-v2-title' className='text-base font-medium'>{copy.title}</h3>
        {owner && (
          <div className='flex flex-wrap gap-2'>
            <Button variant='glass' disabled={refresh.isPending} onClick={() => void recompute('weekly')}>{refresh.isPending ? copy.refreshing : copy.refresh}</Button>
            <Button variant='quiet' disabled={refresh.isPending} onClick={() => void recompute('monthly')}>{copy.refreshMonthly}</Button>
          </div>
        )}
      </div>
      <SegmentedControl label={copy.frequencyLabel} size='sm' widths='content' className='self-start' value={frequency} onChange={setFrequency}
                        options={(['weekly', 'monthly'] as const).map((value) => ({ value, label: copy.frequency[value] }))} />
      <p className='text-muted-foreground text-sm'>{copy.intro}</p>
      {notice && <p className='text-sm' role='status'>{notice}</p>}
      {proofs.isPending && !list.length ? <StateMessage kind='loading' layout='inline' title={copy.title} />
        : proofs.isError && !list.length ? (
          <StateMessage kind='error' layout='inline' title={copy.loadError} description={proofFailure(proofs.error as Failure, copy, lang)}
                        action={<Button variant='glass' onClick={() => void proofs.refetch()}>{copy.retry}</Button>} />
        ) : list.length === 0 ? <StateMessage kind='empty' layout='inline' title={copy.empty} />
        : list.map((proof) => (
          <ProofCard key={proof.proofId} proof={proof} owner={owner} copy={copy} lang={lang} locale={locale}
                     badge={shownPinned?.proof.proofId === proof.proofId ? (shownPinned.why === 'recomputed' ? copy.recomputed : copy.linked) : null} />
        ))}
      {proofs.hasNextPage && (
        <Button variant='quiet' className='self-start' disabled={proofs.isFetchingNextPage} onClick={() => void proofs.fetchNextPage()}>
          {proofs.isFetchingNextPage ? copy.loadingMore : copy.loadMore}
        </Button>
      )}
    </section>
  );
}

function ProofCard({ proof, owner, copy, lang, locale, badge }: { proof: ProofView; owner: boolean; copy: Copy; lang: Lang; locale: string; badge: string | null }) {
  const counts = proof.latest.counts;
  const figures = counts.figures;
  const headingId = useId();
  const local = (epoch: number) => formatDate(epoch, { timeZone: proof.timeZone });
  const state = proof.latest.dataState;
  const reasons = coverageReasons(counts, proof.maturity.mature, copy);
  return (
    <Surface material='quiet' className='rafii-focus flex scroll-mt-24 flex-col gap-4 p-5' as='article' aria-labelledby={headingId} id={`proof-${proof.proofId}`} tabIndex={-1}>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <h4 id={headingId} className='text-sm font-medium'>{local(proof.periodStart)}–{local(proof.periodEnd - 1)} · {copy.frequency[proof.frequency]} · {copy.revision(proof.latest.revision)}</h4>
        <div className='flex flex-wrap items-center gap-2'>
          {badge && <ToneChip tone='neutral' icon='sparkles'>{badge}</ToneChip>}
          <ToneChip tone={state === 'available' ? 'success' : 'attention'} icon={state === 'available' ? 'check' : 'warning'}>{copy.overall[state] ?? state}</ToneChip>
        </div>
      </div>
      <p className='text-muted-foreground text-xs'>
        {proof.maturity.mature ? copy.mature : copy.maturing} · {copy.timeZone}: {proof.timeZone} · {copy.asOf} {formatDateTime(proof.latest.asOf)} · {proof.latest.definitionVersion}
      </p>
      {state !== 'available' && reasons.length > 0 && (
        <div className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-control)] px-3 py-2 text-xs' role='note'>
          <p className='font-medium'>{copy.whyPartial}</p>
          <ul className='text-muted-foreground list-disc pl-4'>{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </div>
      )}
      <dl className='grid gap-3 sm:grid-cols-2'>
        {FIGURE_ORDER.map((name) => {
          const figure = figures[name];
          const coverage = counts.coverage?.find((entry) => entry.figure === name);
          const status = figureState(name, figure, copy, coverage?.reason);
          const groups = evidenceGroups(figure, copy);
          const pointer = evidenceLink(figure, copy);
          return (
            <div key={name} className='flex min-w-0 flex-col gap-1'>
              <dt className='text-muted-foreground text-xs'>
                {copy.figure[name]}
                {status.label && <span className='text-foreground'> · {status.label}</span>}
              </dt>
              <dd className='text-sm tabular-nums'>{figureText(name, figure, copy)}</dd>
              {status.state === 'partial' && status.reason && <dd className='text-muted-foreground text-xs'>{status.reason}</dd>}
              {figure && (
                <dd className='text-xs'>
                  <details>
                    <summary className='rafii-focus min-h-11 cursor-pointer text-muted-foreground'>{copy.evidence}</summary>
                    <p className='text-muted-foreground py-1'>{serverText(figure.definition, copy)}</p>
                    {groups.map((group) => <p key={group.label} className='text-muted-foreground break-all'>{group.label}: {group.ids.join(', ')}</p>)}
                    {figure.evidenceTruncated && <p className='text-muted-foreground'>{copy.truncated}</p>}
                    {pointer && (
                      <p className='text-muted-foreground flex flex-wrap items-center gap-x-2'>
                        {copy.evidenceRecords}: {local(proof.periodStart)}–{local(proof.periodEnd - 1)}
                        <Link className='rafii-focus text-foreground inline-flex min-h-11 items-center underline underline-offset-4' href={pointer.href}>{pointer.label}</Link>
                      </p>
                    )}
                  </details>
                </dd>
              )}
            </div>
          );
        })}
      </dl>
      {proof.revisions.length > 1 && (
        <details className='text-sm'>
          <summary className='rafii-focus min-h-11 cursor-pointer'>{copy.history}</summary>
          <ol className='text-muted-foreground flex flex-col gap-2 py-2 text-xs'>
            {proof.revisions.map((revision) => (
              <li key={revision.id} className='break-words'>
                {copy.revision(revision.revision)} · {formatDateTime(revision.createdAt)} · {copy.reason[revision.reason] ?? revision.reason}
                {revision.correction.length > 0 && <> — {copy.correction}: {revision.correction.map((entry) => correctionText(entry, copy)).join('; ')}</>}
              </li>
            ))}
          </ol>
        </details>
      )}
      <NextStep proposals={proof.nextStep.proposals} owner={owner} copy={copy} lang={lang} locale={locale} timeZone={proof.timeZone} />
      <ul className='text-muted-foreground list-disc pl-5 text-xs'>
        {counts.limitations.map((limitation) => <li key={limitation}>{serverText(limitation, copy)}</li>)}
      </ul>
    </Surface>
  );
}

function NextStep({ proposals, owner, copy, lang, locale, timeZone }: { proposals: StrategyDecision[]; owner: boolean; copy: Copy; lang: Lang; locale: string; timeZone: string }) {
  return (
    <section className='flex flex-col gap-2 border-t border-border pt-3' aria-label={copy.nextStep}>
      <h5 className='text-sm font-medium'>{copy.nextStep}</h5>
      <p className='text-muted-foreground text-xs'>{copy.proposalRule}</p>
      {proposals.length === 0 ? <p className='text-muted-foreground text-sm'>{copy.noProposal}</p>
        : proposals.map((decision) => <DecisionRow key={decision.id} decision={decision} owner={owner} copy={copy} lang={lang} locale={locale} timeZone={timeZone} />)}
    </section>
  );
}

function DecisionRow({ decision, owner, copy, lang, locale, timeZone }: { decision: StrategyDecision; owner: boolean; copy: Copy; lang: Lang; locale: string; timeZone: string }) {
  const decide = useDecide();
  const channels = useChannels();
  const [editing, setEditing] = useState(false);
  const [statement, setStatement] = useState(decision.statement);
  const [channelId, setChannelId] = useState('');
  const [failure, setFailure] = useState<string | null>(null);
  const [planning, setPlanning] = useState<string[]>([]);
  const keys = useRef(new Map<string, string>());
  const fieldId = useId();
  const accountId = useId();
  const rowId = useId();
  const [focusId, setFocusId] = useState<string | null>(null);

  // The form always starts from the decision as it is now (a newer revision may have arrived since it was last open),
  // cancelling discards what was typed, and saving names the revision the form was opened on: if the decision changed
  // meanwhile the server refuses (409) instead of the edit silently replacing wording the person never saw.
  const [editRevision, setEditRevision] = useState<number | null>(null);
  function openEdit() {
    setStatement(decision.statement);
    setChannelId('');
    setFailure(null);
    setEditRevision(decision.revision);
    setEditing(true);
  }
  function cancelEdit() {
    setEditing(false);
    setStatement(decision.statement);
    setChannelId('');
    setEditRevision(null);
    setFocusId(`${rowId}-edit`);
  }
  const editForm = useInlineForm<HTMLTextAreaElement>(editing, cancelEdit);
  useEffect(() => {   // focus returns to the Edit button on cancel, to the decision's wording after a change
    if (!focusId) return;
    document.getElementById(focusId)?.focus();
    setFocusId(null);
  }, [focusId, editing, decision.revision]);
  const channelName = (id: string) => {
    const channel = channels.data?.channels.find((c) => c.id === id);
    return channel ? `${channel.platform} · ${channel.account || channel.id}` : id;
  };

  async function act(action: DecisionAction, extra: { statement?: string; scope?: { channelId: string } } = {}) {
    setFailure(null);
    const expected = action === 'edit' && editRevision !== null ? editRevision : decision.revision;
    const intent = `${action}:${expected}:${extra.statement ?? ''}:${extra.scope?.channelId ?? ''}`;
    if (!keys.current.has(intent)) keys.current.set(intent, idempotencyKey('decide'));
    try {
      const result = await decide.mutateAsync({ decisionId: decision.id, body: { action, expectedRevision: expected, idempotencyKey: keys.current.get(intent) as string, ...extra } });
      if (!result.verified) {
        setFailure(copy.unverified);
        return;
      }
      keys.current.delete(intent);
      setEditing(false);
      setEditRevision(null);
      setPlanning(planningText(result.planning, copy, locale));
      setFocusId(`${rowId}-statement`);
      toast.success(<span lang={lang}>{copy.status[result.decision.status] ?? result.decision.status}</span>);
    } catch (error) {
      const failed = error as Failure;
      // The decision changed while the form was open: its current wording is now shown above the form, so a second
      // Save is a choice made after seeing it (it applies to the latest revision).
      if (action === 'edit' && failed?.code === 'revision_conflict') setEditRevision(null);
      setFailure(proofFailure(failed, copy, lang));
    }
  }

  const actions = decisionActions(decision, owner);
  const appliesFrom = appliesFromText(decision, timeZone, locale);
  const scope = scopeText(decision.scope, copy, channelName);
  return (
    <article className='rafii-quiet flex min-w-0 flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3' aria-label={decision.statement}>
      <div className='flex flex-wrap items-center gap-2'>
        <ToneChip tone={decision.inEffect ? 'success' : 'neutral'} icon={decision.inEffect ? 'check' : 'circle'}>{copy.status[decision.status] ?? decision.status}</ToneChip>
        <span className='text-muted-foreground text-xs'>{copy.revision(decision.revision)}</span>
        {appliesFrom && decision.inEffect && <span className='text-muted-foreground text-xs'>{copy.appliesFrom} {appliesFrom}</span>}
      </div>
      <p id={`${rowId}-statement`} tabIndex={-1} className='rafii-focus text-sm break-words' dir='auto'>{decision.statement}</p>
      {scope.length > 0 && <p className='text-muted-foreground text-xs'>{scope.join(' · ')}</p>}
      {planning.length > 0 && <p className='text-muted-foreground text-xs' role='status'>{planning.join(' ')}</p>}
      {failure && <p role='alert' className='text-destructive text-sm'>{failure}</p>}
      {editing ? (
        <form ref={editForm.formRef} className='grid min-w-0 gap-2' onSubmit={(event) => { event.preventDefault(); void act('edit', { statement, ...(channelId ? { scope: { channelId } } : {}) }); }}>
          <label className='grid gap-1 text-sm' htmlFor={fieldId}>
            {copy.editLabel}
            <textarea id={fieldId} ref={editForm.firstRef} aria-label={copy.editLabel} maxLength={240} required minLength={3} className='rafii-focus rafii-quiet min-h-20 rounded-xl border border-border p-3 text-base'
                      dir='auto' value={statement} onChange={(event) => setStatement(event.target.value)} />
          </label>
          {!decision.scope.channelId && (
            <div className='grid min-w-0 gap-1'>
              <label className='grid min-w-0 gap-1 text-sm' htmlFor={accountId}>
                {copy.narrowAccount}
                <select id={accountId} className='rafii-focus rafii-quiet min-h-11 w-full max-w-full min-w-0 rounded-xl border border-border px-3 text-base' value={channelId} onChange={(event) => setChannelId(event.target.value)}>
                  <option value=''>{copy.anyAccount}</option>
                  {(channels.data?.channels ?? []).map((channel) => <option key={channel.id} value={channel.id}>{channel.platform} · {channel.account || channel.id}</option>)}
                </select>
              </label>
              {channels.isError && (
                <p role='alert' className='text-destructive flex flex-wrap items-center gap-2 text-xs'>
                  {copy.channelsError}
                  <Button type='button' variant='quiet' onClick={() => void channels.refetch()}>{copy.retry}</Button>
                </p>
              )}
            </div>
          )}
          <div className='flex flex-wrap gap-2'>
            <Button type='submit' variant='glass' disabled={decide.isPending}>{copy.save}</Button>
            <Button type='button' variant='quiet' onClick={cancelEdit}>{copy.cancel}</Button>
          </div>
        </form>
      ) : actions.length > 0 && (
        <div className='flex flex-wrap gap-2'>
          {actions.map((action) => (
            <Button key={action} id={`${rowId}-${action}`} variant={action === 'accept' ? 'glass' : 'quiet'} disabled={decide.isPending}
                    onClick={() => (action === 'edit' ? openEdit() : void act(action))}>{copy.action[action]}</Button>
          ))}
        </div>
      )}
    </article>
  );
}
