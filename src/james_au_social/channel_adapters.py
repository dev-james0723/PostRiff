"""Explicit native-format draft mappings. No network or publishing transport.

Profiles encode the V14 content contract, NOT current platform API capability.
Only reviewed authored input is packaged. A manual handoff still needs human
review of platform rules, rights, media and exact destination before posting.
"""
from .execution import payload_hash
from urllib.parse import urlsplit

# channel: (language guidance, formats: required media, native fields)
PROFILES = {
 'dcard':('zh-Hant',{"dcard.post":["optional",["board_ref","title","rules_ref","identity_mode","affiliation_disclosure"]]}),
 'kuaishou':('zh-Hans',{"kuaishou.video":["video",["creator_ref","cover_ref","sound_rights"]]}),
 'naver-blog':('ko',{"naver-blog.article":["optional",["blog_ref","title","category"]]}),
 'kakaotalk-channel':('ko',{"kakaotalk-channel.message":["optional",["business_channel_ref","sender_profile_ref","template_ref","consented_audience_ref"]]}),
 'moj':('hi',{"moj.video":["video",["region","language_review_ref","sound_rights","cover_ref"]]}),
 'sharechat':('hi',{"sharechat.post":["optional",["region","language_review_ref"]]}),
 'note-jp':('ja',{"note.article":["optional",["title","monetization_state"]]}),
 'line-official-account':('ja',{"line-official-account.broadcast":["optional",["official_account_ref","consented_audience_ref","quota_ref"]]}),
 'whatsapp-channels':('en',{"whatsapp-channels.update":["optional",["channel_ref"]]}),
 'snapchat':('en',{"snapchat.story":["video",["public_profile_ref","sound_rights"]],"snapchat.spotlight":["video",["public_profile_ref","sound_rights"]]}),
 'mastodon':('en',{"mastodon.status":["optional",["instance_ref","visibility","content_warning"]],"mastodon.poll":["optional",["instance_ref","visibility","question","options"]]}),
 'pixelfed':('en',{"pixelfed.photo":["image",["instance_ref","visibility"]],"pixelfed.album":["image",["instance_ref","visibility"]],"pixelfed.video":["video",["instance_ref","visibility"]]}),
 'tencent-qq':('zh-Hans',{"qq.community_message":["optional",["group_ref","bot_ref","allowed_mentions"]],"qzone.post":["optional",["profile_ref"]]}),
 'zhihu':('zh-Hans',{"zhihu.answer":["optional",["question_ref","promotion_disclosure"]],"zhihu.article":["optional",["title"]],"zhihu.idea":["optional",[]]}),
 'weibo':('zh-Hans',{"weibo.post":["optional",[]],"weibo.video":["video",["title"]]}),
 'feishu-lark':('zh-Hans',{"feishu-lark.message":["optional",["region","tenant_ref","chat_ref","message_type"]]}),
 'discord':('en',{"discord.message":["optional",["guild_ref","channel_ref","allowed_mentions"]],"discord.forum_post":["optional",["guild_ref","channel_ref","title","allowed_mentions"]]}),
 'google-business-profile':('en',{"google-business-profile.update":["optional",["location_ref","cta"]],"google-business-profile.event":["optional",["location_ref","title","start","end"]],"google-business-profile.offer":["optional",["location_ref","title","start","end","terms"]]}),
 'telegram':('en',{"telegram.message":["optional",["chat_ref","parse_mode","notification_mode"]],"telegram.poll":["optional",["chat_ref","question","options"]]}),
 'bluesky':('en',{"bluesky.post":["optional",["did","pds","facets"]]}),
 'pinterest':('en',{"pinterest.pin":["image",["title","board_ref","destination_url"]]}),
 'reddit':('en',{"reddit.post":["optional",["subreddit","title","rules_ref","flair","promotion_disclosure"]]}),
 'bilibili':('zh-Hans',{"bilibili.video":["video",["title","description","cover_ref","category"]]}),
 'wechat-channels':('zh-Hans',{"wechat-channels.video":["video",["cover_ref","title"]]}),
 'douyin':('zh-Hans',{"douyin.video":["video",["cover_ref","sound_rights"]]}),
 'xiaohongshu':('zh-Hans',{"xiaohongshu.note":["image",["title","originality"]],"xiaohongshu.video":["video",["title","originality"]]}),
 'threads':('en',{"threads.post":["optional",[]],"threads.reply":["optional",["parent_ref"]]}),
 'tiktok':('en',{"tiktok.video":["video",["cover_ref","sound_rights"]]}),
 'x':('en',{"x.post":["optional",[]],"x.thread":["optional",["sequence"]]}),
 'linkedin':('en',{"linkedin.post":["optional",[]],"linkedin.document":["document",["title"]]}),
 'facebook':('en',{"facebook.page_post":["optional",["page_ref"]],"facebook.story":["image",["page_ref"]],"facebook.reel":["video",["page_ref"]]}),
 'instagram':('en',{"instagram.post":["image",[]],"instagram.carousel":["image",[]],"instagram.story":["image",[]],"instagram.reel":["video",[]]}),
 'youtube':('en',{'youtube.video':('video',['title','description']), 'youtube.short':('video',['title']), 'youtube.community_post':('optional',[])}),
}

