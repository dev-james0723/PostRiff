'use client';

import { useEffect, useId, useRef, type ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerFooter, DrawerHeader, DrawerTitle } from '@/components/ui/drawer';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useIsMobile } from '@/hooks/use-mobile';
import type { AssetRef, Locator } from '@/lib/api/library-intelligence-types';
import { formatBytes, formatDateTime, relativeTime } from '@/lib/time';
import { STATUS } from '@/lib/status-labels';
import { cn } from '@/lib/utils';
import { assetRefFor, openerSelector } from '@/lib/library/url-state';
import { formatClock } from '@/lib/library/wording';
import { AssetOrganizer } from './library-organizer';
import { assetTitle, badgeClass, copyHash, dimensionsOf, kindLabel, useAssetImage } from './asset-card';
import { imageRuleChecks } from './image-rules';
import type { AssetUse, LibraryAsset } from './use-library';
import { toast } from 'sonner';
import { kindOf } from '@/lib/media/asset-kinds';
import { useNowPlaying } from '@/lib/media/now-playing';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { AssetFileThumbnail } from './asset-thumbnail';
import { AudioMomentPlayer } from './intelligence/audio-player';
import { VersionsPanel } from './intelligence/versions-panel';
import { UsagePanel } from './intelligence/usage-panel';
import { VoicePanel } from './intelligence/voice-panel';
import {
  CapabilityList,
  DangerArea,
  DetailSection,
  PurposeList,
  SectionNav,
  SegmentList,
  SuggestedUses,
  UnderstandingSummary,
  useAssetIntelligence,
  type AssetIntelligence
} from './intelligence/detail-sections';
import { DocumentViewerLauncher } from './document-viewer';
import { Control, IconControl, controlClass } from './ui/controls';

interface AssetDetailProps {
  asset: LibraryAsset | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  uses: AssetUse[];
  publishing: boolean;
  canEdit: boolean;
  /** Preparing a post (`p2_review`) needs approve permission. */
  canApprove: boolean;
  /** Voice and other workspace-wide purposes are the owner's decision. */
  isOwner?: boolean;
  deleting: boolean;
  currentUserId: string | null;
  /** Platforms of the workspace's connected accounts, for the image rules. */
  platforms: string[];
  onDelete: (asset: LibraryAsset) => void;
  /** Library intelligence answers in this build; per-item reads are attempted only then. */
  intelligence?: boolean;
  /** The passage or moment a search result pointed at. */
  focusLocator?: Locator | null;
  onAnnounce?: (message: string) => void;
  /** Open another item (a related version or a suggestion) in this panel. */
  onOpenAsset?: (assetId: string) => void;
  /** "Use in draft": build a source pack starting from this item (absent where source packs are off). */
  onUseInDraft?: (asset: LibraryAsset, ref: AssetRef) => void;
  /** Voice examples are switched on here; otherwise `voiceNote` says why the voice panel is missing. */
  voiceEnabled?: boolean;
  voiceNote?: string | null;
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

/* Elevated glass on the existing overlay primitives (DNA §12.2). The global material falls back to an opaque fill. */
const SHEET_CLASS = 'rafii-elevated gap-0 border-0 bg-transparent data-[side=right]:w-full data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0 data-[side=right]:sm:max-w-[520px]';
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
        <IconControl label={`Copy ${term.toLowerCase()}`} size='sm' className='-mt-1.5' onClick={() => void copyHash(hash)}>
          <Icons.copy aria-hidden />
        </IconControl>
      </span>
    </Fact>
  );
}

