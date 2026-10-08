"""Allowlisted native-action contracts; no arbitrary provider proxy or implicit effects."""
import re
from postriff_alpha.domain import AlphaError

PROVIDER_ACTIONS = {
    'linkedin': {'delete','edit','reply','react','remove_reaction','comment_edit','delete_comment'},
    'threads': {'delete','hide','unhide','repost'},
    'instagram': {'reply','hide','unhide','delete_comment'},
    'facebook': {'reply','hide','unhide','delete','delete_comment','edit'},
    'x': {'delete','edit','reply','quote','repost','article_draft','article_publish'},
    'youtube': {'delete','reply','comment','comment_edit','delete_comment','moderate','playlist_create','playlist_edit','playlist_delete','playlist_item','playlist_item_delete','playlist_image','video_edit','thumbnail','caption_upload','caption_update','caption_delete','reporting_create','reporting_delete','live_broadcast_create','live_broadcast_delete','live_stream_create','live_stream_delete','live_bind','live_transition','live_chat_send','live_chat_delete','live_chat_ban','live_chat_unban'},
    'pinterest': {'delete','edit','board_create','board_edit','board_delete','section_create','section_edit','section_delete','product_tag','feed_create','feed_edit','feed_delete','feed_ingest','product_group_create','product_group_edit','product_group_delete'},
    'tiktok': {'cancel_transfer'},
}

RESOURCE_PARTS = {
    'playlist_create': {'snippet': {'title','description','defaultLanguage'}, 'status': {'privacyStatus','podcastStatus'}, 'localizations': None},
    'playlist_edit': {'snippet': {'title','description','defaultLanguage'}, 'status': {'privacyStatus','podcastStatus'}, 'localizations': None},
    'video_edit': {'snippet': {'title','description','categoryId','tags','defaultLanguage','defaultAudioLanguage'}, 'status': {'privacyStatus','publishAt','embeddable','license','publicStatsViewable','selfDeclaredMadeForKids','containsSyntheticMedia'}, 'localizations': None},
    'live_broadcast_create': {'snippet': {'title','description','scheduledStartTime','scheduledEndTime'}, 'status': {'privacyStatus','selfDeclaredMadeForKids'}, 'contentDetails': {'enableAutoStart','enableAutoStop','enableDvr','enableEmbed','recordFromStart','enableClosedCaptions','latencyPreference','monitorStream'}},
    'live_stream_create': {'snippet': {'title','description'}, 'cdn': {'format','ingestionType','resolution','frameRate'}, 'contentDetails': {'isReusable'}},
    'live_chat_ban': {'snippet': {'liveChatId','type','banDurationSeconds','bannedUserDetails'}},
}


