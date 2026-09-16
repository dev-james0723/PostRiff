'use client';

import { AppIcons } from '../app-icons';
import { accountNames, Monogram } from '../parts';
import type { TemplateProps } from '../types';
import { RailItem, VerticalFeed } from './vertical-feed';

// Douyin 40.4 App Store screenshots and the creator centre's preview frame.
const RED = '#fe2c55';
const TAB_BAR = '#161616';
const INACTIVE = '#888888';

/**
 * Douyin 首页 › 推荐: scrolling top tabs ending in 推荐 with its ⇌ mark, the right column (avatar with red +,
 * 赞 / 抢首评 / 收藏 / 分享, spinning record), @昵称 and a two-line caption with 展开, and the black tab bar with the
 * white-outlined +.
 */
export default function DouyinTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);

  return (
    <VerticalFeed
      post={post}
      scale={scale}
      lang='zh-CN'
      label={`抖音预览：${names.display}`}
      topLeft={<AppIcons.menu size={24} stroke={2} />}
      tabs={[{ label: '精选' }, { label: '团购' }, { label: '关注' }, { label: '经验' }, { label: '推荐', active: true }]}
      activeMark='⇌'
      topRight={<AppIcons.search size={24} stroke={2.2} />}
      rail={
        <>
          <span className='relative mb-2'>
            <Monogram name={names.display} size={48} style={{ boxShadow: '0 0 0 2px #fff' }} />
            <span className='absolute -bottom-2.5 left-1/2 flex size-[20px] -translate-x-1/2 items-center justify-center rounded-full' style={{ background: RED }}>
              <AppIcons.plus size={14} stroke={3} />
            </span>
          </span>
          <RailItem icon={<AppIcons.heartFilled size={34} />} label='赞' />
          <RailItem icon={<AppIcons.commentRound size={32} stroke={1.8} className='-scale-x-100' />} label='抢首评' />
          <RailItem icon={<AppIcons.starFilled size={32} />} label='收藏' />
          <RailItem icon={<AppIcons.forward size={32} stroke={2} />} label='分享' />
          <span className='mt-1 flex size-[44px] items-center justify-center rounded-full bg-[#222] ring-[8px] ring-[#161616]'>
            <Monogram name={names.display} size={20} />
          </span>
        </>
      }
      creator={<p className='text-[17px] font-semibold'>@{names.display}</p>}
      moreLabel='展开'
      footnote={
        <>
          <AppIcons.music size={15} stroke={2} />
          <span className='truncate'>@{names.display}创作的原声</span>
        </>
      }
      missingMedia='抖音需要视频或图文。'
      tabBarBackground={TAB_BAR}
      tabBar={
        <>
          <span className='pt-2 text-[17px] font-bold text-white'>首页</span>
          <span className='pt-2 text-[17px] font-medium' style={{ color: INACTIVE }}>
            朋友
          </span>
          <span className='mt-[6px] flex h-[30px] w-[42px] items-center justify-center rounded-[9px] border-2 border-white text-white'>
            <AppIcons.plus size={18} stroke={3} />
          </span>
          <span className='pt-2 text-[17px] font-medium' style={{ color: INACTIVE }}>
            消息
          </span>
          <span className='pt-2 text-[17px] font-medium' style={{ color: INACTIVE }}>
            我
          </span>
        </>
      }
    />
  );
}
