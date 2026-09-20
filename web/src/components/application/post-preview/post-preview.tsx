'use client';

import { lazy, Suspense, useCallback, useMemo, useRef, useState, type ComponentType, type LazyExoticComponent } from 'react';
import { useTheme } from 'next-themes';
import { cn } from '@/lib/utils';
import { AppearanceContext, type Appearance } from './appearance';
import { createGuideStore, GuideProvider } from './guides';
import { AccountPictureContext, accountNames } from './parts';
import { SCREEN_HEIGHT, SCREEN_WIDTH } from './phone-frame';
import { PlaybackContext, type Playback } from './playback';
import { PreviewTools } from './preview-tools';
import { usePreviewSetting } from './preview-settings';
import { TEMPLATE_LOADERS } from './templates';
import { templateCheck } from './templates/checks';
import type { PreviewPost, TemplateProps } from './types';

// One lazy component per channel for the life of the page, so re-renders never remount a template.
const templates = new Map<string, LazyExoticComponent<ComponentType<TemplateProps>>>();

function templateFor(channel: string) {
  let template = templates.get(channel);
  if (!template) {
    template = lazy(TEMPLATE_LOADERS[channel] ?? TEMPLATE_LOADERS.generic);
    templates.set(channel, template);
  }
  return template;
}

export function hasTemplate(channel: string) {
  return channel in TEMPLATE_LOADERS && channel !== 'generic';
}

interface PostPreviewProps {
  post: PreviewPost;
  /** 0.62 draws a phone about 262px wide. */
  scale?: number;
  /** Notes and controls under the phone; off where several phones share one set. */
  tools?: boolean;
  className?: string;
}

const SWITCH = ['off', 'on'] as const;
const APPEARANCES = ['auto', 'light', 'dark'] as const;

/** The post drawn inside its destination app on an iPhone, from the channel's template, with notes on what readers will not see. */
export function PostPreview({ post, scale = 0.62, tools = true, className }: PostPreviewProps) {
  const Template = templateFor(post.channel);
  const [store] = useState(createGuideStore);
  const [guides, setGuides] = usePreviewSetting('guides', 'off', SWITCH);
  const show = tools && guides === 'on';
  const display = accountNames(post.account).display;
  const picture = useMemo(() => (post.avatarUrl ? { name: display, url: post.avatarUrl } : null), [display, post.avatarUrl]);
  const [index, setIndex] = useState(0);
  const [slides, setSlides] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [videos, setVideos] = useState(0);
  const addVideo = useCallback(() => {
    setVideos((count) => count + 1);
    return () => setVideos((count) => count - 1);
  }, []);
  const playback = useMemo<Playback>(
    () => ({ index, setIndex, slides, setSlides, playing, setPlaying, videos, addVideo }),
    [index, slides, playing, videos, addVideo]
  );
  // Light or dark follows the app's theme until the viewer picks one; only templates with a sourced dark palette offer it.
  const { resolvedTheme } = useTheme();
  const [appearanceChoice, setAppearanceChoice] = usePreviewSetting('appearance', 'auto', APPEARANCES);
  const appearance: Appearance = appearanceChoice === 'auto' ? (resolvedTheme === 'dark' ? 'dark' : 'light') : appearanceChoice;
  const [darkChannel, setDarkChannel] = useState<string | null>(null);
  const declareDark = useCallback(() => setDarkChannel(post.channel), [post.channel]);
  const appearanceValue = useMemo(() => ({ appearance, declareDark }), [appearance, declareDark]);
  const darkReady = darkChannel === post.channel;
  const figure = useRef<HTMLElement>(null);
  const phone = useCallback(() => figure.current?.querySelector<HTMLElement>('[role="img"]') ?? null, []);
  const check = templateCheck(post.channel);

  return (
    <figure ref={figure} className={cn('m-0 flex flex-col items-center gap-2', className)}>
      <GuideProvider store={store} show={show} channelName={post.channelName}>
        <AccountPictureContext.Provider value={picture}>
          <PlaybackContext.Provider value={playback}>
            <AppearanceContext.Provider value={appearanceValue}>
              <Suspense fallback={<PhoneSkeleton scale={scale} />}>
                <Template post={post} scale={scale} />
              </Suspense>
            </AppearanceContext.Provider>
          </PlaybackContext.Provider>
        </AccountPictureContext.Provider>
      </GuideProvider>
      {tools && (
        <PreviewTools
          store={store}
          post={post}
          playback={playback}
          show={show}
          onShowChange={(next) => setGuides(next ? 'on' : 'off')}
          appearance={darkReady ? appearance : null}
          onAppearanceChange={setAppearanceChoice}
          phone={phone}
          width={SCREEN_WIDTH * scale + 18}
        />
      )}
      <figcaption className='text-muted-foreground max-w-60 text-center text-[11px] leading-snug'>
        {hasTemplate(post.channel) ? `Preview in ${post.channelName}` : 'Generic preview'}
        {check ? (check.stale ? `, last checked against the app ${check.label}; it may have changed since.` : `, checked ${check.label}.`) : '.'} The app has
        the final say on layout.
      </figcaption>
    </figure>
  );
}

function PhoneSkeleton({ scale }: { scale: number }) {
  return (
    <div
      aria-hidden
      className='bg-muted animate-pulse'
      style={{ width: SCREEN_WIDTH * scale + 18, height: SCREEN_HEIGHT * scale + 18, borderRadius: 55 * scale + 9 }}
    />
  );
}
