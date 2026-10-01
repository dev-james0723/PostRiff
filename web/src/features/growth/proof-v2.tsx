'use client';

/**
 * Proof revisions and the next-week decision inside the existing Growth Loop proof section (PRD R-PROOF-01/02).
 * Each figure shows its definition, data state and the evidence ids it counts; late data appears as a new revision
 * with what changed, earlier revisions stay listed. Owners can recompute a completed period from stored records and
 * accept, edit, reject or revoke a proposed next-week action. Hidden when the deployment has proof v2 off (the
 * existing recap cards below keep working). English and Traditional Chinese follow the person's language preference.
 */
import { useEffect, useId, useRef, useState } from 'react';
import { toast } from 'sonner';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { ToneChip } from '@/features/coworker/parts';
import { useChannels } from '@/lib/api/hooks';
import { usePreferences } from '@/lib/preferences';
import { formatDate, formatDateTime } from '@/lib/time';
import { errorCode, errorMessage, idempotencyKey, isFeatureDisabled } from '@/lib/growth-v2/request';
import { useDecide, useProofs, useRefreshProof } from '@/lib/growth-v2/proof-hooks';
import { correctionText, decisionActions, evidenceGroups, FIGURE_ORDER, figureText, proofCopy, scopeText } from '@/lib/growth-v2/proof-present';
import type { DecisionAction, ProofView, StrategyDecision } from '@/lib/growth-v2/proof-types';

type Copy = ReturnType<typeof proofCopy>;

