"""Permissioned official reads and reviewable native actions for the eight providers.

Only fixed endpoints and allowlisted operations are available. No browser fallback,
arbitrary proxy, invented analytics or implicit messaging/commerce authorization.
"""
import copy
import hashlib
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import quote, urlencode, urlsplit
from postriff_alpha.domain import AlphaError, uid
from .contracts import digest
from .official_social import THREADS_VERSION

MANAGE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"

READ_FEATURES = {
    "linkedin": {"historical_content_read", "comments_read", "reactions", "organization_reactions", "analytics", "organization_analytics", 'organization_follower_analytics', 'organization_page_analytics', 'video_analytics', "organization_posts_read", "organization_comments_read"},
    "threads": {"post_read", 'owned_posts', "replies_read", "conversation", "insights", "account_insights", "quota", "mentions"},
    "instagram": {"media_read", "comments_read", "comment_replies", "insights", "account_insights", "quota"},
    "facebook": {"post_read", "comments", "comment_replies", "reactions", "insights", "page_roles"},
    "x": {"post_read", "conversation_read", "analytics"},
    "youtube": {"media_read", "comments_read", "comment_replies", "analytics", "monetary_analytics", "reporting", "reporting_types", "reporting_reports", "reporting_download", "live_broadcast", "live_stream", "live_chat", "memberships", "membership_levels", "playlists", "playlist_images", "captions"},
    "tiktok": {"media_read", "creator_info", "processing"},
    "pinterest": {"boards", "sections", "pin_read", "analytics", "account_analytics", "video_analytics", "trends", 'audience_insights', 'catalogs', 'product_groups', 'product_tags', 'feeds', 'feed', 'feed_ingestions'},
}


def _identifier(value):
    # Quotes applied by each builder; delimiters/query injection cannot enter a URL.
    if not isinstance(value, str) or not 1 <= len(value) <= 500 or any(ord(c) < 32 for c in value) or any(c in value for c in "?/\\#&="):
        raise AlphaError("Use a valid provider identifier.", 400)
    return quote(value, safe="")


def _options(options, allowed):
    if not isinstance(options, dict) or set(options)-set(allowed): raise AlphaError("Unsupported provider parameters.", 400)
    if len(json.dumps(options).encode()) > 128000: raise AlphaError("Provider parameters are too large.", 400)
    return copy.deepcopy(options)


def _dates(params):
    result = {}
    for key in ('startDate','endDate'):
        if key in params:
            try: result[key] = date.fromisoformat(params[key])
            except (ValueError,TypeError): raise AlphaError('Use valid ISO reporting dates.',400)
    if len(result) == 2 and result['endDate'] < result['startDate']: raise AlphaError('Reporting end precedes its start.',400)
    return result


