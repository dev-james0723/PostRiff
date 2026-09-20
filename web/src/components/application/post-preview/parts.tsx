'use client';

import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react';
import Image from 'next/image';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { cropNote, foldNote, GUIDE_COLOR, hiddenShare, NOTE_ORDER, ratioName, useGuideNote, useGuides } from './guides';
import { SlideContext, usePlayback, useSlideIndex } from './playback';
import type { PreviewMedia, PreviewPost } from './types';

/** The account as a display name, a bare handle and an initial for the avatar. */
export function accountNames(account: string) {
  const bare = account.trim().replace(/^@/, '');
  const handle = bare.replace(/\s+/g, '').toLowerCase() || 'account';
  const display = bare || 'Account';
  return { display, handle, initial: Array.from(display)[0]?.toUpperCase() ?? 'A' };
}

const AVATAR_HUES = [12, 32, 145, 172, 198, 222, 262, 292, 330];

/** The posting account's real picture, keyed by the display name templates pass to `Monogram`. */
export const AccountPictureContext = createContext<{ name: string; url: string } | null>(null);

/**
 * The account's avatar: its real profile picture when the provider gave PostRiff one, otherwise a lettered
 * avatar. PostRiff never draws a stand-in photo.
 */
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
  const picture = useContext(AccountPictureContext);
  const { initial } = accountNames(name);
  if (picture && picture.name === name) {
    return (
      <Image
        src={picture.url}
        alt=''
        width={size}
        height={size}
        unoptimized
        className={cn('shrink-0 object-cover', className)}
        style={{ width: size, height: size, borderRadius: shape === 'circle' ? '50%' : shape === 'rounded' ? size * 0.22 : 4, ...style }}
      />
    );
  }
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
    <span data-guide-text className={cn('break-words whitespace-pre-line', className)} style={style}>
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
 * line on a fade of the background colour. Inside a preview it reports how much text shows before the cut and,
 * while guides show, marks the fold.
 */
export function ClampText({
  lines,
  more,
  background,
  children,
  className,
  moreClassName,
  style,
  guide
}: {
  lines: number;
  more?: ReactNode;
  background: string;
  children: ReactNode;
  className?: string;
  moreClassName?: string;
  style?: CSSProperties;
  /** What the text is when it is not the post itself (`Title`); false when a cut here is not worth a note. */
  guide?: string | false;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLSpanElement>(null);
  const [cut, setCut] = useState(false);
  const [shown, setShown] = useState<{ text: string; next: string; more?: string } | null>(null);
  const guides = useGuides();
  const measure = Boolean(guides) && guide !== false;

  useLayoutEffect(() => {
    const element = ref.current;
    if (element) setCut(element.scrollHeight > element.clientHeight + 1);
  }, [children, lines]);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!measure || !cut || !element) {
      setShown(null);
      return;
    }
    const { text, next } = shownText(element, moreRef.current);
    const label = moreRef.current?.textContent?.trim() || undefined;
    setShown((current) => (current && current.text === text && current.next === next && current.more === label ? current : { text, next, more: label }));
  }, [measure, cut, children, lines]);

  useGuideNote(shown ? foldNote(shown.text, { more: shown.more, next: shown.next, label: typeof guide === 'string' ? guide : undefined }) : null);

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
          ref={moreRef}
          className={cn('absolute right-0 bottom-0 pl-10', moreClassName)}
          style={{ background: `linear-gradient(to right, transparent, ${background} 2.25rem)` }}
        >
          {more}
        </span>
      )}
      {guides?.show && shown && <GuideLine label='Fold' />}
    </div>
  );
}

/** A dashed guide along the bottom of the element above, tagged. Drawn by PostRiff, never by the app. */
function GuideLine({ label }: { label: string }) {
  return (
    <span aria-hidden className='pointer-events-none absolute inset-x-0 -bottom-[3px] z-30 border-t-2 border-dashed' style={{ borderColor: GUIDE_COLOR }}>
      <GuideTag className='absolute top-[3px] right-0'>{label}</GuideTag>
    </span>
  );
}

function GuideTag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn('rounded-[4px] px-1.5 text-[11px] leading-[16px] font-semibold whitespace-nowrap text-white', className)}
      style={{ background: GUIDE_COLOR, fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }}
    >
      {children}
    </span>
  );
}

/**
 * The text a clamped box shows (characters laid out inside it and not under the "more" label) and the few
 * characters after it. Reads only the post text (`data-guide-text`) when the box also holds a name.
 */