export function ProofRevisions({ owner }: { owner: boolean }) {
  const proofs = useProofs('weekly');
  const refresh = useRefreshProof();
  const copy = proofCopy(usePreferences().locale);
  const [notice, setNotice] = useState<string | null>(null);
  if (proofs.isError && isFeatureDisabled(proofs.error)) return null;
  if (proofs.isPending) return <StateMessage kind='loading' title={copy.title} />;
  if (proofs.isError) return <StateMessage kind='error' title={copy.title} description={errorMessage(proofs.error)} />;

  async function recompute(frequency: 'weekly' | 'monthly') {
    setNotice(null);
    try {
      const result = await refresh.mutateAsync({ frequency });
      if (result.reason === 'period_in_progress') setNotice(copy.inProgress);
      else if (!result.verified) setNotice(copy.unverified);
      else setNotice(result.appended && result.revision ? copy.appended(result.revision) : copy.noChange);
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }

  return (
    <section aria-labelledby='proof-v2-title' className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h3 id='proof-v2-title' className='text-base font-medium'>{copy.title}</h3>
        {owner && (
          <div className='flex flex-wrap gap-2'>
            <Button variant='glass' disabled={refresh.isPending} onClick={() => void recompute('weekly')}>{refresh.isPending ? copy.refreshing : copy.refresh}</Button>
            <Button variant='quiet' disabled={refresh.isPending} onClick={() => void recompute('monthly')}>{copy.refreshMonthly}</Button>
          </div>
        )}
      </div>
      <p className='text-muted-foreground text-sm'>{copy.intro}</p>
      {notice && <p className='text-sm' role='status'>{notice}</p>}
      {proofs.data.proofs.length === 0 ? <StateMessage kind='empty' layout='inline' title={copy.empty} />
        : proofs.data.proofs.map((proof) => <ProofCard key={proof.proofId} proof={proof} owner={owner} copy={copy} />)}
    </section>
  );
}

function ProofCard({ proof, owner, copy }: { proof: ProofView; owner: boolean; copy: Copy }) {
  const figures = proof.latest.counts.figures;
  const headingId = useId();
  const local = (epoch: number) => formatDate(epoch, { timeZone: proof.timeZone });
  return (
    <Surface material='quiet' className='flex flex-col gap-4 p-5' as='article' aria-labelledby={headingId} id={`proof-${proof.proofId}`}>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <h4 id={headingId} className='text-sm font-medium'>{local(proof.periodStart)}–{local(proof.periodEnd - 1)} · {copy.revision(proof.latest.revision)}</h4>
        <ToneChip tone={proof.latest.dataState === 'available' ? 'success' : 'attention'} icon={proof.maturity.mature ? 'check' : 'clock'}>
          {proof.maturity.mature ? copy.mature : copy.maturing}
        </ToneChip>
      </div>
      <p className='text-muted-foreground text-xs'>{copy.timeZone}: {proof.timeZone} · {copy.asOf} {formatDateTime(proof.latest.asOf)} · {proof.latest.definitionVersion}</p>
      <dl className='grid gap-3 sm:grid-cols-2'>
        {FIGURE_ORDER.map((name) => {
          const figure = figures[name];
          const groups = evidenceGroups(figure);
          return (
            <div key={name} className='flex flex-col gap-1'>
              <dt className='text-muted-foreground text-xs'>{copy.figure[name]}</dt>
              <dd className='text-sm tabular-nums'>{figureText(name, figure, copy)}</dd>
              {figure && (
                <dd className='text-xs'>
                  <details>
                    <summary className='rafii-focus min-h-11 cursor-pointer text-muted-foreground'>{copy.evidence}</summary>
                    <p className='text-muted-foreground py-1'>{figure.definition}</p>
                    {groups.map((group) => <p key={group.label} className='text-muted-foreground break-all'>{group.label}: {group.ids.join(', ')}</p>)}
                    {figure.evidenceTruncated && <p className='text-muted-foreground'>{copy.truncated}</p>}
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
              <li key={revision.id}>
                {copy.revision(revision.revision)} · {formatDateTime(revision.createdAt)} · {copy.reason[revision.reason] ?? revision.reason}
                {revision.correction.length > 0 && <> — {copy.correction}: {revision.correction.map((entry) => correctionText(entry, copy)).join('; ')}</>}
              </li>
            ))}
          </ol>
        </details>
      )}
      <NextStep proposals={proof.nextStep.proposals} owner={owner} copy={copy} />
      <ul className='text-muted-foreground list-disc pl-5 text-xs'>
        {proof.latest.counts.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
      </ul>
    </Surface>
  );
}

function NextStep({ proposals, owner, copy }: { proposals: StrategyDecision[]; owner: boolean; copy: Copy }) {
  return (
    <section className='flex flex-col gap-2 border-t border-border pt-3' aria-label={copy.nextStep}>
      <h5 className='text-sm font-medium'>{copy.nextStep}</h5>
      <p className='text-muted-foreground text-xs'>{copy.proposalRule}</p>
      {proposals.length === 0 ? <p className='text-muted-foreground text-sm'>{copy.noProposal}</p>
        : proposals.map((decision) => <DecisionRow key={decision.id} decision={decision} owner={owner} copy={copy} />)}
    </section>
  );
}

function DecisionRow({ decision, owner, copy }: { decision: StrategyDecision; owner: boolean; copy: Copy }) {
  const decide = useDecide();
  const channels = useChannels();
  const [editing, setEditing] = useState(false);
  const [statement, setStatement] = useState(decision.statement);
  const [channelId, setChannelId] = useState('');
  const [failure, setFailure] = useState<string | null>(null);
  const keys = useRef(new Map<string, string>());
  const fieldId = useId();
  const rowId = useId();
  const [focusId, setFocusId] = useState<string | null>(null);
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
    const intent = `${action}:${decision.revision}:${extra.statement ?? ''}:${extra.scope?.channelId ?? ''}`;
    if (!keys.current.has(intent)) keys.current.set(intent, idempotencyKey('decide'));
    try {
      const result = await decide.mutateAsync({ decisionId: decision.id, body: { action, expectedRevision: decision.revision, idempotencyKey: keys.current.get(intent) as string, ...extra } });
      if (!result.verified) throw new Error(copy.unverified);
      keys.current.delete(intent);
      setEditing(false);
      setFocusId(`${rowId}-statement`);
      toast.success(copy.status[result.decision.status] ?? result.decision.status);
    } catch (error) {
      setFailure(errorCode(error) === 'revision_conflict' ? copy.conflict : errorMessage(error, copy.unverified));
    }
  }

  const actions = decisionActions(decision, owner);
  return (
    <article className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3' aria-label={decision.statement}>
      <div className='flex flex-wrap items-center gap-2'>
        <ToneChip tone={decision.inEffect ? 'success' : 'neutral'} icon={decision.inEffect ? 'check' : 'circle'}>{copy.status[decision.status] ?? decision.status}</ToneChip>
        <span className='text-muted-foreground text-xs'>{copy.revision(decision.revision)}</span>
        {decision.appliesFrom && <span className='text-muted-foreground text-xs'>{copy.appliesFrom} {formatDate(decision.appliesFrom)}</span>}
      </div>
      <p id={`${rowId}-statement`} tabIndex={-1} className='rafii-focus text-sm' dir='auto'>{decision.statement}</p>
      {scopeText(decision.scope, copy, channelName).length > 0 && <p className='text-muted-foreground text-xs'>{scopeText(decision.scope, copy, channelName).join(' · ')}</p>}
      {failure && <p role='alert' className='text-destructive text-sm'>{failure}</p>}
      {editing ? (
        <form className='grid gap-2' onSubmit={(event) => { event.preventDefault(); void act('edit', { statement, ...(channelId ? { scope: { channelId } } : {}) }); }}
              onKeyDown={(event) => { if (event.key === 'Escape') { setEditing(false); setFocusId(`${rowId}-edit`); } }}>
          <label className='grid gap-1 text-sm' htmlFor={fieldId}>
            {copy.editLabel}
            <textarea id={fieldId} autoFocus maxLength={240} required minLength={3} className='rafii-focus rafii-quiet min-h-20 rounded-xl border border-border p-3 text-base'
                      value={statement} onChange={(event) => setStatement(event.target.value)} />
          </label>
          {!decision.scope.channelId && (
            <label className='grid gap-1 text-sm'>
              {copy.narrowAccount}
              <select className='rafii-focus rafii-quiet min-h-11 rounded-xl border border-border px-3 text-base' value={channelId} onChange={(event) => setChannelId(event.target.value)}>
                <option value=''>{copy.anyAccount}</option>
                {(channels.data?.channels ?? []).map((channel) => <option key={channel.id} value={channel.id}>{channel.platform} · {channel.account || channel.id}</option>)}
              </select>
            </label>
          )}
          <div className='flex flex-wrap gap-2'>
            <Button type='submit' variant='glass' disabled={decide.isPending}>{copy.save}</Button>
            <Button type='button' variant='quiet' onClick={() => { setEditing(false); setFocusId(`${rowId}-edit`); }}>{copy.cancel}</Button>
          </div>
        </form>
      ) : actions.length > 0 && (
        <div className='flex flex-wrap gap-2'>
          {actions.map((action) => (
            <Button key={action} id={`${rowId}-${action}`} variant={action === 'accept' ? 'glass' : 'quiet'} disabled={decide.isPending}
                    onClick={() => (action === 'edit' ? setEditing(true) : void act(action))}>{copy.action[action]}</Button>
          ))}
        </div>
      )}
    </article>
  );
}
