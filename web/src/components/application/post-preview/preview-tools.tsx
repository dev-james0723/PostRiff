'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Toggle } from '@/components/ui/toggle';
import { cn } from '@/lib/utils';
import { GUIDE_COLOR, useGuideNotes, type GuideStore } from './guides';
import { limitNotes } from './limits';
import type { Appearance } from './appearance';
import { canCopyImages, previewFileName, previewImage } from './export-image';
import type { Playback } from './playback';
import type { PreviewPost } from './types';

interface PreviewToolsProps {
  store: GuideStore;
  post: PreviewPost;
  playback: Playback;
  show: boolean;
  onShowChange: (show: boolean) => void;
  /** The phone's appearance when the template can draw both; null hides the switch. */
  appearance: Appearance | null;
  onAppearanceChange: (appearance: Appearance) => void;
  /** The drawn phone, for Copy image and Download PNG. */
  phone: () => HTMLElement | null;
  /** The phone's width, which the tools do not outgrow. */
  width: number;
}

/**
 * Under the phone: the pager and play control (the keyboard's way to move through the post, since the phone is a
 * picture to assistive tech), the guides switch, and the notes on what readers will not see.
 */
export function PreviewTools({
  store,
  post,
  playback,
  show,
  onShowChange,
  appearance,
  onAppearanceChange,
  phone,
  width
}: PreviewToolsProps) {
  const [busy, setBusy] = useState(false);
  const reported = useGuideNotes(store);
  const marks = reported.some((note) => note.marks);
  const notes = [...limitNotes(post), ...reported]
    .filter((note) => note.tone !== 'legend' || show)
    .toSorted((a, b) => a.order - b.order);
  const { index, setIndex, slides, playing, setPlaying, videos } = playback;
  const paged = slides > 1;
  const current = Math.min(index, Math.max(slides - 1, 0));

  const draw = () => {
    const element = phone();
    if (!element) return Promise.reject(new Error('The preview is still loading.'));
    return previewImage(element, {
      channelName: post.channelName,
      dark: appearance === 'dark'
    });
  };
  const copy = async () => {
    setBusy(true);
    try {
      // Safari only accepts a clipboard item made during the click, holding the image still being drawn.
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': draw() })]);
      toast.success('Preview image copied.');
    } catch {
      toast.error('The preview image could not be copied. Try Download instead.');
    } finally {
      setBusy(false);
    }
  };
  const download = async () => {
    setBusy(true);
    try {
      const url = URL.createObjectURL(await draw());
      const link = document.createElement('a');
      link.href = url;
      link.download = previewFileName(post.channel);
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      toast.error('The preview image could not be made.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className='flex max-w-full flex-col items-center gap-2' style={{ width }}>
      <div className='flex flex-wrap items-center justify-center gap-1'>
        {paged && (
          <span className='flex items-center'>
            <Button
              variant='ghost'
              size='icon-xs'
              aria-label='Previous slide'
              disabled={current === 0}
              onClick={() => setIndex(current - 1)}
            >
              <Icons.chevronLeft />
            </Button>
            <span
              aria-live='polite'
              className='text-muted-foreground min-w-8 text-center font-mono text-[11px] tabular-nums'
            >
              <span className='sr-only'>Slide </span>
              {current + 1}/{slides}
            </span>
            <Button
              variant='ghost'
              size='icon-xs'
              aria-label='Next slide'
              disabled={current >= slides - 1}
              onClick={() => setIndex(current + 1)}
            >
              <Icons.chevronRight />
            </Button>
          </span>
        )}
        {videos > 0 && (
          <Button
            variant='outline'
            size='xs'
            className='text-[11px]'
            onClick={() => setPlaying(!playing)}
          >
            {playing ? <Icons.pause /> : <Icons.play />}
            {playing ? 'Pause' : 'Play'}
          </Button>
        )}
        {appearance && (
          <Button
            variant='ghost'
            size='icon-xs'
            aria-label={
              appearance === 'dark' ? 'Show the app in light mode' : 'Show the app in dark mode'
            }
            onClick={() => onAppearanceChange(appearance === 'dark' ? 'light' : 'dark')}
          >
            {appearance === 'dark' ? <Icons.sun /> : <Icons.moon />}
          </Button>
        )}
        {marks && (
          <Toggle
            variant='outline'
            size='sm'
            pressed={show}
            onPressedChange={onShowChange}
            className='h-6 gap-1 rounded-md px-2 text-[11px]'
          >
            <Icons.ruler className='size-3.5' />
            Guides
          </Toggle>
        )}
        {canCopyImages() && (
          <Button
            variant='ghost'
            size='icon-xs'
            aria-label='Copy preview image'
            title='Copy preview image'
            disabled={busy}
            onClick={copy}
          >
            <Icons.copy />
          </Button>
        )}
        <Button
          variant='ghost'
          size='icon-xs'
          aria-label='Download preview as PNG'
          title='Download preview as PNG'
          disabled={busy}
          onClick={download}
        >
          <Icons.download />
        </Button>
      </div>
      {notes.length > 0 && (
        <ul
          aria-label='Notes on this preview'
          className='flex w-full flex-col gap-1 text-left text-[11px] leading-snug'
        >
          {notes.map((note) => (
            <li key={`${note.order}:${note.text}`} className='flex items-start gap-1.5'>
              <span
                aria-hidden
                className={cn(
                  'mt-[4.5px] size-1.5 shrink-0 rounded-full',
                  note.tone === 'problem' ? 'bg-destructive' : 'bg-muted-foreground/45'
                )}
                style={show && note.marks ? { background: GUIDE_COLOR } : undefined}
              />
              <span
                className={note.tone === 'problem' ? 'text-destructive' : 'text-muted-foreground'}
              >
                {note.text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
