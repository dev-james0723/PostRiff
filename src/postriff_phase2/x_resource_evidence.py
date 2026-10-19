"""Short-lived eligibility from fresh internal X GET results; never client proof."""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import math
import re
from uuid import UUID

TTL_SECONDS=60
_FIELDS={'summoned_reply':frozenset(('author_id','entities')),
         'post_edit':frozenset(('author_id','edit_controls'))}

@dataclass(frozen=True)
class Evidence:
    kind:str
    resource_id:str
    source_sha256:str
    expires_at:float

def xid(v):
    return isinstance(v,str) and re.fullmatch(r'[1-9][0-9]{0,18}',v) is not None

def _epoch(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=253402300739:
        raise ValueError('Invalid evidence clock')
    return float(value)

def _scope(ws,conn,gen=None):
    workspace=str(UUID(str(ws)))
    if not isinstance(conn,str) or not re.fullmatch(r'[0-9a-f]{32}',conn):
        raise ValueError('Invalid X connection')
    if gen is not None and (not isinstance(gen,str) or not 1<=len(gen)<=256 or gen!=gen.strip() or '\x00' in gen):
        raise ValueError('Invalid X generation')
    return workspace,conn

def _fields(query):
    if not isinstance(query,Mapping):
        return frozenset()
    keys=[k for k in ('tweet.fields','post.fields') if k in query]
    if len(keys)!=1 or not isinstance(query[keys[0]],str):
        return frozenset()
    return frozenset(query[keys[0]].split(','))

def _checked(credential,request,result,now):
    try:
        now=_epoch(now)
        generation=credential.get('generation')
        if not isinstance(generation,str) or not generation or not xid(credential.get('account')):
            return None
        if not {'tweet.read','users.read'}<=set(credential.get('scopes') or []):
            return None
        if request.operation_id!='posts.get' or request.method!='GET':
            return None
        target=request.path.removeprefix('/2/tweets/')
        if request.path!='/2/tweets/'+target or not xid(target) or not isinstance(result,Mapping):
            return None
        r=result.get('receipt')
        if result.get('state')!='verified' or result.get('partial') is not False or not isinstance(r,Mapping):
            return None
        if (r.get('source')!='X API' or r.get('method')!='GET' or r.get('path')!=request.path
            or r.get('requestFingerprint')!=request.fingerprint or type(r.get('httpStatus')) is not int
            or r['httpStatus']!=200 or r.get('partial') is not False
            or not isinstance(r.get('responseSha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',r['responseSha256'])
            or not isinstance(request.fingerprint,str) or not re.fullmatch(r'[0-9a-f]{64}',request.fingerprint)):
            return None
        post=result.get('data')
        if not isinstance(post,Mapping) or post.get('id')!=target or not xid(post.get('author_id')):
            return None
        return post,_fields(request.query),r['responseSha256'],now
    except (AttributeError,ValueError,TypeError):
        return None

def extract_read_evidence(credential,request,result,now):
    checked=_checked(credential,request,result,now)
    if checked is None: return ()
    post,fields,digest,observed=checked
    actor=credential['account'];out=[]
    entities=post.get('entities')
    mentions=entities.get('mentions') if isinstance(entities,Mapping) else None
    if (post['author_id']!=actor and _FIELDS['summoned_reply']<=fields
            and isinstance(mentions,(list,tuple)) and any(isinstance(m,Mapping) and m.get('id')==actor for m in mentions)):
        out.append(Evidence('summoned_reply',post['id'],digest,observed+TTL_SECONDS))
    controls=post.get('edit_controls')
    if post['author_id']==actor and _FIELDS['post_edit']<=fields and isinstance(controls,Mapping):
        try:
            raw=controls.get('editable_until')
            if not isinstance(raw,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)',raw):
                raise ValueError('Unverified edit deadline')
            until=datetime.fromisoformat(raw.replace('Z','+00:00')).timestamp()
            remaining=controls.get('edits_remaining')
            if (controls.get('is_edit_eligible') is True and type(remaining) is int and remaining>0
                    and math.isfinite(until) and until>observed):
                out.append(Evidence('post_edit',post['id'],digest,min(until,observed+TTL_SECONDS)))
        except (ValueError,OverflowError):
            pass
    return tuple(out)

def schema_ready(cur):
    cur.execute("SELECT to_regclass('public.pr_x_resource_evidence')")
    return bool(cur.fetchone()[0])

def record_read(cur,ws,conn,credential,request,result,now):
    workspace,connection=_scope(ws,conn,credential['generation'])
    checked=_checked(credential,request,result,now)
    if checked is None or not schema_ready(cur): return 0
    post,fields,_,_=checked
    for kind,required in _FIELDS.items():
        if required<=fields:
            cur.execute("""DELETE FROM public.pr_x_resource_evidence
                WHERE workspace_id=%s AND connection_id=%s AND credential_generation=%s
                AND post_id=%s AND evidence_kind=%s""",
                (workspace,connection,credential['generation'],post['id'],kind))
    values=extract_read_evidence(credential,request,result,now)
    for item in values:
        cur.execute("""INSERT INTO public.pr_x_resource_evidence
            (workspace_id,connection_id,credential_generation,post_id,evidence_kind,source_sha256,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s))
            ON CONFLICT(workspace_id,connection_id,credential_generation,post_id,evidence_kind)
            DO UPDATE SET source_sha256=excluded.source_sha256,expires_at=excluded.expires_at""",
            (workspace,connection,credential['generation'],item.resource_id,item.kind,item.source_sha256,item.expires_at))
    return len(values)

def entitlements(cur,ws,conn,gen,now):
    workspace,connection=_scope(ws,conn,gen);now=_epoch(now)
    if not schema_ready(cur): return frozenset()
    cur.execute("""SELECT evidence_kind,post_id FROM public.pr_x_resource_evidence
        WHERE workspace_id=%s AND connection_id=%s AND credential_generation=%s
        AND expires_at>greatest(to_timestamp(%s),clock_timestamp())
        AND expires_at<=to_timestamp(%s)""",(workspace,connection,gen,now,now+TTL_SECONDS))
    return frozenset(kind+':'+target for kind,target in cur.fetchall() if kind in _FIELDS and xid(target))

def purge_connection(cur,ws,conn):
    workspace,connection=_scope(ws,conn)
    if not schema_ready(cur): return 0
    cur.execute("DELETE FROM public.pr_x_resource_evidence WHERE workspace_id=%s AND connection_id=%s",(workspace,connection))
    return max(0,cur.rowcount)
