import assert from 'node:assert/strict';
import test from 'node:test';
import {CHANNEL_ICON_IDS,channelIcons} from '../src/channelIcons.ts';

const expected=[
  'youtube','instagram','facebook','linkedin','x','tiktok','threads','xiaohongshu',
  'douyin','wechat-channels','bilibili','reddit','pinterest','bluesky','telegram',
  'google-business-profile','discord','feishu-lark','weibo','zhihu','tencent-qq',
  'pixelfed','mastodon','snapchat','whatsapp-channels','line-official-account',
  'note-jp','sharechat','moj','kakaotalk-channel','naver-blog','kuaishou','dcard',
];

test('every Studio channel has a local icon definition',()=>{
  assert.deepEqual([...CHANNEL_ICON_IDS].sort(),[...expected].sort());
  for(const id of expected){
    const definition=channelIcons[id];
    assert.match(definition.color,/^#[0-9A-F]{6}$/i,id);
    assert.ok(definition.icon?.path||definition.path||definition.mark,`${id} has no visible mark`);
  }
});
