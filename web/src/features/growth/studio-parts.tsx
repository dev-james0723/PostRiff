'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { IconArrowUpRight, IconArrowRight, IconChartDots3, IconMessageCircle2, IconSparkles } from '@tabler/icons-react';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { useGrowthCatalog } from './shared';

export function GrowthMark({ small = false }: { small?: boolean }) {
  return <div className={`growth-mark ${small ? 'is-small' : ''}`} aria-hidden><span /><span /><span /><span /><i /></div>;
}

export function GrowthHero({ eyebrow, title, accent, description }: { eyebrow: string; title: string; accent: string; description: string }) {
  return <header className='growth-hero'>
    <div className='growth-hero-copy'>
      <p className='growth-kicker'><span className='growth-status-dot' />{eyebrow}</p>
      <h2>{title}<br /><em>{accent}</em></h2>
      <p className='growth-intro'>{description}</p>
      <div className='growth-cycle' aria-label='The growth workflow'>
        <span>Write</span><IconArrowRight size={13} aria-hidden /><span>Publish</span><IconArrowRight size={13} aria-hidden /><span>Observe</span><IconArrowRight size={13} aria-hidden /><strong>Learn</strong>
      </div>
    </div>
    <div className='growth-hero-art'><GrowthMark /><span className='growth-art-note'>Small observations.<br />A stronger voice.</span></div>
  </header>;
}

export function GrowthEntry({ audience = false }: { audience?: boolean }) {
  const catalog = useGrowthCatalog();
  if (audience ? !catalog.data?.audienceMiner : !catalog.data?.postmortem) return null;
  const Icon = audience ? IconMessageCircle2 : IconChartDots3;
  return <Link href={`/app/growth?view=${audience ? 'audience' : 'results'}`} className={`growth-entry ${audience ? 'is-audience' : ''}`}>
    <span className='growth-entry-icon'><Icon size={24} aria-hidden /></span>
    <span><span className='growth-kicker'>{audience ? 'Audience Miner' : 'Growth Studio'}</span><strong>{audience ? 'There’s a next post in these conversations.' : 'Turn your results into your next move.'}</strong><small>{audience ? 'Find recurring questions. Save a topic worth exploring.' : 'Review what happened. Choose what your Genome learns.'}</small></span>
    <IconArrowUpRight size={22} aria-hidden />
  </Link>;
}

export function EmptyGrowth({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className='growth-empty'><IconSparkles size={28} aria-hidden /><h3>{title}</h3><div>{children}</div></div>;
}

export function useGrowthAction() {
  const snapshot = useSnapshot();
  const act = useAct();
  const client = useQueryClient();
  const [error, setError] = useState('');
  async function run(action: string, payload: Record<string, unknown>) {
    setError('');
    if (!snapshot.data) return null;
    try {
      const result = await act.mutateAsync({ revision: snapshot.data.revision, action, payload });
      await Promise.all([snapshot.refetch(), client.invalidateQueries({ queryKey: ['growth-overview'] }), client.invalidateQueries({ queryKey: ['growth-audience'] }), client.invalidateQueries({ queryKey: ['creator-genome'] }), client.invalidateQueries({ queryKey: ['growth-catalog'] })]);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'This change could not be saved.');
      return null;
    }
  }
  return { run, error, busy: act.isPending };
}
