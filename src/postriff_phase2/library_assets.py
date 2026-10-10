"""Private workspace Library. No model calls; durable, leased extraction jobs.

Legacy photos/videos stay in their existing pipeline. Normalized files share organization,
search and source provenance without copying file bytes into the workspace JSON.
"""
import hashlib
import json
import os
import re
import time
import uuid
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError
from .permissions import require
from .library_extract import MIMES, MAX_FILE_BYTES, MAX_TEXT, chunks, extract_text, extract_isolated, normalize, AUDIO_MIMES, LEGACY

TOKEN_SECONDS = 7200
SWEEP_MARGIN = 86400
FILENAME = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,255}$")
EXT = re.compile(r"^[a-z0-9]{1,12}$")
ASSET_ID = re.compile(r"^[0-9a-f]{32}$")
READY = ('ready', 'unsupported')
INLINE = {'txt','md','markdown','html','htm','csv','json'}


def _member(row):
    from .permissions import Membership
    return Membership.from_row(*row[2:7])


def _type(name, mime):
    if not isinstance(name, str) or not FILENAME.fullmatch(name.strip()) or name.strip() in ('.','..'):
        raise AlphaError('Choose a file with a valid name.')
    name = name.strip()
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else 'bin'
    if not EXT.fullmatch(ext):
        raise AlphaError('Use a simple file extension.')
    mime = str(mime or 'application/octet-stream').split(';', 1)[0].strip().lower()
    allowed = MIMES.get(ext) or AUDIO_MIMES.get(ext)
    if allowed is None:
        return name, ext, 'application/octet-stream', 'file'
    if mime not in allowed:
        raise AlphaError('The file extension and content type do not match.')
    return name, ext, mime, 'audio' if ext in AUDIO_MIMES else 'document'


def _tags(value):
    if not isinstance(value, list) or len(value) > 30 or any(not isinstance(x, str) or not 1 <= len(x.strip()) <= 40 or '\x00' in x for x in value):
        raise AlphaError('Use up to 30 tags, each from 1 to 40 characters.')
    return list(dict.fromkeys(x.strip() for x in value))


def _asset(a):
    provenance = {**a['provenance']}
    if isinstance(provenance.get('thumbnail'),dict):
        provenance['thumbnail'] = {k:v for k,v in provenance['thumbnail'].items() if k not in {'pages','claim'}}
    result = {
        'id': str(a['id']).replace('-', ''), 'createdBy': str(a['created_by']),
        'uploadedBy': str(a['created_by']), 'originalFilename': a['original_filename'],
        'displayTitle': a['display_title'], 'titleSource': a['title_source'],
        'summary': a['summary'], 'aiSummary': a['summary'], 'tags': a['tags'], 'aiTags': a['tags'],
        'kind': a['kind'], 'assetKind': a['kind'], 'mime': a['mime'], 'extension': a['extension'],
        'bytes': a['bytes'], 'hash': a['sha256'] or '', 'sha256': a['sha256'],
        'processing': a['processing_status'], 'processingStatus': a['processing_status'],
        'analysisStatus': a['analysis_status'], 'indexingStatus': a['indexing_status'],
        'createdAt': float(a['epoch']), 'provenance': provenance, 'deleted': False,
        'extractionError': a['extraction_error'], 'attempts': a.get('attempts', 0),
        'canRetryProcessing': a['processing_status'] in ('failed','queued') or (a['processing_status']=='unsupported' and a['extension'] in LEGACY),
        'transcriptionStatus': a.get('transcription_status', 'not_applicable'), 'sourceId': a.get('source_id'),
        'duplicateOf': str(a['duplicate_of']).replace('-', '') if a.get('duplicate_of') else None,
    }
    return result


