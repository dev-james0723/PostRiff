'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { LEGAL_LAST_UPDATED, LEGAL_REVIEW_STATUS } from '@/config/legal';
import { siteConfig } from '@/config/site';
import type { MemoryEgress, PrivacyNotice, ResearchEgress } from '@/lib/api/types';
import { plural, retentionLabel, sentence } from './privacy-model';
import { PrivacySection, Unavailable, type Refetchable } from './section';

const linkClass = 't-learn text-foreground inline-flex items-center gap-0.5 text-sm font-medium hover:underline';

function SwitchRow({ title, badge, detail }: { title: string; badge: { label: string; status: AnimatedBadgeStatus }; detail?: ReactNode }) {
  return (
    <div className='flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between sm:gap-4'>
      <div className='flex min-w-0 flex-col gap-0.5'>
        <span className='text-sm font-medium'>{title}</span>
        {detail && <span className='text-muted-foreground text-xs'>{detail}</span>}
      </div>
      <AnimatedBadge size='sm' status={badge.status} contentKey={badge.label} pulse={false} className='w-fit'>
        {badge.label}
      </AnimatedBadge>
    </div>
  );
}

function cloudRow(egress: MemoryEgress | undefined) {
  if (!egress) return { badge: { label: 'Unavailable', status: 'neutral' as const }, detail: 'This setting could not be read.' };
  const withheld = egress.withheldBoundaries > 0 ? `${plural(egress.withheldBoundaries, 'boundary', 'boundaries')} marked private or local-only never leave.` : null;
  if (egress.cloud) {
    return {
      badge: { label: 'Shared', status: 'success' as const },
      detail: [egress.sharedFiles.length > 0 ? `Files it may read: ${egress.sharedFiles.join(', ')}.` : null, withheld].filter(Boolean).join(' ')
    };
  }
  return { badge: { label: 'Not shared', status: 'neutral' as const }, detail: withheld ?? 'Your voice, identity and boundaries stay out of cloud model requests.' };
}

/** `null` means the row does not apply here (research is switched off for the whole deployment). */
function researchRow(research: ResearchEgress | undefined) {
  if (!research) return { badge: { label: 'Unavailable', status: 'neutral' as const }, detail: 'This setting could not be read.' };
  if (!research.enabled) return null;
  if (!research.hosted) return { badge: { label: 'On', status: 'info' as const }, detail: 'Always on when drafting on your own machine.' };
  if (research.web) {
    return {
      badge: { label: 'On', status: 'success' as const },
      detail: research.processors.length > 0 ? `Search queries go to: ${research.processors.join(', ')}.` : 'Search queries leave PostRiff when a draft needs facts.'
    };
  }
  return { badge: { label: 'Off', status: 'neutral' as const }, detail: 'Drafts use only the sources you add.' };
}

function NoticeSkeleton({ tall }: { tall?: boolean }) {
  return (
    <div className='grid gap-4 lg:grid-cols-2' aria-hidden>
      <Skeleton className={tall ? 'h-56 w-full' : 'h-40 w-full'} />
      <Skeleton className={tall ? 'h-56 w-full' : 'h-40 w-full'} />
    </div>
  );
}

