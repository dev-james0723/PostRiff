'use client';

import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import Image from 'next/image';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { PreviewMedia, PreviewPost } from './types';

/** The account as a display name, a bare handle and an initial for the avatar. */
export function accountNames(account: string) {
  const bare = account.trim().replace(/^@/, '');
  const handle = bare.replace(/\s+/g, '').toLowerCase() || 'account';
  const display = bare || 'Account';
  return { display, handle, initial: Array.from(display)[0]?.toUpperCase() ?? 'A' };
}

const AVATAR_HUES = [12, 32, 145, 172, 198, 222, 262, 292, 330];

/** A lettered avatar. PostRiff does not have the account's profile photo, so it never pretends to. */
export function Monogram({
  name,
  size,
  shape = 'circle',
  className,
  style
}: {
  name: string;
  size: number;
  shape?: 'circle' | 'rounded' | 'square';
  className?: string;
  style?: CSSProperties;
}) {
  const { initial } = accountNames(name);
  const hue = AVATAR_HUES[Array.from(name).reduce((sum, char) => sum + (char.codePointAt(0) ?? 0), 0) % AVATAR_HUES.length];
  return (
    <span
      className={cn('flex shrink-0 items-center justify-center font-semibold text-white', className)}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.42,
        borderRadius: shape === 'circle' ? '50%' : shape === 'rounded' ? size * 0.22 : 4,
        background: `linear-gradient(135deg, hsl(${hue} 62% 58%), hsl(${(hue + 28) % 360} 58% 44%))`,
        ...style
      }}
    >
      {initial}
    </span>
  );
}

const TOKEN = /(https?:\/\/[^\s]+|#[^\s#]+#|#[\p{L}\p{N}_]+|@[\p{L}\p{N}_.]+)/gu;

/** Post text with links, #topics and @mentions in the app's link colour. */
export function RichText({ text, accent, className, style }: { text: string; accent: string; className?: string; style?: CSSProperties }) {
  const parts = text.split(TOKEN);
  return (
    <span className={cn('break-words whitespace-pre-line', className)} style={style}>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <span key={index} style={{ color: accent }}>
            {part}
          </span>
        ) : (
          part
        )
      )}
    </span>
  );
}

/**
 * Clamps to `lines` and, only when something was cut, lays the app's "more" label over the end of the last
 * line on a fade of the background colour.
 */
export function ClampText({
  lines,
  more,
  background,
  children,
  className,
  moreClassName,
  style
}: {
  lines: number;
  more?: ReactNode;
  background: string;
  children: ReactNode;
  className?: string;
  moreClassName?: string;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [cut, setCut] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (element) setCut(element.scrollHeight > element.clientHeight + 1);
  }, [children, lines]);

  return (
    <div className='relative'>
      <div
        ref={ref}
        className={className}
        style={{ display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: lines, overflow: 'hidden', ...style }}
      >
        {children}
      </div>
      {cut && more && (
        <span
          className={cn('absolute right-0 bottom-0 pl-10', moreClassName)}
          style={{ background: `linear-gradient(to right, transparent, ${background} 2.25rem)` }}
        >
          {more}
        </span>
      )}
    </div>
  );
}

/** One media item filling its box: image, first frame of a video, or a quiet loading state. */
export function MediaFill({ media, className, style, rounded = 0 }: { media: PreviewMedia; className?: string; style?: CSSProperties; rounded?: number }) {
  const box = cn('relative overflow-hidden', className);
  const boxStyle = { borderRadius: rounded, ...style };
  if (media.status === 'loading') return <div className={cn(box, 'animate-pulse bg-[#e5e5ea]')} style={boxStyle} />;
  if (media.status === 'error' || !media.url) {
    return (
      <div className={cn(box, 'flex items-center justify-center bg-[#e5e5ea] text-[13px] text-[#8e8e93]')} style={boxStyle}>
        Media unavailable
      </div>
    );
  }
  if (media.kind === 'video') {
    return (
      <div className={box} style={boxStyle}>
        <video
          src={`${media.url}#t=0.1`}
          aria-label={media.alt || 'Video'}
          muted
          playsInline
          preload='metadata'
          className='absolute inset-0 size-full object-cover'
        />
      </div>
    );
  }
  return (
    <div className={box} style={boxStyle}>
      <Image src={media.url} alt={media.alt} fill unoptimized sizes='393px' className='object-cover' />
    </div>
  );
}

/**
 * PostRiff's own note inside a mockup where the app needs media the post does not have. Styled as an
 * annotation (dashed, neutral), never as part of the app.
 */
