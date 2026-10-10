'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Surface } from '@/components/rafii';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { SnapshotVariant } from '@/lib/api/types';
import type { AdviceGoal, PostCheck, PostRewrite } from '@/lib/growth/types';
import { CheckResult, GrowthConsent, useGrowthCatalog } from './shared';
import { MemoryReceiptDetails, type MemoryRunReceipt } from '@/features/memory/brand-brain-memory';

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
  const act = useAct();
  const client = useQueryClient();
  const [goal, setGoal] = useState<AdviceGoal>(variant.postDoctorGoal ?? 'general');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [check, setCheck] = useState<PostCheck | null>(null);
  const [rewritten, setRewritten] = useState<(PostRewrite & { memoryReceipt?: MemoryRunReceipt }) | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [facts, setFacts] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  // Keep the key after a lost response: another click reconciles instead of buying a duplicate run.
  const factsId = useId();
  const requests = useRef<{ check?: string; rewrite?: string }>({});
  useEffect(() => {
    setCheck(null); setRewritten(null); setSelected([]); requests.current = {};
  }, [variant.id, variant.revision]);
  if (!catalog.data?.postDoctor) return null;
  const enabled = checkAccess(access, { permission: 'edit' });

  async function run(kind: 'check' | 'rewrite') {
    setError('');
    setBusy(kind);
    requests.current[kind] ??= crypto.randomUUID();
    try {
      if (kind === 'check') {
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
      } else if (check && catalog.data) {
        const entries = facts
          .split('\n')
          .map((f) => f.trim())
          .filter(Boolean);
        if (entries.length > 10) throw new Error('Use at most ten facts or real examples.');
        const result = await api.postDoctorRewrite(workspaceId, {
          checkId: check.runId,
          model: catalog.data.writer,
          facts: Object.fromEntries(entries.map((f, i) => [`fact${i + 1}`, f])),
          confirmed,
          requestKey: requests.current.rewrite!
        });
        setRewritten(result);
        setSelected(!result.comparison || result.comparison.recommended === 'candidate' ? result.changes.map((c) => c.id) : []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'This request could not be completed.');
    } finally {
      setBusy('');
    }
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
              onChange={(e) => setConfirmed(e.target.checked)}
              className='mt-1'
            />
            Analyze this saved draft with the allowed AI models. Up to 10 checks and one rewrite per
            day.
          </label>
          <Button
            variant='glass'
            disabled={!enabled || !confirmed || dirty || Boolean(busy)}
            onClick={() => void run('check')}
          >
            {busy === 'check' ? 'Checking…' : check ? 'Check this draft again' : 'Check draft'}
          </Button>
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
                disabled={!enabled || !confirmed || dirty || Boolean(busy)}
                onClick={() => void run('rewrite')}
              >
                {busy === 'rewrite' ? 'Rewriting and rechecking…' : 'Rewrite and recheck'}
              </Button>
            </>
          )}
          {rewritten && (
            <>
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
              {rewritten.memoryReceipt && <MemoryReceiptDetails receipt={rewritten.memoryReceipt} />}
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
