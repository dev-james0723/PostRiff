'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { parseAsString, useQueryState } from 'nuqs';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { StateMessage, Surface, type StateKind } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useInfobar, type InfobarContent } from '@/components/ui/infobar';
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useMemory, useSnapshot, useUsage } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDate } from '@/lib/time';
import { CaptureCard, type CaptureCardHandle } from './capture-card';
import { SourceInspector } from './source-inspector';
import { SourceList } from './source-list';
import { ideaSources, useMedia, useUseApprovals } from './use-sources';
import { useSiteAgentPageContext } from '@/features/site-agent/use-page-context';

interface Reminder {
  id: string;
  /** The shared state grammar (DNA §20.1): a reminder nudges, it never blocks capture. */
  kind: StateKind;
  title: string;
  description: string;
  href?: string;
  action?: string;
}

/** A tertiary text action (DNA §9.2): text plus an arrow, with a comfortable hit area. */
const TEXT_LINK = 'rafii-focus text-foreground decoration-muted-foreground/60 hover:decoration-foreground inline-flex min-h-9 w-fit items-center gap-1 rounded-md text-sm font-medium underline underline-offset-4';

/**
 * Ideas is the workspace's raw material: capture a thought, text, a link or a file; decide per
 * source which facts may be used, how, and whether a cloud model may read it; then draft from any
 * of them in an agent conversation. Every count and status reads the snapshot or the API.
 */
