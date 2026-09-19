'use client';

import type { ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerFooter, DrawerHeader, DrawerTitle } from '@/components/ui/drawer';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useIsMobile } from '@/hooks/use-mobile';
import { formatBytes, formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { copyHash, dimensionsOf, useAssetImage } from './asset-card';
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

/** The job vocabulary of `src/postriff_phase2/store.py`, one badge per group so "held" never reads as "scheduled". */
function badgeFor(use: AssetUse): { status: AnimatedBadgeStatus; label: string } {
  if (use.kind === 'review') return { status: 'info', label: 'waiting for approval' };
  const state = use.state;
  const ended = state === 'verified' || state === 'failed' || state === 'canceled';
  if (use.cancelRequested && !ended) return { status: 'loading', label: 'cancelling' };
  if (state === 'scheduled' || state === 'approved' || state === 'claimed') return { status: 'info', label: 'waiting' };
  if (state === 'submitting' || state === 'provider_accepted' || state === 'published') return { status: 'loading', label: state.replace(/_/g, ' ') };
  if (state === 'uncertain') return { status: 'warning', label: 'uncertain' };
  if (state === 'held') return { status: 'warning', label: 'held' };
  if (state === 'verified') return { status: 'success', label: 'verified' };
  if (state === 'failed') return { status: 'danger', label: 'failed' };
  if (state === 'canceled') return { status: 'neutral', label: 'cancelled' };
  return { status: 'neutral', label: state.replace(/_/g, ' ') };
}

function whenOf(use: AssetUse) {
  const parsed = Date.parse(use.timing.utc);
  return Number.isNaN(parsed) ? `${use.timing.local} (${use.timing.timeZone})` : formatDateTime(parsed / 1000);
}

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
        <Button variant='ghost' size='icon-xs' aria-label={`Copy ${term.toLowerCase()}`} onClick={() => void copyHash(hash)}>
          <Icons.copy aria-hidden />
        </Button>
      </span>
    </Fact>
  );
}

