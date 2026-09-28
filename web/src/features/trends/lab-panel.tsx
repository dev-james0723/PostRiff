'use client';
import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { LabRun, TrendOpportunity } from '@/lib/coworker/trend-types';
import { useExpired, useTrendContext, useTrendQuery } from './hooks';
import { DemoNotice, QueryContent, TrendError, words } from './present';
import { labMatches, applyExactEdit, type LabDraft, type ApplyLabEdit } from './lab-contract';
import { Disclosure } from './disclosure';
import './trends.css';
function BoundLab({
  draft,
  opportunity,
  onApply
}: {
  draft: LabDraft;
  opportunity: TrendOpportunity;
  onApply: (edit: ApplyLabEdit) => Promise<void>;
}) {
  const { api, w, enabled, flags } = useTrendContext();
  const canEdit = checkAccess(useWorkspaceAccess(), { permission: 'edit' });
  const [run, setRun] = useState<LabRun | null>(null);
  const [runLimitations, setRunLimitations] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [started, setStarted] = useState(0);
  const [frozenText, setFrozenText] = useState('');
  const request = useRef({ fingerprint: '', key: '' });
  const alive = useRef({ draft, opportunity });
  alive.current = { draft, opportunity };
  const expired = useExpired(opportunity.expires_at);
  const labOn = enabled && flags.RAFII_TREND_OPPORTUNITY_LAB_ENABLED === true;
  const result = useQuery({
    queryKey: ['trends', w, 'lab-run', run?.id],
    queryFn: ({ signal }) => api.labRun(w, run!.id, signal),
    enabled:
      labOn &&
      Boolean(run && ['queued', 'running'].includes(run.state)) &&
      Date.now() - started < 120000,
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      Date.now() - started < 120000 &&
      ['queued', 'running'].includes(query.state.data?.data.state ?? run?.state ?? '')
        ? 2000
        : false
  });
  const current = result.data?.data ?? run;
  const runExpired = useExpired(current?.expires_at);
  const stale = Boolean(
    current &&
    (runExpired || !labMatches(current, draft, opportunity) || frozenText !== draft.text || applied)
  );
  const unavailable =
    expired ||
    opportunity.verification_state !== 'verified' ||
    !opportunity.platform_targets.some((p) => p.toLowerCase() === draft.platform.toLowerCase());
  async function evaluate() {
    if (!canEdit || !labOn || busy || draft.dirty || unavailable) return;
    const fingerprint = JSON.stringify([
      w,
      draft.id,
      draft.revision,
      opportunity.id,
      opportunity.revision,
      draft.platform
    ]);
    if (request.current.fingerprint !== fingerprint)
      request.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    setError(null);
    setRun(null);
    setRunLimitations([]);
    setApplied(false);
    setFrozenText(draft.text);
    setStarted(Date.now());
    try {
      const response = await api.runLab(w, {
        draft_id: draft.id,
        draft_revision: draft.revision,
        opportunity_id: opportunity.id,
        opportunity_revision: opportunity.revision,
        target_platform: draft.platform,
        idempotency_key: request.current.key
      });
      setRun(response.data);
      setRunLimitations(response.limitations);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function apply(index: number) {
    const item = current?.diagnostics[index];
    const latest = alive.current;
    if (
      !current ||
      !item?.suggested_edit ||
      item.requires_user_fact ||
      !labOn ||
      !canEdit ||
      !labMatches(current, latest.draft, latest.opportunity) ||
      frozenText !== latest.draft.text ||
      applied ||
      applying
    )
      return;
    const next = applyExactEdit(
      latest.draft.text,
      item.suggested_edit.before,
      item.suggested_edit.after
    );
    if (next === null) return;
    setApplying(item.suggested_edit.id);
    setError(null);
    try {
      const [freshReceipt, freshOpportunities] = await Promise.all([
        api.receipt(w, latest.opportunity.trend_id, current.trust_receipt_id),
        api.opportunities(w)
      ]);
      const freshOpportunity = freshOpportunities.data.find(
        (item) => item.id === current.opportunity_id
      );
      if (
        freshReceipt.data.verification_state !== 'verified' ||
        Date.parse(freshReceipt.data.expires_at) <= Date.now() ||
        !freshOpportunity ||
        !labMatches(current, alive.current.draft, freshOpportunity) ||
        frozenText !== alive.current.draft.text
      ) {
        throw new Error('Evidence or draft changed. Recheck before applying this edit.');
      }
      await onApply({
        text: next,
        expected_revision: current.draft_revision,
        run_id: current.id,
        edit_id: item.suggested_edit.id
      });
      setApplied(true);
    } catch (e) {
      setError(e);
    } finally {
      setApplying(null);
    }
  }
  if (!labOn) return <StateMessage kind='unsupported' title='Opportunity Lab is not enabled' />;
  return (
    <Surface
      as='section'
      material='quiet'
      className='trend-lab space-y-5'
      aria-label='Opportunity Lab'
    >
      <div>
        <h3 className='text-lg font-semibold'>Opportunity Lab</h3>
        <p className='text-sm'>
          Explore suggestions for this draft, then choose the changes that sound like you. These
          checks don’t predict reach.
        </p>
      </div>
      <Disclosure title={`Current draft · revision ${draft.revision}`}>
        <p className='whitespace-pre-wrap' dir='auto'>
          {draft.text}
        </p>
      </Disclosure>
      <p className='text-sm'>
        Opportunity: {opportunity.title} · revision {opportunity.revision}
      </p>
      {draft.dirty && (
        <p role='status'>Save your draft changes before checking. Any previous result is stale.</p>
      )}
      {unavailable && (
        <StateMessage
          kind='stale'
          title='Current evidence or platform support is unavailable'
          description='Lab needs a valid receipt and permitted comparison scope.'
        />
      )}
      <Button
        variant='glass'
        onClick={() => void evaluate()}
        disabled={!canEdit || busy || draft.dirty || unavailable || applying !== null}
      >
        {busy ? 'Reviewing this draft…' : 'Review this draft'}
      </Button>
      <p className='text-sm'>
        Uses this workspace’s evaluation allowance. Your draft changes only when you choose an edit.
        It never publishes or changes your voice memory.
      </p>
      {error !== null && <TrendError error={error} />}
      {result.isError && <TrendError error={result.error} retry={() => void result.refetch()} />}
      {current && !result.isError && (
        <div aria-live='polite' aria-atomic='false' className='space-y-3'>
          {stale ? (
            <StateMessage
              kind='stale'
              title='This check is stale'
              description='The draft, opportunity or evidence changed. Check the saved revision again before applying any suggestion.'
            />
          ) : ['queued', 'running'].includes(current.state) ? (
            <p role='status'>Evaluation {current.state}. Your draft is unchanged.</p>
          ) : current.state !== 'completed' ? (
            <StateMessage
              kind={current.state === 'stale' ? 'stale' : 'unsupported'}
              title={`Evaluation ${words(current.state)}`}
              description={current.failure_reason ?? 'No current diagnostics are available.'}
            />
          ) : (
            <>
              <p role='status'>Review ready for saved version {current.draft_revision}.</p>
              <DemoNotice limitations={result.data?.limitations ?? runLimitations} />
              {current.diagnostics.map((item, i) => (
                <Surface
                  key={`${item.dimension}:${i}`}
                  material='canvas'
                  padding='none'
                  className='trend-diagnostic space-y-3'
                >
                  <h4 className='font-medium'>
                    {words(item.dimension)} · {item.assessment}
                  </h4>
                  <p>{item.claim}</p>
                  <p className='text-sm'>Keep in mind: {item.uncertainty}</p>
                  {item.requires_user_fact && (
                    <p>
                      Your own facts are needed. Add only experiences or results you can verify,
                      then save and check again.
                    </p>
                  )}
                  {item.suggested_edit && (
                    <>
                      <Disclosure title='Original wording'>
                        <p className='whitespace-pre-wrap' dir='auto'>
                          {item.suggested_edit.before}
                        </p>
                      </Disclosure>
                      <p className='trend-suggested-edit' dir='auto'>
                        <strong>Suggested edit:</strong> {item.suggested_edit.after}
                      </p>
                      <p className='text-sm'>{item.suggested_edit.reason}</p>
                      <Button
                        variant='glass'
                        onClick={() => void apply(i)}
                        disabled={
                          !canEdit ||
                          applying !== null ||
                          item.requires_user_fact ||
                          applyExactEdit(
                            draft.text,
                            item.suggested_edit.before,
                            item.suggested_edit.after
                          ) === null
                        }
                      >
                        Apply this edit
                      </Button>
                      <p className='text-sm'>
                        Saves this change in your draft. Review and approve the updated version
                        again before posting.
                      </p>
                    </>
                  )}
                  <Disclosure title='Evidence and comparison'>
                    <p>Comparison: {item.comparison_frame}</p>
                    <p>Evidence: {item.evidence_refs.join(', ') || 'None — support unknown'}</p>
                  </Disclosure>
                </Surface>
              ))}
            </>
          )}
        </div>
      )}
    </Surface>
  );
}
/** Embeds in the existing draft editor. No draft/opportunity IDs are inferred from user text. */
export function OpportunityLabPanel({
  draft,
  onApply
}: {
  draft: LabDraft;
  onApply: (edit: ApplyLabEdit) => Promise<void>;
}) {
  const { flags, w, enabled } = useTrendContext();
  const on = enabled && flags.RAFII_TREND_OPPORTUNITY_LAB_ENABLED === true;
  const opportunities = useTrendQuery(['opportunities'], (a, w, s) => a.opportunities(w, s), on);
  if (!on) return null;
  return (
    <QueryContent query={opportunities}>
      {(items) => {
        const linked = items.filter((o) => o.draft_id === draft.id);
        return linked.length === 1 ? (
          <BoundLab
            key={`${w}:${draft.id}:${linked[0].id}`}
            draft={draft}
            opportunity={linked[0]}
            onApply={onApply}
          />
        ) : (
          <StateMessage
            kind='unsupported'
            title='Opportunity Lab unavailable for this draft'
            description={
              linked.length
                ? 'More than one opportunity is linked; the server must resolve the current context.'
                : 'No current server-resolved opportunity is linked. You can continue editing normally.'
            }
          />
        );
      }}
    </QueryContent>
  );
}