/** The real preview in its own colours (DNA §21.9); broken media says why and offers Retry, never a blank box. */
function LargeImage({ asset, peaks }: { asset: LibraryAsset; peaks?: number[] | null }) {
  const assetKind = kindOf(asset);
  const mediaAsset = assetKind === 'image' || assetKind === 'video';
  const image = useAssetImage(asset.id, mediaAsset);
  const { api, workspaceId } = useWorkspaceApi();
  const isVideo = assetKind === 'video';
  if (!mediaAsset) {
    return <div className='flex flex-col gap-3'><AssetFileThumbnail asset={asset} size='detail' peaks={peaks} /><DocumentViewerLauncher key={asset.id} asset={asset} /></div>;
  }
  if (isVideo) {
    return (
      <div data-library-thumbnail='video' data-thumbnail-preview='video-poster' className='bg-foreground/[0.035] flex max-h-[40vh] items-center justify-center overflow-hidden rounded-[var(--rafii-radius-card)] md:max-h-[44vh]'>
        {/* The poster is a picture; playback is the one Rafii player, started only by this press. */}
        <button
          type='button'
          className='rafii-focus relative flex min-h-11 w-full items-center justify-center'
          onClick={() => void api.mediaUrl(workspaceId, asset.id).then(({ url }) => useNowPlaying.getState().open({ workspaceId, assetId: asset.id, title: assetTitle(asset), url })).catch((error) => toast.error(error instanceof Error ? error.message : 'Video unavailable'))}
        >
          {image.data ? <Image src={image.data} alt='' width={asset.width ?? 480} height={asset.height ?? 270} unoptimized className='h-auto max-h-[40vh] w-auto max-w-full object-contain md:max-h-[50vh]' /> : <span className='h-40 w-full' />}
          <span className='bg-background/90 ring-foreground/10 absolute inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-medium shadow-xs ring-1'>
            <Icons.play className='size-4' aria-hidden />
            Play video in Now Playing
          </span>
        </button>
      </div>
    );
  }
  const ratio = asset.width && asset.height ? `${asset.width} / ${asset.height}` : '1 / 1';
  return (
    <div className='bg-foreground/[0.035] flex max-h-[40vh] items-center justify-center overflow-hidden rounded-[var(--rafii-radius-card)] md:max-h-[44vh]'>
      {image.data ? (
        <Image src={image.data} alt='' width={asset.width ?? 800} height={asset.height ?? 800} unoptimized className='h-auto max-h-[40vh] w-auto max-w-full object-contain md:max-h-[50vh]' />
      ) : image.isError ? (
        <div className='text-muted-foreground flex aspect-video w-full flex-col items-center justify-center gap-3 p-4 text-center text-sm'>
          <span>{image.errorStatus === 404 ? 'Image file missing' : image.storageNotConfigured ? 'Previews aren’t available yet' : 'Preview unavailable'}</span>
          {image.canRetry && (
            <Control tone='secondary' size='sm' disabled={image.isFetching} icon={<Icons.refresh className={cn(image.isFetching && 'animate-spin')} aria-hidden />} onClick={() => void image.refetch()}>
              Retry
            </Control>
          )}
        </div>
      ) : (
        <Skeleton className='max-h-[40vh] w-full rounded-none md:max-h-[50vh]' style={{ aspectRatio: ratio }} />
      )}
    </div>
  );
}

