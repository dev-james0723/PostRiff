'use client';

import { useState, useSyncExternalStore } from 'react';
import { channels } from '@/config/channels';
import { PostPreview } from './post-preview';
import type { PreviewMedia, PreviewPost } from './types';

/**
 * Development-only review sheet: every channel's template with the same sample post, so the set can be
 * compared at a glance. Images are drawn SVGs; nothing here reads a workspace.
 */

const SAMPLE_TEXT: Record<string, string> = {
  global:
    'New recital dates are live 🎹\nTwo evenings of Debussy and Ravel at City Hall, with a short talk before each half. Programme notes and tickets: https://example.com/recital #piano #recital',
  cn: '秋季独奏会开票啦🎹\n德彪西与拉威尔两晚演出，每半场前有十分钟导赏。节目单和购票方式都整理在这里 #钢琴 #独奏会',
  tw: '秋季獨奏會開賣🎹\n德布西與拉威爾兩晚演出，每半場前有十分鐘導聆。節目單和購票方式整理在這裡 #鋼琴 #獨奏會',
  jp: '秋のリサイタル日程を公開しました🎹\nドビュッシーとラヴェルの二夜。各ステージの前に短いお話があります。プログラムとチケットはこちら #ピアノ #リサイタル',
  kr: '가을 리사이틀 일정을 공개합니다🎹\n드뷔시와 라벨의 이틀 밤. 각 무대 전에 짧은 해설이 있습니다. 프로그램과 예매 안내 #피아노 #리사이틀',
  in: 'नई रिसाइटल तारीखें आ गई हैं 🎹\nदो शामें, डेब्यूसी और रावेल के साथ। कार्यक्रम और टिकट की जानकारी यहाँ #पियानो #रिसाइटल'
};

function svgImage(width: number, height: number, hue: number) {
  const whites = 18;
  const keyWidth = (width * 0.84) / whites;
  const keysTop = height * 0.62;
  const keys = Array.from({ length: whites }, (_, index) => {
    const x = width * 0.08 + index * keyWidth;
    const black = [1, 1, 0, 1, 1, 1, 0][index % 7] && index < whites - 1;
    return `<rect x='${x}' y='${keysTop}' width='${keyWidth - 3}' height='${height * 0.22}' rx='6' fill='#f6f1e7'/>${
      black ? `<rect x='${x + keyWidth * 0.68}' y='${keysTop}' width='${keyWidth * 0.62}' height='${height * 0.13}' rx='4' fill='#171310'/>` : ''
    }`;
  }).join('');
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}' viewBox='0 0 ${width} ${height}'><defs><linearGradient id='b' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='hsl(${hue} 45% 12%)'/><stop offset='1' stop-color='hsl(${hue + 20} 55% 32%)'/></linearGradient><radialGradient id='s' cx='0.55' cy='0.3' r='0.6'><stop offset='0' stop-color='hsl(${hue + 30} 90% 80%)' stop-opacity='0.8'/><stop offset='1' stop-color='hsl(${hue + 30} 90% 80%)' stop-opacity='0'/></radialGradient></defs><rect width='100%' height='100%' fill='url(#b)'/><rect width='100%' height='100%' fill='url(#s)'/>${keys}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const SAMPLE_MEDIA: PreviewMedia[] = [
  { id: 'portrait', kind: 'image', url: svgImage(1080, 1350, 24), alt: 'Piano keys under a warm stage light', width: 1080, height: 1350, status: 'ready' },
  { id: 'square', kind: 'image', url: svgImage(1080, 1080, 200), alt: 'Piano keys in blue light', width: 1080, height: 1080, status: 'ready' },
  { id: 'landscape', kind: 'image', url: svgImage(1920, 1080, 330), alt: 'Concert hall stage', width: 1920, height: 1080, status: 'ready' }
];

const VERTICAL_MEDIA: PreviewMedia = { id: 'vertical', kind: 'image', url: svgImage(1080, 1920, 262), alt: 'Piano keys in violet light', width: 1080, height: 1920, status: 'ready' };

const VERTICAL_FIRST = new Set(['tiktok', 'douyin', 'kuaishou', 'wechat-channels', 'moj', 'snapchat']);

type MediaChoice = 'none' | 'one' | 'several';

const subscribeToNothing = () => () => {};

export function PostPreviewGallery() {
  const [choice, setChoice] = useState<MediaChoice>('one');
  // Times and zones differ between server and browser, so the sheet renders in the browser only.
  const mounted = useSyncExternalStore(subscribeToNothing, () => true, () => false);
  if (!mounted) return null;
  const publishAt = new Date();
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <main className='flex flex-col gap-6 p-6'>
      <header className='flex flex-wrap items-center justify-between gap-4'>
        <div>
          <h1 className='text-xl font-semibold'>Post preview templates</h1>
          <p className='text-muted-foreground text-sm'>{channels.length} channels · development only</p>
        </div>
        <div role='radiogroup' aria-label='Media' className='flex gap-1 rounded-lg border p-1 text-sm'>
          {(['none', 'one', 'several'] as MediaChoice[]).map((value) => (
            <button
              key={value}
              type='button'
              role='radio'
              aria-checked={choice === value}
              onClick={() => setChoice(value)}
              className={choice === value ? 'bg-primary text-primary-foreground rounded-md px-3 py-1' : 'rounded-md px-3 py-1'}
            >
              {value === 'none' ? 'Text only' : value === 'one' ? 'One image' : 'Several images'}
            </button>
          ))}
        </div>
      </header>
      <div className='grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-x-4 gap-y-8'>
        {channels.map((channel) => {
          const first = VERTICAL_FIRST.has(channel.slug) ? VERTICAL_MEDIA : SAMPLE_MEDIA[0];
          const media = choice === 'none' ? [] : choice === 'one' ? [first] : [first, ...SAMPLE_MEDIA.slice(1)];
          const post: PreviewPost = {
            channel: channel.slug,
            channelName: channel.name,
            account: channel.region === 'global' || !channel.region ? '@yourstudio' : 'Your Studio',
            text: SAMPLE_TEXT[channel.region ?? 'global'] ?? SAMPLE_TEXT.global,
            media,
            publishAt,
            timeZone
          };
          return (
            <section key={channel.slug} className='flex flex-col items-center gap-2'>
              <h2 className='text-sm font-medium'>
                {channel.name} <span className='text-muted-foreground font-normal'>{channel.slug}</span>
              </h2>
              <PostPreview post={post} scale={0.52} />
            </section>
          );
        })}
      </div>
    </main>
  );
}