def validate(provider, action, payload):
    if action not in PROVIDER_ACTIONS.get(provider, set()):
        raise AlphaError('This provider action is unavailable. Threads replies use the approved publishing lifecycle.', 409)
    if action in ('reply','quote','comment','edit','comment_edit','live_chat_send') and provider != 'pinterest':
        limit = 280 if provider == 'x' else 5000 if provider == 'youtube' else 3000
        if not isinstance(payload.get('text'), str) or not 1 <= len(payload['text']) <= limit: raise AlphaError('Review valid action text within the provider limit.',400)
    if provider == 'linkedin':
        if action == 'reply' and not re.fullmatch(r'urn:li:(share|ugcPost|activity):\d+', str(payload.get('rootPostUrn',''))): raise AlphaError('Preserve the root post URN for the reply.',400)
        if action in ('comment_edit','delete_comment') and not re.fullmatch(r'\d+', str(payload.get('commentId',''))): raise AlphaError('Choose the exact comment ID and its parent post URN.',400)
        if action == 'react' and payload.get('reactionType') not in ('LIKE','PRAISE','EMPATHY','INTEREST','APPRECIATION','ENTERTAINMENT'): raise AlphaError('Choose a supported LinkedIn reaction.',400)
    if provider == 'x' and action == 'article_draft':
        state = payload.get('content_state')
        if not isinstance(payload.get('title'), str) or not 1 <= len(payload['title']) <= 200 or not isinstance(state, dict) or set(state) != {'blocks','entities'} or not isinstance(state['blocks'],list) or not 1 <= len(state['blocks']) <= 500 or not isinstance(state['entities'],list) or len(state['entities']) > 1000: raise AlphaError('Review the title and official Article blocks/entities content_state.',400)
        for entity in state['entities']:
            if not isinstance(entity,dict) or set(entity) != {'key','value'} or not isinstance(entity['key'],str) or not isinstance(entity['value'],dict): raise AlphaError('Review official Article entities.',400)
        if len({e['key'] for e in state['entities']}) != len(state['entities']): raise AlphaError('Article entity keys must be unique.',400)
        for block in state['blocks']:
            if not isinstance(block,dict) or set(block)-{'text','type','key','data','entity_ranges','inline_style_ranges'} or not isinstance(block.get('text'),str) or block.get('type') not in ('unstyled','header-one','header-two','header-three','unordered-list-item','ordered-list-item','blockquote','atomic'): raise AlphaError('Review supported official Article blocks.',400)
            for field in ('entity_ranges','inline_style_ranges'):
                ranges=block.get(field,[])
                if not isinstance(ranges,list) or len(ranges)>1000: raise AlphaError('Review Article formatting ranges.',400)
                for item in ranges:
                    keys={'key','offset','length'} if field=='entity_ranges' else {'style','offset','length'}
                    if not isinstance(item,dict) or set(item)!=keys or type(item.get('offset')) is not int or type(item.get('length')) is not int or not 0 <= item['offset'] <= item['offset']+item['length'] <= len(block['text'].encode('utf-16-le'))//2: raise AlphaError('Review valid Article formatting offsets.',400)
                    if field=='entity_ranges' and (type(item['key']) is not int or str(item['key']) not in {e['key'] for e in state['entities']}): raise AlphaError('Preserve referenced Article entity keys.',400)
                    if field=='inline_style_ranges' and item['style'] not in ('bold','italic','strikethrough'): raise AlphaError('Choose supported Article styles.',400)
        if 'cover_media' in payload:
            cover=payload['cover_media']
            if not isinstance(cover,dict) or set(cover)!={'media_category','media_id'} or cover['media_category']!='tweet_image' or not re.fullmatch(r'\d+',str(cover['media_id'])): raise AlphaError('Review an uploaded Article cover media ID.',400)
    if provider == 'youtube':
        if action in RESOURCE_PARTS:
            resource = payload.get('resource');parts = RESOURCE_PARTS[action]
            if not isinstance(resource,dict) or set(resource)-set(parts) or not resource: raise AlphaError('Review an allowlisted YouTube resource.',400)
            for part, fields in parts.items():
                if part not in resource: continue
                if not isinstance(resource[part],dict) or (fields is not None and set(resource[part])-fields): raise AlphaError('Unsupported YouTube resource field.',400)
            if action in ('playlist_create','playlist_edit','video_edit','live_broadcast_create','live_stream_create') and not isinstance(resource.get('snippet',{}).get('title'),str): raise AlphaError('Supply the complete reviewed title and metadata.',400)
        if action == 'moderate' and payload.get('moderationStatus') not in ('published','heldForReview','rejected'): raise AlphaError('Choose a moderation status.',400)
        if action == 'live_transition' and payload.get('broadcastStatus') not in ('testing','live','complete'): raise AlphaError('Choose a documented live transition.',400)
        if action in ('caption_upload','caption_update'):
            caption = payload.get('caption')
            if not isinstance(caption,str) or not 1 <= len(caption.encode()) <= 100_000 or not (caption.startswith('WEBVTT') or re.search(r'\d{2}:\d{2}:\d{2}[,.]\d{3} -->',caption)): raise AlphaError('Supply reviewed SRT or WebVTT captions up to 100 kB.',400)
            if action == 'caption_upload' and not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*',str(payload.get('language',''))): raise AlphaError('Choose a caption language.',400)
            if 'isDraft' in payload and type(payload['isDraft']) is not bool: raise AlphaError('Choose caption draft status.',400)
        if action == 'reporting_create' and not all(isinstance(payload.get(k),str) and 1 <= len(payload[k]) <= 100 for k in ('reportTypeId','name')): raise AlphaError('Choose a report type and job name.',400)
    if provider == 'pinterest':
        if action.startswith('feed_') and action in ('feed_create','feed_edit'):
            from .social_formats import web_url
            if payload.get('catalog_type') != 'RETAIL': raise AlphaError('This commerce flow supports a separately enabled RETAIL merchant feed.',400)
            if action == 'feed_create' and not all(payload.get(k) for k in ('name','location','format','default_country','default_locale')): raise AlphaError('Review all required retail feed fields.',400)
            if 'location' in payload: web_url(payload['location'])
            if 'format' in payload and payload['format'] not in ('CSV','TSV','XML','INTEGRATION'): raise AlphaError('Choose a documented feed format.',400)
            if 'name' in payload and (not isinstance(payload['name'],str) or not 1 <= len(payload['name']) <= 200): raise AlphaError('Choose a feed name.',400)
            if 'default_country' in payload and not re.fullmatch(r'[A-Z]{2}',str(payload['default_country'])): raise AlphaError('Choose an ISO country.',400)
            if 'default_locale' in payload and not re.fullmatch(r'[a-z]{2}[-_][A-Z]{2}',str(payload['default_locale'])): raise AlphaError('Choose a catalog locale.',400)
            if 'status' in payload and payload['status'] not in ('ACTIVE','INACTIVE'): raise AlphaError('Choose a feed status.',400)
        if action.startswith('product_group_') and not action.endswith('delete'):
            if 'name' in payload and (not isinstance(payload['name'],str) or not 1 <= len(payload['name']) <= 200): raise AlphaError('Choose a product group name.',400)
            if action == 'product_group_create' and (not payload.get('name') or not re.fullmatch(r'\d+',str(payload.get('feed_id',''))) or 'filters' not in payload): raise AlphaError('Review the feed, name and filters.',400)
            if 'filters' in payload:
                filters=payload['filters']
                if not isinstance(filters,dict) or set(filters) not in ({'all_of'},{'any_of'}): raise AlphaError('Use a documented all_of or any_of filter.',400)
                items=next(iter(filters.values()))
                if not isinstance(items,list) or not 1 <= len(items) <= 20: raise AlphaError('Review 1–20 product group filters.',400)
                for item in items:
                    if not isinstance(item,dict) or len(item) != 1 or next(iter(item)) not in ('BRAND','ITEM_ID','ITEM_GROUP_ID','CUSTOM_LABEL_0','CUSTOM_LABEL_1','CUSTOM_LABEL_2','CUSTOM_LABEL_3','CUSTOM_LABEL_4'): raise AlphaError('Choose an implemented string product filter.',400)
                    criteria=next(iter(item.values()))
                    if not isinstance(criteria,dict) or set(criteria)-{'values','negated'} or not isinstance(criteria.get('values'),list) or not 1 <= len(criteria['values']) <= 100 or any(not isinstance(v,str) or not 1 <= len(v) <= 300 for v in criteria['values']) or ('negated' in criteria and type(criteria['negated']) is not bool): raise AlphaError('Review string filter values and optional negation.',400)
        if action.startswith(('board_','section_')) and not action.endswith('delete') and (not isinstance(payload.get('name'),str) or not 1 <= len(payload['name']) <= 180): raise AlphaError('Choose a board/section name.',400)
        if action in ('section_edit','section_delete') and not re.fullmatch(r'\d{1,30}',str(payload.get('boardId',''))): raise AlphaError('Preserve the section’s parent board ID.',400)
        if action == 'product_tag':
            tags = payload.get('product_tags')
            if not isinstance(tags,list) or not 1 <= len(tags) <= 24 or any(not isinstance(t,dict) or set(t) != {'pin_id'} or not re.fullmatch(r'\d+',str(t['pin_id'])) for t in tags) or len({t['pin_id'] for t in tags}) != len(tags): raise AlphaError('Review 1–24 unique eligible product Pin IDs.',400)
    return payload
