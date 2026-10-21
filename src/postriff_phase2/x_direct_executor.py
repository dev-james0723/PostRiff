"""Official X JSON execution and evidence; every transport request is cost-admitted."""
import hashlib
import html
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from urllib.parse import urlencode, urlsplit
from postriff_alpha.domain import AlphaError

READ_OPERATIONS = frozenset((
 'identity.read','users.get','users.by_username','posts.get','posts.lookup',
 'timelines.user','timelines.mentions','timelines.home','search.recent','search.all',
 'likes.list','likes.users','reposts.users','quotes.list','follows.followers','follows.following',
 'bookmarks.list','bookmarks.folders.list','bookmarks.folders.get','mutes.list','blocks.list',
 'lists.get','lists.members.list','lists.followers','lists.posts','lists.owned','lists.followed',
 'lists.memberships','lists.pinned','dm.events','dm.conversation.events','dm.participant.events',
 'dm.event','analytics.public','analytics.owned'))
POST_OPERATIONS = frozenset(('posts.create','posts.reply','posts.quote','posts.edit'))
BOOL_RESULTS = {
 'posts.delete': ('deleted',True), 'posts.hide_reply': ('hidden',None),
 'likes.create': ('liked',True), 'likes.delete': ('liked',False),
 'reposts.create': ('retweeted',True), 'reposts.delete': ('retweeted',False),
 'follows.create': ('following',True), 'follows.delete': ('following',False),
 'bookmarks.create': ('bookmarked',True), 'bookmarks.delete': ('bookmarked',False),
 'mutes.create': ('muting',True), 'mutes.delete': ('muting',False),
 'blocks.create': ('blocking',True), 'blocks.delete': ('blocking',False),
 'lists.update': ('updated',True), 'lists.delete': ('deleted',True),
 'lists.members.add': ('is_member',True), 'lists.members.delete': ('is_member',False),
 'lists.follow': ('following',True), 'lists.unfollow': ('following',False),
 'lists.pin': ('pinned',True), 'lists.unpin': ('pinned',False),
 'dm.delete': ('deleted',True), 'dm.block': ('blocked',True), 'dm.unblock': ('blocked',False),
}
DM_CREATES = frozenset(('dm.send','dm.conversation.send','dm.group.create'))
ID_RESULTS = {'lists.create':'id', **{key:'dm_event_id' for key in DM_CREATES}}
IMPLEMENTED_OPERATIONS = READ_OPERATIONS | POST_OPERATIONS | frozenset(BOOL_RESULTS) | frozenset(ID_RESULTS)
_ID = re.compile(r'[1-9][0-9]{0,18}\Z', re.ASCII)
# Current conceptual docs still use this dialect; reference/OpenAPI disagree.
# One admitted lookup uses this pinned documented dialect, with NO fallback probe.
LOOKUP_DIALECT = 'tweet.fields-conceptual-docs-2026-10-19'


def valid_id(value):
    return isinstance(value,str) and _ID.fullmatch(value) is not None


def valid_conversation(value):
    return isinstance(value,str) and 1 <= len(value.split('-')) <= 2 and all(valid_id(p) for p in value.split('-'))


