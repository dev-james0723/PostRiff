'use client';

import { useState } from 'react';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { ScheduleDialog } from '@/features/queue/schedule-dialog';
import { cn } from '@/lib/utils';

interface CardItem {
  id: string;
  schedulable?: boolean;
  platform?: string;
  title: string;
  subtitle?: string;
  body: string;
  tone?: 'default' | 'outline' | 'secondary' | 'destructive';
  tag?: string;
}

interface Column {
  key: string;
  title: string;
  hint: string;
  href: string;
  cta: string;
  items: CardItem[];
}

const infoContent = {
  title: 'Pipeline',
  sections: [
    { title: 'Left to right', description: 'Sources become drafts; drafts are prepared for a channel and time; the exact review is approved; the worker publishes; the provider confirms.' },
    { title: 'Why no dragging', description: 'Every move right is an explicit decision with a receipt (a review, an approval, a provider confirmation). The board shows state; the actions live on each page.' }
  ]
};

const WAITING = new Set(['scheduled', 'approved', 'claimed', 'submitting', 'provider_accepted', 'published', 'uncertain']);

export function PipelineView() {
  const snapshot = useSnapshot();
  const access = useWorkspaceAccess();
  const canSchedule = checkAccess(access, { permission: 'edit' });
  const [scheduling, setScheduling] = useState<string | null>(null);
  const state = snapshot.data?.state;
  const phase2 = state?.phase2;
  const reviewedVariantIds = new Set([...(phase2?.reviews ?? []).map((r) => r.manifest.variantId), ...(phase2?.jobs ?? []).map((j) => j.manifest.variantId)]);

  const columns: Column[] = [
    {
      key: 'sources',
      title: 'Sources',
      hint: 'What drafts may draw from',
      href: '/app/ideas',
      cta: 'Add a source',
      items: (state?.sources ?? []).filter((s) => s.active).map((s) => ({ id: s.id, title: s.title || s.kind, subtitle: s.visibility, body: s.text }))
    },
    {
      key: 'drafts',
      title: 'Drafts',
      hint: 'Candidates you added',
      href: '/app/ideas',
      cta: 'Draft more',
      items: (state?.variants ?? [])
        .filter((v) => !reviewedVariantIds.has(v.id) && !v.blockedByRetraction)
        .map((v) => ({ id: v.id, schedulable: true, platform: v.platform, title: `${v.platform} · ${v.language === '繁體中文' ? '繁中' : 'EN'}`, subtitle: v.proposedUpdate ? 'update proposed' : v.needsReview ? 'needs review' : undefined, body: v.proposedUpdate?.text ?? v.text, tag: v.warnings[0] }))
    },
    {
      key: 'review',
      title: 'Needs approval',
      hint: 'Exact text, media, account and time',
      href: '/app/queue',
      cta: 'Review now',
      items: (phase2?.reviews ?? []).filter((r) => r.status === 'needs_review').map((r) => ({ id: r.id, platform: r.manifest.platform, title: `${r.manifest.platform} · ${r.manifest.account}`, subtitle: r.manifest.timing.local, body: r.manifest.payload.text, tone: 'default' as const }))
    },
    {
      key: 'scheduled',
      title: 'Scheduled',
      hint: 'Approved; the worker publishes at the time',
      href: '/app/calendar',
      cta: 'See calendar',
      items: (phase2?.jobs ?? []).filter((j) => WAITING.has(j.state)).map((j) => ({ id: j.id, platform: j.manifest.platform, title: `${j.manifest.platform} · ${j.manifest.account}`, subtitle: j.state.replace(/_/g, ' '), body: j.manifest.payload.text, tone: 'secondary' as const }))
    },
    {
      key: 'published',
      title: 'Published',
      hint: 'Confirmed by the provider',
      href: '/app/analytics',
      cta: 'See analytics',
      items: (phase2?.jobs ?? []).filter((j) => j.state === 'verified').map((j) => ({ id: j.id, platform: j.manifest.platform, title: `${j.manifest.platform} · ${j.manifest.account}`, subtitle: j.providerReference, body: j.manifest.payload.text, tone: 'outline' as const }))
    }
  ];

  return (
    <PageContainer pageTitle='Pipeline' pageDescription='Where every idea is, from source to confirmed publication.' infoContent={infoContent}>
      {scheduling && <ScheduleDialog key={scheduling} open onOpenChange={(open) => !open && setScheduling(null)} variantId={scheduling} />}
      {snapshot.isLoading ? (
        <Skeleton className='h-[32rem] w-full' />
      ) : (
        <ScrollArea className='w-full'>
          <div className='flex min-w-max gap-4 pb-4'>
            {columns.map((column) => (
              <section key={column.key} aria-labelledby={`col-${column.key}`} className='bg-muted/40 flex w-72 shrink-0 flex-col rounded-xl border'>
                <header className='flex items-center justify-between px-3 py-2'>
                  <div>
                    <h3 id={`col-${column.key}`} className='text-sm font-semibold'>
                      {column.title} <span className='text-muted-foreground font-normal'>{column.items.length}</span>
                    </h3>
                    <p className='text-muted-foreground text-xs'>{column.hint}</p>
                  </div>
                </header>
                <div className='flex flex-col gap-2 px-2 pb-2'>
                  {column.items.length === 0 ? (
                    <p className='text-muted-foreground px-1 py-4 text-center text-xs'>Empty</p>
                  ) : (
                    column.items.slice(0, 30).map((item) => (
                      <article key={item.id} className='bg-card flex flex-col gap-1 rounded-lg border p-3 text-sm shadow-xs'>
                        <div className='flex items-center justify-between gap-2'>
                          <span className='flex min-w-0 items-center gap-1.5 font-medium'>
                            {item.platform && <ChannelIcon platform={item.platform} name={item.platform} size='xs' />}
                            <span className='truncate'>{item.title}</span>
                          </span>
                          {item.subtitle && (
                            <Badge variant={item.tone ?? 'outline'} className='shrink-0 truncate'>
                              {item.subtitle}
                            </Badge>
                          )}
                        </div>
                        <p className='text-muted-foreground line-clamp-3 text-xs whitespace-pre-wrap'>{item.body}</p>
                        {item.tag && <span className='text-xs text-amber-600 dark:text-amber-400'>{item.tag}</span>}
                        {item.schedulable && canSchedule && (
                          <button type='button' className='text-primary mt-1 w-fit text-xs underline-offset-2 hover:underline' onClick={() => setScheduling(item.id)}>
                            Schedule…
                          </button>
                        )}
                      </article>
                    ))
                  )}
                  <Link href={column.href} className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), 'justify-start')}>
                    {column.cta} <Icons.chevronRight className='size-4' />
                  </Link>
                </div>
              </section>
            ))}
          </div>
        </ScrollArea>
      )}
    </PageContainer>
  );
}