class OfficialAPI:
    def __init__(self, adapter, grant):
        self.adapter, self.grant, self.provider = adapter, grant, adapter.id
        self.token = grant["accessToken"]

    def require(self, scopes):
        if not set(scopes).issubset(self.grant.get("scopes") or []):
            raise AlphaError("Enable this feature and grant its permissions first.", 409, code="social_scope_missing")

    def meta(self, method, target, edge="", params=None):
        from .providers import GRAPH_VERSION
        instagram = self.provider == "instagram"
        base = "https://graph.instagram.com/" + GRAPH_VERSION if instagram else "https://graph.threads.net/" + THREADS_VERSION
        address = base + "/" + _identifier(target) + ("/"+edge if edge else "")
        data = {**(params or {}), "access_token": self.token}
        return self.adapter.transport(method, address+"?"+urlencode(data)) if method in ("GET", "DELETE") else self.adapter.transport(method, address, form=data)

    def read(self, feature, target, options=None):
        if feature not in READ_FEATURES.get(self.provider, set()): raise AlphaError("This official read is not implemented.", 409)
        if self.provider == 'instagram' and feature in ('insights','account_insights'):
            from .official_social import CATALOG
            if CATALOG['instagram']['insights'].support != 'documented': raise AlphaError('Official Instagram Login Insights audit is unavailable; do not request an unverified permission.',409)
        params = _options(options or {}, ("after", "pageToken", "bookmark", "since", "until", "startDate", "endDate", "metric", "period", "queryType", "aggregation", "region", "trendType", "metrics", "dimensions", "filters", 'organizationUrn', 'reportId'))
        dates = _dates(params)
        if self.provider in ('threads','instagram','facebook'):
            for source, destination in (('startDate','since'),('endDate','until')):
                if source in dates: params[destination] = int(datetime.combine(dates[source],datetime.min.time(),timezone.utc).timestamp());params.pop(source)
        if self.provider == 'x' and not target: self._x_budget()
        target = target or self.adapter.identity(self.token)["providerAccountId"]
        encoded = _identifier(target)
        pid = self.provider
        if pid == "linkedin":
            scopes = {"historical_content_read": ["r_member_social"], "comments_read": ["r_member_social_feed"], "reactions": ["r_member_social_feed"],
                      "analytics": ["r_member_postAnalytics"], "organization_analytics": ["rw_organization_admin"], 'organization_follower_analytics':['rw_organization_admin'], 'organization_page_analytics':['rw_organization_admin'], 'video_analytics':['r_organization_social'],
                      "organization_posts_read": ["r_organization_admin", "r_organization_social"], "organization_comments_read": ["r_organization_admin", "r_organization_social_feed"], "organization_reactions": ["r_organization_admin", "r_organization_social_feed"]}[feature]
            self.require(scopes)
            if feature in ('organization_analytics','organization_follower_analytics','organization_page_analytics'):
                org = target
                action = 'SHARE_ANALYTICS' if feature == 'organization_analytics' else 'FOLLOWER_ANALYTICS' if feature == 'organization_follower_analytics' else 'PAGE_ANALYTICS'
                if not self.adapter.organization_authorized(self.token,self.adapter.identity(self.token)['providerAccountId'],org,action): raise AlphaError('The current organization does not authorize this analytics action.',409)
            if feature in ('video_analytics','organization_posts_read','organization_comments_read','organization_reactions'):
                self.require(['r_organization_admin'])
                org = target if feature == 'organization_posts_read' else params.get('organizationUrn')
                if not self.adapter.organization_feed_authorized(self.token,self.adapter.identity(self.token)['providerAccountId'],org): raise AlphaError('The current organization role does not authorize this read.',409)
            if feature == "historical_content_read" and not self.adapter.history_approved:
                raise AlphaError("BLOCKED — LINKEDIN APPROVAL: restricted historical member-content access.", 409)
            if feature.endswith("posts_read") or feature == "historical_content_read":
                path = "/posts?"+urlencode({"q": "author", "author": target, "count": 50})
            elif feature in ("comments_read", "organization_comments_read"):
                path = "/socialActions/"+encoded+"/comments?count=50"
            elif feature in ("reactions", "organization_reactions"): path = "/socialMetadata/"+encoded
            elif feature == "analytics":
                query_type = params.get("queryType", "IMPRESSION")
                if query_type not in ("IMPRESSION", "MEMBERS_REACHED", "RESHARE", "REACTION", "COMMENT", "POST_SAVE", "POST_SEND", "LINK_CLICKS", "PREMIUM_CTA_CLICKS", "FOLLOWER_GAINED_FROM_CONTENT", "PROFILE_VIEW_FROM_CONTENT"):
                    raise AlphaError("Choose a documented LinkedIn metric.", 400)
                aggregation = params.get('aggregation','TOTAL')
                if aggregation not in ('TOTAL','DAILY') or (aggregation == 'DAILY' and query_type in ('MEMBERS_REACHED','LINK_CLICKS','FOLLOWER_GAINED_FROM_CONTENT','PROFILE_VIEW_FROM_CONTENT','IMPRESSION')):
                    raise AlphaError('This LinkedIn metric does not permit the requested aggregation.',400)
                kind = 'ugc' if target.startswith('urn:li:ugcPost:') else 'share' if target.startswith('urn:li:share:') else None
                if not kind: raise AlphaError('Member post analytics requires a share or ugcPost URN.',400)
                path = '/memberCreatorPostAnalytics?q=entity&entity=('+kind+':'+encoded+')&'+urlencode({'queryType':query_type,'aggregation':aggregation})
                if dates:
                    parts = [name+':(day:'+str(d.day)+',month:'+str(d.month)+',year:'+str(d.year)+')' for key,name in (('startDate','start'),('endDate','end')) if (d := dates.get(key))]
                    path += '&dateRange=('+','.join(parts)+')'
            elif feature == 'video_analytics':
                metric, aggregation = params.get('metric','VIDEO_VIEW'), params.get('aggregation','ALL')
                if metric not in ('VIDEO_VIEW','VIEWER','TIME_WATCHED','TIME_WATCHED_FOR_VIDEO_VIEWS') or aggregation not in ('ALL','DAY','WEEK') or not re.fullmatch(r'urn:li:ugcPost:\d+',target): raise AlphaError('Choose a documented video metric and ugcPost URN.',400)
                path = '/videoAnalytics?'+urlencode({'q':'entity','entity':target,'type':metric,'aggregation':aggregation})
                if dates:
                    parts = [name+':'+str(int(datetime.combine(d,datetime.min.time(),timezone.utc).timestamp()*1000)) for key,name in (('startDate','start'),('endDate','end')) if (d := dates.get(key))]
                    path += '&timeRange=('+','.join(parts)+')'
            else:
                endpoint = 'organizationalEntityFollowerStatistics' if feature == 'organization_follower_analytics' else 'organizationPageStatistics' if feature == 'organization_page_analytics' else 'organizationalEntityShareStatistics'
                path = '/'+endpoint+'?'+urlencode({'q':'organizationalEntity','organizationalEntity':target})
                if dates:
                    if len(dates) != 2: raise AlphaError('Organization statistics require both reporting dates.',400)
                    first,last = (int(datetime.combine(dates[k],datetime.min.time(),timezone.utc).timestamp()*1000) for k in ('startDate','endDate'))
                    path += '&timeIntervals=(timeRange:(start:'+str(first)+',end:'+str(last)+'),timeGranularityType:DAY)'
            response = self.adapter.api(self.token, "GET", path)
        elif pid in ("threads", "instagram"):
            if pid == "threads":
                permission = {"replies_read": "threads_read_replies", "conversation": "threads_read_replies", "insights": "threads_manage_insights", "account_insights": "threads_manage_insights", "mentions": "threads_manage_mentions"}.get(feature)
                self.require(["threads_basic"] + ([permission] if permission else []))
                edge = {"post_read": "", 'owned_posts':'threads', "replies_read": "replies", "conversation": "conversation", "insights": "insights", "account_insights": "insights", "quota": "threads_publishing_limit", "mentions": "mentions"}[feature]
                if feature in ("insights", "account_insights"):
                    params = {"metric": params.get("metric", "views,likes,replies,reposts,quotes"), **{k: v for k,v in params.items() if k in ("since", "until")}}
                elif feature == "quota": params = {"fields": "quota_usage,config"}
                else: params = {"fields": "id,text,username,timestamp,permalink,owner,is_reply,root_post,replied_to", "limit": 50, **{k: v for k,v in params.items() if k in ("after", "since", "until")}}
            else:
                permission = "instagram_business_manage_comments" if feature in ("comments_read", "comment_replies") else "instagram_business_manage_insights" if "insights" in feature else None
                self.require(["instagram_business_basic"]+([permission] if permission else []))
                edge = {"media_read": "media", "comments_read": "comments", "comment_replies": "replies", "insights": "insights", "account_insights": "insights", "quota": "content_publishing_limit"}[feature]
                if "insights" in feature:
                    # No fabricated fallback: a provider's unavailable metric is unavailable.
                    if not isinstance(params.get("metric"), str) or not params["metric"]:
                        raise AlphaError("Choose the metrics supported by this account/media type.", 400)
                    params = {k:v for k,v in params.items() if k in ("metric", "period", "since", "until")}
                elif feature == "quota": params = {"fields": "quota_usage,config"}
                else: params = {"fields": "id,caption,media_type,permalink,timestamp" if feature == "media_read" else "id,text,username,timestamp,parent_id", "limit": 50, **{k:v for k,v in params.items() if k == "after"}}
            response = self.meta("GET", target, edge, params)
        elif pid == "facebook":
            task = None if feature in ('page_roles','post_read','reactions') else "ANALYZE" if feature == "insights" else "MODERATE"
            page = self.adapter.revalidate_page(self.token, task)
            scopes = ['pages_show_list'] if feature == 'page_roles' else ["pages_read_engagement"] + (["read_insights"] if feature == "insights" else ["pages_read_user_content"] if feature in ("comments", "comment_replies") else [])
            self.require(scopes)
            if feature == "page_roles":
                response = {"status": 200, "body": {"id": page["id"], "tasks": page["tasks"]}}
            else:
                edge = {"post_read": "", "comments": "comments", "comment_replies": "comments", "reactions": "reactions", "insights": "insights"}[feature]
                params = {k:v for k,v in params.items() if k in ("after", "metric", "period", "since", "until")}
                if edge == "insights" and not params.get("metric"): raise AlphaError("Choose current Page/media metrics.", 400)
                if edge in ("comments", "reactions"): params.update(limit=50)
                response = self.adapter.graph("GET", "/"+encoded+("/"+edge if edge else ""), page["token"], params)
        elif pid == "x":
            self.require(["tweet.read", "users.read"])
            self._x_budget()
            if feature == "conversation_read":
                path = "/2/tweets/search/recent?"+urlencode({"query": "conversation_id:"+str(target), "max_results": 10, "tweet.fields": "conversation_id,referenced_tweets,author_id,created_at"})
            else:
                path = "/2/tweets/"+encoded+"?"+urlencode({"tweet.fields": "public_metrics,organic_metrics,non_public_metrics,author_id,conversation_id,edit_controls,edit_history_tweet_ids" if feature == "analytics" else "author_id,conversation_id,referenced_tweets,created_at"})
            response = self.adapter.api(self.token, "GET", path)
        elif pid == "youtube":
            self.require([MANAGE_SCOPE] if feature == "captions" else [READ_SCOPE] if feature not in ("analytics", "monetary_analytics", "reporting", "reporting_types", "reporting_reports", "reporting_download", "memberships", "membership_levels") else [])
            if feature in ("analytics", "monetary_analytics"):
                scope = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly" if feature == "monetary_analytics" else ANALYTICS_SCOPE
                self.require([scope])
                if not all(isinstance(params.get(k), str) for k in ("startDate", "endDate", "metrics")): raise AlphaError("Choose a reporting period and documented metrics.", 400)
                response = self.adapter.api(self.token, "GET", "https://youtubeanalytics.googleapis.com/v2/reports?"+urlencode({"ids": "channel==MINE", **{k:v for k,v in params.items() if k in ("startDate", "endDate", "metrics", "dimensions", "filters")}}))
            elif feature in ('reporting', 'reporting_types', 'reporting_reports', 'reporting_download'):
                self.require([ANALYTICS_SCOPE])
                if feature == 'reporting_download':
                    report_id = _identifier(params.get('reportId'))
                    metadata = self.adapter._ok(self.adapter.api(self.token,'GET','https://youtubereporting.googleapis.com/v1/jobs/'+encoded+'/reports/'+report_id))
                    address = metadata.get('downloadUrl','');parts = urlsplit(address)
                    if parts.scheme != 'https' or parts.netloc != 'youtubereporting.googleapis.com' or not parts.path.startswith('/v1/media/') or parts.fragment:
                        raise AlphaError('Provider report download URL is outside the audited Reporting API.',502)
                    response = self.adapter.api(self.token,'GET',address,response_format='csv',headers={'Accept':'text/csv'})
                    result = self.envelope(response,feature,params)
                    result['report'] = {k:metadata[k] for k in ('id','startTime','endTime','createTime','jobId') if k in metadata}
                    result['provenance']['reportingPeriod'] = {k:metadata[k] for k in ('startTime','endTime') if k in metadata}
                    return result
                route = 'jobs/'+encoded+'/reports' if feature == 'reporting_reports' else 'reportTypes' if feature == 'reporting_types' else 'jobs'
                response = self.adapter.api(self.token, "GET", "https://youtubereporting.googleapis.com/v1/"+route)
            elif feature in ("memberships", 'membership_levels'):
                self.require(["https://www.googleapis.com/auth/youtube.channel-memberships.creator"])
                response = self.adapter.api(self.token, "GET", self.adapter.API+("/members?part=snippet&maxResults=50" if feature == 'memberships' else '/membershipsLevels?part=snippet'))
            else:
                resource, query = {
                    "media_read": ("videos", {"part": "snippet,status,processingDetails,statistics", "id": target}),
                    "comments_read": ("commentThreads", {"part": "snippet,replies", "videoId": target, "maxResults": 50}),
                    "comment_replies": ("comments", {"part": "snippet", "parentId": target, "maxResults": 50}),
                    "live_broadcast": ("liveBroadcasts", {"part": "snippet,status,contentDetails", "mine": "true", "maxResults": 50}),
                    "live_stream": ("liveStreams", {"part": "snippet,status,cdn", "mine": "true", "maxResults": 50}),
                    "live_chat": ("liveChat/messages", {"part": "snippet,authorDetails", "liveChatId": target, "maxResults": 200}),
                    "playlists": ("playlists", {"part": "snippet,status", "mine": "true", "maxResults": 50}),
                    'playlist_images': ('playlistImages', {'part':'snippet','playlistId':target}),
                    "captions": ("captions", {"part": "snippet", "videoId": target}),
                }[feature]
                if params.get("pageToken"): query["pageToken"] = params["pageToken"]
                response = self.adapter.api(self.token, "GET", self.adapter.API+"/"+resource+"?"+urlencode(query))
        elif pid == "tiktok":
            if feature == "creator_info":
                self.require(["video.publish"])
                response = self.adapter.api(self.token, "POST", "/v2/post/publish/creator_info/query/", body={})
            elif feature == "processing":
                if not {'video.publish','video.upload'}.intersection(self.grant.get('scopes') or []):
                    raise AlphaError('Enable Direct Post or upload-to-inbox first.',409,code='social_scope_missing')
                response = self.adapter.api(self.token, "POST", "/v2/post/publish/status/fetch/", body={"publish_id": target})
            else:
                self.require(["video.list"])
                response = self.adapter.api(self.token, "POST", "/v2/video/list/?fields=id,title,video_description,share_url,create_time,duration", body={"max_count": 20})
        else:
            self.require(['ads:read'] if feature == 'audience_insights' else ['catalogs:read'] if feature in ('catalogs','product_groups','feeds','feed','feed_ingestions') else ["user_accounts:read"] if feature in ("account_analytics", "trends") else ["boards:read"] if feature in ("boards", "sections") else ["pins:read"])
            if feature == "boards": path = "/v5/boards?page_size=100"
            elif feature == "sections": path = "/v5/boards/"+encoded+"/sections?page_size=100"
            elif feature == "trends":
                if not re.fullmatch(r"[A-Z_]{2,30}", str(params.get("region", ""))) or params.get("trendType") not in ("growing", "monthly", "yearly", "seasonal"):
                    raise AlphaError("Choose a supported Pinterest region and trend type.", 400)
                path = "/v5/trends/keywords/"+params["region"]+"/top/"+params["trendType"]
            elif feature == "pin_read": path = "/v5/pins/"+encoded
            elif feature == 'product_tags': path = '/v5/pins/'+encoded+'/product_tags'
            elif feature == 'audience_insights': path = '/v5/ad_accounts/'+encoded+'/audience_insights?audience_type=YOUR_TOTAL_AUDIENCE'
            elif feature == 'catalogs': path = '/v5/catalogs'
            elif feature == 'product_groups': path = '/v5/catalogs/product_groups'
            elif feature in ('feeds','feed','feed_ingestions'): path = '/v5/catalogs/feeds'+('/'+encoded if feature != 'feeds' else '')+('/ingestions' if feature == 'feed_ingestions' else '')
            else:
                if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(params.get(k, ""))) for k in ("startDate", "endDate")): raise AlphaError("Choose the reporting period.", 400)
                path = ("/v5/pins/"+encoded+"/analytics" if feature == "analytics" else "/v5/user_account/analytics/top_video_pins" if feature == "video_analytics" else "/v5/user_account/analytics")+"?"+urlencode({"start_date": params["startDate"], "end_date": params["endDate"], **({"metric_types": params["metric"]} if params.get("metric") else {})})
            response = self.adapter.api(self.token, "GET", path, content=True)
        return self.envelope(response, feature, params)

    def x_product(self, product):
        proof=getattr(self.adapter,'official_approvals',{}).get(product,{})
        if proof.get('state')!='approved' or not proof.get('evidenceRef') or proof.get('appId')!=self.adapter.client_id:
            raise AlphaError('BLOCKED — X ENTERPRISE ACCESS' if product=='x_enterprise' else 'BLOCKED — X ARTICLE ACCESS',409)

    def _x_budget(self):
        # A console credit balance is not spending consent. No guessed costs or
        # silent unlimited read-heavy analytics; a server-owned budget authorizer
        # reserves each actual request before dispatch.
        budget = getattr(self.token, 'budget', None)
        reserve = budget.available if budget else getattr(self.adapter, "reserve_api_budget", None)
        if not callable(reserve) or reserve() is not True:
            raise AlphaError("X API request budget is not authorized or is exhausted.", 409, code="x_budget_required")

    def envelope(self, response, feature, params=None):
        status = response.get("status")
        headers = response.get("headers") or {}
        return {"provider": self.provider, "feature": feature, "availability": "available" if status in (200, 201, 204) else "permission_lost" if status in (401, 403) else "limited" if status in (402, 429) else "unavailable",
                "httpStatus": status, "data": response.get("body") or {}, "provenance": {"kind": "provider_native", "provider": self.provider, "reportingPeriod": {k:v for k,v in (params or {}).items() if k in ("since", "until", "startDate", "endDate", "period")}},
                "rate": {key: value for key,value in headers.items() if key in ("retry-after", "x-rate-limit-limit", "x-rate-limit-remaining", "x-rate-limit-reset", "x-app-usage", "x-business-use-case-usage")},
                "metered": self.provider == "x"}

    def write(self, action, target, payload):
        if not getattr(self.adapter, "official_social_enabled", False) or not self.adapter.production_reviewed:
            raise AlphaError("Official native action execution is not enabled/reviewed.", 409)
        from .official_action_contracts import validate
        validate(self.provider, action, payload)
        encoded = _identifier(target)
        pid = self.provider
        if pid in ("threads", "instagram"):
            if action == "delete" and pid == "threads":
                self.require(["threads_basic", "threads_delete"]);response = self.meta("DELETE", target)
            elif action in ("hide", "unhide"):
                self.require(["threads_basic", "threads_manage_replies"] if pid == "threads" else ["instagram_business_basic", "instagram_business_manage_comments"])
                response = self.meta("POST", target, "manage_reply" if pid == "threads" else "", {"hide": "true" if action == "hide" else "false"})
            elif action == "delete_comment" and pid == "instagram":
                self.require(["instagram_business_basic", "instagram_business_manage_comments"]);response = self.meta("DELETE", target)
            elif action == "reply" and pid == "instagram":
                self.require(["instagram_business_basic", "instagram_business_manage_comments"])
                response = self.meta("POST", target, "replies", {"message": payload["text"]})
            elif action == "repost" and pid == "threads":
                self.require(["threads_basic", "threads_content_publish"]);response = self.meta("POST", target, "repost")
            else: raise AlphaError("Use the approved publishing lifecycle for this action.", 409)
        elif pid == "linkedin":
            authenticated = self.adapter.identity(self.token)['providerAccountId']
            actor = payload.get("actor") or authenticated
            if not actor.startswith('urn:li:organization:') and actor != authenticated:
                raise AlphaError('Member actor must match the connected identity.', 409)
            organization = actor.startswith("urn:li:organization:")
            feed_action = action in ("reply", 'comment_edit', 'delete_comment', 'react', 'remove_reaction')
            scope = ("w_organization_social_feed" if organization else "w_member_social_feed") if feed_action else ("w_organization_social" if organization else "w_member_social")
            self.require([scope])
            if organization:
                self.require(['r_organization_admin'] if feed_action else ['rw_organization_admin'])
                authorized = self.adapter.organization_feed_authorized(self.token, authenticated, actor, write=True) if feed_action else self.adapter.organization_authorized(self.token, authenticated, actor, "DELETE" if action == "delete" else "UPDATE")
                if not authorized: raise AlphaError("The exact organization action is not authorized.", 409)
            if action == "delete": response = self.adapter.api(self.token, "DELETE", "/posts/"+encoded)
            elif action == "edit":
                headers = {"Authorization": "Bearer "+self.token, "LinkedIn-Version": "202609", "X-Restli-Protocol-Version": "2.0.0", "X-RestLi-Method": "PARTIAL_UPDATE"}
                response = self.adapter.transport("POST", "https://api.linkedin.com/rest/posts/"+encoded, headers=headers, body={"patch": {"$set": {"commentary": payload["text"]}}})
            elif action == "reply":
                body = {"actor": actor, "object": payload["rootPostUrn"], "message": {"text": payload["text"]}}
                if target.startswith('urn:li:comment:'): body['parentComment'] = target
                response = self.adapter.api(self.token, "POST", "/socialActions/"+encoded+"/comments", body=body)
            elif action == 'react':
                response = self.adapter.api(self.token, 'POST', '/reactions?'+urlencode({'actor':actor}), body={'root':target, 'reactionType':payload['reactionType']})
            elif action == 'remove_reaction':
                key = '(actor:'+quote(actor, safe='')+',entity:'+encoded+')'
                response = self.adapter.api(self.token, 'DELETE', '/reactions/'+key)
            elif action in ('comment_edit', 'delete_comment'):
                route = '/socialActions/'+encoded+'/comments/'+_identifier(str(payload['commentId']))+'?'+urlencode({'actor':actor})
                if action == 'delete_comment': response = self.adapter.api(self.token, 'DELETE', route)
                else:
                    from .official_publishers import OfficialPublishers
                    headers = {**OfficialPublishers.linkedin_headers(self.token),'X-RestLi-Method':'PARTIAL_UPDATE'}
                    response = self.adapter.transport('POST','https://api.linkedin.com/rest'+route,headers=headers,body={'patch':{'$set':{'message':{'text':payload['text']}}}})
            else: raise AlphaError("Official LinkedIn action unavailable.", 409)
        elif pid == "facebook":
            task = "MODERATE" if action in ("reply", "hide", "unhide", "delete_comment") else "CREATE_CONTENT"
            page = self.adapter.revalidate_page(self.token, task)
            self.require(["pages_manage_engagement"] if task == "MODERATE" else ["pages_manage_posts"])
            if action in ("delete", "delete_comment"): response = self.adapter.graph("DELETE", "/"+encoded, page["token"])
            elif action == "reply": response = self.adapter.graph("POST", "/"+encoded+"/comments", page["token"], form={"message": payload["text"]})
            elif action in ("hide", "unhide"): response = self.adapter.graph("POST", "/"+encoded, page["token"], form={"is_hidden": "true" if action == "hide" else "false"})
            elif action == "edit": response = self.adapter.graph("POST", "/"+encoded, page["token"], form={"message": payload["text"]})
            else: raise AlphaError("Official Page action unavailable.", 409)
        elif pid == "x":
            if action in ('quote','article_draft','article_publish'): self.x_product('x_enterprise' if action=='quote' else 'x_articles')
            self.require(["users.read", "tweet.read", "tweet.write"]);self._x_budget()
            if action == "delete": response = self.adapter.api(self.token, "DELETE", "/2/tweets/"+encoded)
            elif action in ("reply", "quote", "edit"):
                body = {"text": payload["text"]}
                body.update({"reply": {"in_reply_to_tweet_id": target}} if action == "reply" else {"quote_tweet_id": target} if action == "quote" else {"edit_options": {"previous_tweet_id": target}})
                response = self.adapter.api(self.token, "POST", "/2/tweets", body=body)
            elif action == "repost":
                user = self.adapter.identity(self.token)["providerAccountId"]
                response = self.adapter.api(self.token, "POST", "/2/users/"+_identifier(user)+"/retweets", body={"tweet_id": target})
            elif action == "article_draft":
                response = self.adapter.api(self.token, "POST", "/2/articles/draft", body={"title": payload["title"], "content_state": payload["content_state"], **({'cover_media':payload['cover_media']} if 'cover_media' in payload else {})})
            elif action == "article_publish": response = self.adapter.api(self.token, "POST", "/2/articles/"+encoded+"/publish")
            else: raise AlphaError("Official X action unavailable.", 409)
        elif pid == "youtube":
            if action in ('reporting_create', 'reporting_delete'):
                self.require([ANALYTICS_SCOPE])
                response = self.adapter.api(self.token, 'POST' if action == 'reporting_create' else 'DELETE', 'https://youtubereporting.googleapis.com/v1/jobs'+('' if action == 'reporting_create' else '/'+encoded), **({'body':{'reportTypeId':payload['reportTypeId'],'name':payload['name']}} if action == 'reporting_create' else {}))
                result = self.envelope(response, action)
                result['executionState'] = 'submitted' if response.get('status') in (200,201,204) else 'uncertain'
                return result
            if action == 'thumbnail':
                if not ({MANAGE_SCOPE, 'https://www.googleapis.com/auth/youtube.upload'} & set(self.grant.get('scopes') or [])): raise AlphaError('Enable YouTube publishing or management.',409)
            else: self.require([MANAGE_SCOPE])
            if action in ('thumbnail', 'playlist_image', 'caption_upload', 'caption_update'):
                if action in ('caption_upload', 'caption_update'):
                    raw = payload['caption'].encode('utf-8');mime = 'application/octet-stream'
                    metadata = {'snippet':{'videoId':target, 'language':payload['language'], 'name':payload.get('name', ''), 'isDraft':payload.get('isDraft', False)}} if action == 'caption_upload' else {'id':target, 'snippet':{'isDraft':payload.get('isDraft', False)}}
                    resource = 'captions';params = {'part':'snippet','uploadType':'multipart'};method = 'POST' if action == 'caption_upload' else 'PUT'
                else:
                    raw, mime = payload['_media']['raw'], payload['_media']['mime']
                    resource = 'thumbnails/set' if action == 'thumbnail' else 'playlistImages'
                    metadata = None if action == 'thumbnail' else {'snippet':{'playlistId':target,'type':'hero', 'width':payload['_media']['width'],'height':payload['_media']['height']}}
                    params = {'videoId':target,'uploadType':'media'} if action == 'thumbnail' else {'part':'snippet','uploadType':'multipart'};method = 'POST'
                if metadata is not None:
                    import secrets
                    boundary = 'rafii-'+secrets.token_hex(16)
                    raw = ('--'+boundary+'\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'+json.dumps(metadata)+'\r\n--'+boundary+'\r\nContent-Type: '+mime+'\r\n\r\n').encode()+raw+('\r\n--'+boundary+'--\r\n').encode()
                    mime = 'multipart/related; boundary='+boundary
                response = self.adapter.api(self.token, method, 'https://www.googleapis.com/upload/youtube/v3/'+resource+'?'+urlencode(params), headers={'Content-Type':mime}, data=raw)
                result = self.envelope(response, action);result['executionState'] = 'submitted' if response.get('status') in (200,201) else 'uncertain'
                return result
            definitions = {
                "delete": ("DELETE", "videos", {"id": target}, None),
                "reply": ("POST", "comments", {"part": "snippet"}, {"snippet": {"parentId": target, "textOriginal": payload.get("text")}}),
                "comment": ("POST", "commentThreads", {"part": "snippet"}, {"snippet": {"videoId": target, "topLevelComment": {"snippet": {"textOriginal": payload.get("text")}}}}),
                "delete_comment": ("DELETE", "comments", {"id": target}, None),
                'comment_edit': ('PUT','comments',{'part':'snippet'},{'id':target,'snippet':{'textOriginal':payload['text']}}),
                "moderate": ("POST", "comments/setModerationStatus", {"id": target, "moderationStatus": payload.get("moderationStatus"), "banAuthor": str(payload.get("banAuthor", False)).lower()}, None),
                "playlist_create": ("POST", "playlists", {"part": "snippet,status,localizations"}, payload.get("resource")),
                "playlist_edit": ("PUT", "playlists", {"part": "snippet,status,localizations"}, {**(payload.get("resource") or {}), "id": target}),
                "playlist_item": ("POST", "playlistItems", {"part": "snippet"}, {"snippet": {"playlistId": target, "resourceId": {"kind": "youtube#video", "videoId": payload.get("videoId")}}}),
                'playlist_delete': ('DELETE','playlists',{'id':target},None),
                'playlist_item_delete': ('DELETE','playlistItems',{'id':target},None),
                'caption_delete': ('DELETE','captions',{'id':target},None),
                "video_edit": ("PUT", "videos", {"part": "snippet,status,localizations"}, {**(payload.get("resource") or {}), "id": target}),
                "live_broadcast_create": ("POST", "liveBroadcasts", {"part": "snippet,status,contentDetails"}, payload.get("resource")),
                "live_stream_create": ("POST", "liveStreams", {"part": "snippet,cdn,contentDetails"}, payload.get("resource")),
                "live_bind": ("POST", "liveBroadcasts/bind", {"part": "id,contentDetails", "id": target, "streamId": payload.get("streamId")}, None),
                "live_transition": ("POST", "liveBroadcasts/transition", {"part": "id,status", "id": target, "broadcastStatus": payload.get("broadcastStatus")}, None),
                "live_chat_send": ("POST", "liveChat/messages", {"part": "snippet"}, {"snippet": {"liveChatId": target, "type": "textMessageEvent", "textMessageDetails": {"messageText": payload.get("text")}}}),
                "live_chat_delete": ("DELETE", "liveChat/messages", {"id": target}, None),
                "live_chat_ban": ("POST", "liveChat/bans", {"part": "snippet"}, payload.get("resource")),
                'live_chat_unban': ('DELETE','liveChat/bans',{'id':target},None),
                'live_broadcast_delete': ('DELETE','liveBroadcasts',{'id':target},None),
                'live_stream_delete': ('DELETE','liveStreams',{'id':target},None),
            }
            if action not in definitions: raise AlphaError("Official YouTube action unavailable.", 409)
            method, resource, params, body = definitions[action]
            response = self.adapter.api(self.token, method, self.adapter.API+"/"+resource+"?"+urlencode(params), **({"body": body} if body is not None else {}))
        elif pid == "tiktok":
            if action != 'cancel_transfer': raise AlphaError('Official TikTok action unavailable.',409)
            if not {'video.publish','video.upload'}.intersection(self.grant.get('scopes') or []): raise AlphaError('Enable Direct Post or upload-to-inbox first.',409,code='social_scope_missing')
            response=self.adapter.api(self.token,'POST','/v2/post/publish/cancel/',body={'publish_id':target})
            result=self.envelope(response,action);error=(response.get('body') or {}).get('error') or {}
            result['executionState']='submitted' if response.get('status')==200 and error.get('code')=='ok' else 'held' if response.get('status') in (400,401,403) else 'uncertain'
            result['limitation']='Best-effort URL pull cancellation; processing or near-complete downloads may already be non-cancellable. This does not delete a published post.'
            return result
        elif pid == "pinterest":
            self.require(['catalogs:write'] if action.startswith(('feed_','product_group_')) else ["boards:write"] if action.startswith(("board", "section")) else ["pins:write"])
            definitions = {
                "delete": ("DELETE", "/v5/pins/"+encoded, None), "edit": ("PATCH", "/v5/pins/"+encoded, payload),
                "board_create": ("POST", "/v5/boards", payload), "board_edit": ("PATCH", "/v5/boards/"+encoded, payload),
                "board_delete": ("DELETE", "/v5/boards/"+encoded, None), "section_create": ("POST", "/v5/boards/"+encoded+"/sections", payload),
                'product_tag': ('POST','/v5/pins/'+encoded+'/product_tags',payload),
                'feed_create': ('POST','/v5/catalogs/feeds',payload), 'feed_edit': ('PATCH','/v5/catalogs/feeds/'+encoded,payload),
                'feed_delete': ('DELETE','/v5/catalogs/feeds/'+encoded,None), 'feed_ingest': ('POST','/v5/catalogs/feeds/'+encoded+'/ingest',None),
                'product_group_create': ('POST','/v5/catalogs/product_groups',payload), 'product_group_edit': ('PATCH','/v5/catalogs/product_groups/'+encoded,payload), 'product_group_delete': ('DELETE','/v5/catalogs/product_groups/'+encoded,None),
            }
            if action in ('section_edit','section_delete'):
                route = '/v5/boards/'+_identifier(payload['boardId'])+'/sections/'+encoded
                definitions[action] = ('PATCH',route,{'name':payload['name']}) if action == 'section_edit' else ('DELETE',route,None)
            if action == 'product_tag': self.require(['boards:read','boards:write','pins:read','pins:write'])
            if action not in definitions: raise AlphaError("Official Pinterest action unavailable.", 409)
            method, path, body = definitions[action]
            response = self.adapter.api(self.token, method, path, content=True, **({"body": body} if body is not None else {}))
        else: raise AlphaError("No official creator-management write for this provider.", 409)
        result = self.envelope(response, action)
        result["executionState"] = "submitted" if response.get("status") in (200, 201, 204) else "held" if response.get("status") in (401, 403) else "uncertain"
        return result


