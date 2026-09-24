'use client';

import { useId, useMemo, useState, useSyncExternalStore } from 'react';
import { Icons } from '@/components/icons';
import { SegmentedControl } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { channelBySlug } from '@/config/channels';
import { useTimeZone } from '@/lib/preferences';
import { useMotionPreference, type MotionSetting } from '@/lib/rafii/motion';
import { ExpandedPreviewDialog } from './expanded-preview-dialog';
import { SAMPLE_AVATAR, sampleMedia, sampleText } from './gallery';
import { PreviewDeck, type DeckItem } from './preview-deck';
import { PreviewDock, type DockItem, type DockStatus } from './preview-dock';
import type { PreviewPost } from './types';

/**
 * Development-only sheet for the preview deck: the gallery's sample posts across six apps on one stage, the
 * dock, a caption field to show that edits never replay the transition, statuses on the dock, the motion
 * setting, and the expanded dialog. Nothing here reads a workspace.
 */

const SLUGS = ['instagram', 'linkedin', 'threads', 'x', 'facebook', 'xiaohongshu'] as const;
const MEDIA = ['none', 'one', 'several'] as const;
type MediaChoice = (typeof MEDIA)[number];
const MOTION: { value: MotionSetting; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'full', label: 'Full' },
  { value: 'reduced', label: 'Reduced' }
];

const subscribeToNothing = () => () => {};

export function PreviewDeckSheet() {
  const mounted = useSyncExternalStore(subscribeToNothing, () => true, () => false);
  const timeZone = useTimeZone();
  const [openedAt] = useState(() => new Date());
  const [active, setActive] = useState<string>(SLUGS[0]);
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries(SLUGS.map((slug) => [slug, sampleText(channelBySlug(slug)?.region)]))
  );
  const [media, setMedia] = useState<MediaChoice>('one');
  const [withPicture, setWithPicture] = useState(false);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const { setting, setSetting } = useMotionPreference();
  const captionId = useId();

  const items = useMemo<DeckItem[]>(
    () =>
      SLUGS.flatMap((slug) => {
        const channel = channelBySlug(slug);
        if (!channel) return [];
        const post: PreviewPost = {
          channel: slug,
          channelName: channel.name,
          account: channel.region === 'global' || !channel.region ? '@yourstudio' : 'Your Studio',
          avatarUrl: withPicture ? SAMPLE_AVATAR : undefined,
          text: texts[slug] ?? '',
          media: sampleMedia(slug, media),
          publishAt: openedAt,
          timeZone
        };
        return [
          {
            key: slug,
            post,
            caption: (
              <div className='mx-auto flex max-w-[18rem] items-center justify-between gap-3'>
                <div className='min-w-0'>
                  <strong className='text-foreground block text-sm font-medium'>{channel.name}</strong>
                  <small className='text-muted-foreground text-xs'>Sample post · iPhone preview</small>
                </div>
                <Button variant='glass' size='icon-control' aria-label='Expand iPhone preview' aria-haspopup='dialog' onClick={() => setExpanded(true)}>
                  <Icons.arrowUpRight className='size-4' />
                </Button>
              </div>
            )
          }
        ];
      }),
    [texts, media, withPicture, openedAt, timeZone]
  );
  const dock = useMemo<DockItem[]>(
    () =>
      items.map((item) => {
        const status: DockStatus | undefined = pending && item.key === 'threads' ? 'pending' : failed && item.key === 'x' ? 'error' : undefined;
        return { key: item.key, channel: item.post.channel, name: item.post.channelName, status };
      }),
    [items, pending, failed]
  );

  if (!mounted) return null;

  return (
    <main className='mx-auto flex max-w-[60rem] flex-col gap-6 p-6'>
      <header className='flex flex-col gap-1'>
        <h1 className='text-xl font-semibold'>Preview deck</h1>
        <p className='text-muted-foreground text-sm'>Six sample posts on one stage · development only. Swipe the phone, use the dock, or press the arrows on a dock button.</p>
      </header>

      <div className='grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]'>
        <section aria-label='Deck' className='flex min-w-0 flex-col gap-4'>
          <PreviewDock items={dock} activeKey={active} onChange={setActive} label='Choose an app to preview' className='mx-auto max-w-[27rem]' />
          <PreviewDeck items={items} activeKey={active} onChange={setActive} scale={0.6} label='Post preview deck' />
        </section>

        <aside aria-label='Controls' className='flex flex-col gap-5'>
          <label className='flex flex-col gap-1.5 text-sm'>
            <span className='font-medium'>Caption of the active post</span>
            <textarea
              id={captionId}
              aria-label='Caption of the active post'
              value={texts[active] ?? ''}
              onChange={(event) => setTexts((current) => ({ ...current, [active]: event.target.value }))}
              rows={6}
              className='rafii-field rafii-focus rounded-[var(--rafii-radius-control)] px-3 py-2 text-base leading-relaxed'
            />
            <span className='text-muted-foreground text-xs'>Typing updates the active phone in place; the deck does not replay its transition.</span>
          </label>

          <SegmentedControl options={MEDIA.map((value) => ({ value, label: value === 'none' ? 'Text only' : value === 'one' ? 'One image' : 'Several' }))} value={media} onChange={setMedia} label='Sample media' size='sm' />

          <SegmentedControl options={MOTION} value={setting} onChange={setSetting} label='Motion' size='sm' />

          <div className='flex flex-col gap-2 text-sm'>
            <label className='flex items-center gap-2'>
              <input type='checkbox' aria-label='Sample profile picture' checked={withPicture} onChange={(event) => setWithPicture(event.target.checked)} />
              Sample profile picture
            </label>
            <label className='flex items-center gap-2'>
              <input type='checkbox' aria-label='Mark Threads as pending' checked={pending} onChange={(event) => setPending(event.target.checked)} />
              Mark Threads as pending
            </label>
            <label className='flex items-center gap-2'>
              <input type='checkbox' aria-label='Mark X as failed' checked={failed} onChange={(event) => setFailed(event.target.checked)} />
              Mark X as failed
            </label>
          </div>

          <Button variant='glass' size='control' aria-haspopup='dialog' onClick={() => setExpanded(true)}>
            <Icons.arrowUpRight />
            Open the expanded preview
          </Button>
        </aside>
      </div>

      <ExpandedPreviewDialog open={expanded} onOpenChange={setExpanded} items={items} dock={dock} activeKey={active} onChange={setActive} />
    </main>
  );
}