function shownText(container: HTMLElement, more: HTMLElement | null) {
  const root = container.querySelector<HTMLElement>('[data-guide-text]') ?? container;
  const box = container.getBoundingClientRect();
  const scale = container.offsetWidth ? box.width / container.offsetWidth : 1;
  const label = more?.getBoundingClientRect();
  // The label fades in across its 40px left padding; text under the second half of the fade reads as hidden.
  const labelEdge = label ? label.left + 20 * scale : Infinity;
  const range = document.createRange();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let shown = '';
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const value = (node as Text).data;
    for (let index = 0; index < value.length; index++) {
      range.setStart(node, index);
      range.setEnd(node, index + 1);
      const rects = range.getClientRects();
      const rect = rects[rects.length - 1];
      if (rect && (rect.bottom > box.bottom + scale || (label && rect.top >= label.top - scale && rect.right > labelEdge))) {
        return { text: shown, next: value.slice(index, index + 4) };
      }
      shown += value[index];
    }
  }
  return { text: shown, next: '' };
}

/**
 * One media item filling its box: image, a video that plays and pauses on click, or a quiet loading state. With
 * `crop`, the template declares the box follows the app's documented ratio range, so a photo that does not fit
 * is cropped by the app too: that is reported (for the slide in view) and, while guides show, marked.
 */
export function MediaFill({
  media,
  className,
  style,
  rounded = 0,
  crop
}: {
  media: PreviewMedia;
  className?: string;
  style?: CSSProperties;
  rounded?: number;
  /** `tall` when only photos taller than the range are cropped (wider ones letterbox or scale). */
  crop?: boolean | 'tall';
}) {
  const box = cn('relative overflow-hidden', className);
  const boxStyle = { borderRadius: rounded, ...style };
  const ref = useRef<HTMLDivElement>(null);
  const guides = useGuides();
  const active = useContext(SlideContext);
  const [natural, setNatural] = useState<number | null>(null);
  const [boxRatio, setBoxRatio] = useState<number | null>(null);
  const watch = Boolean(guides) && Boolean(crop) && media.kind === 'image' && active;

  useLayoutEffect(() => {
    const element = ref.current;
    if (!watch || !element) return;
    const measure = () => {
      if (element.offsetWidth) setBoxRatio(element.offsetHeight / element.offsetWidth);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [watch, media.url, media.status]);

  const mediaRatio = media.width && media.height ? media.height / media.width : natural;
  const hidden = watch && mediaRatio && boxRatio ? hiddenShare(mediaRatio, boxRatio) : null;
  const cropped = hidden && hidden.share >= 0.03 && boxRatio && (crop !== 'tall' || hidden.axis === 'height') ? { hidden, boxRatio } : null;
  useGuideNote(cropped && guides ? cropNote(cropped.boxRatio, cropped.hidden, guides.channelName) : null);

  if (media.status === 'loading') return <div className={cn(box, 'animate-pulse bg-[#e5e5ea]')} style={boxStyle} />;
  if (media.status === 'error' || !media.url) {
    return (
      <div className={cn(box, 'flex items-center justify-center bg-[#e5e5ea] text-[13px] text-[#8e8e93]')} style={boxStyle}>
        Media unavailable
      </div>
    );
  }
  if (media.kind === 'video') return <VideoFill url={media.url} alt={media.alt} className={box} style={boxStyle} />;
  return (
    <div ref={ref} className={box} style={boxStyle}>
      <Image
        src={media.url}
        alt={media.alt}
        fill
        unoptimized
        sizes='393px'
        className='object-cover'
        onLoad={watch && !(media.width && media.height) ? (event) => setNatural(event.currentTarget.naturalHeight / event.currentTarget.naturalWidth || null) : undefined}
      />
      {guides?.show && cropped && (
        <span aria-hidden className='pointer-events-none absolute inset-0 z-30 border-2 border-dashed' style={{ borderColor: GUIDE_COLOR, borderRadius: rounded }}>
          <GuideTag className='absolute top-2 left-2'>
            Cropped to {ratioName(cropped.boxRatio)} · {Math.round(cropped.hidden.share * 100)}% of {cropped.hidden.axis} hidden
          </GuideTag>
        </span>
      )}
    </div>
  );
}

/** A muted, looping video: click plays or pauses it, as does the play control under the phone. */
function VideoFill({ url, alt, className, style }: { url: string; alt: string; className: string; style: CSSProperties }) {
  const playback = usePlayback();
  const active = useContext(SlideContext);
  const ref = useRef<HTMLVideoElement>(null);
  const play = Boolean(playback?.playing && active);
  const addVideo = playback?.addVideo;
  const setPlaying = playback?.setPlaying;

  useEffect(() => addVideo?.(), [addVideo]);
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (play) video.play().catch(() => setPlaying?.(false));
    else video.pause();
  }, [play, setPlaying]);

  return (
    <div className={className} style={style}>
      <video ref={ref} src={`${url}#t=0.1`} aria-label={alt || 'Video'} muted loop playsInline preload='metadata' className='absolute inset-0 size-full object-cover' />
      {playback && (
        <button
          type='button'
          tabIndex={-1}
          data-export='skip'
          aria-label={play ? 'Pause video' : 'Play video'}
          onClick={() => setPlaying?.(!play)}
          className='absolute inset-0 flex cursor-pointer items-center justify-center'
        >
          {!play && (
            <span className='flex size-[64px] items-center justify-center rounded-full bg-black/35 text-white'>
              <svg width='28' height='28' viewBox='0 0 24 24' fill='currentColor' aria-hidden>
                <path d='M8 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L9.2 4.5A.8.8 0 0 0 8 5.2Z' />
              </svg>
            </span>
          )}
        </button>
      )}
    </div>
  );
}