function UsageAndServices({ notice }: { notice: PrivacyNotice }) {
  const usage: { label: string; text: string }[] = [
    { label: 'AI processing', text: notice.aiProcessing },
    { label: 'Connected accounts', text: notice.providerAccess },
    { label: 'Metrics and comments', text: notice.ingestion },
    { label: 'Telemetry', text: notice.telemetry }
  ];

  return (
    <div className='grid min-w-0 gap-4 lg:grid-cols-2'>
      <Card>
        <CardHeader>
          <CardTitle className='text-base'>How your content is used</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-3 text-sm'>
          {usage.map((item) =>
            item.text ? (
              <div key={item.label} className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs font-medium'>{item.label}</span>
                <p>{item.text}</p>
              </div>
            ) : null
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className='text-base'>Services that process your data</CardTitle>
          <CardDescription>As the privacy notice lists them today.</CardDescription>
        </CardHeader>
        <CardContent>
          {(notice.subprocessors ?? []).length === 0 ? (
            <p className='text-muted-foreground text-sm'>The notice lists none.</p>
          ) : (
            <ul className='divide-y'>
              {notice.subprocessors.map((processor) => (
                <li key={processor.name} className='flex flex-col gap-0.5 py-2.5 text-sm first:pt-0 last:pb-0'>
                  <span className='font-medium'>{processor.name}</span>
                  <span className='text-muted-foreground'>{sentence(processor.purpose)}</span>
                  <span className='text-muted-foreground text-xs'>
                    {sentence(processor.status)}
                    {processor.region ? ` · Region ${processor.region}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RetentionAndRights({ notice }: { notice: PrivacyNotice }) {
  const retention = Object.entries(notice.retention ?? {});
  return (
    <div className='grid min-w-0 gap-4 lg:grid-cols-3'>
      <Card className='lg:col-span-2'>
        <CardHeader>
          <CardTitle className='text-base'>What is kept, and for how long</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className='grid gap-x-8 gap-y-3 md:grid-cols-2'>
            {retention.map(([key, value]) => (
              <div key={key} className='flex min-w-0 flex-col gap-0.5 border-b pb-3 text-sm'>
                <dt className='font-medium'>{retentionLabel(key)}</dt>
                <dd>{sentence(value.retention)}</dd>
                {value.note && <dd className='text-muted-foreground text-xs'>{value.note}</dd>}
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Card className='h-fit'>
        <CardHeader>
          <CardTitle className='text-base'>Your rights</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className='flex flex-col gap-2 text-sm'>
            {(notice.rights ?? []).map((right) => (
              <li key={right} className='flex items-start gap-2'>
                <Icons.check className='mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400' aria-hidden />
                <span>{sentence(right)}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

type NoticeQuery = Refetchable & { data?: PrivacyNotice; isPending: boolean };

function LegalReviewBadge() {
  const reviewed = LEGAL_REVIEW_STATUS === 'reviewed';
  return (
    <AnimatedBadge size='sm' status={reviewed ? 'success' : 'warning'} pulse={false} contentKey={LEGAL_REVIEW_STATUS}>
      {reviewed ? `Reviewed · ${LEGAL_LAST_UPDATED}` : 'Draft — pending legal review'}
    </AnimatedBadge>
  );
}

/** The rest of the privacy notice: retention per kind of data and the rights it lists. Rendered from the API only. */
export function RetentionSection({ notice }: { notice: NoticeQuery }) {
  return (
    <PrivacySection
      id='privacy-retention'
      title='What is kept, and your rights'
      description='The rest of the privacy notice: how long each kind of data is kept, and what you can ask for.'
      action={
        <Link href={siteConfig.links.dataDeletion} className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
          Deletion steps
        </Link>
      }
      data-tour='privacy-retention'
    >
      {notice.isPending ? (
        <NoticeSkeleton />
      ) : notice.data ? (
        <RetentionAndRights notice={notice.data} />
      ) : (
        <Unavailable query={notice} fallback='The privacy notice could not be loaded.' />
      )}
    </PrivacySection>
  );
}

export function WhereItGoesSection({
  memory,
  notice,
  canEdit
}: {
  memory: Refetchable & { data?: { egress?: MemoryEgress; research?: ResearchEgress }; isPending: boolean };
  notice: NoticeQuery;
  canEdit: boolean;
}) {
  const cloud = memory.data ? cloudRow(memory.data.egress) : null;
  const research = memory.data ? researchRow(memory.data.research) : null;

  return (
    <PrivacySection
      id='privacy-where'
      title='Where it goes'
      description='What this workspace allows to leave PostRiff, and what the privacy notice says about the rest.'
      action={
        <Link href={siteConfig.links.privacy} className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
          Full policy <Icons.externalLink className='size-3.5' />
        </Link>
      }
    >
      <Card data-tour='privacy-egress'>
        <CardHeader>
          <CardTitle className='text-base'>This workspace&apos;s switches</CardTitle>
          <CardDescription>
            {canEdit ? (
              <Link href='/app/workspace/memory' className={linkClass}>
                The owner changes these on Memory <LearnMoreChevron className='size-3.5' />
              </Link>
            ) : (
              'Only the workspace owner can change these.'
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {memory.isPending ? (
            <div className='flex flex-col gap-3' aria-hidden>
              <Skeleton className='h-10 w-full' />
              <Skeleton className='h-10 w-full' />
            </div>
          ) : memory.error ? (
            <Unavailable query={memory} fallback='These settings could not be read.' />
          ) : (
            <div className='divide-y'>
              {cloud && <SwitchRow title='A cloud model may read your memory files' badge={cloud.badge} detail={cloud.detail} />}
              {research && <SwitchRow title='Drafting may look facts up on the web' badge={research.badge} detail={research.detail} />}
            </div>
          )}
        </CardContent>
      </Card>

      <div className='flex min-w-0 flex-col gap-3' data-tour='privacy-notice'>
        <div className='flex flex-wrap items-center gap-2'>
          <span className='text-sm font-medium'>Privacy notice</span>
          <LegalReviewBadge />
        </div>
        {notice.isPending ? (
          <NoticeSkeleton tall />
        ) : notice.data ? (
          <>
            {notice.data.status && <p className='text-muted-foreground text-xs'>{sentence(notice.data.status)}</p>}
            <UsageAndServices notice={notice.data} />
          </>
        ) : (
          <Unavailable query={notice} fallback='The privacy notice could not be loaded.' />
        )}
      </div>
    </PrivacySection>
  );
}