def plain(value):
    if is_dataclass(value):
        return {field.name:plain(getattr(value,field.name)) for field in fields(value)}
    if isinstance(value,(set,frozenset)):
        return sorted(plain(item) for item in value)
    if isinstance(value,Mapping):
        return {key:plain(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [plain(item) for item in value]
    return value


def response_hash(body):
    return hashlib.sha256(json.dumps(plain(body),ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()


def provider_reason(body):
    if not isinstance(body,dict):
        return 'X did not return a valid API response.'
    reason = next((body[k] for k in ('detail','title','message') if isinstance(body.get(k),str)),'')
    return ' '.join(re.sub(r'[\x00-\x1f\x7f]',' ',reason).split())[:300] or 'X did not accept this request.'


def provider_failure(response, *, read=False, now=0):
    status = response.get('status')
    reason = provider_reason(response.get('body'))
    if status == 429:
        headers = {str(k).lower():v for k,v in (response.get('headers') or {}).items()}
        try:
            retry = max(15,min(86400,int(headers.get('retry-after',60))))
            next_at = max(now+retry,min(now+86400,float(headers.get('x-rate-limit-reset',0))))
        except (TypeError,ValueError,OverflowError):
            next_at = now+60
        return {'state':'held' if read else 'queued','reasonCode':'x_rate_limited',
                'reason':reason,'nextAt':next_at,'providerStatus':status}
    if status == 402:
        return {'state':'held','reasonCode':'x_provider_billing_denied',
                'reason':'Unavailable — X API billing restriction: '+reason,'providerStatus':status}
    if status in (401,403):
        return {'state':'held','reasonCode':'x_authorization_or_entitlement_denied',
                'reason':'Unavailable — X API restriction: '+reason,'providerStatus':status}
    if status in (400,404,409,422):
        return {'state':'failed','reasonCode':'x_provider_rejected','reason':reason,'providerStatus':status}
    return {'state':'failed' if read else 'uncertain','reasonCode':'x_provider_result_unknown',
            'reason':reason if read else 'X may have accepted this request. It will not be submitted again.',
            'providerStatus':status}


def receipt(request,response,data, *, resource_id=None,partial=False,observed=None):
    headers = {str(k).lower():v for k,v in (response.get('headers') or {}).items()}
    trace = headers.get('x-request-id') or headers.get('x-transaction-id')
    value = {'source':'X API','operation':request.operation_id,'method':request.method,
        'path':request.path,'requestFingerprint':request.fingerprint,
        'responseSha256':response_hash(response.get('body')),'httpStatus':response.get('status'),
        'resourceId':resource_id,'partial':partial}
    if isinstance(trace,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',trace):
        value['providerRequestId'] = trace
    if resource_id and request.operation_id in POST_OPERATIONS:
        value['url'] = 'https://x.com/i/web/status/'+resource_id
    if observed is not None:
        value['observedState'] = observed
    return value


def _unknown(reason='The X response does not prove the requested state. No success is claimed.', evidence=None):
    result = {'state':'uncertain','reasonCode':'x_write_confirmation_missing','reason':reason}
    if evidence is not None:
        result['receipt'] = evidence
    return result


def decode_post(data):
    """Compatibility decoding is explicit; conflicting documented aliases fail."""
    if not isinstance(data,dict):
        raise ValueError('Missing post')
    value = dict(data)
    for canonical,modern in (('referenced_tweets','referenced_posts'),('edit_history_tweet_ids','edit_history_post_ids')):
        if canonical in value and modern in value and value[canonical] != value[modern]:
            raise ValueError('Conflicting post fields')
        if modern in value:
            value[canonical] = value[modern]
    for group in ('public_metrics','non_public_metrics','organic_metrics','promoted_metrics'):
        if group in value:
            if not isinstance(value[group],dict):
                raise ValueError('Malformed metrics')
            metrics = dict(value[group])
            if 'retweet_count' in metrics and 'repost_count' in metrics and metrics['retweet_count'] != metrics['repost_count']:
                raise ValueError('Conflicting metric fields')
            if 'repost_count' in metrics:
                metrics['retweet_count'] = metrics['repost_count']
            if any(type(v) is not int or v < 0 for v in metrics.values()):
                raise ValueError('Malformed metric count')
            value[group] = metrics
    return value


def _read_result(request,response,grant):
    from .x_direct_contract import CAPABILITIES
    body = response.get('body')
    if not isinstance(body,dict):
        raise ValueError('Missing response')
    data,errors = body.get('data'),body.get('errors')
    meta = body.get('meta') if isinstance(body.get('meta'),dict) else {}
    collection = CAPABILITIES[request.operation_id].collection or request.operation_id=='posts.lookup'
    if collection:
        if data is None and type(meta.get('result_count')) is int and meta['result_count']==0 and not errors:
            data=[]
        if not isinstance(data,list) or len(data)>request.max_billable_resources:
            raise ValueError('Collection cardinality outside admitted bound')
        if any(not isinstance(v,dict) or not valid_id(v.get('id')) for v in data):
            raise ValueError('Missing resource identifiers')
        ids=[v['id'] for v in data]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate resource identifiers')
        if request.operation_id=='posts.lookup' and not set(ids)<=set(request.query['ids'].split(',')):
            raise ValueError('Lookup returned an unrequested post')
    else:
        if not isinstance(data,dict) or not valid_id(data.get('id')):
            raise ValueError('Missing resource identifier')
        expected = (grant['providerAccountId'] if request.operation_id=='identity.read'
                    else request.path.rsplit('/',1)[-1])
        if request.operation_id=='users.by_username':
            if not isinstance(data.get('username'),str) or data['username'].casefold()!=expected.casefold():
                raise ValueError('Wrong requested username')
        elif data['id']!=expected:
            raise ValueError('Wrong requested resource')
    post_operation = ('/tweets' in request.path or request.operation_id.startswith('analytics.')
        or request.operation_id in ('bookmarks.list','bookmarks.folders.get','likes.list',
                                    'timelines.mentions','timelines.home'))
    if post_operation:
        data = [decode_post(v) for v in data] if isinstance(data,list) else decode_post(data)
    if request.operation_id=='analytics.public' and 'public_metrics' not in data:
        raise ValueError('Requested metrics missing')
    return {'state':'verified','receipt':receipt(request,response,data,partial=bool(errors)),
        'data':data,'meta':meta,'partial':bool(errors),
        'warnings':['Some requested X resources are unavailable.'] if errors else []}



def _execution_contract(request,grant,thread_context=None):
    from .x_direct_contract import validate_wire_request, ContractValidationError
    try:
        validate_wire_request(request,workspace_id=grant.get("workspaceId"),
            account_id=grant.get("connectionId"),actor_user_id=grant.get("providerAccountId"),
            thread_context=thread_context)
    except (ContractValidationError,KeyError,TypeError,ValueError) as error:
        raise AlphaError("The X execution contract is not bound to this account.",503,
            code="x_contract_mismatch") from error


def _accepted_receipt(request,evidence):
    return (isinstance(evidence,dict) and evidence.get("source")=="X API"
        and evidence.get("operation")==request.operation_id and evidence.get("method")=="POST"
        and evidence.get("path")==request.path and evidence.get("requestFingerprint")==request.fingerprint
        and type(evidence.get("httpStatus")) is int and evidence["httpStatus"] in (200,201)
        and isinstance(evidence.get("responseSha256"),str)
        and re.fullmatch(r"[0-9a-f]{64}",evidence["responseSha256"]) is not None
        and valid_id(evidence.get("resourceId")))

def attachment_keys(request, grant, now=None):
    media = request.body.get('media')
    if not media:
        return []
    ids = media.get('media_ids')
    proofs = grant.get('verifiedMedia')
    if not isinstance(proofs, dict) or not ids or set(proofs) != set(ids):
        raise AlphaError('Exact account-bound X upload evidence is required.', 409, code='x_media_ownership_required')
    keys = []
    for rid in ids:
        proof = proofs.get(rid)
        if (not isinstance(proof, dict) or not valid_id(rid) or not isinstance(proof.get('mediaKey'), str)
                or not re.fullmatch(r'[1-9][0-9]{0,3}_' + re.escape(rid), proof['mediaKey'])
                or type(proof.get('expiresAt')) not in (int, float) or not math.isfinite(proof['expiresAt'])
                or (now is not None and proof['expiresAt'] <= now + 30)):
            raise AlphaError('The X attachment expired or changed.', 409, code='x_media_ownership_required')
        keys.append(proof['mediaKey'])
    return keys


def execute(request,provider,grant, *, now, thread_context=None):
    _execution_contract(request,grant,thread_context)
    if request.operation_id not in IMPLEMENTED_OPERATIONS or getattr(provider,'id',None)!='x':
        raise AlphaError('Unavailable — no verified X execution handler exists for this operation.',409,code='x_handler_unavailable')
    if (request.operation_id in READ_OPERATIONS)!=(request.method=='GET'):
        raise AlphaError('Invalid X execution contract.',503,code='x_contract_mismatch')
    if request.operation_id in POST_OPERATIONS:
        attachment_keys(request, grant, now)
    query=plain(request.query or {})
    if query.get('expansions'):
        raise AlphaError('Unavailable — expanded X resource billing has not been admitted.',409,code='x_expansion_cost_unverified')
    path=request.path+('?'+urlencode(query,doseq=True) if query else '')
    options={} if request.method=='GET' else {'json_body':plain(request.body or {})}
    try:
        response=provider.api(grant['accessToken'],request.method,path,max_resources=request.max_billable_resources,**options)
    except AlphaError as error:
        if error.code!='x_provider_transport_unknown':
            raise
        return {'state':'failed' if request.method=='GET' else 'uncertain','reasonCode':'x_transport_result_unknown',
                'reason':'The X API result is unknown. No automatic write retry is allowed.'}
    except (OSError,TimeoutError,ValueError,TypeError):
        return {'state':'failed' if request.method=='GET' else 'uncertain','reasonCode':'x_transport_result_unknown',
                'reason':'The X API result is unknown. No automatic write retry is allowed.'}
    if not isinstance(response,dict) or type(response.get('status')) is not int or response['status'] not in (200,201):
        return provider_failure(response if isinstance(response,dict) else {},read=request.method=='GET',now=now)
    if request.method=='GET':
        try:
            return _read_result(request,response,grant)
        except (ValueError,KeyError,TypeError):
            return {'state':'failed','reasonCode':'x_read_data_unavailable',
                'reason':'X did not return matching data within the requested resource bound. Missing metrics are not zero.'}
    body=response.get('body')
    data=body.get('data') if isinstance(body,dict) else None
    errors=body.get('errors') if isinstance(body,dict) else None
    resource = data.get('id') if isinstance(data,dict) and request.operation_id in POST_OPERATIONS else None
    evidence = receipt(request,response,data,resource_id=resource,partial=bool(errors)) if valid_id(resource) else None
    if errors and evidence is not None:
        return {'state':'accepted','receipt':evidence,'reasonCode':'x_partial_post_response',
            'reason':'X returned a post ID with partial errors; exact API readback is required before success.'}
    if errors or not isinstance(data,dict):
        return _unknown(evidence=evidence)
    if request.operation_id in POST_OPERATIONS:
        if not valid_id(resource):
            return _unknown('X returned no valid post ID. No successful publication is claimed.')
        return {'state':'accepted','receipt':evidence,'reason':'X returned a post ID; authorized API readback is pending.'}
    if request.operation_id=='lists.create':
        if valid_id(data.get('id')) and isinstance(data.get('name'),str) and data['name']==request.body['name']:
            return {'state':'verified','receipt':receipt(request,response,data,resource_id=data['id'])}
    if request.operation_id in DM_CREATES:
        event,conversation=data.get('dm_event_id'),data.get('dm_conversation_id')
        if valid_id(event) and valid_conversation(conversation):
            if request.operation_id!='dm.conversation.send' or conversation==request.path.split('/')[3]:
                return {'state':'verified','receipt':receipt(request,response,data,resource_id=event,
                    observed={'dmConversationId':conversation})}
        return _unknown()
    if request.operation_id in BOOL_RESULTS:
        key,expected=BOOL_RESULTS[request.operation_id]
        expected=request.body.get('hidden') if expected is None else expected
        if request.operation_id=='follows.create':
            following,pending=data.get('following'),data.get('pending_follow')
            if following is False and pending is True:
                return {'state':'verified','receipt':receipt(request,response,data,observed={'pending_follow':True}),
                        'reason':'X confirmed a pending follow request; following is not active.'}
            if following is not True or pending is not False:
                return _unknown()
        if type(expected) is bool and data.get(key) is expected:
            return {'state':'verified','receipt':receipt(request,response,data,observed={key:expected})}
    return _unknown()


def normalized_text(value):
    if not isinstance(value,str):
        raise ValueError('Missing text')
    return unicodedata.normalize('NFC',value).replace('\r\n','\n').replace('\r','\n')


def expanded_text(data):
    """Only transform a t.co entity at its proven full span. Never strip URLs."""
    text=data.get('text')
    if not isinstance(text,str):
        raise ValueError('Missing post text')
    entities=data.get('entities') or {}
    if not isinstance(entities,dict) or not isinstance(entities.get('urls',[]),list):
        raise ValueError('Malformed URL evidence')
    urls=entities.get('urls',[])
    if not urls:
        return text
    candidates=[]
    for utf16 in (False,True):
        converted=[]
        try:
            for entity in urls:
                if not isinstance(entity,dict):
                    raise ValueError('Malformed entity')
                a,b=entity.get('start'),entity.get('end')
                if type(a) is not int or type(b) is not int or not 0<=a<b:
                    raise ValueError('Malformed entity span')
                if utf16:
                    raw=text.encode('utf-16-le')
                    if b*2>len(raw):
                        raise ValueError('Span outside text')
                    a=len(raw[:a*2].decode('utf-16-le'))
                    b=len(raw[:b*2].decode('utf-16-le'))
                url,expanded=entity.get('url'),entity.get('expanded_url')
                if not isinstance(url,str) or not isinstance(expanded,str) or b>len(text) or text[a:b]!=url:
                    raise ValueError('Span does not match URL')
                if urlsplit(url).netloc!='t.co' or urlsplit(expanded).scheme not in ('http','https'):
                    raise ValueError('Unverified URL transformation')
                converted.append((a,b,expanded))
            converted.sort()
            if any(converted[i-1][1]>converted[i][0] for i in range(1,len(converted))):
                raise ValueError('Overlapping URL evidence')
            value=text
            for a,b,url in reversed(converted):
                value=value[:a]+url+value[b:]
            candidates.append(value)
        except (ValueError,UnicodeError):
            continue
    if not candidates or len(set(candidates))!=1:
        raise ValueError('URL span dialect unresolved')
    return candidates[0]



def _matching_post_text(data, expected, verified_media_keys=()):
    actual = normalized_text(expanded_text(data))
    approved = normalized_text(expected.get("text", ""))
    if actual == approved:
        return True
    # Provider-appended URLs are removable only at exact, evidenced suffixes:
    # the quoted post or THIS post's attachment with the approved media key.
    allowed = set()
    target = expected.get("quote_tweet_id")
    own = data.get('id')
    for entity in (data.get("entities") or {}).get("urls", []):
        expanded = entity.get("expanded_url")
        if not isinstance(expanded, str):
            continue
        parsed = urlsplit(expanded)
        if (parsed.scheme != "https" or parsed.netloc not in ("x.com", "twitter.com")
                or parsed.query or parsed.fragment):
            continue
        quote_path = (r"/(?:[A-Za-z0-9_]{1,15}/status|i/web/status)/" + re.escape(target)) if valid_id(target) else None
        media_path = (r"/(?:[A-Za-z0-9_]{1,15}/status|i/web/status)/" + re.escape(own)
                      + r"/(?:photo|video)/[1-4]") if valid_id(own) else None
        if ((quote_path and re.fullmatch(quote_path, parsed.path)) or
                (media_path and re.fullmatch(media_path, parsed.path)
                 and entity.get('media_key') in verified_media_keys)):
            allowed.add(expanded)
    if not allowed:
        return False
    prefix = approved + ' ' if approved else ''
    if not actual.startswith(prefix):
        return False
    suffixes = actual[len(prefix):].split(' ')
    return bool(suffixes and len(set(suffixes)) == len(suffixes) and all(url in allowed for url in suffixes))


def reconcile_post(request,provider,grant,accepted_receipt, *, now, thread_context=None):
    _execution_contract(request,grant,thread_context)
    post_id=accepted_receipt.get('resourceId')
    if request.operation_id not in POST_OPERATIONS or not _accepted_receipt(request,accepted_receipt):
        return {'state':'uncertain','reasonCode':'x_exact_reference_required','reason':'No exact X reference is available for readback.'}
    path='/2/tweets/'+post_id
    query='?tweet.fields=author_id,text,entities,referenced_tweets,edit_history_tweet_ids,attachments'
    try:
        response=provider.api(grant['accessToken'],'GET',path+query,max_resources=1)
    except AlphaError as error:
        if error.code!='x_provider_transport_unknown':
            raise
        return {'state':'accepted','nextAt':now+60,'reasonCode':'x_readback_transport_unknown','reason':'The saved X receipt remains pending bounded readback.'}
    except (OSError,TimeoutError,ValueError,TypeError):
        return {'state':'accepted','nextAt':now+60,'reasonCode':'x_readback_transport_unknown','reason':'The saved X receipt remains pending bounded readback.'}
    if not isinstance(response,dict) or response.get('status')!=200:
        result=provider_failure(response if isinstance(response,dict) else {},read=True,now=now)
        if result['state']=='failed' or result['reasonCode']=='x_rate_limited':
            result.update(state='accepted',nextAt=result.get('nextAt',now+60))
        return result
    body=response.get('body')
    raw=body.get('data') if isinstance(body,dict) else None
    if not isinstance(raw,dict) or body.get('errors') or 'author_id' not in raw:
        return {'state':'accepted','nextAt':now+60,'reasonCode':'x_readback_incomplete',
                'reason':'X has not returned complete authorship and post readback evidence.'}
    try:
        data=decode_post(raw)
        expected=plain(request.body or {})
        refs=data.get('referenced_tweets') or []
        if not isinstance(refs,list) or any(not isinstance(r,dict) or not valid_id(r.get('id')) for r in refs):
            raise ValueError('Malformed post references')
        references={(r.get('type'),r['id']) for r in refs}
        wanted=set()
        reply=(expected.get('reply') or {}).get('in_reply_to_tweet_id')
        quote=expected.get('quote_tweet_id')
        if reply: wanted.add(('replied_to',reply))
        if quote: wanted.add(('quoted',quote))
        previous=(expected.get('edit_options') or {}).get('previous_post_id')
        expected_keys = attachment_keys(request, grant)
        mismatch=(data.get('id')!=post_id or data.get('author_id')!=grant['providerAccountId']
            or not _matching_post_text(data,expected,expected_keys)
            or references!=wanted
            or (previous and previous not in data.get('edit_history_tweet_ids',[])))
        attachments=data.get('attachments') or {}
        actual_keys = attachments.get('media_keys', []) if isinstance(attachments, dict) else None
        if (not isinstance(actual_keys, list) or len(actual_keys) != len(expected_keys)
                or any(not isinstance(key, str) for key in actual_keys)
                or set(actual_keys) != set(expected_keys) or attachments.get('poll_ids') or expected.get('poll')):
            raise ValueError('The exact approved attachment keys were not verified')
        if mismatch:
            raise ValueError('Post content or actor does not match')
    except (ValueError,TypeError,KeyError):
        return {'state':'uncertain','reasonCode':'x_readback_mismatch',
                'reason':'X readback does not match the approved account, exact content or references.'}
    evidence={**accepted_receipt,'method':'GET','path':path,'responseSha256':response_hash(body),
        'httpStatus':200,'partial':False,'readbackVerified':True,'authorId':data['author_id'],'dialect':LOOKUP_DIALECT}
    if expected_keys:
        evidence['mediaKeys'] = expected_keys
    return {'state':'verified','receipt':evidence,'reason':'The exact post was verified through the authorized official X API.'}