const HIDE_SCROLLBAR = '[scrollbar-width:none] [&::-webkit-scrollbar]:hidden';

/** Mouse drag for a horizontal scroller; touch and trackpads scroll natively. Returns handlers and a click guard. */
function useDragScroll(onRelease?: (element: HTMLDivElement, moved: number) => void) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; left: number; scale: number } | null>(null);
  const dragged = useRef(false);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const element = ref.current;
    if (event.pointerType !== 'mouse' || event.button !== 0 || !element || element.scrollWidth <= element.clientWidth) return;
    drag.current = { x: event.clientX, left: element.scrollLeft, scale: element.getBoundingClientRect().width / element.offsetWidth || 1 };
    dragged.current = false;
    element.setPointerCapture(event.pointerId);
    element.style.scrollSnapType = 'none';
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    const element = ref.current;
    if (!current || !element) return;
    // The phone is scaled, so pointer pixels are converted to the screen's own.
    const moved = (event.clientX - current.x) / current.scale;
    if (Math.abs(moved) > 4) dragged.current = true;
    element.scrollLeft = current.left - moved;
  };
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    const element = ref.current;
    if (!current || !element) return;
    drag.current = null;
    onRelease?.(element, (event.clientX - current.x) / current.scale);
    // Snapping comes back once the release has settled, so it does not fight the settling scroll.
    window.setTimeout(() => {
      if (!drag.current) element.style.scrollSnapType = '';
    }, 450);
  };
  // A drag that ends over a video must not also toggle it.
  const onClickCapture = (event: { stopPropagation: () => void; preventDefault: () => void }) => {
    if (!dragged.current) return;
    dragged.current = false;
    event.stopPropagation();
    event.preventDefault();
  };
  return { ref, handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp, onClickCapture } };
}

/**
 * Several photos or videos the way feed apps page through them: one slide per width, swiped on touch, dragged
 * with a mouse, or moved with the arrows that show on hover. The slide in view is shared with the pager under the
 * phone (`playback.tsx`); templates draw their own dots or counter from `useSlideIndex`.
 */
