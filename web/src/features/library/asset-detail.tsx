'use client';

import type { ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerFooter, DrawerHeader, DrawerTitle } from '@/components/ui/drawer';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useIsMobile } from '@/hooks/use-mobile';
import { formatBytes, formatDateTime, relativeTime } from '@/lib/time';
import { STATUS } from '@/lib/status-labels';
import { cn } from '@/lib/utils';
import { badgeClass, copyHash, dimensionsOf, useAssetImage } from './asset-card';
import { imageRuleChecks } from './image-rules';
import type { AssetUse, LibraryAsset } from './use-library';

interface AssetDetailProps {
  asset: LibraryAsset | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  uses: AssetUse[];
  publishing: boolean;
  canEdit: boolean;
  /** Preparing a post (`p2_review`) needs approve permission. */
  canApprove: boolean;
  deleting: boolean;
  currentUserId: string | null;
  /** Platforms of the workspace's connected accounts, for the image rules. */
  platforms: string[];
  onDelete: (asset: LibraryAsset) => void;
}

/**
 * The job vocabulary of `src/postriff_phase2/store.py` in the shared status words (`STATUS`), one badge per group so
 * "held" never reads as "scheduled".
 */
function badgeFor(use: AssetUse): { status: AnimatedBadgeStatus; label: string } {
  if (use.kind === 'review') return { status: 'info', label: STATUS.needsReview };
  const state = use.state;
  const ended = state === 'verified' || state === 'failed' || state === 'canceled';
  if (use.cancelRequested && !ended) return { status: 'loading', label: 'Cancelling…' };
  if (state === 'scheduled' || state === 'approved' || state === 'claimed') return { status: 'info', label: STATUS.scheduled };
  if (state === 'submitting' || state === 'provider_accepted' || state === 'published' || state === 'processing') return { status: 'loading', label: STATUS.publishing };
  if (state === 'uncertain') return { status: 'warning', label: 'Result not confirmed' };
  if (state === 'held') return { status: 'warning', label: 'Needs action' };
  if (state === 'verified') return { status: 'success', label: STATUS.published };
  if (state === 'failed') return { status: 'danger', label: STATUS.failed };
  if (state === 'canceled') return { status: 'neutral', label: 'Cancelled' };
  return { status: 'neutral', label: state.replace(/_/g, ' ') };
}

/** Relative by default; the exact time goes in the tooltip. */
function whenOf(use: AssetUse) {
  const parsed = Date.parse(use.timing.utc);
  return Number.isNaN(parsed) ? { text: `${use.timing.local} (${use.timing.timeZone})`, exact: undefined } : { text: relativeTime(parsed / 1000), exact: formatDateTime(parsed / 1000) };
}

/* Elevated glass on the existing overlay primitives (DNA §12.2). */
const SHEET_CLASS = 'rafii-elevated gap-0 border-0 bg-transparent data-[side=right]:w-full data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0 data-[side=right]:sm:max-w-[480px]';
const DRAWER_CLASS = 'rafii-elevated bg-transparent data-[swipe-direction=down]:rounded-t-[var(--rafii-radius-mobile-dialog)] data-[swipe-direction=down]:border-t-0 data-[swipe-axis=y]:[--drawer-content-max-height:85dvh]';

function Fact({ term, children, className }: { term: string; children: ReactNode; className?: string }) {
  return (
    <div className='grid grid-cols-[7.5rem_minmax(0,1fr)] items-baseline gap-3 py-2'>
      <dt className='text-muted-foreground text-xs'>{term}</dt>
      <dd className={cn('min-w-0 text-sm', className)}>{children}</dd>
    </div>
  );
}

function HashFact({ term, hash }: { term: string; hash: string }) {
  return (
    <Fact term={term}>
      <span className='flex items-start gap-1'>
        <code className='min-w-0 flex-1 font-mono text-xs break-all'>{hash}</code>
        <Button variant='quiet' size='icon-lg' className='-mt-2 rounded-full' aria-label={`Copy ${term.toLowerCase()}`} onClick={() => void copyHash(hash)}>
          <Icons.copy aria-hidden />
        </Button>
      </span>
    </Fact>
  );
}

/** The real image in its own colours (DNA §21.9); broken media says why and offers Retry, never a blank box. */
function LargeImage({ asset }: { asset: LibraryAsset }) {
  const image = useAssetImage(asset.id);
  const ratio = asset.width && asset.height ? `${asset.width} / ${asset.height}` : '1 / 1';
  return (
    <div className='rafii-quiet flex max-h-[40vh] items-center justify-center overflow-hidden rounded-[var(--rafii-radius-card)] md:max-h-[50vh]'>
      {image.data ? (
        <Image
          src={image.data}
          alt=''
          width={asset.width ?? 800}
          height={asset.height ?? 800}
          unoptimized
          className='h-auto max-h-[40vh] w-auto max-w-full object-contain md:max-h-[50vh]'
        />
      ) : image.isError ? (
        <div className='text-muted-foreground flex aspect-video w-full flex-col items-center justify-center gap-3 p-4 text-center text-sm'>
          <span>
            {image.errorStatus === 404 ? 'Image file missing' : image.storageNotConfigured ? 'Previews aren’t available yet' : 'Preview unavailable'}
          </span>
          {image.canRetry && (
            <Button size='control' variant='glass' disabled={image.isFetching} onClick={() => void image.refetch()}>
              <Icons.refresh className={cn(image.isFetching && 'animate-spin')} aria-hidden />
              Retry
            </Button>
          )}
        </div>
      ) : (
        <Skeleton className='max-h-[40vh] w-full rounded-none md:max-h-[50vh]' style={{ aspectRatio: ratio }} />
      )}
    </div>
  );
}

