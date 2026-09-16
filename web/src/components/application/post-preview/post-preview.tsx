'use client';

import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react';
import { cn } from '@/lib/utils';
import { SCREEN_HEIGHT, SCREEN_WIDTH } from './phone-frame';
import { TEMPLATE_LOADERS } from './templates';
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
  className?: string;
}

/** The post drawn inside its destination app on an iPhone, from the channel's template. */
export function PostPreview({ post, scale = 0.62, className }: PostPreviewProps) {
  const Template = templateFor(post.channel);

  return (
    <figure className={cn('m-0 flex flex-col items-center gap-2', className)}>
      <Suspense fallback={<PhoneSkeleton scale={scale} />}>
        <Template post={post} scale={scale} />
      </Suspense>
      <figcaption className='text-muted-foreground max-w-60 text-center text-[11px] leading-snug'>
        {hasTemplate(post.channel) ? `Preview in ${post.channelName}.` : 'Generic preview.'} The app has the final say on layout.
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
