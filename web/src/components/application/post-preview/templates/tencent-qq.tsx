'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, formatClock, formatTime, MediaFill, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// QQ空间 8.9.8 App Store screenshots (light).
const INK = '#010101';
const TIME = '#999999';
const ICON = '#393939';
const LINK = '#0f2c53';
const YELLOW = '#ffd819';

/** Qzone 说说 in the 好友动态 feed: author with 今天 time, body, edge-to-edge photo or grid, like / comment / share icons. */
export default function TencentQqTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind === 'image');
  const time = formatTime(post, 'zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' lang='zh-CN' label={`QQ空间预览：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='relative flex h-[44px] shrink-0 items-center justify-center border-b border-[#f2f2f3] text-[17px] font-semibold'>
          <AppIcons.back size={26} stroke={2} className='absolute left-2' />
          好友动态
          <AppIcons.search size={23} stroke={2} className='absolute right-4' />
        </header>

        <article className='flex min-h-0 flex-1 flex-col gap-2.5 overflow-hidden pt-3'>
          <div className='flex items-center gap-2.5 px-4'>
            <Monogram name={names.display} size={40} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[16px] font-medium'>{names.display}</p>
              <p className='mt-1 text-[12px]' style={{ color: TIME }}>
                今天{time}
              </p>
            </div>
            <AppIcons.chevronDown size={20} stroke={1.8} color={TIME} />
          </div>
          <div className='px-4'>
            <ClampText lines={6} background='#ffffff' className='text-[16px] leading-[24px]' more={<span style={{ color: LINK }}>展开全文</span>}>
              <RichText text={post.text} accent={LINK} />
            </ClampText>
          </div>
          {media.length === 1 && (
            <MediaFill media={media[0]} className='w-full shrink-0' style={{ height: mediaHeight(media[0], 393, { min: 0.56, max: 1.25, fallback: 1 }) }} />
          )}
          {media.length > 1 && (
            <div className={`grid shrink-0 gap-[3px] px-4 ${media.length === 2 || media.length === 4 ? 'grid-cols-2' : 'grid-cols-3'}`}>
              {media.slice(0, 9).map((item) => (
                <MediaFill key={item.id} media={item} className='aspect-square w-full' />
              ))}
            </div>
          )}
          <div className='flex items-center justify-end gap-6 px-4 pt-1' style={{ color: ICON }}>
            <AppIcons.thumbUp size={21} stroke={1.7} />
            <AppIcons.commentRound size={21} stroke={1.7} />
            <AppIcons.forward size={21} stroke={1.7} />
          </div>
        </article>

        <TabBar background='#ffffff' border='#f2f2f3'>
          <TabItem color={INK} label='动态' icon={<AppIcons.homeFilled size={25} />} />
          <TabItem color={TIME} label='消息' icon={<AppIcons.commentRound size={25} stroke={1.7} />} />
          <span className='mt-[3px] flex size-[36px] items-center justify-center rounded-[10px] text-black' style={{ background: YELLOW }}>
            <AppIcons.plus size={22} stroke={2.6} />
          </span>
          <TabItem color={TIME} label='我的' icon={<AppIcons.user size={25} stroke={1.7} />} />
          <TabItem color={TIME} label='小视频' icon={<AppIcons.video size={25} stroke={1.7} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