DESTINATION_FIELDS={'facebook':'page_ref','reddit':'subreddit','pinterest':'board_ref',
    'telegram':'chat_ref','google-business-profile':'location_ref','discord':'channel_ref',
    'feishu-lark':'chat_ref','whatsapp-channels':'channel_ref','line-official-account':'official_account_ref',
    'kakaotalk-channel':'business_channel_ref','naver-blog':'blog_ref','dcard':'board_ref'}

def draft_handoff(draft):
    required={'channel','native_format_id','account_ref','destination_ref','language','copy','media','fields','audience'}
    if set(draft)!=required or any(not isinstance(draft[k],str) or not draft[k].strip() for k in required-{'media','fields'}):
        raise ValueError('exact_draft_fields_required')
    if draft['channel'] not in PROFILES:
        raise ValueError('unsupported_channel')
    _,formats=PROFILES[draft['channel']]
    if draft['native_format_id'] not in formats:
        raise ValueError('unsupported_native_format')
    if draft['channel'] in {'discord','tencent-qq'} and any(x in draft['copy'] for x in ('@everyone','@here','<@&')):
        raise ValueError('mass_mention_requires_separate_approval_workflow')
    kind,fields=formats[draft['native_format_id']]
    if not isinstance(draft['fields'],dict) or any(not draft['fields'].get(k) for k in fields):
        raise ValueError('native_fields_missing')
    if set(draft['fields'])-set(fields):
        raise ValueError('unreviewed_native_fields')
    destination_field=DESTINATION_FIELDS.get(draft['channel'])
    if draft['native_format_id'] in {'qq.community_message','qzone.post','zhihu.answer'}:
        destination_field={'qq.community_message':'group_ref','qzone.post':'profile_ref','zhihu.answer':'question_ref'}[draft['native_format_id']]
    if destination_field and draft['fields'][destination_field]!=draft['destination_ref']:
        raise ValueError('native_destination_mismatch')
    if draft['channel']=='pinterest':
        url=urlsplit(draft['fields']['destination_url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password:
            raise ValueError('https_destination_required')
    if not isinstance(draft['media'],list):
        raise ValueError('ordered_media_required')
    if kind!='optional' and (not draft['media'] or any(m.get('kind')!=kind for m in draft['media'])):
        raise ValueError('native_media_required')
    for media in draft['media']:
        if set(media)!={'asset_ref','sha256','kind','alt_text'} or not all(media.values()):
            raise ValueError('media_binding_required')
    body={'channel':draft['channel'],'native_format_id':draft['native_format_id'],
          'account_ref':draft['account_ref'],'destination_ref':draft['destination_ref'],
          'copy':draft['copy'],'language':draft['language'],'ordered_media':draft['media'],
          'native_fields':draft['fields'],'audience':draft['audience'],
          'state':'manual_handoff_ready','route':'draft_only','route_driver':'none',
          'publish_authorized':False,'platform_constraints_checked':False,
          'required_review':['current_native_format_rules','exact_account_destination','source_and_rights',
                             'native_language_review','preview_and_exact_approval'],
          'remote_operations':[]}
    return {**body,'handoff_hash':payload_hash(body)}


def campaign_handoff(drafts):
    if not isinstance(drafts,list) or not drafts:
        raise ValueError('draft_list_required')
    targets=[]
    seen=set()
    for index,draft in enumerate(drafts):
        try:
            identity=tuple(draft[k] for k in ('channel','native_format_id','account_ref','destination_ref'))
            if identity in seen:
                raise ValueError('duplicate_target')
            seen.add(identity)
            targets.append(draft_handoff(draft))
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            # Preserve only local validation reason codes, never arbitrary
            # provider exceptions, draft text, credential or browser data.
            reason=str(exc) if type(exc) is ValueError else 'malformed_draft'
            targets.append({'index':index,'state':'blocked','reason':reason})
    ready=sum(t['state']=='manual_handoff_ready' for t in targets)
    return {'state':'handoff_ready' if ready==len(targets) else 'partial_handoff' if ready else 'blocked',
            'targets':targets,'published':False,'remote_operations':[]}
