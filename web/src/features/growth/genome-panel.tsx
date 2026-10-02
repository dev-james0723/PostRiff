'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Surface } from '@/components/rafii';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { CreatorGenome, GenomeResponse } from '@/lib/growth/types';
import { useGrowthCreditApproval } from '@/lib/growth-v2/growth-credits';
import { GrowthCreditConfirm } from './post-doctor-panel';
import { GrowthConsent, useGrowthCatalog } from './shared';

export function GenomePanel() {
  const { api, workspaceId } = useWorkspaceApi();
  const catalog = useGrowthCatalog();
  const access = useWorkspaceAccess();
  const snapshot = useSnapshot();
  const act = useAct();
  const query = useQuery({
    queryKey: ['creator-genome', workspaceId],
    queryFn: () => api.creatorGenome(workspaceId),
    enabled: catalog.data?.genome === true,
    retry: false
  });
  const [data, setData] = useState('');
  const [account, setAccount] = useState('');
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [versionId, setVersionId] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [sharePath, setSharePath] = useState('');
  const key = useRef<string | null>(null);
  // Creator under Pricing v2: the analysis is priced and confirmed before it runs (credit bridge), like Post Doctor.
  const credits = useGrowthCreditApproval<{ genome: CreatorGenome }>(workspaceId);
  if (!catalog.data?.genome) return null;
  const owner = access.role === 'owner';
  const samples =
    snapshot.data?.state.sources?.filter(
      (s) => s.kind === 'voice_sample' && s.active && s.selected
    ) ?? [];
  const version = query.data?.versions.find((v) => v.id === versionId) ?? query.data?.versions[0];
  function changed() {
    key.current = null;
    setConfirmed(false);
    credits.cancel(); // a limit confirmed for other input never runs this one
  }

  async function analyzed(result: { genome: CreatorGenome } | null) {
    if (!result) return; // waiting for the credit limit to be confirmed
    setVersionId(result.genome.id);
    await query.refetch();
    await snapshot.refetch();
  }

  /** The request exactly as the screen shows it now (Propose sends it; Confirm checks the priced one still matches). */
  function requestBody(): Record<string, unknown> {
    return {
      ...(data ? { data, account } : { sourceIds }),
      ownContent: confirmed,
      retainText: confirmed,
      confirmed,
      requestKey: key.current
    };
  }

  async function analyze() {
    setBusy(true);
    setError('');
    key.current ??= crypto.randomUUID();
    try {
      await analyzed(await credits.run('genome', requestBody(), (b) => api.analyzeHistory(workspaceId, b as unknown as Parameters<typeof api.analyzeHistory>[1])));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'History could not be analyzed.');
    } finally {
      setBusy(false);
    }
  }

  async function confirmCredits() {
    setBusy(true);
    setError('');
    try {
      await analyzed(await credits.confirm(requestBody()));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'History could not be analyzed.');
    } finally {
      setBusy(false);
    }
  }

  async function action(name: string, payload: Record<string, unknown>) {
    if (!snapshot.data) return;
    setError('');
    try {
      const result = await act.mutateAsync({
        revision: snapshot.data.revision,
        action: name,
        payload
      });
      if ('path' in result && typeof result.path === 'string') setSharePath(result.path);
      await query.refetch();
      await snapshot.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'This change could not be saved.');
    }
  }

  return (
    <Surface material='quiet' className='growth-genome flex flex-col gap-4' aria-label='Creator Genome'>
      <div>
        <h2 className='text-lg font-medium'>Creator Genome</h2>
        <p className='text-muted-foreground text-sm'>
          Patterns from your own posts, alongside your existing voice. Review the evidence before
          approving a version. Approved, supported patterns guide future writing and send existing
          drafts back for review.
        </p>
      </div>
      <GrowthConsent catalog={catalog.data} onChange={() => void catalog.refetch()} />
      {catalog.data.consented && (
        <>
          {owner && (
            <>
              <label className='flex flex-col gap-2 text-sm'>
                Import your own history (CSV, up to 20 posts)
                <input
                  aria-label='Owned history CSV'
                  type='file'
                  accept='.csv,text/csv'
                  onChange={async (e) => {
                    changed();
                    const file = e.target.files?.[0];
                    if (!file) return;
                    if (file.size > 100_000) {
                      setError('Choose a CSV of at most 100 KB.');
                      return;
                    }
                    setData(await file.text());
                  }}
                />
              </label>
              {data && (
                <label className='flex flex-col gap-1 text-sm'>
                  Account represented by this CSV
                  <input
                    aria-label='CSV account'
                    className='rafii-field rounded-xl p-3'
                    value={account}
                    maxLength={80}
                    onChange={(e) => {
                      setAccount(e.target.value);
                      changed();
                    }}
                    placeholder='Your account name'
                  />
                </label>
              )}
              <details className='text-muted-foreground text-xs'>
                <summary className='cursor-pointer'>CSV columns and metric evidence</summary>
                <p className='mt-2 break-words'>
                  Required: text, platform. Optional: language, post_id, published_at, format,
                  time_bucket, horizon (1h, 24h, 7d), shares, reposts, saves, replies, comments,
                  likes, views. Metrics from an upload stay user supplied. Without an explicit
                  horizon, the Genome describes writing only.
                </p>
              </details>
            </>
          )}
          {!data && samples.length > 0 && (
            <fieldset className='flex flex-col gap-2 text-sm'>
              <legend className='mb-2'>Or select existing owned voice samples</legend>
              {samples.map((s) => (
                <label key={s.id} className='flex gap-2'>
                  <input
                    aria-label={`Analyze ${s.title || s.id}`}
                    type='checkbox'
                    checked={sourceIds.includes(s.id)}
                    onChange={(e) => {
                      changed();
                      setSourceIds((ids) =>
                        e.target.checked ? [...ids, s.id] : ids.filter((id) => id !== s.id)
                      );
                    }}
                  />
                  {s.title || s.id}
                </label>
              ))}
            </fieldset>
          )}
          <label className='flex items-start gap-2 text-sm'>
            <input
              aria-label='Confirm owned history retention and analysis'
              type='checkbox'
              className='mt-1'
              checked={confirmed}
              onChange={(e) => {
                setConfirmed(e.target.checked);
                credits.cancel(); // a limit shown for the request with the earlier consent never runs this one
              }}
            />
            These are my own posts. Retain their text in my voice corpus and analyze selected
            samples with the allowed AI routes.
          </label>
          <Button
            variant='glass'
            disabled={
              !confirmed ||
              busy ||
              (!data && !sourceIds.length) ||
              (Boolean(data) && !account.trim())
            }
            onClick={() => void analyze()}
          >
            {busy ? 'Analyzing your history…' : 'Propose my Genome'}
          </Button>
          <GrowthCreditConfirm quote={credits.pending} busy={busy || credits.quoting} onConfirm={() => void confirmCredits()} onCancel={credits.cancel} />
        </>
      )}
      {query.isError && (
        <p role='alert' className='text-destructive text-sm'>
          The Genome could not be loaded.{' '}
          <Button size='sm' variant='quiet' onClick={() => void query.refetch()}>
            Retry
          </Button>
        </p>
      )}
      {query.data && query.data.versions.length === 0 && (
        <p className='text-muted-foreground text-sm'>
          No Genome yet. Start with owned posts or your selected voice samples.
        </p>
      )}
      {version && (
        <>
          <label className='text-sm'>
            Version
            <select
              aria-label='Genome version'
              className='rafii-field ml-2 max-w-full rounded-lg p-2'
              value={version.id}
              onChange={(e) => {
                setVersionId(e.target.value);
                setSelected([]);
              }}
            >
              {query.data?.versions.map((v, i) => (
                <option key={v.id} value={v.id}>
                  Version {query.data!.versions.length - i} · {v.status}
                </option>
              ))}
            </select>
          </label>
          <GenomeEvidence genome={version} evidence={query.data?.evidence ?? {}} />
          {owner && ['proposed', 'superseded'].includes(version.status) && (
            <Button
              variant='action'
              disabled={act.isPending}
              onClick={() =>
                void action(version.status === 'superseded' ? 'genome_restore' : 'genome_approve', {
                  genomeId: version.id,
                  confirmed: true
                })
              }
            >
              {version.status === 'superseded'
                ? 'Restore this approved version'
                : 'Approve this Genome'}
            </Button>
          )}
          {owner && version.status === 'approved' && query.data?.active?.id === version.id && (
            <details>
              <summary className='cursor-pointer text-sm'>Create a public Content DNA card</summary>
              <div className='mt-3 flex flex-col gap-3 text-sm'>
                <p>
                  Only the labels you select will be public. Preview these exact labels, then create
                  a revocable link.
                </p>
                {version.statements
                  .filter((s) => s.grade !== 'conflicting')
                  .map((s) => (
                    <label key={s.id} className='flex gap-2'>
                      <input
                        aria-label={`Share ${s.label}`}
                        type='checkbox'
                        checked={selected.includes(s.id)}
                        onChange={(e) =>
                          setSelected((ids) =>
                            e.target.checked ? [...ids, s.id] : ids.filter((id) => id !== s.id)
                          )
                        }
                      />
                      {s.label}
                    </label>
                  ))}
                <Button
                  variant='glass'
                  disabled={act.isPending || !selected.length || selected.length > 6}
                  onClick={() =>
                    void action('share_card_create', {
                      genomeId: version.id,
                      statementIds: selected,
                      confirmed: true
                    })
                  }
                >
                  Create public link for selected labels
                </Button>
                {sharePath && (
                  <Link className='underline' href={sharePath} target='_blank' rel='noreferrer'>
                    Open my Content DNA card
                  </Link>
                )}
              </div>
            </details>
          )}
        </>
      )}
      {owner &&
        query.data?.shares
          .filter((s) => !s.revoked)
          .map((s) => (
            <Button
              key={s.id}
              variant='quiet'
              size='sm'
              disabled={act.isPending}
              onClick={() => void action('share_card_revoke', { shareId: s.id })}
            >
              Revoke Content DNA card {s.id.slice(0, 6)}
            </Button>
          ))}
      {error && (
        <p role='alert' className='text-destructive text-sm'>
          {error}
        </p>
      )}
    </Surface>
  );
}

