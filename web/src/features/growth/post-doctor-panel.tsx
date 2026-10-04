'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Surface } from '@/components/rafii';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAct, useSnapshot, useUsage } from '@/lib/api/hooks';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { PostDoctorRewriteRequest, SnapshotVariant } from '@/lib/api/types';
import type { AdviceGoal, PostCheck, PostRewrite } from '@/lib/growth/types';
import { CheckResult, GrowthConsent, useGrowthCatalog } from './shared';
import { baseCheckAvailability, rewriteAvailability as rewriteReadiness } from './availability';
import { parseCreditLimit } from '@/features/agent/credit-limit';
import { prepareRewrite, submitApprovedRewrite, RewriteReviewChanged, type RewriteApproval } from './rewrite-with-credit';
import { RewriteCreditReview } from './rewrite-credit-review';

export function PostDoctorPanel({
  variant,
  dirty = false,
  onAccepted
}: {
  variant: SnapshotVariant;
  dirty?: boolean;
  onAccepted?: (text: string) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const catalog = useGrowthCatalog();
  const access = useWorkspaceAccess();
  const snapshot = useSnapshot();
  const usage = useUsage();
  const catalogReady = catalog.isSuccess && !catalog.isError && !usage.isError;
  const checkAvailability = baseCheckAvailability(usage.data, catalog.data, catalogReady);
  const rewriteAvailability = rewriteReadiness(usage.data, catalog.data, catalogReady);
  const act = useAct();
  const client = useQueryClient();
  const [goal, setGoal] = useState<AdviceGoal>(variant.postDoctorGoal ?? 'general');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [check, setCheck] = useState<PostCheck | null>(null);
  const [rewritten, setRewritten] = useState<PostRewrite | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [facts, setFacts] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [approval, setApproval] = useState<RewriteApproval | null>(null);
  const [maximum, setMaximum] = useState('');
  const pendingRewrite = useRef<PostDoctorRewriteRequest | null>(null);
  // Keep the key after a lost response: another click reconciles instead of buying a duplicate run.
  const factsId = useId();
  const requests = useRef<{ check?: string; rewrite?: string }>({});
  useEffect(() => {
    setCheck(null); setRewritten(null); setSelected([]); requests.current = {};
  }, [variant.id, variant.revision]);
  useEffect(() => {
    setApproval(null); setMaximum(''); pendingRewrite.current = null;
    requests.current.rewrite = undefined;
  }, [variant.id, variant.revision, facts, goal, confirmed, catalog.data?.writer]);
  if (!catalog.data?.postDoctor) return null;
  const enabled = checkAccess(access, { permission: 'edit' });

  async function run(kind: 'check' | 'rewrite') {
    const availability = kind === 'check' ? checkAvailability : rewriteAvailability;
    if ((!availability.available && !(kind === 'rewrite' && pendingRewrite.current)) || busy || !enabled || !confirmed || dirty || catalog.isError) { setError(availability.detail); return; }
    setError('');
    setBusy(kind);
    requests.current[kind] ??= crypto.randomUUID();
    let rewriteRequest: PostDoctorRewriteRequest | undefined;
    try {
      if (kind === 'check') {
        if (usage.data?.billingMode === 'managed_credits') {
          const freshCatalog = await api.growthCatalog(workspaceId);
          const fresh = baseCheckAvailability(usage.data, freshCatalog, true);
          if (!fresh.available) throw new Error(fresh.detail);
        }
        const result = await api.postDoctor(workspaceId, {
          ...(catalog.data?.postDoctorV2 ? { goal } : {}),
          variantId: variant.id,
          variantRevision: variant.revision,
          requestKey: requests.current.check!,
          confirmed
        });
        setCheck(result);
        setRewritten(null);
        requests.current = {};
        await snapshot.refetch();
        await usage.refetch();
        await catalog.refetch();
      } else if (check && catalog.data) {
        const entries = facts
          .split('\n')
          .map((f) => f.trim())
          .filter(Boolean);
        if (entries.length > 10) throw new Error('Use at most ten facts or real examples.');
        const body: PostDoctorRewriteRequest = {
          checkId: check.runId,
          model: catalog.data.writer,
          facts: Object.fromEntries(entries.map((f, i) => [`fact${i + 1}`, f])),
          confirmed: true,
          requestKey: requests.current.rewrite!
        };
        rewriteRequest = body;
        if (pendingRewrite.current) {
          showRewrite(await api.postDoctorRewrite(workspaceId, pendingRewrite.current));
          pendingRewrite.current = null;
        } else if (usage.data?.billingMode === 'legacy_allowances') {
          showRewrite(await api.postDoctorRewrite(workspaceId, body));
        } else {
          const freshCatalog = await api.growthCatalog(workspaceId);
          if (!rewriteReadiness(usage.data, freshCatalog, true).available) throw new Error('Rewrite funding is unavailable. Your request was not submitted.');
          const next = await prepareRewrite(api, workspaceId, body);
          if (next.estimate.cached) showRewrite(await submitApprovedRewrite(api, workspaceId, next, null));
          else { setApproval(next); setMaximum(''); }
        }
      }
    } catch (err) {
      if (kind === 'rewrite' && rewriteRequest && err && typeof err === 'object' && 'status' in err && (err.status === 409 || err.status === 402)) {
        pendingRewrite.current = null; setMaximum('');
        try { const next = await prepareRewrite(api, workspaceId, rewriteRequest); setApproval(next.estimate.cached ? null : next); }
        catch { setApproval(null); }
      }
      setError(err instanceof Error ? err.message : 'This request could not be completed.');
    } finally {
      setBusy('');
    }
  }

  function showRewrite(result: PostRewrite) {
    setRewritten(result); setApproval(null); setMaximum('');
    setSelected(!result.comparison || result.comparison.recommended === 'candidate' ? result.changes.map(c => c.id) : []);
  }
  async function approveRewrite() {
    if (!approval || busy || !enabled || !confirmed || dirty || !rewriteAvailability.available) return;
    setBusy('rewrite'); setError('');
    try {
      const freshCatalog = await api.growthCatalog(workspaceId);
      if (!rewriteReadiness(usage.data, freshCatalog, true).available) throw new Error('Rewrite funding is unavailable. Review availability before approving.');
      showRewrite(await submitApprovedRewrite(api, workspaceId, approval, parseCreditLimit(maximum), body => { pendingRewrite.current = body; }));
      pendingRewrite.current = null;
      await usage.refetch();
    } catch (err) {
      if (err instanceof RewriteReviewChanged) { setApproval(err.approval); setMaximum(''); }
      // Binding errors never inherit the old quote or approval. Lost responses keep the exact quoted body for reconciliation.
      else if (err && typeof err === 'object' && 'status' in err && (err.status === 409 || err.status === 402)) {
        pendingRewrite.current = null; setMaximum('');
        try { setApproval(await prepareRewrite(api, workspaceId, approval.request)); } catch { setApproval(null); }
      }
      setError(err instanceof Error ? err.message : 'This rewrite could not be completed.');
    } finally { setBusy(''); }
  }

  async function accept() {
    if (!snapshot.data || !rewritten) return;
    setError('');
    setBusy('accept');
    try {
      const result = await act.mutateAsync({
        revision: snapshot.data.revision,
        action: 'post_doctor_accept',
        payload: { rewriteId: rewritten.runId, changeIds: selected }
      });
      const saved = result.state.variants?.find((v) => v.id === variant.id);
      if (saved) onAccepted?.(saved.text);
      setRewritten(null);
      setCheck(null);
      requests.current = {};
      await client.invalidateQueries({ queryKey: ['memory', workspaceId] });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Changes could not be saved.');
    } finally {
      setBusy('');
    }
  }

  async function helpful(value: boolean) {
    if (!snapshot.data || !check) return;
    try {
      await act.mutateAsync({
        revision: snapshot.data.revision,
        action: 'post_doctor_feedback',
        payload: { runId: check.runId, helpful: value }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Feedback could not be saved.');
    }
  }

  return (
    <Surface material='quiet' padding='sm' className='growth-doctor flex flex-col gap-4' aria-label='Post Doctor'>
      <div>
        <h3 className='font-medium'>Post Doctor</h3>
        <p className='text-muted-foreground text-sm'>
          Find what helps this draft, then choose your own changes.
        </p>
      </div>
      {!catalog.data.consented ? (
        <GrowthConsent catalog={catalog.data} onChange={() => void catalog.refetch()} />
      ) : (
        <>
          {catalog.data.postDoctorV2 && (
            <label className='flex flex-col gap-2 text-sm'>
              What should this post do?
              <select aria-label='Advice goal' value={goal} disabled={Boolean(busy)}
                className='bg-background border-input min-h-11 w-full rounded-lg border px-3'
                onChange={(event) => {
                  setGoal(event.target.value as AdviceGoal); setCheck(null); setRewritten(null);
                  setSelected([]); requests.current = {};
                }}>
                <option value='general'>Make the idea clear</option>
                <option value='conversation'>Start a conversation</option>
                <option value='shareability'>Make it useful to share</option>
                <option value='authority'>Support my expertise</option>
                <option value='reach'>Strengthen the opening</option>
              </select>
            </label>
          )}
          {dirty && (
            <p className='text-muted-foreground text-sm'>
              Save your edits before checking this revision.
            </p>
          )}
          <label className='flex items-start gap-2 text-sm'>
            <input
              aria-label='Allow AI analysis of this draft'
              type='checkbox'
              checked={confirmed}
              disabled={Boolean(busy)}
              onChange={(e) => setConfirmed(e.target.checked)}
              className='mt-1'
            />
            Analyze this saved draft with the allowed AI models.
            {usage.data?.billingMode === 'legacy_allowances' ? ` Up to ${catalog.data.checksPerDay} checks and ${catalog.data.rewritesPerDay} rewrite per day.` : ''}
          </label>
          <Button
            variant='glass'
            disabled={!enabled || !confirmed || dirty || Boolean(busy) || !checkAvailability.available}
            onClick={() => void run('check')}
          >
            {busy === 'check' ? 'Checking…' : check ? 'Check this draft again' : 'Check draft'}
          </Button>
          <p role='status' className='text-muted-foreground text-sm'>{checkAvailability.detail}</p>
          {check && (
            <>
              <CheckResult result={check} />
              <div className='flex gap-2'>
                <Button
                  variant='quiet'
                  size='sm'
                  disabled={act.isPending}
                  onClick={() => void helpful(true)}
                >
                  Useful
                </Button>
                <Button
                  variant='quiet'
                  size='sm'
                  disabled={act.isPending}
                  onClick={() => void helpful(false)}
                >
                  Not useful
                </Button>
              </div>
              <label htmlFor={factsId} className='flex flex-col gap-2 text-sm'>
                Your real facts or examples (one per line, optional)
                <Textarea
                  id={factsId}
                  aria-label='Your real facts or examples'
                  value={facts}
                  disabled={Boolean(busy)}
                  onChange={(e) => {
                    setFacts(e.target.value); setRewritten(null); setSelected([]);
                    requests.current.rewrite = undefined;
                  }}
                  maxLength={10_000}
                  placeholder='Use only facts you are ready to review as sources.'
                  rows={3}
                />
              </label>
              <Button
                variant='glass'
                disabled={!enabled || !confirmed || dirty || Boolean(busy) || catalog.isError || (!rewriteAvailability.available && !pendingRewrite.current)}
                onClick={() => void run('rewrite')}
              >
                {busy === 'rewrite' ? 'Rewriting and rechecking…' : pendingRewrite.current ? 'Reconcile rewrite' : 'Rewrite and recheck'}
              </Button>
              {!rewriteAvailability.available && <p role='status' className='text-muted-foreground text-sm'>{rewriteAvailability.detail}</p>}
              {approval && <RewriteCreditReview approval={approval} maximum={maximum} onMaximum={setMaximum} onApprove={() => void approveRewrite()} onCancel={() => { setApproval(null); setMaximum(''); }} busy={Boolean(busy)} available={rewriteAvailability.available && enabled && confirmed && !dirty} />}
            </>
          )}
          {rewritten && (
            <>
              {rewritten.userMilliCreditsCharged !== undefined && <p role='status' className='text-muted-foreground text-sm'>{rewritten.userMilliCreditsCharged === null ? 'The customer credit charge is not yet known.' : `Actual charge: ${(rewritten.userMilliCreditsCharged / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} credits.`}</p>}
              {rewritten.comparison && <div role='status' className='rafii-paper rounded-xl p-3 text-sm'>
                <p className='font-medium'>{{ candidate: 'The proposed version better supports your goal.', original: 'Keep the original for this goal.', equivalent: 'Neither version has a clear advantage.', unsure: 'There is not enough evidence to choose a version.' }[rewritten.comparison.recommended]}</p>
                <p className='text-muted-foreground mt-1'>{rewritten.comparison.reasons.map((reason) => ({
                  criterion_improved: 'The comparison found a concrete improvement while preserving facts and voice.',
                  original_preferred: 'The original better meets the selected writing criterion.',
                  no_material_difference: 'The changes do not establish a material improvement.',
                  insufficient_evidence: 'Review the edits yourself or provide more context.',
                  voice_not_preserved: 'The proposed wording may change your voice.',
                  order_disagreement: 'The comparison changed when the versions switched order.',
                  unsupported_claims: 'The proposal contains claims that could not be supported.'
                }[reason] ?? 'Review this change before accepting it.')).join(' ')}</p>
                <p className='text-muted-foreground mt-1 text-xs'>This compares writing quality, not expected engagement.</p>
              </div>}
              <h4 className='font-medium'>Choose sentence changes</h4>
              {rewritten.changes.map((change) => (
                <label key={change.id} className='rafii-paper flex gap-3 rounded-xl p-3 text-sm'>
                  <input
                    aria-label={`Use change ${change.index + 1}`}
                    type='checkbox'
                    className='mt-1 shrink-0'
                    checked={selected.includes(change.id)}
                    onChange={(e) =>
                      setSelected((prev) =>
                        e.target.checked
                          ? [...prev, change.id]
                          : prev.filter((id) => id !== change.id)
                      )
                    }
                  />
                  <span className='min-w-0'>
                    <span className='text-muted-foreground block whitespace-pre-wrap'>
                      <del>{change.before}</del>
                    </span>
                    <span className='block whitespace-pre-wrap'>{change.text}</span>
                  </span>
                </label>
              ))}
              {rewritten.missingFacts.length > 0 && (
                <p className='text-muted-foreground text-sm'>
                  Still needed: {rewritten.missingFacts.join(' ')}
                </p>
              )}
              <details open>
                <summary className='cursor-pointer text-sm'>
                  Recheck of all proposed changes
                </summary>
                <div className='mt-3'>
                  <CheckResult result={rewritten.after} />
                </div>
              </details>
              <p className='text-muted-foreground text-xs'>
                Selecting only some changes needs a fresh check. New facts require source review
                before publishing.
              </p>
              <Button
                variant='action'
                disabled={!enabled || !selected.length || Boolean(busy) || dirty}
                onClick={() => void accept()}
              >
                {busy === 'accept' ? 'Saving changes…' : 'Use selected changes'}
              </Button>
            </>
          )}
        </>
      )}
      {error && (
        <p role='alert' className='text-destructive text-sm'>
          {error}
        </p>
      )}
    </Surface>
  );
}