ACTION_FIELDS = {
    'cancel_transfer': (),
    "delete": (), "delete_comment": (), "hide": (), "unhide": (), "repost": (), "article_publish": (),
    "reply": ("text", "actor", "rootPostUrn"), "comment": ("text",), "quote": ("text",), "edit": ("text", "actor", "title", "description", "alt_text", "link", "board_id", "board_section_id"),
    "article_draft": ("title", "content_state", "cover_media"), "moderate": ("moderationStatus", "banAuthor"),
    "playlist_create": ("resource",), "playlist_edit": ("resource",), "playlist_item": ("videoId",), "video_edit": ("resource",),
    "live_broadcast_create": ("resource",), "live_stream_create": ("resource",), "live_bind": ("streamId",), "live_transition": ("broadcastStatus",),
    "live_chat_send": ("text",), "live_chat_delete": (), "live_chat_ban": ("resource",),
    "board_create": ("name", "description", "privacy"), "board_edit": ("name", "description"), "board_delete": (), "section_create": ("name",),
    'comment_edit': ('text','actor','commentId'), 'react': ('actor','reactionType'), 'remove_reaction': ('actor',),
    'thumbnail': ('assetId','rightsConfirmed'), 'playlist_image': ('assetId','rightsConfirmed'),
    'caption_upload': ('caption','language','name','isDraft'), 'caption_update': ('caption','isDraft'), 'caption_delete': (),
    'playlist_delete': (), 'playlist_item_delete': (), 'reporting_create': ('reportTypeId','name'), 'reporting_delete': (),
    'live_chat_unban': (), 'live_broadcast_delete': (), 'live_stream_delete': (),
    'section_edit': ('boardId','name'), 'section_delete': ('boardId',), 'product_tag': ('product_tags',),
    'feed_create': ('catalog_type','catalog_id','name','location','format','default_country','default_locale'),
    'feed_edit': ('catalog_type','name','location','format','status'), 'feed_delete': (), 'feed_ingest': (),
    'product_group_create': ('feed_id','name','description','filters'), 'product_group_edit': ('name','description','filters'), 'product_group_delete': (),
}
ACTION_FIELDS['delete_comment'] = ('actor','commentId')