function GenomeEvidence({
  genome,
  evidence
}: {
  genome: CreatorGenome;
  evidence: GenomeResponse['evidence'];
}) {
  return (
    <div className='flex flex-col gap-3 text-sm'>
      <p className='text-muted-foreground'>
        {genome.postCount} posts · {genome.measuredPosts} with comparable 24h readings ·{' '}
        {genome.suppliedMetricsPosts} with user supplied figures. Patterns describe associations.
      </p>
      {genome.statements.map((s) => (
        <div key={s.id} className='rafii-paper rounded-xl p-3'>
          <p>{s.text}</p>
          <p className='text-muted-foreground mt-1 text-xs'>
            {s.grade} · {s.evidenceIds.length} examples · {s.counterEvidenceIds.length}{' '}
            counterexamples · {s.cohort.platform} · {s.cohort.language}
            {s.metric ? ` · ${s.metric}` : ''}
            {s.provenance?.includes('user_supplied') ? ' · user supplied' : ''}
          </p>
          <details className='mt-2 text-xs'>
            <summary className='cursor-pointer'>
              Review supporting posts and counterexamples
            </summary>
            {[...s.evidenceIds, ...s.counterEvidenceIds].map((id) => (
              <blockquote key={id} className='mt-2 border-l pl-3'>
                <p>
                  {s.counterEvidenceIds.includes(id) ? 'Counterexample' : 'Supporting post'} ·{' '}
                  {evidence[id]?.platform ?? 'Unavailable'}
                </p>
                <p className='whitespace-pre-wrap'>
                  {evidence[id]?.text ?? 'This evidence is no longer selected or retained.'}
                </p>
              </blockquote>
            ))}
          </details>
        </div>
      ))}
    </div>
  );
}
