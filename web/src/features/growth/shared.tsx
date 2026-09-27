'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { useWorkspaceAccess } from '@/lib/auth/access';
import { Button } from '@/components/ui/button';
import type { GrowthCatalog, PostCheck } from '@/lib/growth/types';

export function useGrowthCatalog() {
  const { api, workspaceId } = useWorkspaceApi();
  return useQuery({
    queryKey: ['growth-catalog', workspaceId],
    queryFn: () => api.growthCatalog(workspaceId),
    staleTime: 60_000,
    retry: false
  });
}

export function GrowthConsent({
  catalog,
  onChange
}: {
  catalog: GrowthCatalog;
  onChange: () => void;
}) {
  const access = useWorkspaceAccess();
  const snapshot = useSnapshot();
  const act = useAct();
  const [confirmed, setConfirmed] = useState(false);
  const [audience, setAudience] = useState(catalog.audienceConsent ?? false);
  const [error, setError] = useState('');
  const requiredRoutes = [...new Set([...catalog.routes, catalog.writerRoute, ...(catalog.postmortem || catalog.audienceMiner ? [catalog.summaryRoute] : [])])];
  if (access.role !== 'owner')
    return (
      <p className='text-muted-foreground text-sm'>
        Ask the workspace owner to allow AI analysis in Brand & voice.
      </p>
    );
  async function decide(routes: string[]) {
    if (!snapshot.data) return;
    setError('');
    try {
      await act.mutateAsync({
        revision: snapshot.data.revision,
        action: 'growth_consent',
        payload: { routes, confirmed: true, audience: audience && routes.length > 0 }
      });
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Permission could not be saved.');
    }
  }
  if (catalog.consented && requiredRoutes.every((r) => catalog.allowedRoutes.includes(r)) && (!catalog.audienceMiner || catalog.audienceConsent))
    return (
      <Button variant='quiet' size='sm' disabled={act.isPending} onClick={() => void decide([])}>
        Revoke growth AI permission
      </Button>
    );
  return (
    <div className='flex flex-col gap-3 text-sm'>
      <p>
        AI analysis sends selected drafts to Jev, with Gemini Flash Lite as a fallback. Rewrites use
        your current writer. Each run uses the configured daily allowance.
        {(catalog.postmortem || catalog.audienceMiner) && ' Growth reviews and audience topic suggestions also use Claude Haiku.'}
      </p>
      <details>
        <summary className='cursor-pointer text-muted-foreground'>Review AI models</summary>
        <ul className='mt-2 break-words'>
          {requiredRoutes.map((r) => (
            <li key={r}>{r.replace('cloud:vercel-ai-gateway:', '')}</li>
          ))}
        </ul>
      </details>
      {catalog.audienceMiner && <label className='flex min-h-11 items-start gap-2'><input type='checkbox' aria-label='Allow comment analysis' checked={audience} onChange={(e) => setAudience(e.target.checked)} className='mt-1' />Also allow selected comments on my own posts to be sent for classification and topic suggestions. Author handles are not sent; this never authorizes replies.</label>}
      <label className='flex items-start gap-2'>
        <input
          aria-label='Allow growth AI models'
          type='checkbox'
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
          className='mt-1'
        />
        Allow these models to analyze selected drafts, explain selected readings, and rewrite using the facts I supply.
      </label>
      <Button
        variant='glass'
        disabled={!confirmed || act.isPending}
        onClick={() => void decide(requiredRoutes)}
      >
        Allow growth AI
      </Button>
      {error && (
        <p role='alert' className='text-destructive'>
          {error}
        </p>
      )}
    </div>
  );
}

export function CheckResult({ result }: { result: PostCheck }) {
  const reasons: Record<string, string> = {
    uncalibrated_language: 'The rubric has not been calibrated for this language.',
    few_measured_posts: 'Too few comparable posts have metric readings.',
    fallback_model: 'A fallback model answered.',
    many_abstained: 'Several questions lacked enough evidence.'
  };
  return (
    <div className='flex flex-col gap-3 text-sm' aria-live='polite'>
      <p className='text-muted-foreground'>
        Confidence: {result.confidence.replace(/_/g, ' ')}.{' '}
        {result.confidenceReasons
          .map((r) => reasons[r] ?? 'The analysis was incomplete.')
          .join(' ')}
      </p>
      <dl className='grid grid-cols-2 gap-2 sm:grid-cols-3'>
        {result.dimensions.map((d) => (
          <div key={d.id} className='growth-dimension' data-level={d.level}>
            <dt className='text-muted-foreground text-xs'>{d.label}</dt>
            <dd>{d.levelName}</dd>
            <div className='growth-level-bars' aria-hidden>{[0,1,2,3].map((i) => <i key={i} className={d.level !== null && i <= d.level ? 'is-on' : ''} />)}</div>
          </div>
        ))}
      </dl>
      {result.helping.length > 0 && (
        <p>
          <strong>Helping:</strong> {result.helping.join(', ')}
        </p>
      )}
      {result.hurting.length > 0 && (
        <p>
          <strong>Hurting:</strong> {result.hurting.join(', ')}
        </p>
      )}
      {result.change.length > 0 && (
        <ul className='list-disc space-y-1 pl-5'>
          {result.change.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      )}
      {result.risks.length > 0 && (
        <p className='text-muted-foreground'>Review: {result.risks.join(', ')}</p>
      )}
      {result.computed?.fit_winners && (
        <p>
          Fit to your stronger posts:{' '}
          {['weak', 'medium', 'strong', 'very strong'][result.computed.fit_winners.level]} ·{' '}
          {result.computed.fit_winners.measuredPosts} comparable posts.{' '}
          {result.computed.fit_winners.description}
        </p>
      )}
      {Boolean(result.computed?.creatorFit?.length) && <div><strong>Your approved outcome calibration</strong><ul>{result.computed?.creatorFit?.map((fit) => <li key={fit.dimension + fit.metric}>{fit.dimension}: {fit.level} association with {fit.metric} · {fit.postCount} comparable publications.</li>)}</ul><p className='text-muted-foreground text-xs'>Separate from writing quality. This does not predict reach.</p></div>}
      <p className='text-muted-foreground text-xs'>
        Writing advice. It cannot predict reach or guarantee results.
      </p>
    </div>
  );
}