class SocialActionsService:
    """Native actions share Rafii's membership, immutable approvals, audit and token vault.

    Persist intent in one transaction before dispatch. A crash/ambiguous response
    cannot be re-approved to send a second action; explicit manual reconciliation
    is required. No external request is made while preparing a preview.
    """
    def __init__(self, oauth): self.oauth, self.repository = oauth, oauth.repository

    def read(self, workspace, token, connection, feature, target=None, options=None):
        adapter, grant = self.oauth._member_grant(workspace, token, connection, "read")
        return OfficialAPI(adapter, grant).read(feature, target, options)

    def preview(self, workspace, token, connection, action, target, payload):
        if action not in ACTION_FIELDS: raise AlphaError("Choose a supported native action.", 400)
        _identifier(target)
        payload = _options(payload or {}, ACTION_FIELDS[action])
        if action in ("reply", "quote", "comment", "live_chat_send") and (not isinstance(payload.get("text"), str) or not 1 <= len(payload["text"]) <= 4000):
            raise AlphaError("Review the exact action text.", 400)
        with self.repository.transaction(token, workspace) as (cur, row, principal):
            from .hosted import _membership
            from .permissions import require
            require(_membership(row), "edit")
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            channel = next((c for c in state.get("phase2", {}).get("channels", []) if c["id"] == connection and not c.get("revoked")), None)
            if not channel or channel.get("evidenceSource") != "live_provider": raise AlphaError("Connect a real provider account.", 409)
            from .official_action_contracts import validate
            from .providers import ADAPTERS
            provider_id = next((pid for pid, adapter in ADAPTERS.items() if adapter.platform == channel['platform']), None)
            validate(provider_id, action, payload)
            manifest = {"schema": "rafii.native-social-action.v1", "workspaceId": workspace, "connectionId": connection,
                        "providerAccountId": channel["providerAccountId"], "platform": channel["platform"], "actor": principal,
                        "action": action, "target": target, "payload": payload, "createdAt": self.oauth.clock()}
            if action in ('thumbnail', 'playlist_image'):
                from .asset_kinds import is_postable_image
                image = next((a for a in state['phase2'].get('assets',[]) if a.get('id') == payload.get('assetId')), None)
                if payload.get('rightsConfirmed') is not True or not is_postable_image(image) or image.get('mime') != 'image/jpeg' or image['bytes'] > 2_000_000 or (action == 'playlist_image' and image['width'] != image['height']):
                    raise AlphaError('Review a decoded JPEG up to 2 MB with rights confirmed. Podcast images must be square.',409)
                manifest['mediaProof'] = {k:image[k] for k in ('id','hash','bytes','mime','width','height','objectName')}
            item = {"id": uid(), "state": "preview", "manifest": manifest, "digest": digest(manifest)}
            actions = state["phase2"].setdefault("nativeSocialActions", [])
            if len(actions) >= 500: raise AlphaError("Native action history is full; archive reviewed receipts before adding more.", 409)
            actions.append(item)
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace))
            return copy.deepcopy(item)

    def approve(self, workspace, token, action_id, approval_digest, confirmed):
        if confirmed is not True: raise AlphaError("Confirm the exact native action.", 400)
        with self.repository.transaction(token, workspace) as (cur, row, principal):
            from .hosted import _membership, audit
            from .permissions import require
            require(_membership(row), "approve")
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            item = next((a for a in state.get("phase2", {}).get("nativeSocialActions", []) if a["id"] == action_id), None)
            if not item or item["state"] != "preview" or item["digest"] != approval_digest or digest(item["manifest"]) != approval_digest:
                raise AlphaError("Action changed or was already attempted. Reconcile its receipt before a new approval.", 409)
            manifest = copy.deepcopy(item["manifest"])
            if self.oauth.clock()-manifest["createdAt"] > 600: raise AlphaError("Action preview expired. Review it again.", 409)
            item.update(state="submitting", approvedBy=principal, attemptedAt=self.oauth.clock())
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace))
            audit(cur, workspace, principal, "social.native_action_attempted", action_id, {"action": manifest["action"]})
        try:
            adapter, grant = self.oauth._member_grant(workspace, token, manifest["connectionId"], "approve")
            if adapter.identity(grant["accessToken"])["providerAccountId"] != manifest["providerAccountId"]:
                raise AlphaError("Connected identity changed; review again.", 409)
            payload = copy.deepcopy(manifest['payload'])
            if manifest.get('mediaProof'):
                proof = manifest['mediaProof']
                if not getattr(self, 'assets', None): raise AlphaError('Approved image storage is unavailable.',503)
                with self.repository.transaction(token,workspace) as (_,row,_):
                    state = json.loads(row[1]) if isinstance(row[1],str) else row[1]
                    image = next((a for a in state['phase2'].get('assets',[]) if a.get('id') == proof['id'] and not a.get('deleted') and not a.get('deletionPending')), None)
                    if not image or any(image.get(k) != v for k,v in proof.items()): raise AlphaError('Approved image changed.',409)
                raw = self.assets.storage.get(workspace,'media',proof['objectName'])
                if len(raw) != proof['bytes'] or hashlib.sha256(raw).hexdigest() != proof['hash']: raise AlphaError('Approved image bytes changed.',409)
                payload['_media'] = {'raw':raw,**proof}
            result = OfficialAPI(adapter, grant).write(manifest["action"], manifest["target"], payload)
        except AlphaError as error:
            result = {"executionState": "uncertain", "message": str(error)}
        except Exception:
            result = {'executionState':'uncertain','message':'Provider outcome unknown. The durable intent cannot be repeated; reconcile its receipt first.'}
        with self.repository.transaction(token, workspace) as (cur, row, _):
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            item = next(a for a in state["phase2"]["nativeSocialActions"] if a["id"] == action_id)
            item.update(state=result["executionState"], receipt=result, completedAt=self.oauth.clock())
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace))
        return result