class UniversalLibrary:
    def __init__(self, service, storage=None, clock=None, bucket='postriff-library'):
        self.service, self.storage, self.bucket = service, storage, bucket
        self.clock = clock or time.time
        try:
            self.storage_limit = max(MAX_FILE_BYTES, min(int(os.environ.get('POSTRIFF_LIBRARY_WORKSPACE_BYTES', 1073741824)), 10 * 1073741824))
        except ValueError:
            self.storage_limit = 1073741824

    def _store(self):
        if self.storage is None:
            raise AlphaError("File uploads aren't available yet.", 503, code='library_storage_not_configured')
        return self.storage

    def _row(self, cur, w, i, lock=False):
        if not isinstance(i, str) or not ASSET_ID.fullmatch(i):
            raise AlphaError('File unavailable.', 404)
        cur.execute("SELECT to_jsonb(a)||jsonb_build_object('epoch',extract(epoch from created_at)) FROM public.pr_library_assets a WHERE workspace_id=%s AND id=%s" + (' FOR UPDATE' if lock else ''), (w, uuid.UUID(hex=i)))
        row = cur.fetchone()
        if not row:
            raise AlphaError('File unavailable.', 404)
        return row[0]

    def _exists(self, cur, row, w, i):
        if not isinstance(i, str) or not ASSET_ID.fullmatch(i):
            raise AlphaError('Asset unavailable.', 404)
        cur.execute("SELECT 1 FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s AND processing_status NOT IN ('deleting','duplicate')", (w, uuid.UUID(hex=i)))
        if cur.fetchone():
            return
        state = self.service.ideas._state(row)
        if not any(a.get('id') == i and not a.get('deleted') and not a.get('deletionPending') for a in state.get('phase2', {}).get('assets', [])):
            raise AlphaError('Asset unavailable.', 404)

    def _edit(self,row):
        require(_member(row),'edit')
        if (self.service.ideas._state(row).get('workspace') or {}).get('sample'):
            raise AlphaError('Hosted sample workspaces are read-only.',403,code='sample_read_only')

    def assert_capacity(self,cur,state,w,size=0):
        # Runs under the caller's workspace lock, covering both file and legacy media paths.
        cur.execute("SELECT to_regclass('public.pr_library_assets')")
        if not cur.fetchone()[0]:
            return  # Backward compatible before the Library migration is deployed.
        cur.execute("SELECT coalesce(sum(bytes + coalesce((provenance->'thumbnail'->>'bytes')::bigint,0)),0) FROM public.pr_library_assets WHERE workspace_id=%s AND processing_status NOT IN ('duplicate','deleting')",(w,))
        used=int(cur.fetchone()[0])+sum(int(a.get('bytes') or 0) for a in state.get('phase2',{}).get('assets',[]) if not a.get('deleted'))
        cur.execute("SELECT coalesce(sum(declared_bytes),0) FROM public.pr_media_uploads WHERE workspace_id=%s AND status='pending'",(w,))
        used+=int(cur.fetchone()[0])
        if used+size>self.storage_limit:
            raise AlphaError('This workspace has reached its Library storage limit. Remove unused files first.',413,code='library_storage_limit')

    def begin(self, w, t, b):
        b = b if isinstance(b, dict) else {}
        name, ext, mime, kind = _type(b.get('filename'), b.get('mime'))
        size = b.get('bytes')
        if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
            raise AlphaError('This file is empty or over 50 MB.')
        i = uuid.uuid4().hex
        o = f'{i}.{ext}'
        s = self._store()
        with self.service.repository.transaction(t, w) as (cur, row, p):
            self._edit(row)
            cur.execute("SELECT count(*) FILTER (WHERE processing_status='pending'),coalesce(sum(bytes + coalesce((provenance->'thumbnail'->>'bytes')::bigint,0)),0) FROM public.pr_library_assets WHERE workspace_id=%s AND processing_status NOT IN ('duplicate','deleting')", (w,))
            pending, used = cur.fetchone()
            legacy = self.service.ideas._state(row).get('phase2', {}).get('assets', [])
            used += sum(int(a.get('bytes') or 0) for a in legacy if not a.get('deleted'))
            if pending >= 8:
                raise AlphaError('Finish or remove pending file uploads first.', 409)
            self.assert_capacity(cur,self.service.ideas._state(row),w,size)
            if used + size > self.storage_limit:
                raise AlphaError('This workspace has reached its Library storage limit. Remove unused files first.', 413, code='library_storage_limit')
            cur.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,kind,mime,extension,bytes,bucket,object_name,token_expires_at,provenance,transcription_status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>%s),%s::jsonb,%s)", (i,w,p,name,name.rsplit('.',1)[0][:160],kind,mime,ext,size,self.bucket,o,TOKEN_SECONDS,json.dumps({'source':'upload'}),'unavailable' if kind == 'audio' else 'not_applicable'))
        try:
            url = s.signed_upload_url(w, 'file', o)
        except Exception:
            # No signed capability was returned. The pending reservation is safely retryable/deletable.
            raise AlphaError('Private storage could not start this upload. Remove the pending item and try again.', 503) from None
        return {'upload': {'assetId': i, 'url': url, 'mime': mime, 'bytes': size, 'filename': name, 'expiresIn': TOKEN_SECONDS}}

    def commit(self, w, t, i):
        s = self._store()
        with self.service.repository.transaction(t, w) as (cur, row, p):
            self._edit(row)
            a = self._row(cur, w, i)
            if a['processing_status'] != 'pending':
                return {'asset': _asset(a), 'status': a['processing_status']}
            if str(a['created_by']) != p:
                raise AlphaError('Only the uploader can finish this file.', 403)
        info = s.object_info(w, 'file', a['object_name'])
        if (info.get('bytes'), info.get('mime')) != (a['bytes'], a['mime']) or not info.get('etag'):
            raise AlphaError('The uploaded file does not match its declared identity.', 409)
        with self.service.repository.transaction(t, w) as (cur, row, p):
            self._edit(row)
            current = self._row(cur, w, i, True)
            if current['processing_status'] == 'pending':
                cur.execute("UPDATE public.pr_library_assets SET etag=%s,processing_status='queued',next_attempt_at=now(),updated_at=now() WHERE workspace_id=%s AND id=%s", (info['etag'],w,i))
            a = self._row(cur, w, i)
        # Bounded small plain text/generic files can finish immediately. Complex parsers run on the cron worker.
        if a['processing_status'] == 'queued' and a['bytes'] <= 262144 and (a['extension'] in INLINE or (a['kind'] == 'file' and a['extension'] not in MIMES)):
            self.process(self.service.repository.connection_factory, w, i)
            with self.service.repository.transaction(t, w) as (cur, row, p):
                a = self._row(cur, w, i)
        return {'asset': _asset(a), 'status': a['processing_status']}

    def process(self, connect, w, i):
        i = str(i).replace('-', '')
        lease = str(uuid.uuid4())
        with connect() as db, db.cursor() as cur:
            cur.execute("UPDATE public.pr_library_assets SET processing_status='processing',lease_token=%s,lease_expires_at=now()+interval '180 seconds',attempts=attempts+1 WHERE workspace_id=%s AND id=%s AND attempts<3 AND next_attempt_at<=now() AND EXISTS (SELECT 1 FROM public.pr_workspaces w WHERE w.id=pr_library_assets.workspace_id AND NOT (w.state ? 'accountBlock') AND NOT (w.state ? 'accountDeletion')) AND (processing_status='queued' OR (processing_status='processing' AND lease_expires_at<now())) RETURNING to_jsonb(pr_library_assets)||jsonb_build_object('epoch',extract(epoch from created_at))", (lease,w,i))
            found = cur.fetchone()
        if not found:
            return 'not_claimed'
        a = found[0]
        try:
            s = self._store()
            info = s.object_info(w, 'file', a['object_name'])
            if (info.get('bytes'),info.get('mime'),info.get('etag')) != (a['bytes'],a['mime'],a['etag']):
                raise AlphaError('The uploaded file changed before verification.', 409)
            raw = s.get_bounded(w, 'file', a['object_name'], a['bytes'])
            after = s.object_info(w, 'file', a['object_name'])
            if len(raw) != a['bytes'] or after != info:
                raise AlphaError('The uploaded file changed during verification.', 409)
            digest = hashlib.sha256(raw).hexdigest()
            if a['kind'] == 'audio':
                from .library_extract import validate_audio
                validate_audio(raw, a['extension'])
                status, text = 'unsupported', ''
            else:
                status, text = (extract_text(raw,a['extension']) if a['extension'] in INLINE or (a['kind'] == 'file' and a['extension'] not in MIMES) else extract_isolated(raw,a['extension']))
            parts = chunks(text)
            with connect() as db, db.cursor() as cur:
                # Serializes digest admission with other files in this workspace, without a network call under lock.
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (w,))
                workspace = cur.fetchone()
                if not workspace or workspace[0].get('accountBlock') or workspace[0].get('accountDeletion'):
                    return 'workspace_frozen'
                current = self._row(cur,w,i,True)
                if str(current.get('lease_token')) != lease or current['processing_status'] != 'processing':
                    return 'lease_lost'
                cur.execute("SELECT id FROM public.pr_library_assets WHERE workspace_id=%s AND sha256=%s AND id<>%s AND processing_status IN ('ready','unsupported') ORDER BY created_at,id LIMIT 1", (w,digest,i))
                duplicate = cur.fetchone()
                if duplicate:
                    cur.execute("UPDATE public.pr_library_assets SET sha256=%s,processing_status='duplicate',duplicate_of=%s,lease_token=null,lease_expires_at=null,updated_at=now() WHERE workspace_id=%s AND id=%s", (digest,duplicate[0],w,i))
                    return 'duplicate'
                cur.execute('DELETE FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=%s',(w,i))
                for n, part in enumerate(parts):
                    cur.execute('INSERT INTO public.pr_library_chunks(asset_id,workspace_id,ordinal,text) VALUES(%s,%s,%s,%s)',(i,w,n,part))
                cur.execute("UPDATE public.pr_library_assets SET sha256=%s,processing_status=%s,analysis_status='not_applicable',indexing_status=%s,summary=%s,extraction_error=null,token_expires_at=null,lease_token=null,lease_expires_at=null,updated_at=now() WHERE workspace_id=%s AND id=%s",(digest,status,'ready' if status == 'ready' else 'not_applicable',normalize(text)[:360] or None,w,i))
            return status
        except Exception as e:
            transient = not isinstance(e,AlphaError) or e.status >= 500
            error = 'Private storage is temporarily unavailable.' if transient else str(e)[:300]
            with connect() as db, db.cursor() as cur:
                cur.execute("UPDATE public.pr_library_assets SET processing_status=CASE WHEN %s AND attempts<3 THEN 'queued' ELSE 'failed' END,indexing_status=CASE WHEN %s AND attempts<3 THEN 'pending' ELSE 'failed' END,extraction_error=%s,lease_token=null,lease_expires_at=null,next_attempt_at=now()+make_interval(secs=>least(300,30*attempts)),updated_at=now() WHERE workspace_id=%s AND id=%s AND lease_token=%s AND processing_status='processing'",(transient,transient,error,w,i,lease))
            return 'retrying' if transient and a['attempts'] < 3 else 'failed'

    def retry(self,w,t,i):
        with self.service.repository.transaction(t,w) as (cur,row,p):
            self._edit(row)
            a = self._row(cur,w,i,True)
            if a['processing_status'] not in ('failed','queued') and not (a['processing_status']=='unsupported' and a['extension'] in LEGACY):
                raise AlphaError('This file is not waiting for a retry.',409)
            cur.execute("UPDATE public.pr_library_assets SET processing_status='queued',attempts=0,indexing_status='pending',extraction_error=null,next_attempt_at=now(),lease_token=null,lease_expires_at=null WHERE workspace_id=%s AND id=%s",(w,i))
        # An explicit retry can complete a bounded small file without waiting
        # for cron (preview deployments do not run production cron schedules).
        # Larger files retain their durable background queue and lease.
        status = self.process(self.service.repository.connection_factory,w,i) if a['bytes']<=262144 else 'queued'
        return {'status':status,'assetId':i}

    def detail(self,w,t,i):
        with self.service.repository.transaction(t,w) as (cur,row,p):
            require(_member(row),'read')
            a = self._row(cur,w,i)
            cur.execute('SELECT ordinal,text FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=%s ORDER BY ordinal LIMIT 17',(w,i))
            parts = [{'ordinal':int(n),'text':x} for n,x in cur.fetchall()]
            result = _asset(a)
            self._decorate(cur,w,[result])
        return {'asset':result,'chunks':parts,'extractedText':'\n'.join(x['text'] for x in parts)[:100000]}

    def rename(self,w,t,i,title):
        return self.metadata(w,t,i,{'title':title})

    def metadata(self,w,t,i,body):
        from .library_metadata import validate_metadata
        body = validate_metadata(body)
        with self.service.repository.transaction(t,w) as (cur,row,p):
            self._edit(row)
            self._exists(cur,row,w,i)
            self._write_metadata(cur,w,i,body)
            cur.execute('SELECT 1 FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s',(w,i))
            normalized = bool(cur.fetchone())
        return {'asset':self.detail(w,t,i)['asset']} if normalized else {'assetId':i,'status':'updated'}

    def _write_metadata(self,cur,w,i,body):
        """Already-authorized, validated metadata write on the caller's workspace transaction."""
        cur.execute('INSERT INTO public.pr_library_labels(workspace_id,asset_key) VALUES(%s,%s) ON CONFLICT DO NOTHING',(w,i))
        if 'title' in body:
            cur.execute('UPDATE public.pr_library_labels SET display_title=%s,updated_at=now() WHERE workspace_id=%s AND asset_key=%s',(body['title'],w,i))
            cur.execute("UPDATE public.pr_library_assets SET display_title=%s,title_source='user',updated_at=now() WHERE workspace_id=%s AND id=%s",(body['title'],w,i))
        if 'tags' in body:
            cur.execute('UPDATE public.pr_library_labels SET tags=%s,updated_at=now() WHERE workspace_id=%s AND asset_key=%s',(body['tags'],w,i))
            cur.execute('UPDATE public.pr_library_assets SET tags=%s,updated_at=now() WHERE workspace_id=%s AND id=%s',(body['tags'],w,i))
        if 'collections' in body:
            collections=body['collections']
            cur.execute('SELECT id::text FROM public.pr_library_collections WHERE workspace_id=%s AND id=ANY(%s::uuid[])',(w,collections))
            if len(cur.fetchall()) != len(collections):
                raise AlphaError('Collection unavailable.',404)
            cur.execute('DELETE FROM public.pr_library_collection_items WHERE workspace_id=%s AND asset_key=%s',(w,i))
            for c in collections:
                cur.execute('INSERT INTO public.pr_library_collection_items(workspace_id,collection_id,asset_key) VALUES(%s,%s,%s)',(w,c,i))

    def collections(self,w,t,body=None,collection_id=None,delete=False):
        with self.service.repository.transaction(t,w) as (cur,row,p):
            require(_member(row),'edit' if body is not None or delete else 'read')
            if delete:
                if not isinstance(collection_id,str) or not ASSET_ID.fullmatch(collection_id.replace('-','')):
                    raise AlphaError('Collection unavailable.',404)
                cur.execute('DELETE FROM public.pr_library_collections WHERE workspace_id=%s AND id=%s RETURNING id',(w,collection_id))
                if not cur.fetchone():
                    raise AlphaError('Collection unavailable.',404)
            elif body is not None:
                name = body.get('name') if isinstance(body,dict) else None
                if not isinstance(name,str) or not 1<=len(name.strip())<=80 or '\x00' in name:
                    raise AlphaError('Use a collection name from 1 to 80 characters.')
                cur.execute('SELECT count(*) FROM public.pr_library_collections WHERE workspace_id=%s',(w,))
                if cur.fetchone()[0]>=100:
                    raise AlphaError('This workspace has reached 100 collections.',409)
                cur.execute('INSERT INTO public.pr_library_collections(id,workspace_id,name,created_by) VALUES(%s,%s,%s,%s) ON CONFLICT(workspace_id,name) DO NOTHING',(uuid.uuid4(),w,name.strip(),p))
            cur.execute('SELECT c.id::text,c.name,count(i.asset_key) FROM public.pr_library_collections c LEFT JOIN public.pr_library_collection_items i ON i.workspace_id=c.workspace_id AND i.collection_id=c.id WHERE c.workspace_id=%s GROUP BY c.id ORDER BY c.name',(w,))
            return {'collections':[{'id':i.replace('-',''),'name':n,'count':int(c)} for i,n,c in cur.fetchall()]}

    def transcript(self,w,t,i,text):
        if not isinstance(text,str) or not text.strip() or len(text)>250000 or '\x00' in text:
            raise AlphaError('Supply a transcript within 250,000 characters.')
        with self.service.repository.transaction(t,w) as (cur,row,p):
            self._edit(row)
            a = self._row(cur,w,i,True)
            if a['kind'] != 'audio' or a['processing_status'] not in READY:
                raise AlphaError('Finish an audio upload before adding its transcript.',409)
            self._retract_source(cur,row,w,p,a)
            cur.execute('UPDATE public.pr_library_assets SET source_id=null WHERE workspace_id=%s AND id=%s',(w,i))
            cur.execute('DELETE FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=%s',(w,i))
            for n,part in enumerate(chunks(text)):
                cur.execute('INSERT INTO public.pr_library_chunks(asset_id,workspace_id,ordinal,text) VALUES(%s,%s,%s,%s)',(i,w,n,part))
            cur.execute("UPDATE public.pr_library_assets SET transcription_status='ready',indexing_status='ready',summary=%s,provenance=provenance||%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id=%s",(normalize(text)[:360],json.dumps({'transcriptSource':'user_supplied','transcriptBy':p}),w,i))
        return self.detail(w,t,i)

    @staticmethod
    def _preview_object(a, page=1):
        from .library_preview import VERSION
        digest = hashlib.sha256((str(a['sha256']) + VERSION + ('' if page==1 else ':page:'+str(page))).encode()).hexdigest()
        return str(a['id']).replace('-', '')+'-'+digest+'.jpg'

    @classmethod
    def _preview_objects(cls,a):
        thumbnail = (a.get('provenance') or {}).get('thumbnail') or {}
        numbers = {1,int(thumbnail.get('page',1)),*[int(n) for n in thumbnail.get('pages',{})]}
        return [cls._preview_object(a,n) for n in numbers]

    def preview(self,w,t,i):
        result = self.viewer_page(w,t,i,1)
        return {'url':result['url'],'mime':'image/jpeg','page':1}

    def viewer_page(self,w,t,i,page=1):
        from .library_preview import SUPPORTED, VERSION, render_isolated
        if type(page) is not int or not 1<=page<=2147483647:
            raise AlphaError('Choose a valid document page.',422)
        store = self._store()
        claim = uuid.uuid4().hex
        now = self.clock()
        with self.service.repository.transaction(t,w) as (cur,row,p):
            require(_member(row),'read')
            a = self._row(cur,w,i,True)
            if a['extension'] not in SUPPORTED or a['processing_status'] not in READY or not a['sha256']:
                raise AlphaError('Document preview unavailable for this file.',422)
            name = self._preview_object(a,page)
            previous = (a.get('provenance') or {}).get('thumbnail') or {}
            pages = previous.get('pages',{}) if previous.get('version')==VERSION else {}
            cached_page = pages.get(str(page))
            if not cached_page:
                if previous.get('pageCount') and page>previous['pageCount']:
                    raise AlphaError('This page is outside the document.',422)
                if previous.get('state') == 'processing' and previous.get('until',0)>now:
                    raise AlphaError('Preparing document page. Try again shortly.',409)
                if previous.get('attempts',0)>=3 and previous.get('until',0)>now-600:
                    raise AlphaError('Document rendering failed. Try again in a few minutes.',422)
                cur.execute("SELECT count(*) FROM public.pr_library_assets WHERE workspace_id=%s AND provenance->'thumbnail'->>'state'='processing' AND (provenance->'thumbnail'->>'until')::numeric>%s",(w,now))
                if cur.fetchone()[0]>=2:
                    raise AlphaError('Preparing other document pages. Try again shortly.',429)
                pending = {**previous,'pages':pages,'bytes':previous.get('bytes',0),'page':page,'state':'processing','version':VERSION,'claim':claim,'until':now+90,'attempts':previous.get('attempts',0)+1 if previous.get('state')=='failed' and previous.get('until',0)>now-600 else 1}
                cur.execute("UPDATE public.pr_library_assets SET provenance=jsonb_set(provenance,'{thumbnail}',%s::jsonb) WHERE workspace_id=%s AND id=%s",(json.dumps(pending),w,i))
        if cached_page:
            return {**cached_page,'pageCount':previous['pageCount'],'page':page,'url':store.signed_url(w,'media',name)}
        stored = published = False
        try:
            info = store.object_info(w,'file',a['object_name'])
            if (info.get('bytes'),info.get('mime'),info.get('etag')) != (a['bytes'],a['mime'],a['etag']):
                raise AlphaError('The source file changed before rendering.',409)
            raw = store.get_bounded(w,'file',a['object_name'],a['bytes'])
            if len(raw)!=a['bytes'] or hashlib.sha256(raw).hexdigest()!=a['sha256'] or store.object_info(w,'file',a['object_name'])!=info:
                raise AlphaError('The source file changed during rendering.',409)
            rendered = render_isolated(raw,a['extension'],page)
            image = rendered.pop('image')
            # Reserve derived bytes under the same workspace lock as uploads.
            with self.service.repository.transaction(t,w) as (cur,row,p):
                current = self._row(cur,w,i,True)
                if current['processing_status'] not in READY or (current.get('provenance') or {}).get('thumbnail',{}).get('claim')!=claim:
                    raise AlphaError('This file is no longer available.',404)
                self.assert_capacity(cur,self.service.ideas._state(row),w,len(image))
                pending['bytes'] = previous.get('bytes',0)+len(image)
                cur.execute("UPDATE public.pr_library_assets SET provenance=jsonb_set(provenance,'{thumbnail}',%s::jsonb) WHERE workspace_id=%s AND id=%s",(json.dumps(pending),w,i))
            try:
                store.put_immutable(w,'media',name,image,'image/jpeg')
                stored = True
            except AlphaError as error:
                if error.status!=409: raise
            with self.service.repository.transaction(t,w) as (cur,row,p):
                current = self._row(cur,w,i,True)
                if current['processing_status'] not in READY or (current.get('provenance') or {}).get('thumbnail',{}).get('claim')!=claim:
                    raise AlphaError('This file is no longer available.',404)
                page_data = {k:rendered[k] for k in ('width','height','text')}
                pages[str(page)] = page_data
                pending.update(state='ready',pageCount=rendered['pageCount'],pages=pages,attempts=0,objectName=self._preview_object(a))
                cur.execute("UPDATE public.pr_library_assets SET provenance=jsonb_set(provenance,'{thumbnail}',%s::jsonb) WHERE workspace_id=%s AND id=%s",(json.dumps(pending),w,i))
            published = True
            return {**rendered,'url':store.signed_url(w,'media',name)}
        except Exception as error:
            if stored and not published:
                store.delete(w,'media',name)
            with self.service.repository.transaction(t,w) as (cur,row,p):
                pending.update(state='failed',bytes=previous.get('bytes',0))
                cur.execute("UPDATE public.pr_library_assets SET provenance=jsonb_set(provenance,'{thumbnail}',%s::jsonb) WHERE workspace_id=%s AND id=%s AND provenance->'thumbnail'->>'claim'=%s",(json.dumps(pending),w,i,claim))
            if isinstance(error,AlphaError): raise
            raise AlphaError('Document page could not be rendered. The original file is still available.',422) from None

    def url(self,w,t,i,download=False):
        with self.service.repository.transaction(t,w) as (cur,row,p):
            require(_member(row),'read')
            a = self._row(cur,w,i)
        if a['processing_status'] not in READY and a['processing_status'] != 'failed':
            raise AlphaError('This file is not ready.',409)
        url = self._store().signed_url(w,'file',a['object_name'])
        # Active document types are always attachments; previews use extracted plain text.
        if download or a['kind']=='file' or a['extension'] in ('html','htm','json'):
            url += '&'+urlencode({'download':a['original_filename']})
        return {'url':url,'mime':a['mime'],'filename':a['original_filename'],'expiresIn':300}

    def delete(self,w,t,i):
        s = self._store()
        with self.service.repository.transaction(t,w) as (cur,row,p):
            self._edit(row)
            a = self._row(cur,w,i,True)
            cur.execute("UPDATE public.pr_library_assets SET processing_status='deleting',lease_token=null,lease_expires_at=null,updated_at=now() WHERE workspace_id=%s AND id=%s",(w,i))
            self._retract_source(cur,row,w,p,a)
        s.delete(w,'file',a['object_name'])
        for preview_name in self._preview_objects(a):
            s.delete(w,'media',preview_name)
        with self.service.repository.transaction(t,w) as (cur,row,p):
            self._edit(row)
            self._forget(cur,w,i)
        return {'assetId':i,'status':'deleted'}

    def _forget(self,cur,w,i):
        cur.execute('DELETE FROM public.pr_library_collection_items WHERE workspace_id=%s AND asset_key=%s',(w,i))
        cur.execute('DELETE FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=%s',(w,i))
        cur.execute('DELETE FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s',(w,i))

    def _decorate(self,cur,w,assets):
        ids = [a['id'] for a in assets]
        cur.execute('SELECT asset_key,display_title,tags FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=ANY(%s)',(w,ids))
        labels = {i:(title,tags) for i,title,tags in cur.fetchall()}
        cur.execute('SELECT asset_key,collection_id::text FROM public.pr_library_collection_items WHERE workspace_id=%s AND asset_key=ANY(%s)',(w,ids))
        groups = {}
        for i,c in cur.fetchall():
            groups.setdefault(i,[]).append(c.replace('-',''))
        for a in assets:
            a['collections'] = groups.get(a['id'],[])
            if a['id'] in labels:
                title,tags = labels[a['id']]
                if title:
                    a.update(displayTitle=title,titleSource='user')
                a.update(tags=tags,aiTags=tags)

    def list(self,w,t,query='',limit=100,offset=0,kind='all',tag='',collection='',sort='newest'):
        try:
            limit=max(1,min(int(limit or 100),200));offset=max(0,min(int(offset or 0),100000))
        except (ValueError,TypeError):
            raise AlphaError('Use a valid Library page size.') from None
        query=str(query or '').strip()[:120]
        hash_prefix=query.lower()+'%' if re.fullmatch(r'[0-9a-fA-F]{1,64}',query) else None
        if kind not in ('all','image','video','audio','document','file') or sort not in ('newest','stored','largest') or (collection and not ASSET_ID.fullmatch(collection.replace('-',''))):
            raise AlphaError('Choose valid Library filters.')
        tag=str(tag or '')[:40]
        order='a.bytes DESC,a.created_at DESC,a.id' if sort=='largest' else 'a.created_at DESC,a.id'
        with self.service.repository.transaction(t,w) as (cur,row,p):
            require(_member(row),'read')
            cur.execute("SELECT to_jsonb(a)||jsonb_build_object('epoch',extract(epoch from a.created_at)) FROM public.pr_library_assets a WHERE workspace_id=%s AND processing_status NOT IN ('deleting','duplicate') AND (%s='all' OR a.kind=%s) AND (%s='' OR %s=ANY(a.tags)) AND (%s='' OR EXISTS(SELECT 1 FROM public.pr_library_collection_items i WHERE i.workspace_id=a.workspace_id AND i.asset_key=replace(a.id::text,'-','') AND replace(i.collection_id::text,'-','')=%s)) AND (%s='' OR a.sha256 LIKE %s OR to_tsvector('simple',coalesce(a.display_title,'')||' '||a.original_filename||' '||coalesce(a.summary,'')||' '||array_to_string(a.tags,' '))@@plainto_tsquery('simple',%s) OR EXISTS(SELECT 1 FROM public.pr_library_chunks c WHERE c.workspace_id=a.workspace_id AND c.asset_id=a.id AND c.search_vector@@plainto_tsquery('simple',%s)) OR a.original_filename ILIKE %s OR a.display_title ILIKE %s OR EXISTS(SELECT 1 FROM public.pr_library_chunks c WHERE c.workspace_id=a.workspace_id AND c.asset_id=a.id AND c.text ILIKE %s)) ORDER BY "+order+" LIMIT %s OFFSET %s",(w,kind,kind,tag,tag,collection,collection.replace('-',''),query,hash_prefix,query,query,'%'+query.replace('%','\\%').replace('_','\\_')+'%','%'+query.replace('%','\\%').replace('_','\\_')+'%','%'+query.replace('%','\\%').replace('_','\\_')+'%',limit+1,offset))
            rows=cur.fetchall();more=len(rows)>limit
            assets=[_asset(r[0]) for r in rows[:limit]]
            state=self.service.ideas._state(row)
            legacy=[{**a,'assetKind':'video' if str(a.get('mime') or '').startswith('video/') else 'image'} for a in state.get('phase2',{}).get('assets',[]) if not a.get('deleted') and not a.get('deletionPending')] if offset==0 else []
            self._decorate(cur,w,assets+legacy)
            legacy=[a for a in legacy if (kind=='all' or a['assetKind']==kind) and (not tag or tag in a.get('tags',[])) and (not collection or collection in a.get('collections',[]))]
            if query:
                words=query.casefold().split()
                legacy=[a for a in legacy if all(word in ' '.join(str(x) for x in [a.get('displayTitle',''),a.get('originalFilename',''),a.get('hash',''),*a.get('tags',[])]).casefold() for word in words)]
            cur.execute("SELECT coalesce(sum(bytes + coalesce((provenance->'thumbnail'->>'bytes')::bigint,0)),0) FROM public.pr_library_assets WHERE workspace_id=%s AND processing_status NOT IN ('duplicate','deleting')",(w,))
            used=int(cur.fetchone()[0])+sum(int(a.get('bytes') or 0) for a in state.get('phase2',{}).get('assets',[]) if not a.get('deleted'))
        return {'assets':legacy+assets,'query':query,'nextOffset':offset+limit if more else None,'storage':{'usedBytes':used,'limitBytes':self.storage_limit},'capabilities':{'automaticTranscription':False,'transcriptImport':True}}

    def sweep(self,connect,limit=100):
        s=self._store();removed=failed=processed=0
        with connect() as db,db.cursor() as cur:
            cur.execute("UPDATE public.pr_library_assets SET processing_status='failed',indexing_status='failed',extraction_error='Processing timed out. Retry this file.',lease_token=null,lease_expires_at=null WHERE processing_status='processing' AND lease_expires_at<now() AND attempts>=3")
            cur.execute("SELECT workspace_id::text,id::text FROM public.pr_library_assets WHERE attempts<3 AND next_attempt_at<=now() AND (processing_status='queued' OR (processing_status='processing' AND lease_expires_at<now())) ORDER BY created_at LIMIT 3")
            jobs=cur.fetchall()
        for w,i in jobs:
            self.process(connect,w,i);processed+=1
        with connect() as db,db.cursor() as cur:
            cur.execute("SELECT workspace_id::text,id::text,object_name FROM public.pr_library_assets WHERE (processing_status='pending' AND token_expires_at+make_interval(secs=>%s)<now()) OR processing_status IN ('deleting','duplicate') ORDER BY updated_at LIMIT %s",(SWEEP_MARGIN,limit))
            due=cur.fetchall()
        for w,i,o in due:
            try:
                s.delete(w,'file',o)
                with connect() as db,db.cursor() as cur:
                    a = self._row(cur,w,i.replace('-',''))
                for preview_name in self._preview_objects(a):
                    s.delete(w,'media',preview_name)
                with connect() as db,db.cursor() as cur:
                    self._forget(cur,w,i.replace('-',''))
                removed+=1
            except Exception:
                failed+=1
                with connect() as db,db.cursor() as cur:
                    cur.execute('UPDATE public.pr_library_assets SET delete_attempts=delete_attempts+1 WHERE workspace_id=%s AND id=%s',(w,i))
        return {'processed':processed,'removed':removed,'failed':failed}

    def purge_workspace(self,cur,w):
        cur.execute('SELECT object_name FROM public.pr_library_assets WHERE workspace_id=%s',(w,))
        for (o,) in cur.fetchall():
            self._store().delete(w,'file',o)
        for p in self._store().list_prefix(f'{w}/file',bucket=self.bucket):
            self._store().delete(w,'file',p.rsplit('/',1)[-1])
        cur.execute('DELETE FROM public.pr_library_assets WHERE workspace_id=%s',(w,))

    def _retract_source(self,cur,row,w,p,a):
        if not a.get('source_id'):
            return
        state=self.service.ideas._state(row)
        source=next((x for x in state.get('sources',[]) if x.get('id')==a['source_id']),None)
        if source:
            source.update(active=False,retracted=True,text='',facts=[])
            self.service.commands.engine._mark_source_stale(state,source['id'])
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),w))
            from .hosted import audit
            audit(cur,w,p,'library.source_withdrawn',str(a['id']),{})

    def as_source(self,w,t,i,body):
        """Explicitly import a bounded excerpt; existing fact approval and egress controls still apply."""
        if not isinstance(body,dict) or type(body.get('expectedRevision')) is not int:
            raise AlphaError('Reload the workspace before importing this source.',409)
        detail=self.detail(w,t,i)
        text=detail['extractedText'][:19000]
        if not text.strip():
            raise AlphaError('This asset has no extracted text. Add an audio transcript or choose a text document.',409)
        a=detail['asset']
        if a.get('sourceId'):
            # Check edit permission even for an idempotent import.
            with self.service.repository.transaction(t,w) as (cur,row,p):
                self._edit(row)
            return {'sourceId':a['sourceId'],'assetId':i,'status':'needs_review','clipped':len(detail['extractedText'])>19000}
        def command(state,actor):
            # The source is reviewable, never silently approved for AI egress or publication.
            self.service.commands.engine._apply(state,'source',{'kind':'text','title':a['displayTitle'] or a['originalFilename'],'text':text})
            source=state['sources'][-1]
            source_id_value=source['id']
            source.update(origin={'kind':'library','assetId':i,'sha256':a['sha256'],'filename':a['originalFilename'],'locator':'extracted text','clipped':len(detail['extractedText'])>19000},sourcePolicy='rewrite_approval',egressConsent=['local'])
            selected['id']=source_id_value
            return state
        selected={}
        def after(cur,state,p):
            current=self._row(cur,w,i,True)
            cur.execute('SELECT text FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=%s ORDER BY ordinal LIMIT 400',(w,i))
            current_text='\n'.join(x[0] for x in cur.fetchall())[:100000]
            if current.get('source_id') or current_text != detail['extractedText'] or current['sha256'] != a['sha256'] or current['processing_status'] not in READY:
                raise AlphaError('This source changed. Reload before importing.',409)
            cur.execute('UPDATE public.pr_library_assets SET source_id=%s WHERE workspace_id=%s AND id=%s',(selected['id'],w,i))
        snap=self.service.repository.command(w,t,body['expectedRevision'],command,after=after,audit_event=lambda state:('library.source_imported',i,{'sourceId':selected['id']}))
        return {'sourceId':selected['id'],'assetId':i,'revision':snap['revision'],'clipped':len(detail['extractedText'])>19000,'status':'needs_review'}
