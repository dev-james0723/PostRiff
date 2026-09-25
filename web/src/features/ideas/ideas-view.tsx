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
  description?: string;
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

  // Reminders only for what someone can act on. Research that is unavailable everywhere is not offered, so it is not mentioned.
  const reminders: Reminder[] = [];
  if (snapshot.isSuccess && !state?.speaker?.activeRevision) {
    reminders.push({ id: 'voice', kind: 'partial', title: 'Set up your voice to schedule drafts', href: '/app/workspace/brand', action: 'Set up your voice' });
  }
  if (memory.isSuccess && research && research.enabled !== false && research.hosted && !research.web) {
    reminders.push({ id: 'research', kind: 'unsupported', title: 'Web research is off', description: 'Drafts use only the sources you add.', href: '/app/workspace/memory', action: 'Open Memory' });
  }
  if (usage.isSuccess && entitlement && entitlement.writingBatchesRemaining === 0) {
    reminders.push({ id: 'allowance', kind: 'partial', title: 'No writing batches left', description: resets ? `Resets ${resets}.` : undefined, href: '/app/account/billing', action: 'Usage & plan' });
  }

  const infoContent: InfobarContent = {
    title: 'How sources work',
    sections: [
      {
        title: 'Four ways to use a source',
        description:
          'Quote it: your own words, quoted as written. Rewrite, then approve use: never quoted; you approve public use of its facts before scheduling. Internal only: left out of public drafts. Do not use: left out of every draft.'
      },
      {
        title: 'Facts',
        description: 'Text and files split into paragraphs. Only approved ones reach a draft; the rest is listed as unknown, never guessed.'
      },
      {
        title: 'Privacy',
        description:
          'A cloud model reads a source’s approved facts only when its cloud switch is on. Other writing routes, like an agent on your own machine, read them without it. What you draft from goes to the model you pick.'
      },
      ...(research?.enabled === false
        ? []
        : [
            {
              title: 'Web research',
              description: memory.isLoading
                ? '…'
                : !research
                  ? 'Status unavailable.'
                  : !research.hosted || research.web
                    ? 'On. A draft that needs missing facts looks them up; each page read becomes a source here.'
                    : 'Off for this workspace. An owner can turn it on under Memory.'
            }
          ]),
      {
        title: 'Cost',
        description:
          batches === '…' || batches === 'Unavailable'
            ? `Writing batches left: ${batches}. Saving sources is free.`
            : `${batches} writing batch${batches === '1' ? '' : 'es'} left${resets ? `, resets ${resets}` : ''}. Only cloud drafts use one; saving sources is free.`
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
      infoContent={infoContent}
      pageHeaderAction={headerCount}
    >
      {snapshot.isError ? (
        <StateMessage
          kind='error'
          title='Couldn’t load your sources'
          description={snapshot.error instanceof Error ? snapshot.error.message : undefined}
          action={
            <Button variant='glass' size='control' onClick={() => void snapshot.refetch()} disabled={snapshot.isFetching}>
              {snapshot.isFetching ? 'Trying again…' : 'Try again'}
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
            {canEdit ? <CaptureCard ref={capture} onSelect={select} /> : <StateMessage kind='permission' layout='inline' title='Only editors can add sources.' />}
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
                  title={sources.length === 0 ? 'Saved sources open here' : 'Pick a source to review'}
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
            <SheetDescription className='sr-only'>Facts, how it may be used, and where it came from.</SheetDescription>
          </SheetHeader>
          <div className='min-h-0 flex-1 overflow-y-auto px-4 pb-[max(1rem,env(safe-area-inset-bottom))]'>
            {sheetSource && <SourceInspector key={sheetSource.id} source={sheetSource} useApproved={useApprovals[sheetSource.id]} />}
          </div>
        </SheetContent>
      </Sheet>
    </PageContainer>
  );
}
