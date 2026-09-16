import type { ComponentType } from 'react';
import type { TemplateProps } from '../types';

type TemplateModule = { default: ComponentType<TemplateProps> };

/** Channel slug to its template, loaded when a preview first opens. */
export const TEMPLATE_LOADERS: Record<string, () => Promise<TemplateModule>> = {
  generic: () => import('./generic'),
  bilibili: () => import('./bilibili'),
  bluesky: () => import('./bluesky'),
  dcard: () => import('./dcard'),
  discord: () => import('./discord'),
  douyin: () => import('./douyin'),
  facebook: () => import('./facebook'),
  'feishu-lark': () => import('./feishu-lark'),
  'google-business-profile': () => import('./google-business-profile'),
  instagram: () => import('./instagram'),
  'kakaotalk-channel': () => import('./kakaotalk-channel'),
  kuaishou: () => import('./kuaishou'),
  'line-official-account': () => import('./line-official-account'),
  linkedin: () => import('./linkedin'),
  mastodon: () => import('./mastodon'),
  moj: () => import('./moj'),
  'naver-blog': () => import('./naver-blog'),
  'note-jp': () => import('./note-jp'),
  pinterest: () => import('./pinterest'),
  pixelfed: () => import('./pixelfed'),
  reddit: () => import('./reddit'),
  sharechat: () => import('./sharechat'),
  snapchat: () => import('./snapchat'),
  telegram: () => import('./telegram'),
  'tencent-qq': () => import('./tencent-qq'),
  threads: () => import('./threads'),
  tiktok: () => import('./tiktok'),
  'wechat-channels': () => import('./wechat-channels'),
  weibo: () => import('./weibo'),
  'whatsapp-channels': () => import('./whatsapp-channels'),
  x: () => import('./x'),
  xiaohongshu: () => import('./xiaohongshu'),
  youtube: () => import('./youtube'),
  zhihu: () => import('./zhihu')
};
