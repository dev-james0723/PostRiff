'use client';

import type { CSSProperties, ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { useGuides } from './guides';

/** iPhone 15/16 Pro logical screen. Templates lay out at this size; the frame scales the whole screen. */
export const SCREEN_WIDTH = 393;
export const SCREEN_HEIGHT = 852;
export const STATUS_BAR_HEIGHT = 54;
export const HOME_INDICATOR_SPACE = 34;

const BEZEL = 9;
const SCREEN_RADIUS = 55;

export const SYSTEM_FONT =
  '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

/** CJK apps lead with the matching system face so glyph forms follow the market. */
export const FONT_BY_LANG: Record<string, string> = {
  'zh-CN': `-apple-system, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", ${SYSTEM_FONT}`,
  'zh-TW': `-apple-system, "PingFang TC", "Noto Sans CJK TC", "Microsoft JhengHei", ${SYSTEM_FONT}`,
  ja: `-apple-system, "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", "Yu Gothic", ${SYSTEM_FONT}`,
  ko: `-apple-system, "Apple SD Gothic Neo", "Noto Sans CJK KR", "Malgun Gothic", ${SYSTEM_FONT}`,
  hi: `-apple-system, "Kohinoor Devanagari", "Noto Sans Devanagari", ${SYSTEM_FONT}`
};

interface PhoneFrameProps {
  scale: number;
  /** Screen background behind every layer, including the status bar. */
  background: string;
  /** Glyph colour of the status bar and home indicator. */
  tone: 'dark' | 'light';
  lang?: string;
  /** Short description for assistive tech; the mockup itself is hidden from it. */
  label: string;
  /** The status bar clock; the time the post goes out reads well here. */
  clock: string;
  children: ReactNode;
  className?: string;
}

/**
 * A phone-shaped stage: bezel, Dynamic Island, status bar and home indicator around a 393x852 screen.
 * Content renders at real app sizes (15px body text and so on) and is scaled down as one picture.
 */
export function PhoneFrame({ scale, background, tone, lang = 'en', label, clock, children, className }: PhoneFrameProps) {
  const screenWidth = SCREEN_WIDTH * scale;
  const screenHeight = SCREEN_HEIGHT * scale;
  const glyph = tone === 'dark' ? '#000000' : '#ffffff';
  // Marks that are plain classes (`COVER_MARK`, `FOLD_MARK`) switch on under this attribute.
  const guides = useGuides();
  const screenStyle: CSSProperties = {
    width: SCREEN_WIDTH,
    height: SCREEN_HEIGHT,
    transform: `scale(${scale})`,
    background,
    fontFamily: FONT_BY_LANG[lang] ?? SYSTEM_FONT
  };

  return (
    <div role='img' aria-label={label} className={cn('shrink-0 select-none', className)}>
      <div
        aria-hidden
        className='relative bg-[#1c1c1e] shadow-[0_24px_48px_-20px_rgb(0_0_0/0.45)] ring-1 ring-black/30 in-data-exporting:shadow-none'
        style={{ width: screenWidth + BEZEL * 2, height: screenHeight + BEZEL * 2, padding: BEZEL, borderRadius: SCREEN_RADIUS * scale + BEZEL }}
      >
        <div className='relative overflow-hidden' style={{ width: screenWidth, height: screenHeight, borderRadius: SCREEN_RADIUS * scale, background }}>
          <div lang={lang} data-guides={guides?.show ? 'on' : undefined} className='absolute top-0 left-0 origin-top-left overflow-hidden antialiased' style={screenStyle}>
            {children}
            <div className='pointer-events-none absolute inset-x-0 top-0 z-40 flex items-center justify-between px-[42px] pt-[17px]' style={{ height: STATUS_BAR_HEIGHT, color: glyph }}>
              <span className='w-[54px] text-center text-[17px] font-semibold tracking-[-0.2px]' style={{ fontFamily: SYSTEM_FONT }}>
                {clock}
              </span>
              <StatusGlyphs color={glyph} />
            </div>
            <div className='absolute top-[11px] left-1/2 z-50 h-[37px] w-[126px] -translate-x-1/2 rounded-full bg-black' />
            <div className='absolute bottom-[8px] left-1/2 z-50 h-[5px] w-[139px] -translate-x-1/2 rounded-full' style={{ background: glyph }} />
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusGlyphs({ color }: { color: string }) {
  return (
    <span className='flex items-center gap-[6px]'>
      <svg width='19' height='12' viewBox='0 0 19 12' fill={color}>
        <rect x='0' y='8' width='3.2' height='4' rx='0.8' />
        <rect x='5' y='5.5' width='3.2' height='6.5' rx='0.8' />
        <rect x='10' y='3' width='3.2' height='9' rx='0.8' />
        <rect x='15' y='0' width='3.2' height='12' rx='0.8' />
      </svg>
      <svg width='17' height='12' viewBox='0 0 17 12' fill={color}>
        <path d='M8.5 2.3c2.4 0 4.6.9 6.3 2.5l1.2-1.3A10.8 10.8 0 0 0 8.5.5 10.8 10.8 0 0 0 1 3.5l1.2 1.3a9.1 9.1 0 0 1 6.3-2.5Z' />
        <path d='M8.5 5.9c1.5 0 2.9.6 4 1.5l1.2-1.3a7.6 7.6 0 0 0-10.4 0l1.2 1.3c1.1-1 2.5-1.5 4-1.5Z' />
        <path d='M8.5 9.4c.6 0 1.2.2 1.7.6L8.5 11.8 6.8 10c.5-.4 1.1-.6 1.7-.6Z' />
      </svg>
      <svg width='27' height='13' viewBox='0 0 27 13' fill='none'>
        <rect x='0.5' y='0.5' width='23' height='12' rx='3.8' stroke={color} strokeOpacity='0.4' />
        <rect x='2' y='2' width='20' height='9' rx='2.5' fill={color} />
        <path d='M25 4.5v4c.8-.3 1.3-1.1 1.3-2s-.5-1.7-1.3-2Z' fill={color} fillOpacity='0.45' />
      </svg>
    </span>
  );
}

/** Keeps content clear of the status bar in apps that do not draw under it. */
export function StatusBarSpace() {
  return <div aria-hidden className='shrink-0' style={{ height: STATUS_BAR_HEIGHT }} />;
}
