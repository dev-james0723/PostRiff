'use client';

import { useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Surface } from '@/components/rafii';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { SnapshotVariant } from '@/lib/api/types';
import type { PostCheck, PostRewrite } from '@/lib/growth/types';
import { CheckResult, GrowthConsent, useGrowthCatalog } from './shared';

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
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [check, setCheck] = useState<PostCheck | null>(null);
  const [rewritten, setRewritten] = useState<PostRewrite | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [facts, setFacts] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  // Keep the key after a lost response: another click reconciles instead of buying a duplicate run.
  const factsId = useId();
  const requests = useRef<{ check?: string; rewrite?: string }>({});
  if (!catalog.data?.postDoctor) return null;
  const enabled = checkAccess(access, { permission: 'edit' });

  async function run(kind: 'check' | 'rewrite') {
    setError('');
    setBusy(kind);
    requests.current[kind] ??= crypto.randomUUID();
    try {
      if (kind === 'check') {
        const result = await api.postDoctor(workspaceId, {
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
        setSelected(result.changes.map((c) => c.id));
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
                    setFacts(e.target.value);
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