/** The deterministic extracted text, used when structural passages with locators are not available. */
function DocumentText({ asset }: { asset: LibraryAsset }) {
  const { api, workspaceId } = useWorkspaceApi();
  const detail = useQuery({
    queryKey: ['library-file-detail', workspaceId, asset.id],
    queryFn: () => api.libraryFile(workspaceId, asset.id),
    enabled: Boolean(workspaceId),
    refetchInterval: (query) => (['pending', 'queued', 'processing'].includes(query.state.data?.asset.processing ?? '') ? 3000 : false),
    staleTime: 10_000
  });
  return (
    <section aria-labelledby='asset-extracted-text' className='flex flex-col gap-2'>
      <h4 id='asset-extracted-text' className='rafii-eyebrow'>
        Extracted text
      </h4>
      {detail.isPending ? (
        <Skeleton className='h-24 w-full' />
      ) : detail.isError ? (
        <Control tone='secondary' size='sm' className='self-start' onClick={() => void detail.refetch()}>
          Retry text preview
        </Control>
      ) : detail.data.extractedText ? (
        <pre className='rafii-quiet max-h-72 overflow-auto rounded-[var(--rafii-radius-card)] p-3 text-xs leading-relaxed whitespace-pre-wrap'>{detail.data.extractedText}</pre>
      ) : (
        <p role='status' className='text-muted-foreground text-sm'>
          {['pending', 'queued', 'processing'].includes(asset.processing ?? '')
            ? 'Extracting and indexing in the background…'
            : asset.extractionError || (kindOf(asset) === 'audio' ? 'Add a transcript below to make this audio searchable. Automatic transcription is unavailable.' : 'No extractable text. Scanned PDFs need a text layer. The original is stored privately.')}
        </p>
      )}
    </section>
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
      <Link href='/app/queue' className={cn('t-learn shrink-0', controlClass({ tone: 'ghost', size: 'sm' }))} aria-label={`Open the ${use.platform} ${use.kind === 'review' ? 'review' : 'post'} in the Queue`}>
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
      <h4 id='asset-rules' className='rafii-eyebrow'>
        Image rules
      </h4>
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

/** "PDF document · 2.1 MB", "Audio · 3:12 · MP3": what this is, before anything else. */
function whatItIs(asset: LibraryAsset, media?: { durationMs?: number; pages?: number; slides?: number } | null) {
  const extension = (asset.extension || asset.originalFilename?.split('.').pop() || '').toUpperCase();
  const seconds = typeof media?.durationMs === 'number' ? media.durationMs / 1000 : typeof asset.duration === 'number' && asset.duration > 0 ? asset.duration : null;
  return [
    kindLabel(asset),
    extension && kindOf(asset) !== 'image' ? extension : null,
    seconds ? formatClock(seconds * 1000) : null,
    typeof media?.pages === 'number' ? `${media.pages} ${media.pages === 1 ? 'page' : 'pages'}` : null,
    typeof media?.slides === 'number' ? `${media.slides} ${media.slides === 1 ? 'slide' : 'slides'}` : null,
    dimensionsOf(asset),
    typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null
  ]
    .filter(Boolean)
    .join(' · ');
}

function DetailBody({
  asset,
  uses,
  publishing,
  currentUserId,
  platforms,
  canEdit,
  deleting,
  onDelete,
  intel,
  focusLocator,
  onAnnounce,
  intelligence,
  onOpenAsset,
  voiceEnabled = true,
  voiceNote,
  actions
}: Pick<AssetDetailProps, 'uses' | 'publishing' | 'currentUserId' | 'platforms' | 'canEdit' | 'deleting' | 'onDelete' | 'focusLocator' | 'onAnnounce' | 'intelligence' | 'onOpenAsset' | 'voiceEnabled' | 'voiceNote'> & {
  asset: LibraryAsset;
  isOwner: boolean;
  intel: AssetIntelligence;
  /** The next actions, right under the preview (wide screens; the phone drawer keeps them in its footer). */
  actions?: ReactNode;
}) {
  const prefix = useId().replace(/:/g, '');
  const dims = dimensionsOf(asset);
  const reencoded = asset.mime === 'image/jpeg' && asset.processing === 'decoded';
  const kind = kindOf(asset);
  const card = intel.card.data;
  const segments = intel.segments.data?.segments ?? [];
  const moments = segments.filter((segment) => segment.kind === 'moment');
  const usage = intel.usage.data ?? null;
  const title = assetTitle(asset);
  const textual = kind === 'document' || kind === 'file' || kind === 'audio';
  return (
    <div className='flex flex-col gap-5'>
      {/* Preview first (redesign §6): the real thing, large, then what to do with it. */}
      <LargeImage asset={asset} peaks={card?.media?.peaks ?? null} />
      {actions}

      <SectionNav prefix={prefix} />

      <DetailSection prefix={prefix} id='overview' title='Overview'>
        <p className='text-muted-foreground text-sm'>{whatItIs(asset, card?.media)}</p>
        <UnderstandingSummary asset={asset} card={card} />
        <SuggestedUses card={card} />
        {publishing && <StateMessage kind='loading' layout='inline' title='A post using this asset is publishing' description='You can delete it once that post finishes.' />}
        {textual && intelligence ? (
          <div className='flex flex-col gap-1.5'>
            <p className='text-muted-foreground text-xs font-medium'>My voice</p>
            {voiceEnabled ? <VoicePanel assetKey={intel.key} segments={segments} enabled /> : <p className='text-muted-foreground text-sm'>{voiceNote ?? 'Voice examples aren’t available here.'}</p>}
          </div>
        ) : null}
        {canEdit ? (
          <div className='flex flex-col gap-2'>
            <p className='text-muted-foreground text-xs font-medium'>Edit details</p>
            <AssetOrganizer key={asset.id} asset={asset} canEdit={canEdit} />
          </div>
        ) : null}
        {/* Processing states and source permissions stay one click away, not the first screen. */}
        <details className='group/permissions rafii-quiet rounded-[var(--rafii-radius-card)] px-3'>
          <summary className='rafii-focus flex min-h-10 cursor-pointer items-center justify-between gap-2 text-sm font-medium pointer-coarse:min-h-11'>
            Processing and permissions
            <Icons.chevronDown className='size-4 transition-transform duration-150 group-open/permissions:rotate-180 motion-reduce:transition-none' aria-hidden />
          </summary>
          <div className='flex flex-col gap-4 pb-3'>
            {card?.capabilityStates?.length ? <CapabilityList states={card.capabilityStates} /> : <p className='text-muted-foreground text-sm'>Processing details appear once the Library service has read this item.</p>}
            <div className='flex flex-col gap-1.5'>
              <p className='text-muted-foreground text-xs font-medium'>What Rafii may use it for</p>
              <PurposeList card={card} />
            </div>
          </div>
        </details>
      </DetailSection>

      <DetailSection prefix={prefix} id='content' title='Content'>
        {kind === 'audio' ? <AudioMomentPlayer asset={asset} title={title} assetRef={card?.assetRef ?? null} durationMs={card?.media?.durationMs ?? null} moments={moments} canEdit={canEdit} onAnnounce={onAnnounce} /> : null}
        {segments.some((segment) => segment.kind !== 'moment') ? <SegmentList segments={segments} focus={focusLocator} /> : textual ? <DocumentText asset={asset} /> : null}
        {kind === 'image' ? <ImageRules asset={asset} platforms={platforms} /> : null}
        {kind === 'video' ? <p className='text-muted-foreground text-sm'>The preview above plays the original in Now Playing.</p> : null}
      </DetailSection>

      <DetailSection prefix={prefix} id='related' title='Related'>
        <VersionsPanel assetKey={intel.key} canEdit={canEdit} enabled={Boolean(intelligence)} onOpenAsset={(assetId) => onOpenAsset?.(assetId)} onAnnounce={(message) => onAnnounce?.(message)} />
      </DetailSection>

      <DetailSection prefix={prefix} id='usage' title='Usage'>
        {usage ? (
          <UsagePanel usage={usage} />
        ) : (
          <>
            {/* Without the usage service: the posts this workspace prepared with it, from the snapshot. */}
            {uses.length === 0 ? <p className='text-muted-foreground text-sm'>Not used yet</p> : null}
            {uses.length ? (
              <ul aria-label='Posts using this item' className='flex flex-col'>
                {uses.map((use) => (
                  <UseRow key={`${use.kind}-${use.id}`} use={use} />
                ))}
              </ul>
            ) : null}
            <p className='text-muted-foreground text-xs'>Post metrics appear here when Library usage is available. Missing values read unknown.</p>
          </>
        )}
        <Link href='/app/queue?view=drafts' className={cn('t-learn self-start', controlClass({ tone: 'ghost', size: 'sm' }))}>
          Drafts
          <LearnMoreChevron />
        </Link>
      </DetailSection>

      {/* Provenance and rights stay inspectable (DNA §21.9), but hashes and formats are secondary. */}
      <details className='group/technical rafii-quiet rounded-[var(--rafii-radius-card)] px-3'>
        <summary className='rafii-focus flex min-h-10 cursor-pointer items-center justify-between gap-2 text-sm font-medium pointer-coarse:min-h-11'>
          Technical details
          <Icons.chevronDown className='size-4 transition-transform duration-150 group-open/technical:rotate-180 motion-reduce:transition-none' aria-hidden />
        </summary>
        <dl className='flex flex-col pb-2'>
          {dims ? <Fact term='Dimensions'>{dims} px</Fact> : null}
          <Fact term='Processing'>{(asset.processing ?? 'unknown').replaceAll('_', ' ')}</Fact>
          {asset.extractionError ? <Fact term='Issue'>{asset.extractionError}</Fact> : null}
          <Fact term='Size'>{typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : 'Not recorded'}</Fact>
          {asset.originalFilename ? <Fact term='Original file'>{asset.originalFilename}</Fact> : null}
          <Fact term='Format'>{reencoded ? 'JPEG · metadata removed' : asset.mime}</Fact>
          {asset.aiTags?.length ? <Fact term='Tags'>{asset.aiTags.join(' · ')}</Fact> : null}
          <HashFact term='Stored hash' hash={asset.hash} />
          {asset.sourceHash && <HashFact term='Source hash' hash={asset.sourceHash} />}
          {typeof asset.createdAt === 'number' && (
            <Fact term='Uploaded'>
              <span title={formatDateTime(asset.createdAt)}>{relativeTime(asset.createdAt)}</span>
              {asset.uploadedBy ? ` · ${asset.uploadedBy === currentUserId ? 'by you' : 'by a teammate'}` : ''}
            </Fact>
          )}
        </dl>
      </details>

      {canEdit ? <DangerArea uses={uses.length} recorded={usage ? usage.uses.filter((entry) => entry.source !== 'post_job' && entry.source !== 'post_review').length : 0} publishing={publishing} deleting={deleting} onDelete={() => onDelete(asset)} /> : null}
    </div>
  );
}

/** Opens the private original (or its download) in a new tab without exposing a signed link in this page. */
function openOriginal(api: ReturnType<typeof useWorkspaceApi>['api'], workspaceId: string, asset: LibraryAsset, download: boolean) {
  const target = window.open('about:blank', '_blank');
  if (target) target.opener = null;
  void api
    .libraryFileUrl(workspaceId, asset.id, download)
    .then(({ url }) => {
      if (target) target.location.href = url;
      else toast.error(download ? 'Allow a new tab to download the file.' : 'Allow a new tab to open the original.');
    })
    .catch(() => {
      target?.close();
      toast.error(download ? 'Download unavailable' : 'File unavailable');
    });
}

/**
 * The next actions (redesign §4, §6): contextual secondary buttons — the page's one primary stays Add — and familiar
 * utilities as named icon buttons. Delete lives apart, in the danger area.
 */
function DetailActions({ asset, assetRef, canEdit, canApprove, onUseInDraft }: Pick<AssetDetailProps, 'canEdit' | 'canApprove' | 'onUseInDraft'> & { asset: LibraryAsset; assetRef: AssetRef }) {
  const { api, workspaceId } = useWorkspaceApi();
  const mediaAsset = kindOf(asset) === 'image' || kindOf(asset) === 'video';
  return (
    <div className='flex flex-col gap-2'>
      {mediaAsset && !canApprove && canEdit && <p className='text-muted-foreground text-xs leading-relaxed'>Only approvers can use media in posts.</p>}
      <div className='flex flex-wrap items-center gap-1.5'>
        {canEdit && onUseInDraft ? (
          <Control tone='secondary' icon={<Icons.sparkles aria-hidden />} onClick={() => onUseInDraft(asset, assetRef)}>
            Use in draft
          </Control>
        ) : null}
        {canApprove && mediaAsset ? (
          <Link href={`/app/queue?asset=${encodeURIComponent(asset.id)}`} className={controlClass({ tone: 'secondary' })}>
            <Icons.send aria-hidden />
            Use in a post
          </Link>
        ) : canEdit ? (
          <Link href='/app/ideas' className={cn('t-learn', controlClass({ tone: 'ghost' }))}>
            Open Ideas
            <LearnMoreChevron />
          </Link>
        ) : null}
        {!mediaAsset ? (
          <span className='ml-auto flex items-center gap-1'>
            <IconControl label='Open original' tone='ghost' onClick={() => openOriginal(api, workspaceId, asset, false)}>
              <Icons.externalLink aria-hidden />
            </IconControl>
            <IconControl label='Download original' tone='ghost' onClick={() => openOriginal(api, workspaceId, asset, true)}>
              <Icons.download aria-hidden />
            </IconControl>
          </span>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The inspector (redesign §6). From 1280 px it is docked beside the results (non-modal: the grid stays usable, Escape
 * closes it and focus returns to the opener); below that a modal sheet; on phones a drawer. One body for all three.
 */
export function AssetDetail(props: AssetDetailProps & { docked?: boolean }) {
  const { asset, open, onOpenChange, docked = false } = props;
  const isMobile = useIsMobile();
  const intel = useAssetIntelligence(open ? asset : null, Boolean(props.intelligence));
  const title = asset ? assetTitle(asset) : '';
  const description = props.uses.length === 0 ? 'Not used in a post yet' : `Used in ${props.uses.length} ${props.uses.length === 1 ? 'post' : 'posts'}`;
  const panelRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // Closing returns focus to the card that opened the panel, found again even if the list re-rendered meanwhile.
  const finalFocus = () => {
    const selector = asset ? openerSelector(asset.id) : null;
    return (selector ? document.querySelector<HTMLElement>(selector) : null) ?? true;
  };
  const dockedOpen = docked && !isMobile && open && asset !== null;
  const openedKey = dockedOpen && asset ? asset.id : null;
  // Docked: opening moves focus to the panel's heading (it is not a dialog, so nothing is trapped).
  useEffect(() => {
    if (openedKey) headingRef.current?.focus({ preventScroll: true });
  }, [openedKey]);
  const closeDocked = () => {
    const opener = finalFocus();
    onOpenChange(false);
    window.requestAnimationFrame(() => {
      if (opener instanceof HTMLElement) opener.focus();
    });
  };
  const actions = asset ? <DetailActions asset={asset} assetRef={intel.card.data?.assetRef ?? assetRefFor(asset.id)} canEdit={props.canEdit} canApprove={props.canApprove} onUseInDraft={props.onUseInDraft} /> : null;
  const body = (withActions: boolean) =>
    asset ? (
      <DetailBody
        asset={asset}
        uses={props.uses}
        publishing={props.publishing}
        currentUserId={props.currentUserId}
        platforms={props.platforms}
        canEdit={props.canEdit}
        isOwner={Boolean(props.isOwner)}
        deleting={props.deleting}
        onDelete={props.onDelete}
        intel={intel}
        focusLocator={props.focusLocator}
        onAnnounce={props.onAnnounce}
        intelligence={props.intelligence}
        onOpenAsset={props.onOpenAsset}
        voiceEnabled={props.voiceEnabled ?? true}
        voiceNote={props.voiceNote}
        actions={withActions ? actions : undefined}
      />
    ) : null;

  if (isMobile) {
    return (
      <Drawer open={open && asset !== null} onOpenChange={onOpenChange}>
        <DrawerContent className={DRAWER_CLASS} finalFocus={finalFocus}>
          {asset && (
            <>
              <DrawerHeader className='flex-row items-start gap-3 text-left'>
                <div className='flex min-w-0 flex-1 flex-col gap-0.5 text-left'>
                  <DrawerTitle className='line-clamp-2'>{title}</DrawerTitle>
                  <DrawerDescription>{description}</DrawerDescription>
                </div>
                <DrawerClose render={<IconControl label='Close asset details' tone='secondary' tooltip={false} />}>
                  <Icons.close aria-hidden />
                </DrawerClose>
              </DrawerHeader>
              <div className='min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4'>{body(false)}</div>
              <DrawerFooter className='pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]'>{actions}</DrawerFooter>
            </>
          )}
        </DrawerContent>
      </Drawer>
    );
  }

  if (docked) {
    if (!dockedOpen || !asset) return null;
    return (
      <aside
        ref={panelRef}
        aria-labelledby='library-inspector-title'
        data-library-inspector=''
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !event.defaultPrevented) {
            event.preventDefault();
            closeDocked();
          }
        }}
        className='bg-card ring-foreground/[0.08] sticky top-4 flex max-h-[calc(100dvh-2rem)] min-w-0 flex-col overflow-hidden rounded-[var(--rafii-radius-card)] ring-1'
      >
        <header className='flex items-start gap-2 border-b border-foreground/[0.06] px-4 py-3'>
          <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
            <h2 id='library-inspector-title' ref={headingRef} tabIndex={-1} className='line-clamp-2 text-[15px] font-medium outline-none'>
              {title}
            </h2>
            <p className='text-muted-foreground text-xs'>{description}</p>
          </div>
          <IconControl label='Close asset details' size='sm' onClick={closeDocked}>
            <Icons.close aria-hidden />
          </IconControl>
        </header>
        <div className='min-h-0 flex-1 overflow-y-auto overscroll-contain p-4'>{body(true)}</div>
      </aside>
    );
  }

  return (
    <Sheet open={open && asset !== null} onOpenChange={onOpenChange}>
      <SheetContent side='right' showCloseButton={false} className={SHEET_CLASS} finalFocus={finalFocus}>
        {asset && (
          <>
            <SheetClose render={<IconControl label='Close asset details' tone='secondary' tooltip={false} className='absolute top-3 right-3 z-20' />}>
              <Icons.close aria-hidden />
            </SheetClose>
            <SheetHeader className='pr-16'>
              <SheetTitle className='line-clamp-2'>{title}</SheetTitle>
              <SheetDescription>{description}</SheetDescription>
            </SheetHeader>
            <div className='min-h-0 flex-1 overflow-y-auto px-4 pb-4'>{body(true)}</div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