function UseRow({ use }: { use: AssetUse }) {
  const badge = badgeFor(use);
  const when = whenOf(use);
  return (
    <li className='flex items-start gap-3 py-2.5'>
      <ChannelIcon platform={use.platform} name={use.platform} size='sm' className='mt-0.5' />
      <div className='flex min-w-0 flex-1 flex-col gap-1'>
        <span className='truncate text-sm font-medium'>
          {use.platform} · {use.account}
        </span>
        <span className='flex flex-wrap items-center gap-x-2 gap-y-1'>
          <AnimatedBadge size='sm' status={badge.status} pulse={false} title={use.state.replace(/_/g, ' ')} className={badgeClass(badge.status)}>
            {badge.label}
          </AnimatedBadge>
          <span className='text-muted-foreground text-xs' title={when.exact}>
            {when.text}
          </span>
        </span>
      </div>
      <Link
        href='/app/queue'
        className={cn('t-learn shrink-0', buttonVariants({ variant: 'quiet', size: 'lg' }))}
        aria-label={`Open the ${use.platform} ${use.kind === 'review' ? 'review' : 'post'} in the Queue`}
      >
        Queue
        <LearnMoreChevron />
      </Link>
    </li>
  );
}

function ImageRules({ asset, platforms }: { asset: LibraryAsset; platforms: string[] }) {
  const checks = imageRuleChecks(platforms, asset.width, asset.height);
  return (
    <section aria-labelledby='asset-rules' className='flex flex-col gap-1'>
      <h3 id='asset-rules' className='rafii-eyebrow'>
        Image rules
      </h3>
      {checks.length === 0 ? (
        <p className='text-muted-foreground py-2 text-sm'>Connect an account to check platform rules.</p>
      ) : (
        <ul className='flex flex-col'>
          {checks.map((check) => (
            <li key={check.platform} className='flex items-start gap-3 py-2.5'>
              <ChannelIcon platform={check.platform} name={check.platform} size='sm' className='mt-0.5' />
              <div className='flex min-w-0 flex-1 flex-col gap-0.5 text-sm'>
                {check.rule ? <span>{check.rule}</span> : null}
                <span className={cn(check.rule ? 'text-muted-foreground text-xs' : 'text-muted-foreground')}>{check.note}</span>
              </div>
              {check.fits === false && (
                <AnimatedBadge size='sm' status='warning' pulse={false} className={badgeClass('warning')}>
                  Outside range
                </AnimatedBadge>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function DetailBody({
  asset,
  uses,
  publishing,
  currentUserId,
  platforms
}: Pick<AssetDetailProps, 'uses' | 'publishing' | 'currentUserId' | 'platforms'> & { asset: LibraryAsset }) {
  const dims = dimensionsOf(asset);
  const reencoded = asset.mime === 'image/jpeg' && asset.processing === 'decoded';
  return (
    <div className='flex flex-col gap-6'>
      <LargeImage asset={asset} />

      {publishing && (
        <StateMessage kind='loading' layout='inline' title='A post using this image is publishing' description='You can delete it once that post finishes.' />
      )}

      {/* Provenance and rights are inspectable facts (DNA §21.9), read as quiet rows without dividers. */}
      <section aria-labelledby='asset-facts' className='flex flex-col gap-1'>
        <h3 id='asset-facts' className='rafii-eyebrow'>
          Details
        </h3>
        <dl className='flex flex-col'>
          <Fact term='Dimensions'>{dims ? `${dims} px` : 'Not recorded'}</Fact>
          <Fact term='Size'>{typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : 'Not recorded'}</Fact>
          <Fact term='Format'>{reencoded ? 'JPEG · metadata removed' : asset.mime}</Fact>
          <HashFact term='Stored hash' hash={asset.hash} />
          {asset.sourceHash && <HashFact term='Source hash' hash={asset.sourceHash} />}
          {typeof asset.createdAt === 'number' && (
            <Fact term='Uploaded'>
              <span title={formatDateTime(asset.createdAt)}>{relativeTime(asset.createdAt)}</span>
              {asset.uploadedBy ? ` · ${asset.uploadedBy === currentUserId ? 'by you' : 'by a teammate'}` : ''}
            </Fact>
          )}
        </dl>
      </section>

      <section aria-labelledby='asset-uses' className='flex flex-col gap-1'>
        <div className='flex items-center justify-between gap-2'>
          <h3 id='asset-uses' className='rafii-eyebrow'>
            Used in
          </h3>
          <Link href='/app/queue?view=drafts' className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'lg' }))}>
            Drafts
            <LearnMoreChevron />
          </Link>
        </div>
        {uses.length === 0 ? (
          <p className='text-muted-foreground py-2 text-sm'>Not used yet</p>
        ) : (
          <ul className='flex flex-col'>
            {uses.map((use) => (
              <UseRow key={`${use.kind}-${use.id}`} use={use} />
            ))}
          </ul>
        )}
      </section>

      <ImageRules asset={asset} platforms={platforms} />
    </div>
  );
}

/** One inverted commitment (Use in a post), quiet glass for the rest; Delete keeps its destructive weight (DNA §10.1). */
function DetailActions({
  asset,
  publishing,
  canEdit,
  canApprove,
  deleting,
  onDelete
}: Pick<AssetDetailProps, 'publishing' | 'canEdit' | 'canApprove' | 'deleting' | 'onDelete'> & { asset: LibraryAsset }) {
  return (
    <>
      {!canApprove && canEdit && <p className='text-muted-foreground text-xs leading-relaxed'>Only approvers can use images in posts.</p>}
      <div className='flex flex-wrap gap-2'>
        {canApprove ? (
          <Link href={`/app/queue?asset=${encodeURIComponent(asset.id)}`} className={cn(buttonVariants({ variant: 'action', size: 'control' }), 'flex-1 sm:flex-none')}>
            <Icons.send aria-hidden />
            Use in a post
          </Link>
        ) : canEdit ? (
          <Link href='/app/ideas' className={cn('t-learn flex-1 sm:flex-none', buttonVariants({ variant: 'glass', size: 'control' }))}>
            Open Ideas
            <LearnMoreChevron />
          </Link>
        ) : null}
        {canEdit && (
          <Button
            variant='destructive'
            size='control'
            className='rounded-[var(--rafii-radius-control)] sm:ml-auto'
            disabled={deleting || publishing}
            title={publishing ? 'A post using this image is publishing' : undefined}
            onClick={() => onDelete(asset)}
          >
            {deleting ? <Icons.spinner className='animate-spin' aria-hidden /> : <Icons.trash aria-hidden />}
            {deleting ? 'Deleting…' : 'Delete…'}
          </Button>
        )}
      </div>
    </>
  );
}

export function AssetDetail(props: AssetDetailProps) {
  const { asset, open, onOpenChange } = props;
  const isMobile = useIsMobile();
  const dims = asset ? dimensionsOf(asset) : null;
  const title = dims ? `Image ${dims}` : 'Image';
  const description = props.uses.length === 0 ? 'Not used in a post yet' : `Used in ${props.uses.length} ${props.uses.length === 1 ? 'post' : 'posts'}`;

  if (isMobile) {
    return (
      <Drawer open={open && asset !== null} onOpenChange={onOpenChange}>
        <DrawerContent className={DRAWER_CLASS}>
          {asset && (
            <>
              <DrawerHeader className='flex-row items-start gap-3 text-left'>
                <div className='flex min-w-0 flex-1 flex-col gap-0.5 text-left'>
                  <DrawerTitle>{title}</DrawerTitle>
                  <DrawerDescription>{description}</DrawerDescription>
                </div>
                <DrawerClose render={<Button variant='glass' size='icon-control' aria-label='Close image details' />}>
                  <Icons.close aria-hidden />
                </DrawerClose>
              </DrawerHeader>
              <div className='min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4'>
                <DetailBody asset={asset} uses={props.uses} publishing={props.publishing} currentUserId={props.currentUserId} platforms={props.platforms} />
              </div>
              <DrawerFooter className='pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]'>
                <DetailActions
                  asset={asset}
                  publishing={props.publishing}
                  canEdit={props.canEdit}
                  canApprove={props.canApprove}
                  deleting={props.deleting}
                  onDelete={props.onDelete}
                />
              </DrawerFooter>
            </>
          )}
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Sheet open={open && asset !== null} onOpenChange={onOpenChange}>
      <SheetContent side='right' showCloseButton={false} className={SHEET_CLASS}>
        {asset && (
          <>
            <SheetClose render={<Button variant='glass' size='icon-control' aria-label='Close image details' className='absolute top-3 right-3 z-10' />}>
              <Icons.close aria-hidden />
            </SheetClose>
            <SheetHeader className='pr-16'>
              <SheetTitle>{title}</SheetTitle>
              <SheetDescription>{description}</SheetDescription>
            </SheetHeader>
            <div className='min-h-0 flex-1 overflow-y-auto px-4 pb-4'>
              <DetailBody asset={asset} uses={props.uses} publishing={props.publishing} currentUserId={props.currentUserId} platforms={props.platforms} />
            </div>
            <SheetFooter className='pt-3'>
              <DetailActions
                  asset={asset}
                  publishing={props.publishing}
                  canEdit={props.canEdit}
                  canApprove={props.canApprove}
                  deleting={props.deleting}
                  onDelete={props.onDelete}
                />
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