export function IdeasView() {
  const snapshot = useSnapshot();
  const memory = useMemory();
  const usage = useUsage();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const [sourceId, setSourceId] = useQueryState('source', parseAsString);
  useSiteAgentPageContext(sourceId ? { selectedEntity: { type: 'source', id: sourceId } } : null);
  const isDesktop = useMedia('(min-width: 1024px)');
  const isPhone = useMedia('(max-width: 767px)');
  const capture = useRef<CaptureCardHandle>(null);
  const { setContent: setInfobarContent } = useInfobar();

  const state = snapshot.data?.state;
  const sources = useMemo(() => ideaSources(state), [state]);
  const useApprovals = useUseApprovals(sources);
  const selected = sources.find((s) => s.id === sourceId) ?? null;

  // The sheet keeps showing the last source while it slides closed.
  const [sheetId, setSheetId] = useState(sourceId);
  if (sourceId && sourceId !== sheetId) setSheetId(sourceId);
  const sheetSource = sources.find((s) => s.id === sheetId) ?? null;

  // A first visit with nothing captured starts in the capture box.
  const focused = useRef(false);
  useEffect(() => {
    if (focused.current || !snapshot.isSuccess || !canEdit) return;
    focused.current = true;
    if (sources.length === 0) capture.current?.focus();
  }, [snapshot.isSuccess, sources.length, canEdit]);

  const select = (id: string) => void setSourceId(id);

  const active = sources.filter((s) => s.active);
  const ideaCount = active.filter((s) => s.kind === 'idea').length;
  const otherCount = active.length - ideaCount;

  const research = memory.data?.research;
  const entitlement = usage.data?.entitlement;
  const batches = usage.isLoading ? '…' : usage.isError || !entitlement ? 'Unavailable' : String(entitlement.writingBatchesRemaining);
  const resets = entitlement?.resetsAt ? formatDate(entitlement.resetsAt) : null;

  const reminders: Reminder[] = [];
  if (snapshot.isSuccess && !state?.speaker?.activeRevision) {
    reminders.push({ id: 'voice', kind: 'partial', title: 'Set up your voice first', description: 'Sources and previews work now, but drafts can only be scheduled once a voice profile is active.', href: '/app/workspace/brand', action: 'Set up your voice' });
  }
  if (memory.isSuccess && research) {
    if (research.enabled === false) {
      reminders.push({ id: 'research', kind: 'unsupported', title: 'Web research is switched off on this deployment', description: 'Drafts use only the sources you add here, and links stay unverified references.' });
    } else if (research.hosted && !research.web) {
      reminders.push({ id: 'research', kind: 'unsupported', title: 'Web research is off for this workspace', description: 'Drafts use only the sources you add here, and links stay unverified references. An owner can turn research on under Memory.', href: '/app/workspace/memory', action: 'Open Memory' });
    }
  }
  if (usage.isSuccess && entitlement && entitlement.writingBatchesRemaining === 0) {
    reminders.push({ id: 'allowance', kind: 'partial', title: 'No writing batches left this period', description: `You can still capture and review sources. A paid cloud model can draft again when the allowance resets${resets ? ` on ${resets}` : ''}.`, href: '/app/account/billing', action: 'Usage & plan' });
  }

  const infoContent: InfobarContent = {
    title: 'How sources work',
    sections: [
      {
        title: 'Four ways to use a source',
        description:
          'Quote it: your own words, which drafts may quote. Rewrite, then approve use: never quoted, and a draft from it is scheduled only after you approve public use of its exact facts. Internal only: left out of public drafts. Do not use: kept here, left out of every draft.'
      },
      {
        title: 'Facts',
        description: 'Pasted text and files are split into paragraphs. Only the ones you approve can reach a draft; anything else stays out and is listed as unknown rather than guessed.'
      },
      {
        title: 'Leaving this server',
        description:
          'A paid cloud model reads a source’s approved facts only when its cloud switch is on. Other writing routes, such as an agent signed in on the machine that runs PostRiff, read them without that switch. The text you draft from (an idea, a link, your message) goes to whichever model you pick.'
      },
      {
        title: 'Web research',
        description: memory.isLoading
          ? '…'
          : !research
            ? 'Unavailable: this server did not report whether web research is on.'
            : research.enabled === false
              ? 'Switched off on this deployment. Drafts use only what you add here.'
              : !research.hosted
                ? 'Always on when drafting on your own machine. A draft that needs facts you have not supplied looks them up, and each page read becomes a source here with its address.'
                : research.web
                  ? 'On for this workspace. A draft that needs facts you have not supplied looks them up, and each page read becomes a source here with its address.'
                  : 'Off for this workspace. An owner can turn it on under Memory.'
      },
      {
        title: 'Cost',
        description:
          batches === '…' || batches === 'Unavailable'
            ? `Writing batches left: ${batches}. Saving and reviewing sources never uses one.`
            : `${batches} writing batch${batches === '1' ? '' : 'es'} left${resets ? `, resets ${resets}` : ''}. Only a draft written by a paid cloud model uses one; saving and reviewing sources never does.`
      }
    ]
  };

  // The info button hands the sidebar its content once, on mount; the web research and allowance
  // lines arrive later, so the open sidebar is refreshed whenever their real values change.
  const infoKey = JSON.stringify(infoContent);
  useEffect(() => {
    setInfobarContent(JSON.parse(infoKey) as InfobarContent);
  }, [infoKey, setInfobarContent]);

  // Quiet, factual counts beside the title (DNA §22.4): real numbers, or the honest loading/unavailable shape.
  const headerCount = (
    <span role='status' className='text-muted-foreground inline-flex min-h-11 items-center gap-2 text-sm tabular-nums'>
      <Icons.paperclip aria-hidden className='hidden size-4 sm:block' />
      {/* Loading keeps the loaded shape, so the heading beside it does not reflow when the counts arrive. */}
      {snapshot.isLoading ? (
        '… ideas · … sources'
      ) : snapshot.isError ? (
        'Unavailable'
      ) : (
        <>
          <DigitSwap value={ideaCount} /> {ideaCount === 1 ? 'idea' : 'ideas'} · <DigitSwap value={otherCount} /> {otherCount === 1 ? 'source' : 'sources'}
        </>
      )}
    </span>
  );

  return (
    <PageContainer
      pageTitle='Ideas'
      pageDescription='Capture a thought, paste text or add a link. Approve the facts, say how each source may be used, and draft from any of them in your voice.'
      infoContent={infoContent}
      pageHeaderAction={headerCount}
    >
      {snapshot.isError ? (
        <StateMessage
          kind='error'
          title='Your sources could not be loaded.'
          description={snapshot.error instanceof Error ? snapshot.error.message : 'The workspace did not answer.'}
          action={
            <Button variant='glass' size='control' onClick={() => void snapshot.refetch()} disabled={snapshot.isFetching}>
              {snapshot.isFetching ? 'Retrying…' : 'Retry'}
            </Button>
          }
        />
      ) : (
        <div className='grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_24rem]'>
          <div className='flex min-w-0 flex-col gap-4'>
            {reminders.length > 0 && (
              <Surface material='quiet' radius='card' padding='sm' className='flex flex-col gap-1'>
                {reminders.map((item) => (
                  <StateMessage
                    key={item.id}
                    kind={item.kind}
                    layout='inline'
                    title={item.title}
                    description={item.description}
                    action={
                      item.href ? (
                        <Link href={item.href} className={TEXT_LINK}>
                          {item.action}
                          <Icons.arrowRight aria-hidden className='size-3.5' />
                        </Link>
                      ) : undefined
                    }
                  />
                ))}
              </Surface>
            )}
            {canEdit ? <CaptureCard ref={capture} onSelect={select} /> : <StateMessage kind='permission' layout='inline' title='You need the edit permission to add sources.' description='You can still open a source and read its facts and permissions.' />}
            <SourceList selectedId={sourceId} onSelect={select} useApprovals={useApprovals} />
          </div>

          {/* The inspector is the page's contextual work surface (DNA §5.2), so it is the one glass panel beside the quiet list. */}
          <aside aria-label='Source inspector' className='hidden lg:sticky lg:top-18 lg:block lg:self-start'>
            <Surface material='glass' radius='card' padding='none' className='max-h-[calc(100svh-6rem)] overflow-y-auto p-5'>
              {/* Rendered only at lg and up, so the tour's anchors resolve to the visible inspector. */}
              {snapshot.isLoading ? (
                <StateMessage kind='loading' title='Loading sources' />
              ) : selected && isDesktop ? (
                <SourceInspector key={selected.id} source={selected} useApproved={useApprovals[selected.id]} />
              ) : (
                <StateMessage
                  kind='empty'
                  title={sources.length === 0 ? 'Once you save a source, pick it to review its facts and permissions.' : 'Pick a source to review its facts and permissions.'}
                />
              )}
            </Surface>
          </aside>
        </div>
      )}

      {/* Below lg the inspector opens over the page: from the right on tablets, from the bottom on phones. Elevated glass (DNA §12.2). */}
      <Sheet open={isDesktop === false && selected !== null} onOpenChange={(open) => !open && void setSourceId(null)}>
        <SheetContent
          side={isPhone ? 'bottom' : 'right'}
          showCloseButton={false}
          className='rafii-elevated gap-0 border-0 bg-transparent data-[side=bottom]:max-h-[85svh] data-[side=bottom]:rounded-t-[var(--rafii-radius-mobile-dialog)] data-[side=bottom]:border-t-0 data-[side=right]:w-[24rem] data-[side=right]:max-w-[calc(100vw-2rem)] data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0'
        >
          <SheetClose render={<Button variant='glass' size='icon-control' aria-label='Close' className='absolute top-3 right-3 z-10' />}>
            <Icons.close className='size-4' />
          </SheetClose>
          <SheetHeader className='pr-16'>
            <SheetTitle>Source</SheetTitle>
            <SheetDescription>Facts, how it may be used, and where it came from.</SheetDescription>
          </SheetHeader>
          <div className='min-h-0 flex-1 overflow-y-auto px-4 pb-[max(1rem,env(safe-area-inset-bottom))]'>
            {sheetSource && <SourceInspector key={sheetSource.id} source={sheetSource} useApproved={useApprovals[sheetSource.id]} />}
          </div>
        </SheetContent>
      </Sheet>
    </PageContainer>
  );
}
