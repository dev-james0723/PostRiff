import {createElement, type CSSProperties} from 'react';
import {
  siBilibili, siBluesky, siDiscord, siFacebook, siGoogle, siInstagram,
  siKakaotalk, siKuaishou, siLine, siMastodon, siNaver, siNote,
  siPinterest, siPixelfed, siQq, siReddit, siSinaweibo, siSnapchat,
  siTelegram, siThreads, siTiktok, siWhatsapp, siWechat, siX,
  siXiaohongshu, siYoutube, siZhihu,
} from 'simple-icons';

type BrandIcon = {path:string; hex:string; title:string};
type IconDefinition = {icon?:BrandIcon; path?:string; mark?:string; color:string; background?:string};

const linkedinPath='M20.45 20.45h-3.56v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.34V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.32 7.43a2.07 2.07 0 1 1 0-4.14 2.07 2.07 0 0 1 0 4.14zM7.1 20.45H3.54V9H7.1v11.45z';
const sharePath='M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.03-.47-.09-.7l7.05-4.11A2.99 2.99 0 1 0 15 5c0 .24.03.47.09.7L8.04 9.81A3 3 0 1 0 8.04 14l7.12 4.16c-.04.2-.07.41-.07.63A2.91 2.91 0 1 0 18 16.08z';
const brand=(icon:BrandIcon,background?:string):IconDefinition=>({icon,color:`#${icon.hex}`,background});

export const channelIcons:Record<string,IconDefinition>={
  youtube:brand(siYoutube),instagram:brand(siInstagram),facebook:brand(siFacebook),
  linkedin:{path:linkedinPath,color:'#0A66C2'},x:brand(siX),tiktok:brand(siTiktok),
  threads:brand(siThreads),xiaohongshu:brand(siXiaohongshu),douyin:brand(siTiktok),
  'wechat-channels':brand(siWechat),bilibili:brand(siBilibili),reddit:brand(siReddit),
  pinterest:brand(siPinterest),bluesky:brand(siBluesky),telegram:brand(siTelegram),
  'google-business-profile':brand(siGoogle),discord:brand(siDiscord),
  'feishu-lark':{mark:'✦',color:'#3370FF'},weibo:brand(siSinaweibo),zhihu:brand(siZhihu),
  'tencent-qq':brand(siQq),pixelfed:brand(siPixelfed),mastodon:brand(siMastodon),
  snapchat:brand(siSnapchat,'#FFFC00'),'whatsapp-channels':brand(siWhatsapp),
  'line-official-account':brand(siLine),'note-jp':brand(siNote),
  sharechat:{path:sharePath,color:'#EF4136'},moj:{mark:'M',color:'#111111',background:'#FFD800'},
  'kakaotalk-channel':brand(siKakaotalk,'#FFCD00'),'naver-blog':brand(siNaver),
  kuaishou:brand(siKuaishou),dcard:{mark:'D',color:'#006AA6'},
};

export const CHANNEL_ICON_IDS=Object.freeze(Object.keys(channelIcons));

export function ChannelIcon({id,name}:{id:string;name:string}) {
  const definition=channelIcons[id]||{mark:name.slice(0,1),color:'#5d6951'};
  const foreground=definition.background?'#171717':definition.color;
  const style={
    '--channel-icon-color':foreground,
    '--channel-icon-background':definition.background||`${definition.color}12`,
    '--channel-icon-border':definition.background||`${definition.color}30`,
  } as CSSProperties;
  const graphic=definition.icon||definition.path
    ? createElement('svg',{viewBox:'0 0 24 24',focusable:false,'aria-hidden':true},
        createElement('path',{d:definition.icon?.path||definition.path,fill:'currentColor'}))
    : createElement('span',{className:'channel-icon-mark','aria-hidden':true},definition.mark);
  return createElement('span',{className:'channel-icon',style,'aria-hidden':true},graphic);
}
