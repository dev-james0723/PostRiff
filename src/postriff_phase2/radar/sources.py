"""Official bounded JSON adapters. No arbitrary URL fetch, redirects, cookies or page scraping."""
import json
import math
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from postriff_alpha.domain import AlphaError
from .core import SOURCE_NAMES, DAY


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def transport(url, headers, payload=None):
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Accept':'application/json','User-Agent':'Rafii-Radar/1.0',**headers})
    with build_opener(NoRedirect).open(request, timeout=10) as response:
        data=response.read(2_000_001)
        if len(data)>2_000_000: raise ValueError('Source response exceeds limit')
        return json.loads(data)


def rights(derive=True, excerpt=True, metrics=True):
    return {'displayLink':True,'displayExcerpt':excerpt,'deriveFeatures':derive,'derivedMetrics':metrics}


class Sources:
    def __init__(self, env, http=transport, clock=time.time): self.env,self.http,self.clock=env,http,clock

    def catalog(self):
        enabled=set(self.env.get('POSTRIFF_RADAR_SOURCES','').split(','))
        keys={'bluesky':'','news':'','exa':'EXA_API_KEY','youtube':'YOUTUBE_API_KEY','x':'X_BEARER_TOKEN'}
        rows=[]
        for source,name in SOURCE_NAMES.items():
            reason='ready'
            if source not in enabled: reason='not_configured'
            elif keys[source] and not self.env.get(keys[source]): reason='credentials_required'
            elif source in ('exa','x') and self.ceiling(source) is None: reason='current_price_ceiling_required'
            rows.append({'id':source,'name':name,'status':reason,'maxRequestUsdMicro':self.ceiling(source),
                         'note':'Native chart numbers only; excluded from opportunity scoring.' if source=='youtube' else 'Public metadata and bounded excerpts; source links retained.'})
        for source in ('threads','instagram','rss','mastodon','google_trends'):
            rows.append({'id':source,'name':source.replace('_',' ').title(),'status':'provider_review_required','maxRequestUsdMicro':None,'note':'Not connected for public discovery.'})
        return rows

    def ceiling(self, source):
        if source in ('bluesky','news','youtube'): return 0
        try:
            value=int(self.env.get('POSTRIFF_RADAR_'+source.upper()+'_REQUEST_MICRO',''))
            at=datetime.fromisoformat(self.env.get('POSTRIFF_RADAR_PRICE_REVIEWED_AT','').replace('Z','+00:00')).timestamp()
            if not 0<value<=10_000_000 or not 0<=self.clock()-at<=30*DAY:return None
            return value
        except (ValueError,TypeError):return None

    def search(self, source, query, limit):
        if not any(s['id']==source and s['status']=='ready' for s in self.catalog()):raise AlphaError('This source is unavailable.',409)
        limit=min(40,max(1,limit));now=self.clock();cost=0;basis='free_api';items=[]
        if source=='news':
            raw=self.http('https://api.gdeltproject.org/api/v2/doc/doc?'+urlencode({'query':query,'mode':'artlist','format':'json','maxrecords':limit,'timespan':'7d','sort':'datedesc'}),{})
            for r in raw.get('articles',[])[:limit]:
                try:at=datetime.strptime(r.get('seendate',''),'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
                except ValueError:at=None
                items.append({'url':r.get('url'),'title':r.get('title'),'author':r.get('domain'),'publishedAt':at,'rights':rights(excerpt=False),'coverage':'search_lead'})
        elif source=='bluesky':
            raw=self.http('https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?'+urlencode({'q':query,'sort':'latest','limit':limit}),{})
            for r in raw.get('posts',[])[:limit]:
                uri=r.get('uri','');author=r.get('author',{}).get('did','');record=r.get('record',{});key=uri.rsplit('/',1)[-1]
                if not author.startswith('did:') or not key:continue
                items.append({'url':f'https://bsky.app/profile/{author}/post/{key}','nativeId':uri,'author':author,
                              'title':record.get('text','')[:180],'excerpt':record.get('text','')[:500],'publishedAt':record.get('createdAt'),
                              'metrics':{'likes':r.get('likeCount'),'replies':r.get('replyCount'),'reposts':r.get('repostCount')},'rights':rights(),'coverage':'official_post'})
        elif source=='exa':
            raw=self.http('https://api.exa.ai/search',{'x-api-key':self.env['EXA_API_KEY'],'Content-Type':'application/json'},
                          {'query':query,'type':'auto','numResults':limit,'contents':{'highlights':{'maxCharacters':500}}})
            amount=raw.get('costDollars',{}).get('total')
            cost=math.ceil(amount*1_000_000) if type(amount) in (int,float) and math.isfinite(amount) and amount>=0 else None
            basis='provider' if cost is not None else 'unknown'
            for r in raw.get('results',[])[:limit]:
                items.append({'url':r.get('url'),'title':r.get('title'),'excerpt':' '.join(r.get('highlights',[])),
                              'author':r.get('author'),'publishedAt':r.get('publishedDate'),'rights':rights(),'coverage':'search_lead'})
        elif source=='youtube':
            raw=self.http('https://www.googleapis.com/youtube/v3/videos?'+urlencode({'key':self.env['YOUTUBE_API_KEY'],'part':'snippet,statistics','chart':'mostPopular','maxResults':limit,'regionCode':'US'}),{})
            for r in raw.get('items',[])[:limit]:
                s=r.get('snippet',{});m=r.get('statistics',{})
                items.append({'url':'https://www.youtube.com/watch?v='+r['id'],'nativeId':r['id'],'title':s.get('title'),
                              'author':s.get('channelId'),'publishedAt':s.get('publishedAt'),'rights':rights(derive=False,excerpt=False,metrics=False),
                              'metrics':{k:int(m[v]) for k,v in [('views','viewCount'),('likes','likeCount'),('comments','commentCount')] if str(m.get(v,'')).isdigit()},'coverage':'official_chart'})
        elif source=='x':
            raw=self.http('https://api.x.com/2/tweets/search/recent?'+urlencode({'query':query,'max_results':max(10,limit),'tweet.fields':'author_id,created_at,public_metrics'}),{'Authorization':'Bearer '+self.env['X_BEARER_TOKEN']})
            # X bills separately: no invoice in this response. Preserve an unknown actual cost.
            cost=None;basis='unknown'
            for r in raw.get('data',[])[:limit]:
                m=r.get('public_metrics',{})
                items.append({'url':'https://x.com/i/status/'+r['id'],'nativeId':r['id'],'title':r.get('text','')[:180],
                              'excerpt':r.get('text'),'author':r.get('author_id'),'publishedAt':r.get('created_at'),'rights':rights(),
                              'metrics':{'likes':m.get('like_count'),'replies':m.get('reply_count'),'reposts':m.get('retweet_count')},'coverage':'official_post'})
        return {'items':items,'costUsdMicro':cost,'costSource':basis,'at':now}

    def verify(self, item):
        """Bounded native-record presence check, never truth verification or a page fetch."""
        if item.get('source')!='bluesky' or not any(s['id']=='bluesky' and s['status']=='ready' for s in self.catalog()):raise AlphaError('This source cannot be verified.',409)
        uri=item.get('nativeId','')
        if not uri.startswith('at://did:') or '/app.bsky.feed.post/' not in uri or len(uri)>200:raise AlphaError('Invalid native record.')
        raw=self.http('https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?'+urlencode({'uris':uri}),{})
        if not isinstance(raw.get('posts'),list):raise ValueError('Missing native result')
        post=next((p for p in raw['posts'] if p.get('uri')==uri),None)
        # Any edited content requires a new scan before it is used as evidence.
        status='removed' if post is None else 'present' if post.get('record',{}).get('text','')[:180]==item['title'] else 'removed'
        return {'status':status,'costUsdMicro':0,'costSource':'free_api'}
