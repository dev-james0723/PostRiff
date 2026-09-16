'use client';

import { AppIcons } from '../app-icons';
import { accountNames, Monogram } from '../parts';
import type { TemplateProps } from '../types';
import { RailItem, VerticalFeed } from './vertical-feed';

// Kuaishou's own preview frame and 应用宝 screenshots (2026).
const PINK = '#fe3666';
const TAB_BAR = '#19181e';
const INACTIVE = '#6f6e74';

/**
 * Kuaishou 精选 (bottom tab): full-screen video with ≡ and 🔍 only, the right column (avatar with the capsule +,
 * like / comment / save / 分享, spinning record), @昵称 with a caption ending in 展开, the 创作的原声 line, and the
 * dark 首页 / 精选 / ⊕ / 消息 / 我 bar.
 */
export default function KuaishouTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);

  return (
    <VerticalFeed
      post={post}
      scale={scale}
      lang='zh-CN'
      label={`快手预览：${names.display}`}
      topLeft={<AppIcons.menu size={24} stroke={2} />}
      tabs={[]}
      topRight={<AppIcons.search size={24} stroke={2.2} />}
      rail={
        <>
          <span className='relative mb-2'>
            <Monogram name={names.display} size={47} style={{ boxShadow: '0 0 0 2px #fff' }} />
            <span className='absolute -bottom-2 left-1/2 flex h-[16px] w-[26px] -translate-x-1/2 items-center justify-center rounded-full text-white' style={{ background: PINK }}>
              <AppIcons.plus size={12} stroke={3.2} />
            </span>
          </span>
          <RailItem icon={<AppIcons.heart size={33} stroke={2} />} />
          <RailItem icon={<AppIcons.commentRound size={32} stroke={2} />} />
          <RailItem icon={<AppIcons.star size={32} stroke={2} />} />
          <RailItem icon={<AppIcons.forward size={32} stroke={2} />} label='分享' />
          <span className='mt-1 flex size-[42px] items-center justify-center rounded-full bg-[#222] ring-[7px] ring-[#161616]'>
            <Monogram name={names.display} size={20} />
          </span>
        </>
      }
      creator={<p className='text-[16px] font-bold'>@{names.display}</p>}
      moreLabel='展开'
      footnote={
        <>
          <AppIcons.music size={15} stroke={2} />
          <span className='truncate'>@{names.display} 创作的原声 -</span>
        </>
      }
      missingMedia='快手作品需要视频或图片。'
      progressColor={PINK}
      tabBarBackground={TAB_BAR}
      tabBar={
        <>
          <span className='pt-2 text-[16px] font-medium' style={{ color: INACTIVE }}>
            首页
          </span>
          <span className='pt-2 text-[16px] font-semibold text-white'>精选</span>
          <span className='mt-[4px] flex size-[34px] items-center justify-center rounded-full border-2 border-white text-white'>
            <AppIcons.plus size={18} stroke={2.8} />
          </span>
          <span className='pt-2 text-[16px] font-medium' style={{ color: INACTIVE }}>
            消息
          </span>
          <span className='pt-2 text-[16px] font-medium' style={{ color: INACTIVE }}>
            我
          </span>
        </>
      }
    />
  );
}