export function MissingMedia({ need, className, style, dark = false }: { need: string; className?: string; style?: CSSProperties; dark?: boolean }) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 border-2 border-dashed px-8 text-center text-[14px] leading-snug',
        dark ? 'border-white/30 bg-white/5 text-white/70' : 'border-[#c7c7cc] bg-[#f2f2f7] text-[#6e6e73]',
        className
      )}
      style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', ...style }}
    >
      <Icons.media className='size-8 opacity-70' stroke={1.5} />
      <span>{need}</span>
    </div>
  );
}

/** Media box height for a width, keeping the item's ratio inside the app's allowed range. */
export function mediaHeight(media: PreviewMedia | undefined, width: number, { min, max, fallback }: { min: number; max: number; fallback: number }) {
  const ratio = media?.width && media?.height ? media.height / media.width : fallback;
  return Math.round(width * Math.min(Math.max(ratio, min), max));
}

export function formatClock(post: PreviewPost) {
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: post.timeZone })
    .format(post.publishAt)
    .replace(/\s?[AP]M$/, '');
}

export function formatTime(post: PreviewPost, locale: string, options: Intl.DateTimeFormatOptions) {
  try {
    return new Intl.DateTimeFormat(locale, { timeZone: post.timeZone, ...options }).format(post.publishAt);
  } catch {
    return '';
  }
}

/**
 * Caption text cut to what an overlay caption shows before its "more" link. Overlays on video cannot fade
 * into a solid background, so they cut by length instead of by measured lines.
 */
export function truncateCaption(text: string, maxChars: number) {
  const flat = text.replace(/\s*\n+\s*/g, ' ').trim();
  const chars = Array.from(flat);
  if (chars.length <= maxChars) return { text: flat, cut: false };
  return { text: `${chars.slice(0, maxChars).join('').trimEnd()}…`, cut: true };
}

export function firstLine(text: string) {
  return text.split('\n').find((line) => line.trim())?.trim() ?? '';
}

/** The text after the first non-empty line, for apps that split a title from the body. */
export function restAfterFirstLine(text: string) {
  const lines = text.split('\n');
  const index = lines.findIndex((line) => line.trim());
  return index === -1 ? '' : lines.slice(index + 1).join('\n').trim();
}

/** A channel's brand mark from the app's channel directory, at any size and colour. */
export function BrandGlyph({ path, size, color, className }: { path?: string; size: number; color: string; className?: string }) {
  if (!path) return null;
  return (
    <svg viewBox='0 0 24 24' width={size} height={size} className={className} aria-hidden>
      <path d={path} fill={color} />
    </svg>
  );
}

/** Up to four media items the way most feeds tile them: one, two side by side, one tall plus two, or a 2x2 grid. */
export function MediaGrid({
  media,
  height,
  gap = 2,
  rounded = 0,
  className,
  style
}: {
  media: PreviewMedia[];
  height: number;
  gap?: number;
  rounded?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const items = media.slice(0, 4);
  if (items.length === 0) return null;
  if (items.length === 1) return <MediaFill media={items[0]} rounded={rounded} className={cn('w-full shrink-0', className)} style={{ height, ...style }} />;
  return (
    <div
      className={cn('grid w-full shrink-0 overflow-hidden', className)}
      style={{
        height,
        gap,
        borderRadius: rounded,
        gridTemplateColumns: '1fr 1fr',
        gridTemplateRows: items.length > 2 ? '1fr 1fr' : '1fr',
        ...style
      }}
    >
      {items.map((item, index) => (
        <MediaFill key={item.id} media={item} className='size-full' style={items.length === 3 && index === 0 ? { gridRow: 'span 2' } : undefined} />
      ))}
    </div>
  );
}

/** iOS tab bar: 49pt of items above the 34pt home-indicator inset. */
export function TabBar({ children, background, border, className }: { children: ReactNode; background: string; border?: string; className?: string }) {
  return (
    <nav
      className={cn('flex h-[83px] shrink-0 items-start justify-around px-1 pt-[7px]', className)}
      style={{ background, borderTop: border ? `0.5px solid ${border}` : undefined }}
    >
      {children}
    </nav>
  );
}

export function TabItem({ icon, label, color, className }: { icon: ReactNode; label?: string; color: string; className?: string }) {
  return (
    <span className={cn('flex min-w-[56px] flex-col items-center gap-[2px]', className)} style={{ color }}>
      {icon}
      {label && <span className='text-[10px] leading-[12px] font-medium whitespace-nowrap'>{label}</span>}
    </span>
  );
}
