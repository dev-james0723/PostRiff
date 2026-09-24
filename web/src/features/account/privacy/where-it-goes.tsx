'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { LEGAL_LAST_UPDATED, LEGAL_REVIEW_STATUS } from '@/config/legal';
import { siteConfig } from '@/config/site';
import type { MemoryEgress, PrivacyNotice, ResearchEgress } from '@/lib/api/types';
import { SettingsSection } from '../settings-section';
import { plural, retentionLabel, sentence } from './privacy-model';
import { PrivacySection, Unavailable, type Refetchable } from './section';

const linkClass = 't-learn rafii-focus text-foreground inline-flex min-h-9 items-center gap-0.5 rounded-sm text-sm font-medium hover:underline';
const quietAction = buttonVariants({ variant: 'quiet', size: 'sm' }) + ' min-h-9';

function SwitchRow({ title, badge, detail }: { title: string; badge: { label: string; status: AnimatedBadgeStatus }; detail?: ReactNode }) {
  return (
    <div className='flex flex-col gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4'>
      <div className='flex min-w-0 flex-col gap-0.5'>
        <span className='text-foreground text-sm font-medium'>{title}</span>
        {detail && <span className='text-muted-foreground text-xs leading-relaxed'>{detail}</span>}
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
      <Skeleton className={tall ? 'h-56 w-full rounded-[var(--rafii-radius-card)]' : 'h-40 w-full rounded-[var(--rafii-radius-card)]'} />
      <Skeleton className={tall ? 'h-56 w-full rounded-[var(--rafii-radius-card)]' : 'h-40 w-full rounded-[var(--rafii-radius-card)]'} />
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
      <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-4'>
        <h4 className='text-foreground text-base font-medium'>How your content is used</h4>
        <div className='flex flex-col gap-3 text-sm'>
          {usage.map((item) =>
            item.text ? (
              <div key={item.label} className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs font-medium'>{item.label}</span>
                <p className='text-foreground leading-relaxed'>{item.text}</p>
              </div>
            ) : null
          )}
        </div>
      </Surface>

      <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-4'>
        <div className='flex flex-col gap-1'>
          <h4 className='text-foreground text-base font-medium'>Services that process your data</h4>
          <p className='text-muted-foreground text-sm'>As the privacy notice lists them today.</p>
        </div>
        {(notice.subprocessors ?? []).length === 0 ? (
          <p className='text-muted-foreground text-sm'>The notice lists none.</p>
        ) : (
          <ul className='flex flex-col gap-3'>
            {notice.subprocessors.map((processor) => (
              <li key={processor.name} className='flex flex-col gap-0.5 text-sm'>
                <span className='text-foreground font-medium'>{processor.name}</span>
                <span className='text-muted-foreground'>{sentence(processor.purpose)}</span>
                <span className='text-muted-foreground text-xs'>
                  {sentence(processor.status)}
                  {processor.region ? ` · Region ${processor.region}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Surface>
    </div>
  );
}

function RetentionAndRights({ notice }: { notice: PrivacyNotice }) {
  const retention = Object.entries(notice.retention ?? {});
  return (
    <div className='grid min-w-0 gap-4 lg:grid-cols-3'>
      <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-4 lg:col-span-2'>
        <h4 className='text-foreground text-base font-medium'>What is kept, and for how long</h4>
        <dl className='grid gap-x-8 gap-y-4 md:grid-cols-2'>
          {retention.map(([key, value]) => (
            <div key={key} className='flex min-w-0 flex-col gap-0.5 text-sm'>
              <dt className='text-foreground font-medium'>{retentionLabel(key)}</dt>
              <dd className='text-foreground'>{sentence(value.retention)}</dd>
              {value.note && <dd className='text-muted-foreground text-xs leading-relaxed'>{value.note}</dd>}
            </div>
          ))}
        </dl>
      </Surface>

      <Surface material='quiet' radius='card' padding='md' className='flex h-fit flex-col gap-4'>
        <h4 className='text-foreground text-base font-medium'>Your rights</h4>
        <ul className='flex flex-col gap-2 text-sm'>
          {(notice.rights ?? []).map((right) => (
            <li key={right} className='flex items-start gap-2'>
              <Icons.check className='text-foreground mt-0.5 size-4 shrink-0' aria-hidden />
              <span className='text-foreground'>{sentence(right)}</span>
            </li>
          ))}
        </ul>
      </Surface>
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
        <Link href={siteConfig.links.dataDeletion} className={quietAction}>
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
        <Link href={siteConfig.links.privacy} className={quietAction}>
          Full policy <Icons.externalLink className='size-3.5' />
        </Link>
      }
      className='gap-5'
    >
      <SettingsSection
        id='privacy-switches'
        title='This workspace’s switches'
        description={
          canEdit ? (
            <Link href='/app/workspace/memory' className={linkClass}>
              The owner changes these on Memory <LearnMoreChevron className='size-3.5' />
            </Link>
          ) : (
            'Only the workspace owner can change these.'
          )
        }
        data-tour='privacy-egress'
      >
        {memory.isPending ? (
          <div className='flex flex-col gap-3' aria-hidden>
            <Skeleton className='h-10 w-full' />
            <Skeleton className='h-10 w-full' />
          </div>
        ) : memory.error ? (
          <Unavailable query={memory} fallback='These settings could not be read.' />
        ) : (
          <div className='flex flex-col gap-4'>
            {cloud && <SwitchRow title='A cloud model may read your memory files' badge={cloud.badge} detail={cloud.detail} />}
            {research && <SwitchRow title='Drafting may look facts up on the web' badge={research.badge} detail={research.detail} />}
          </div>
        )}
      </SettingsSection>

      <div className='flex min-w-0 flex-col gap-3' data-tour='privacy-notice'>
        <div className='flex flex-wrap items-center gap-2 px-1'>
          <span className='text-foreground text-sm font-medium'>Privacy notice</span>
          <LegalReviewBadge />
        </div>
        {notice.isPending ? (
          <NoticeSkeleton tall />
        ) : notice.data ? (
          <>
            {notice.data.status && <p className='text-muted-foreground px-1 text-xs'>{sentence(notice.data.status)}</p>}
            <UsageAndServices notice={notice.data} />
          </>
        ) : (
          <Unavailable query={notice} fallback='The privacy notice could not be loaded.' />
        )}
      </div>
    </PrivacySection>
  );
}
