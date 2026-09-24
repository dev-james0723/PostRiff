'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useTimeZone } from '@/lib/preferences';
import { channels } from '@/config/channels';
import { PostPreview } from './post-preview';
import { usePreviewSetting } from './preview-settings';
import { templateCheck } from './templates/checks';
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

// A drawn portrait standing in for a connected account's profile picture, to check every avatar shape.
const SAMPLE_AVATAR = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
  "<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200' viewBox='0 0 200 200'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='#f6c177'/><stop offset='1' stop-color='#b4637a'/></linearGradient></defs><rect width='200' height='200' fill='url(#g)'/><circle cx='100' cy='82' r='38' fill='#2a2233'/><path d='M34 200c8-44 34-66 66-66s58 22 66 66z' fill='#2a2233'/></svg>"
)}`;

const VERTICAL_FIRST = new Set(['tiktok', 'douyin', 'kuaishou', 'wechat-channels', 'moj', 'snapchat']);

type MediaChoice = 'none' | 'one' | 'tall' | 'several' | 'video';

/** The sample post text for a channel's region, shared with the preview deck sheet. */
export function sampleText(region?: string) {
  return SAMPLE_TEXT[region ?? 'global'] ?? SAMPLE_TEXT.global;
}

/** The drawn sample media for a channel: the first item is 9:16 on short-video apps. */
export function sampleMedia(slug: string, choice: Exclude<MediaChoice, 'video'>): PreviewMedia[] {
  const first = VERTICAL_FIRST.has(slug) ? VERTICAL_MEDIA : SAMPLE_MEDIA[0];
  return choice === 'none' ? [] : choice === 'one' ? [first] : choice === 'tall' ? [VERTICAL_MEDIA] : [first, ...SAMPLE_MEDIA.slice(1)];
}

export { SAMPLE_AVATAR };

// A 9:16 photo on every channel shows which templates crop and where overlays sit.
const MEDIA_LABELS: Record<MediaChoice, string> = { none: 'Text only', one: 'One image', tall: 'Tall photo', several: 'Several images', video: 'Video' };

/** A three-second 9:16 clip recorded from a canvas in this browser, so playback can be reviewed without uploads. */
async function recordSampleVideo() {
  const canvas = document.createElement('canvas');
  canvas.width = 360;
  canvas.height = 640;
  const context = canvas.getContext('2d');
  if (!context || typeof MediaRecorder === 'undefined') return null;
  const recorder = new MediaRecorder(canvas.captureStream(24), { mimeType: 'video/webm' });
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => chunks.push(event.data);
  const stopped = new Promise((resolve) => (recorder.onstop = resolve));
  recorder.start();
  const started = performance.now();
  await new Promise<void>((resolve) => {
    const timer = window.setInterval(() => {
      const seconds = (performance.now() - started) / 1000;
      const lit = Math.floor(seconds * 6) % 12;
      context.fillStyle = `hsl(${250 + seconds * 20} 45% 22%)`;
      context.fillRect(0, 0, 360, 640);
      for (let key = 0; key < 12; key += 1) {
        context.fillStyle = key === lit ? '#f6c177' : '#f6f1e7';
        context.fillRect(24 + key * 26.5, 380, 23, 150);
      }
      if (seconds >= 3) {
        window.clearInterval(timer);
        resolve();
      }
    }, 1000 / 24);
  });
  recorder.stop();
  await stopped;
  return URL.createObjectURL(new Blob(chunks, { type: 'video/webm' }));
}

const subscribeToNothing = () => () => {};
const APPEARANCES = ['auto', 'light', 'dark'] as const;

export function PostPreviewGallery() {
  // ?channel=, ?media=, ?at=, ?tz= and ?appearance= pin the sheet for snapshots (scripts/snapshot-post-previews.mjs); ?snapshot hides the controls.
  const [params] = useState(() => new URLSearchParams(typeof window === 'undefined' ? '' : window.location.search));
  const [, setAppearance] = usePreviewSetting('appearance', 'auto', APPEARANCES);
  useEffect(() => {
    const appearance = params.get('appearance');
    if (appearance === 'light' || appearance === 'dark') setAppearance(appearance);
  }, [params, setAppearance]);
  const [choice, setChoice] = useState<MediaChoice>(() => {
    const media = params.get('media');
    return media && media in MEDIA_LABELS ? (media as MediaChoice) : 'one';
  });
  const [withPicture, setWithPicture] = useState(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  useEffect(() => {
    if (choice !== 'video' || videoUrl) return;
    let live = true;
    void recordSampleVideo().then((url) => {
      if (live && url) setVideoUrl(url);
    });
    return () => {
      live = false;
    };
  }, [choice, videoUrl]);
  // Times and zones differ between server and browser, so the sheet renders in the browser only.
  const mounted = useSyncExternalStore(subscribeToNothing, () => true, () => false);
  const preferredZone = useTimeZone();
  if (!mounted) return null;
  const pinnedAt = params.get('at') ? new Date(params.get('at') ?? '') : null;
  const publishAt = pinnedAt && !Number.isNaN(pinnedAt.getTime()) ? pinnedAt : new Date();
  const timeZone = params.get('tz') ?? preferredZone;
  const only = params.get('channel');
  const snapshot = params.has('snapshot');

  return (
    <main className='flex flex-col gap-6 p-6'>
      {snapshot && <style>{'nextjs-portal{display:none!important}'}</style>}
      <header className={snapshot ? 'hidden' : 'flex flex-wrap items-center justify-between gap-4'}>
        <div>
          <h1 className='text-xl font-semibold'>Post preview templates</h1>
          <p className='text-muted-foreground text-sm'>{channels.length} channels · development only</p>
        </div>
        <label className='flex items-center gap-2 text-sm'>
          <input type='checkbox' aria-label='Profile picture' checked={withPicture} onChange={(event) => setWithPicture(event.target.checked)} />
          Profile picture
        </label>
        <div role='radiogroup' aria-label='Media' className='flex gap-1 rounded-lg border p-1 text-sm'>
          {(['none', 'one', 'tall', 'several', 'video'] as MediaChoice[]).map((value) => (
            <button
              key={value}
              type='button'
              role='radio'
              aria-checked={choice === value}
              onClick={() => setChoice(value)}
              className={choice === value ? 'bg-primary text-primary-foreground rounded-md px-3 py-1' : 'rounded-md px-3 py-1'}
            >
              {MEDIA_LABELS[value]}
            </button>
          ))}
        </div>
      </header>
      <div className='grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-x-4 gap-y-8'>
        {channels.filter((channel) => !only || channel.slug === only).map((channel) => {
          const video: PreviewMedia = { id: 'video', kind: 'video', url: videoUrl ?? undefined, alt: 'Piano keys lighting up in turn', width: 360, height: 640, status: videoUrl ? 'ready' : 'loading' };
          const media = choice === 'video' ? [video] : sampleMedia(channel.slug, choice);
          const post: PreviewPost = {
            channel: channel.slug,
            channelName: channel.name,
            account: channel.region === 'global' || !channel.region ? '@yourstudio' : 'Your Studio',
            avatarUrl: withPicture ? SAMPLE_AVATAR : undefined,
            text: sampleText(channel.region),
            media,
            publishAt,
            timeZone
          };
          const check = templateCheck(channel.slug);
          return (
            <section key={channel.slug} className='flex flex-col items-center gap-2'>
              <h2 className='text-sm font-medium'>
                {channel.name} <span className='text-muted-foreground font-normal'>{channel.slug}</span>
              </h2>
              {check && (
                <p className={check.stale ? 'text-destructive text-[11px]' : 'text-muted-foreground text-[11px]'}>
                  Checked {check.label} · {check.confidence} confidence{check.stale ? ' · due for a re-check' : ''}
                </p>
              )}
              <PostPreview post={post} scale={0.52} />
            </section>
          );
        })}
      </div>
    </main>
  );
}
