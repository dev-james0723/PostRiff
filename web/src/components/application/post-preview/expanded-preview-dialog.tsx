'use client';

import { useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogHeader } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { accountNames } from './parts';
import { SCREEN_HEIGHT, SCREEN_WIDTH } from './phone-frame';
import { PreviewDeck, type DeckItem } from './preview-deck';
import { stepKey } from './preview-deck-core';
import { PreviewDock, type DockItem } from './preview-dock';

export interface ExpandedPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: DeckItem[];
  activeKey: string;
  /** Browsing here only changes which preview is in view, never the destinations. */
  onChange: (key: string) => void;
  /** Dock entries with statuses; derived from `items` when omitted. */
  dock?: DockItem[];
  eyebrow?: ReactNode;
  /** Under the title; defaults to a line naming the account and app. */
  description?: ReactNode;
  /** Largest phone scale; smaller viewports fit a smaller phone. Default 0.68. */
  scale?: number;
  /** The pager, play, guides and export row under the phone. Default true. */
  tools?: boolean;
}

/** Dock entries for deck items: the app's name, or the account when two accounts share an app. */
export function dockFromItems(items: DeckItem[]): DockItem[] {
  const perChannel = new Map<string, number>();
  for (const item of items) perChannel.set(item.post.channel, (perChannel.get(item.post.channel) ?? 0) + 1);
  return items.map((item) => ({
    key: item.key,
    channel: item.post.channel,
    name: (perChannel.get(item.post.channel) ?? 0) > 1 ? accountNames(item.post.account).display : item.post.channelName,
    label: `Preview ${item.post.channelName} on iPhone${(perChannel.get(item.post.channel) ?? 0) > 1 ? ` as ${accountNames(item.post.account).display}` : ''}`
  }));
}

const subscribeToResize = (callback: () => void) => {
  window.addEventListener('resize', callback);
  return () => window.removeEventListener('resize', callback);
};
const readViewport = () => `${window.innerWidth}x${window.innerHeight}`;
const serverViewport = () => '';

/** Room the dialog's header, dock, controls and caption take above and below the phone. */
const VERTICAL_ROOM = 360;
const HORIZONTAL_ROOM = 80;
const MIN_SCALE = 0.42;

/** The largest phone that fits the viewport with the dialog's own chrome, capped at `max`. */
function useFittedScale(max: number) {
  const viewport = useSyncExternalStore(subscribeToResize, readViewport, serverViewport);
  if (!viewport) return max;
  const [width, height] = viewport.split('x').map(Number);
  const byWidth = (width - HORIZONTAL_ROOM) / (SCREEN_WIDTH + 18);
  const byHeight = (height - VERTICAL_ROOM) / (SCREEN_HEIGHT + 18);
  return Math.max(MIN_SCALE, Math.min(max, byWidth, byHeight));
}

/**
 * The expanded phone preview (prototype `#phone-dialog`): an elevated glass dialog with the channel dock,
 * the deck at a larger scale, previous/next buttons and the honesty caption. Focus stays inside and returns
 * to the trigger (Base UI's modal dialog); Escape closes it.
 */
export function ExpandedPreviewDialog({ open, onOpenChange, items, activeKey, onChange, dock, eyebrow = 'In your audience’s hands', description, scale = 0.68, tools = true }: ExpandedPreviewDialogProps) {
  const keys = useMemo(() => items.map((item) => item.key), [items]);
  const dockItems = useMemo(() => dock ?? dockFromItems(items), [dock, items]);
  const fitted = useFittedScale(scale);
  const active = items.find((item) => item.key === activeKey) ?? items[0];
  const position = Math.max(0, keys.indexOf(activeKey));
  const channelName = active?.post.channelName ?? 'Post';
  // The title already names the app; a caller can still pass its own line.
  const intro = description;

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='lg'>
        <RafiiDialogHeader eyebrow={eyebrow} title={channelName} accent='on iPhone.' intro={intro} closeLabel='Close iPhone preview' />
        <RafiiDialogBody className='flex flex-col items-center gap-4 pt-1'>
          <PreviewDock items={dockItems} activeKey={activeKey} onChange={onChange} label='Switch the app in the expanded preview' className='max-w-[27rem]' />
          {active ? (
            <PreviewDeck items={items} activeKey={activeKey} onChange={onChange} scale={fitted} tools={tools} label='Expanded post preview' className='w-full' />
          ) : (
            <p className='text-muted-foreground py-8 text-sm'>Nothing to preview yet.</p>
          )}
          <div className='flex items-center gap-3'>
            <Button variant='glass' size='icon-control' aria-label='Previous app' disabled={items.length < 2} onClick={() => onChange(stepKey(keys, activeKey, -1))}>
              <Icons.chevronLeft className='size-5' />
            </Button>
            <span aria-live='polite' className='text-muted-foreground min-w-12 text-center text-sm tabular-nums'>
              <span className='sr-only'>Preview </span>
              {items.length ? `${position + 1} / ${items.length}` : '0 / 0'}
            </span>
            <Button variant='glass' size='icon-control' aria-label='Next app' disabled={items.length < 2} onClick={() => onChange(stepKey(keys, activeKey, 1))}>
              <Icons.chevronRight className='size-5' />
            </Button>
          </div>
          <p className='text-muted-foreground max-w-[34ch] text-center text-xs leading-relaxed text-balance'>
            Illustrative layout, not a published post.
            <span className='hidden pointer-coarse:inline'> Swipe the phone to change apps.</span>
          </p>
        </RafiiDialogBody>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