function LargeImage({ asset }: { asset: LibraryAsset }) {
  const image = useAssetImage(asset.id);
  const ratio = asset.width && asset.height ? `${asset.width} / ${asset.height}` : '1 / 1';
  return (
    <div className='bg-muted/60 flex max-h-[40vh] items-center md:max-h-[50vh] justify-center overflow-hidden rounded-lg border'>
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
        <div className='text-muted-foreground flex aspect-video w-full flex-col items-center justify-center gap-2 text-sm'>
          <span>
            {image.errorStatus === 404
              ? 'The image file is not in private storage'
              : image.storageNotConfigured
                ? 'Private media storage is not configured'
                : 'Preview unavailable'}
          </span>
          {image.canRetry && (
            <Button size='sm' variant='outline' disabled={image.isFetching} onClick={() => void image.refetch()}>
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
  return (
    <li className='flex items-start gap-3 py-2.5'>
      <ChannelIcon platform={use.platform} name={use.platform} size='sm' className='mt-0.5' />
      <div className='flex min-w-0 flex-1 flex-col gap-1'>
        <span className='truncate text-sm font-medium'>
          {use.platform} · {use.account}
        </span>
        <span className='flex flex-wrap items-center gap-x-2 gap-y-1'>
          <AnimatedBadge size='sm' status={badge.status} pulse={false} title={use.state.replace(/_/g, ' ')}>
            {badge.label}
          </AnimatedBadge>
          <span className='text-muted-foreground text-xs'>
            {use.kind === 'review' ? 'Review' : 'Post'} · publish time {whenOf(use)}
          </span>
        </span>
      </div>
      <Link
        href='/app/queue'
        className={cn('t-learn shrink-0', buttonVariants({ variant: 'ghost', size: 'xs' }))}
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
    <section aria-labelledby='asset-rules' className='flex flex-col'>
      <h3 id='asset-rules' className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>
        Image rules
      </h3>
      {checks.length === 0 ? (
        <p className='text-muted-foreground py-2 text-sm'>No accounts are connected, so there are no platform rules to check.</p>
      ) : (
        <ul className='divide-y'>
          {checks.map((check) => (
            <li key={check.platform} className='flex items-start gap-3 py-2.5'>
              <ChannelIcon platform={check.platform} name={check.platform} size='sm' className='mt-0.5' />
              <div className='flex min-w-0 flex-1 flex-col gap-0.5 text-sm'>
                {check.rule ? <span>{check.rule}</span> : null}
                <span className={cn(check.rule ? 'text-muted-foreground text-xs' : 'text-muted-foreground')}>{check.note}</span>
              </div>
              {check.fits === false && (
                <AnimatedBadge size='sm' status='warning' pulse={false}>
                  outside range
                </AnimatedBadge>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className='text-muted-foreground mt-1 text-xs'>Every post with an image also needs alt text and your confirmation that you may use the image.</p>
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
    <div className='flex flex-col gap-5'>
      <LargeImage asset={asset} />

      {publishing && (
        <Alert>
          <Icons.spinner className='animate-spin' aria-hidden />
          <AlertTitle>A post using this image is still being published or checked</AlertTitle>
          <AlertDescription>Delete it once that post has settled. The workspace refuses to delete an image while a post using it is in flight.</AlertDescription>
        </Alert>
      )}

      <section aria-labelledby='asset-facts' className='flex flex-col'>
        <h3 id='asset-facts' className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>
          Provenance
        </h3>
        <dl className='divide-y'>
          <Fact term='Dimensions'>{dims ? `${dims} px` : 'Not recorded'}</Fact>
          <Fact term='Size'>{typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : 'Not recorded'}</Fact>
          <Fact term='Format'>{reencoded ? 'JPEG, re-encoded on upload with metadata removed' : asset.mime}</Fact>
          <HashFact term='Stored hash' hash={asset.hash} />
          {asset.sourceHash && <HashFact term='Source hash' hash={asset.sourceHash} />}
          {typeof asset.createdAt === 'number' && (
            <Fact term='Uploaded'>
              {formatDateTime(asset.createdAt)}
              {asset.uploadedBy ? ` · ${asset.uploadedBy === currentUserId ? 'by you' : 'by a workspace member'}` : ''}
            </Fact>
          )}
          {asset.decoder && <Fact term='Decoder'>{asset.decoder}</Fact>}
        </dl>
        <p className='text-muted-foreground mt-1 text-xs'>
          The stored hash names the exact bytes a post publishes; a post records it when it is prepared.
          {asset.sourceHash ? ' The source hash names the file as you uploaded it, before it was re-encoded.' : ''}
        </p>
      </section>

      <section aria-labelledby='asset-uses' className='flex flex-col'>
        <div className='flex items-center justify-between gap-2'>
          <h3 id='asset-uses' className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>
            Used in
          </h3>
          <Link href='/app/pipeline' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'xs' }))}>
            Pipeline
            <LearnMoreChevron />
          </Link>
        </div>
        {uses.length === 0 ? (
          <p className='text-muted-foreground py-2 text-sm'>Not used in a post yet.</p>
        ) : (
          <ul className='divide-y'>
            {uses.map((use) => (
              <UseRow key={`${use.kind}-${use.id}`} use={use} />
            ))}
          </ul>
        )}
        <p className='text-muted-foreground mt-1 text-xs'>
          Counts posts in every state and reviews waiting for approval. The workspace keeps its 20 most recent reviews.
        </p>
      </section>

      <ImageRules asset={asset} platforms={platforms} />
    </div>
  );
}

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
      {canApprove ? (
        <p className='text-muted-foreground text-xs'>
          Choose this image under “Schedule a draft” in the Queue. Its hash starts with <code className='font-mono'>{asset.hash.slice(0, 8)}</code>.
        </p>
      ) : canEdit ? (
        <p className='text-muted-foreground text-xs'>Preparing a post needs approve access. Keep drafting in Ideas; someone who approves posts attaches the image.</p>
      ) : null}
      <div className='flex flex-wrap gap-2'>
        {canApprove ? (
          <Link href='/app/queue' className={cn(buttonVariants({ variant: 'default' }), 'flex-1 sm:flex-none')}>
            <Icons.send aria-hidden />
            Use in a post
          </Link>
        ) : canEdit ? (
          <Link href='/app/ideas' className={cn('t-learn flex-1 sm:flex-none', buttonVariants({ variant: 'outline' }))}>
            Open Ideas
            <LearnMoreChevron />
          </Link>
        ) : null}
        <Button variant='outline' onClick={() => void copyHash(asset.hash)}>
          <Icons.copy aria-hidden />
          Copy hash
        </Button>
        {canEdit && (
          <Button
            variant='destructive'
            className='sm:ml-auto'
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
        <DrawerContent className='data-[swipe-axis=y]:[--drawer-content-max-height:85dvh]'>
          {asset && (
            <>
              <DrawerHeader className='flex-row items-start gap-3 text-left'>
                <div className='flex min-w-0 flex-1 flex-col gap-0.5 text-left'>
                  <DrawerTitle>{title}</DrawerTitle>
                  <DrawerDescription>{description}</DrawerDescription>
                </div>
                <DrawerClose render={<Button variant='ghost' size='icon-sm' aria-label='Close image details' />}>
                  <Icons.close aria-hidden />
                </DrawerClose>
              </DrawerHeader>
              <div className='min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4'>
                <DetailBody asset={asset} uses={props.uses} publishing={props.publishing} currentUserId={props.currentUserId} platforms={props.platforms} />
              </div>
              <DrawerFooter className='border-t pt-4'>
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
      <SheetContent side='right' className='gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-[480px]'>
        {asset && (
          <>
            <SheetHeader className='pr-12'>
              <SheetTitle>{title}</SheetTitle>
              <SheetDescription>{description}</SheetDescription>
            </SheetHeader>
            <div className='min-h-0 flex-1 overflow-y-auto px-4 pb-4'>
              <DetailBody asset={asset} uses={props.uses} publishing={props.publishing} currentUserId={props.currentUserId} platforms={props.platforms} />
            </div>
            <SheetFooter className='border-t'>
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
