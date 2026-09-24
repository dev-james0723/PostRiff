'use client';

import { useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { ExpandedPreviewDialog } from '@/components/application/post-preview/expanded-preview-dialog';
import { previewFromDraft } from '@/components/application/post-preview/draft-preview';
import { PreviewDeck, type DeckItem } from '@/components/application/post-preview/preview-deck';
import { PreviewDock, type DockItem } from '@/components/application/post-preview/preview-dock';
import type { PreviewPost } from '@/components/application/post-preview/types';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { channelByPlatform } from '@/config/channels';
import type { Destination } from '@/lib/api/types';
import { languageLabel } from '@/lib/locales';
import { cn } from '@/lib/utils';
import type { GeneratedItem, useHomeGeneration } from './use-home-generation';

/** Sample copy for the idle deck; always labelled as a sample, never presented as a draft. */
const SAMPLE_TEXT = 'One thought, shaped for every place you post. Start writing above and this preview follows your words.';

type Generation = ReturnType<typeof useHomeGeneration>;

export interface PreviewTarget extends Destination {
  /** The connected account's name when the destination is an account. */
  account?: string;
}

function targetKey(target: { platform: string; channelId?: string; language: string }) {
  return `${target.platform}|${target.channelId ?? ''}|${target.language}`;
}

/** Dock names: the app, or the account when two accounts share an app (DNA §17.3). */
function dockName(target: PreviewTarget, all: PreviewTarget[]) {
  const shared = all.filter((t) => t.platform === target.platform && t.channelId !== target.channelId).length > 0;
  return shared && target.account ? target.account : target.platform;
}

function toPost(target: PreviewTarget, text: string, publishAt: Date, timeZone: string, fallbackAccount: string): PreviewPost {
  return previewFromDraft({ platform: target.platform, text, account: target.account ?? fallbackAccount, channelId: target.channelId, publishAt, timeZone });
}

function Caption({ target, sample }: { target: PreviewTarget; sample?: boolean }) {
  const channel = channelByPlatform(target.platform);
  return (
    <span className='flex min-w-0 flex-col'>
      <span className='text-foreground truncate text-sm font-medium'>
        {channel?.name ?? target.platform}
        {target.account ? ` · ${target.account}` : ''}
      </span>
      <span className='text-muted-foreground truncate text-xs'>
        {languageLabel(target.language)} · iPhone preview{sample ? ' · sample text' : ''}
      </span>
    </span>
  );
}

/**
 * The idle preview column (DNA §21.1, prototype "03 / The idea splits"): the selected destinations
 * as a phone deck showing the idea as it is being written. Switching apps never changes destinations.
 */
export function IdlePreview({ targets, idea, timeZone, speaker }: { targets: PreviewTarget[]; idea: string; timeZone: string; speaker: string }) {
  const [openedAt] = useState(() => new Date());
  const [active, setActive] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const text = idea.trim() || SAMPLE_TEXT;
  const items = useMemo<DeckItem[]>(
    () => targets.map((target) => ({ key: targetKey(target), post: toPost(target, text, openedAt, timeZone, speaker), caption: <Caption target={target} sample={!idea.trim()} /> })),
    [targets, text, openedAt, timeZone, speaker, idea]
  );
  const dock = useMemo<DockItem[]>(() => targets.map((target) => ({ key: targetKey(target), channel: channelByPlatform(target.platform)?.slug ?? target.platform.toLowerCase(), name: dockName(target, targets) })), [targets]);
  const activeKey = items.some((item) => item.key === active) ? (active as string) : (items[0]?.key ?? '');
  if (items.length === 0) {
    return <StateMessage kind='empty' title='Choose where this idea should go.' description='Pick accounts in the channel picker and the preview follows.' />;
  }
  return (
    <div className='flex flex-col items-center gap-4 text-center'>
      <div>
        <span className='rafii-eyebrow'>03 / The idea splits</span>
        <h2 className='text-foreground mt-3 text-[26px] leading-[1.1] font-normal tracking-[-0.02em] md:text-[28px]'>
          One thought.
          <br />
          <em className='rafii-serif'>Everywhere, still you.</em>
        </h2>
      </div>
      <PreviewDock items={dock} activeKey={activeKey} onChange={setActive} label='Explore the destination previews' className='w-full max-w-[440px]' />
      <PreviewDeck items={items} activeKey={activeKey} onChange={setActive} scale={0.59} tools={false} label='Destination previews' className='w-full' />
      <div className='flex w-full max-w-[320px] items-center justify-between gap-3 text-left'>
        <p className='text-muted-foreground text-xs leading-relaxed'>Swipe or tap a destination. An illustrative layout; no account is contacted.</p>
        <Button variant='glass' size='icon-control' className='shrink-0' aria-label='Expand iPhone preview' onClick={() => setExpanded(true)}>
          <Icons.arrowUpRight />
        </Button>
      </div>
      <ExpandedPreviewDialog open={expanded} onOpenChange={setExpanded} items={items} activeKey={activeKey} onChange={setActive} dock={dock} tools={false} eyebrow='In your audience’s hands' />
    </div>
  );
}

const STATUS_COPY: Record<GeneratedItem['status'], string> = {
  pending: 'waiting',
  writing: 'writing',
  ready: 'ready',
  failed: 'failed',
  cancelled: 'cancelled'
};

/**
 * The results column: one editable, previewable draft per destination from the real run
 * (prompt §4 "State and real generation"). Edits are local until "Save as drafts", which applies
 * the run through the existing service and records each edited caption as an author edit.
 */
export function IdeaSplits({ generation, timeZone, speaker, onDraftAgain }: { generation: Generation; timeZone: string; speaker: string; onDraftAgain: () => void }) {
  const [openedAt] = useState(() => new Date());
  const [active, setActive] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const { items, running, completed, applied, saving, saved, failure, error, busy } = generation;
  const ready = items.filter((item) => item.status === 'ready');
  const targets: PreviewTarget[] = items.map((item) => item.destination);
  const deck = useMemo<DeckItem[]>(
    () => ready.map((item) => ({ key: item.key, post: toPost(item.destination, item.edited ?? item.text, openedAt, timeZone, speaker), caption: <Caption target={item.destination} /> })),
    [ready, openedAt, timeZone, speaker]
  );
  const dock = useMemo<DockItem[]>(
    () => items.map((item) => ({ key: item.key, channel: channelByPlatform(item.destination.platform)?.slug ?? item.destination.platform.toLowerCase(), name: dockName(item.destination, targets), status: item.status === 'ready' ? undefined : item.status === 'failed' || item.status === 'cancelled' ? 'error' : 'pending', label: `${item.destination.platform}${item.destination.account ? ` · ${item.destination.account}` : ''}, ${STATUS_COPY[item.status]}` })),
    [items, targets]
  );
  const activeKey = deck.some((d) => d.key === active) ? (active as string) : (deck[0]?.key ?? '');
  const current = items.find((item) => item.key === activeKey) ?? null;
  const readyCount = ready.length;
  const notStarted = !generation.run && !busy && Boolean(error);
  const status: ReactNode = busy
    ? 'Sending your idea…'
    : notStarted
      ? 'Nothing was drafted.'
      : running
      ? `Writing your drafts · ${readyCount} of ${items.length} ready`
      : failure
        ? failure
        : applied
          ? `${readyCount} of ${items.length} saved to your drafts`
          : completed
            ? `${readyCount} of ${items.length} ready · yours to edit`
            : '';

  return (
    <section aria-label='Generated drafts' className='flex flex-col gap-4'>
      <div className='flex items-start justify-between gap-3'>
        <div>
          <span className='rafii-eyebrow'>The idea splits</span>
          <h2 className='text-foreground mt-2 text-[26px] leading-[1.12] font-normal tracking-[-0.02em] md:text-[28px]'>
            Your idea, <em className='rafii-serif'>unfolded.</em>
          </h2>
        </div>
        {running && (
          <Button variant='quiet' size='sm' onClick={() => void generation.cancel()}>
            Cancel
          </Button>
        )}
      </div>
      <p role='status' aria-live='polite' className='text-muted-foreground text-sm'>
        {status}
      </p>
      {notStarted ? (
        <StateMessage kind='error' title='The drafts could not be started.' description={error} action={<Button variant='glass' size='control' onClick={onDraftAgain}>Try again</Button>} />
      ) : (
        error && (
          <p role='alert' className='text-foreground text-sm'>
            {error}
          </p>
        )
      )}
      {items.length > 0 && <PreviewDock items={dock} activeKey={activeKey || null} onChange={setActive} label='Choose a draft' className='w-full max-w-[440px]' />}
      {deck.length > 0 ? (
        <>
          <PreviewDeck items={deck} activeKey={activeKey} onChange={setActive} scale={0.57} tools={false} label='Draft previews' className='w-full' />
          <div className='flex items-center justify-between gap-3'>
            <p className='text-muted-foreground text-xs'>App-layout mockup, not a screenshot or a published post.</p>
            <Button variant='glass' size='sm' onClick={() => setExpanded(true)}>
              Expand
              <Icons.arrowUpRight />
            </Button>
          </div>
          {current && current.status === 'ready' && (
            <div className='flex flex-col gap-2'>
              <div className='text-muted-foreground flex items-center justify-between text-xs'>
                <label htmlFor='rafii-draft-editor' className='text-foreground font-medium'>
                  Edit your caption
                </label>
                <span className='rafii-eyebrow'>{applied ? 'Saved' : current.edited !== null ? 'Edited · not saved' : 'Updates live'}</span>
              </div>
              <textarea
                id='rafii-draft-editor'
                aria-label='Edit draft preview'
                value={current.edited ?? current.text}
                onChange={(event) => generation.setEdit(current.key, event.target.value)}
                disabled={applied || saving}
                rows={7}
                className='rafii-field rafii-focus min-h-[150px] w-full resize-y rounded-[var(--rafii-radius-card)] px-4 py-3.5 text-base leading-[1.75] outline-none md:text-sm'
              />
              {current.variant?.warnings && current.variant.warnings.length > 0 && (
                <ul className='text-muted-foreground flex flex-col gap-1 text-xs'>
                  {current.variant.warnings.map((warning, index) => (
                    <li key={index}>{warning}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      ) : running || busy ? (
        <StateMessage kind='loading' title='Shaping your drafts' description='One draft per destination. This is a real run; cancel any time.' />
      ) : failure ? (
        <StateMessage kind='error' title='The run did not complete.' description={failure} action={<Button variant='glass' size='control' onClick={onDraftAgain}>Draft again</Button>} />
      ) : null}
      <div className={cn('flex flex-wrap items-center gap-2', deck.length === 0 && 'hidden')}>
        {!applied && completed && (
          <Button variant='action' size='control' disabled={saving} onClick={() => void generation.save()}>
            {saving ? <Icons.spinner className='animate-spin motion-reduce:animate-none' /> : <Icons.check />}
            Save as drafts
          </Button>
        )}
        {applied && (
          <>
            <Link href='/app/queue?view=drafts' className='rafii-focus text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm underline underline-offset-2'>
              Open drafts
            </Link>
            <Link href='/app/queue' className='rafii-focus text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm underline underline-offset-2'>
              Review in Queue
            </Link>
          </>
        )}
        {generation.conversationId && (
          <Link href={`/app/agent/${encodeURIComponent(generation.conversationId)}`} className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm'>
            Open conversation
            <Icons.arrowRight className='size-3.5' />
          </Link>
        )}
        {saved && <span className='text-muted-foreground text-xs'>{saved.edited > 0 ? `${saved.edited} edited caption${saved.edited === 1 ? '' : 's'} recorded.` : 'Captions saved as generated.'}</span>}
        {saved && saved.pendingReview > 0 && (
          <p className='text-muted-foreground basis-full text-xs leading-relaxed'>
            {saved.pendingReview === 1 ? 'One account already had an unscheduled draft in this language, so this version waits on it as a proposed update.' : `${saved.pendingReview} accounts already had unscheduled drafts in these languages, so these versions wait on them as proposed updates.`}{' '}
            <Link href='/app/queue?view=drafts' className='text-foreground underline underline-offset-2'>
              Review in Drafts
            </Link>
          </p>
        )}
      </div>
      <ExpandedPreviewDialog open={expanded} onOpenChange={setExpanded} items={deck} activeKey={activeKey} onChange={setActive} dock={dock} tools={false} eyebrow='In your audience’s hands' description='Your edited draft inside its destination app. An illustrative layout, not a published post.' />
    </section>
  );
}