export function MediaCarousel({
  media,
  className,
  style,
  rounded = 0,
  crop
}: {
  media: PreviewMedia[];
  className?: string;
  style?: CSSProperties;
  rounded?: number;
  crop?: boolean | 'tall';
}) {
  const playback = usePlayback();
  const count = media.length;
  const index = useSlideIndex(count);
  const setIndex = playback?.setIndex;
  const setSlides = playback?.setSlides;
  const settle = useRef<number | undefined>(undefined);
  // Where a scroll PostRiff started is headed; a pause in its scroll events must not read as a swipe that settled.
  const aim = useRef<{ left: number; until: number } | null>(null);

  const glide = (element: HTMLDivElement, left: number) => {
    aim.current = { left, until: performance.now() + 1200 };
    element.scrollTo({ left, behavior: 'smooth' });
  };
  const go = (element: HTMLDivElement, next: number) => {
    const bounded = Math.min(Math.max(next, 0), count - 1);
    if (bounded !== index && setIndex) setIndex(bounded);
    else glide(element, bounded * element.clientWidth);
  };
  const { ref, handlers } = useDragScroll((element, moved) => go(element, Math.abs(moved) > element.clientWidth * 0.15 ? index + (moved < 0 ? 1 : -1) : index));

  useEffect(() => {
    if (!setSlides) return;
    setSlides(count);
    return () => setSlides(0);
  }, [setSlides, count]);

  // Follow the pager: bring the slide in view.
  useEffect(() => {
    const element = ref.current;
    if (!element?.clientWidth) return;
    const left = index * element.clientWidth;
    if (Math.abs(element.scrollLeft - left) > 1) glide(element, left);
  }, [index, ref]);

  // Follow a swipe: once scrolling settles, the nearest slide is the one in view.
  const onScroll = () => {
    window.clearTimeout(settle.current);
    settle.current = window.setTimeout(() => {
      const element = ref.current;
      if (!element?.clientWidth || element.style.scrollSnapType === 'none') return;
      const target = aim.current;
      if (target && performance.now() < target.until && Math.abs(element.scrollLeft - target.left) > 1) return;
      aim.current = null;
      const next = Math.round(element.scrollLeft / element.clientWidth);
      if (next !== index) setIndex?.(next);
    }, 120);
  };

  return (
    <div className={cn('group/carousel relative overflow-hidden', className)} style={{ borderRadius: rounded, ...style }}>
      {/* Not a tab stop: the phone is one picture to assistive tech, and the pager under it moves the slides. */}
      <div ref={ref} tabIndex={-1} onScroll={onScroll} {...handlers} className={cn('flex size-full snap-x snap-mandatory overflow-x-auto overscroll-x-contain', HIDE_SCROLLBAR)}>
        {media.map((item, position) => (
          <SlideContext.Provider key={item.id} value={position === index}>
            <MediaFill media={item} crop={crop} className='h-full w-full shrink-0 snap-start snap-always' />
          </SlideContext.Provider>
        ))}
      </div>
      {count > 1 && index > 0 && <CarouselArrow side='left' onClick={() => ref.current && go(ref.current, index - 1)} />}
      {count > 1 && index < count - 1 && <CarouselArrow side='right' onClick={() => ref.current && go(ref.current, index + 1)} />}
    </div>
  );
}

/** Round arrow over a carousel edge, shown on hover for mouse users. The pager under the phone is the keyboard path. */
function CarouselArrow({ side, onClick }: { side: 'left' | 'right'; onClick: () => void }) {
  return (
    <button
      type='button'
      tabIndex={-1}
      data-export='skip'
      aria-label={side === 'left' ? 'Previous slide' : 'Next slide'}
      onClick={onClick}
      className={cn(
        'absolute top-1/2 z-20 flex size-[30px] -translate-y-1/2 items-center justify-center rounded-full bg-white/90 text-black opacity-0 shadow-[0_1px_4px_rgb(0_0_0/0.3)] transition-opacity group-hover/carousel:opacity-100',
        side === 'left' ? 'left-2' : 'right-2'
      )}
    >
      <svg width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth='2.6' strokeLinecap='round' strokeLinejoin='round' aria-hidden>
        <path d={side === 'left' ? 'm15 6-6 6 6 6' : 'm9 6 6 6-6 6'} />
      </svg>
    </button>
  );
}

/** A row of media that scrolls sideways freely (Threads, Dcard): swipe, trackpad, or drag with a mouse. */
export function MediaStrip({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  const { ref, handlers } = useDragScroll();
  return (
    <div ref={ref} tabIndex={-1} {...handlers} className={cn('flex snap-x snap-proximity overflow-x-auto overscroll-x-contain', HIDE_SCROLLBAR, className)} style={style}>
      {children}
    </div>
  );
}

/**
 * PostRiff's own note inside a mockup where the app needs media the post does not have. Styled as an
 * annotation (dashed, neutral), never as part of the app. `note` is the same need in English for the list under
 * the phone, when `need` is in the app's language.
 */
export function MissingMedia({
  need,
  note,
  className,
  style,
  dark = false
}: {
  need: string;
  note?: string;
  className?: string;
  style?: CSSProperties;
  dark?: boolean;
}) {
  useGuideNote({ tone: 'problem', order: NOTE_ORDER.media, text: note ?? need });
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
  if (chars.length <= maxChars) return { text: flat, cut: false, rest: '' };
  return { text: `${chars.slice(0, maxChars).join('').trimEnd()}…`, cut: true, rest: chars.slice(maxChars).join('') };
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
