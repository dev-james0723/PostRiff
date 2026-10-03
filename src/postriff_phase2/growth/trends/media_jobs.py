"""Durable WP17 adapter for explicitly reviewed, existing private video assets.

No discovery, model, publishing, schema or replacement media storage. Public
reads MUST use read(); generic TrendStore manifests are trusted-server APIs.
The projection is content-free; all extracted content lives in purgeable chunks.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid

from . import config, contracts, creative_patterns, media_runtime, media_storage, retention, credit_admission
from .jobs import TrendJobs
from .pipeline import encode_manifest, decode_manifest
from .store import TrendStore, TrendStorageError, row, rows, trust_lock, utcnow

KIND = 'trend.local_media'
PROJECTION = 'creative_pattern_local'
BINDING = 'trend.media.binding.v1'
RESULT = 'trend.media.result.v1'
MAX_STAGE_BYTES = 8 * 1024 * 1024  # Existing private storage's bounded range API.
OPS = media_runtime.BASE_RIGHTS
SCAN_PROVIDER = 'rafii.local.media'
SCAN_PARTITION = 'binding-retention-v1'


def _deny(code):
    raise TrendStorageError('media_' + code)


def method_identity():
    paths = [Path(__file__), Path(media_runtime.__file__), Path(media_storage.__file__), Path(creative_patterns.__file__)]
    artifact = contracts.digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    return {'method_id': KIND, 'method_version': 'local-v1-' + artifact[:16], 'artifact_digest': artifact}


def _requests(clips):
    if not isinstance(clips, list) or not 1 <= len(clips) <= 2:
        _deny('clip_bound')
    seen = set()
    for c in clips:
        if not isinstance(c, dict) or set(c) != {'asset_id', 'source_id', 'language', 'modalities', 'frame_count'}:
            _deny('request_contract')
        if not isinstance(c['asset_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', c['asset_id']):
            _deny('asset_id_required')
        if c['asset_id'] in seen or contracts.uuid(c['source_id']) != c['source_id']:
            _deny('request_identity')
        if (not isinstance(c['modalities'],list) or not 1<=len(c['modalities'])<=4
                or not all(isinstance(m,str) and m in media_runtime.MODALITIES for m in c['modalities'])
                or len(set(c['modalities']))!=len(c['modalities']) or type(c['frame_count']) is not int
                or not 0<=c['frame_count']<=12 or not isinstance(c['language'],str)):
            _deny('request_contract')
        seen.add(c['asset_id'])
    return deepcopy(clips)


def _explicit(rights):
    value = contracts.validate_rights(rights)
    if set(value) != set(contracts.PERMISSIONS):
        _deny('explicit_grants_required')
    return value


def _asset_map(state):
    return {a['id']: a for a in state.get('phase2', {}).get('assets', []) if isinstance(a, dict) and a.get('id')}


def _asset_fingerprint(asset):
    return contracts.digest({k: asset.get(k) for k in ('id', 'kind', 'mime', 'category', 'objectName', 'hash',
        'bytes', 'etag', 'processing', 'deleted', 'deletionPending')})


def _revoke(cur, scope_key, manifest_ids):
    if not manifest_ids:
        return
    # Node row locks serialize with put_manifest's dependency locks. These
    # immutable local roots need no provider tombstone/global lock upgrade.
    cur.execute("UPDATE pr_trend_nodes SET validity='revoked' WHERE scope_key=%s AND node_id=ANY(%s::uuid[]) AND validity='valid'",
                (scope_key, manifest_ids))
    cur.execute("""UPDATE pr_trend_jobs SET cancellation_requested=true,state='cancelled',payload='{}',lease_owner=NULL,lease_until=NULL
        WHERE scope_key=%s AND kind=%s AND payload->>'binding_manifest_id'=ANY(%s)
        AND state IN ('queued','retry_wait','leased','running')""", (scope_key, KIND, manifest_ids))


def capture_asset_changes(cur, workspace_id, before, after, actor):
    """repository.effects callback: invalidate on deletionPending, removal or change.

    Run in the workspace mutation transaction, before physical object deletion.
    Optional migration availability is checked; flags never suppress cleanup.
    """
    previous, current = _asset_map(before), _asset_map(after)
    changed = [a for a in previous if a not in current or _asset_fingerprint(previous[a]) != _asset_fingerprint(current[a])]
    if not changed:
        return
    cur.execute("SELECT to_regclass('public.pr_trend_input_manifests')")
    if not cur.fetchone()[0]:
        return
    scope_key = 'workspace:' + contracts.uuid(workspace_id)
    cur.execute("""SELECT m.manifest_id::text FROM pr_trend_input_manifests m JOIN pr_trend_nodes n
        ON(n.scope_key,n.node_id)=(m.scope_key,m.manifest_id) WHERE m.scope_key=%s AND n.validity='valid'
        AND m.recipe->>'schema'=%s AND EXISTS(SELECT 1 FROM jsonb_array_elements(m.recipe->'request') c
        WHERE c->>'asset_id'=ANY(%s))""", (scope_key, BINDING, changed))
    _revoke(cur, scope_key, [r[0] for r in cur.fetchall()])


class MediaJobs:
    def __init__(self, hosted, *, store=None, values=None, runtime_factory=media_runtime.MediaRuntime,
                 storage_factory=media_storage.BoundedStorage, clock=utcnow):
        self.hosted = hosted
        self.store = store or TrendStore(hosted.repository.connection_factory, hosted=hosted)
        if getattr(self.store, 'hosted', None) is None:
            self.store.hosted = hosted
        self.jobs = TrendJobs(self.store)
        self.values, self.runtime_factory, self.clock = values, runtime_factory, clock
        self.storage_factory = storage_factory  # Trusted host-only seam; explicit local test adapters.

    def enabled(self, workspace_id):
        return config.workspace_allowed(workspace_id, self.values) and all(
            config.enabled(k, self.values) for k in ('RADAR', 'TRUST_RECEIPTS', 'MULTIMODAL'))

    def _load(self, cur, workspace_id, actor_id, request, *, decision_cutoff, deploy=False, write=False):
        """One fresh committed authority snapshot; never a sealed copy of grants."""
        if actor_id is not None:
            self.store._actor(cur, workspace_id, actor_id, write=write)
        cur.execute('SELECT state FROM pr_workspaces WHERE id=%s FOR SHARE', (workspace_id,))
        record = cur.fetchone()
        if not record:
            _deny('workspace_unavailable')
        state = record[0] if isinstance(record[0], dict) else json.loads(record[0])
        if state.get('accountDeletion'):
            _deny('workspace_unavailable')
        trust_lock(cur)
        assets = _asset_map(state); scope_key = 'workspace:' + workspace_id
        now = self.clock(); at = contracts.instant(now)
        sources, media, identities, controls, caps, expiries = {}, {}, [], [], None, []
        for c in request:
            asset = assets.get(c['asset_id'])
            if (not asset or asset.get('deleted') or asset.get('deletionPending') or asset.get('kind') != 'video'
                    or asset.get('category') != 'video' or asset.get('processing') != 'ready'
                    or asset.get('mime') not in ('video/mp4', 'video/quicktime')
                    or not re.fullmatch(r'[0-9a-f]{32}\.(mp4|mov)', str(asset.get('objectName', '')))
                    or type(asset.get('bytes')) is not int or not 0 < asset['bytes'] <= MAX_STAGE_BYTES
                    or not asset.get('etag')):
                _deny('supplied_asset_unavailable')
            cur.execute("""SELECT o.*,postriff_private.trend_node_valid(o.scope_key,o.observation_id) AS valid
                FROM pr_trend_observations o WHERE o.scope_key=%s AND o.observation_id=%s FOR SHARE OF o""",
                        (scope_key, c['source_id']))
            obs = row(cur)
            if (not obs or not obs['valid'] or obs['purged_at'] or obs['operation'] == 'delete'
                    or contracts.instant(obs['available_at']) > contracts.instant(decision_cutoff)):
                _deny('source_unavailable')
            policy = self.store._policy(cur, scope_key, obs['provider_id'], obs['source_policy_version'], at=now)
            source_rights, policy_rights = _explicit(obs['rights']), _explicit(policy['rights'])
            if not all(op in policy['contract_operations'] and contracts.permits(source_rights, op, scope_key, now)
                       and contracts.permits(policy_rights, op, scope_key, now) for op in OPS):
                _deny('current_right_not_permitted')
            for op, grant in policy_rights.items():
                if op not in policy['contract_operations']: grant['state'] = 'unknown'
            reviewed = policy['manifest'].get('media_extraction')
            if (not policy['manifest'].get('reviewed_by') or not policy['manifest'].get('review_ref')
                    or not isinstance(reviewed, dict) or set(reviewed) != {'version','approved','deployment','limits','asset_bindings','modality_rights'}
                    or reviewed['version'] != '1' or reviewed['approved'] is not True):
                _deny('review_required')
            grants = obs['provenance'].get('media_modality_rights')
            media_runtime._modality_grants(grants); media_runtime._modality_grants(reviewed['modality_rights'])
            if not all(contracts.permits({'retrieve': g[m]}, 'retrieve', scope_key, now)
                       for g in (grants, reviewed['modality_rights']) for m in c['modalities']):
                _deny('current_modality_denied')
            binding = {'workspace_id': workspace_id, 'asset_id': c['asset_id'], 'asset_hash': asset.get('hash'),
                       'source_id': c['source_id']}
            candidates = reviewed['asset_bindings']
            if not isinstance(candidates, list) or len(candidates) > 100:
                _deny('binding_bound')
            matches = [b for b in candidates if isinstance(b, dict) and all(b.get(k) == v for k,v in binding.items())]
            if len(matches) != 1 or set(matches[0]) != set(binding) | {'media_sha256'}:
                _deny('reviewed_asset_binding_required')
            media_hash = media_runtime._hash(matches[0]['media_sha256'])
            deployment = reviewed['deployment']
            if (not isinstance(deployment, dict) or set(deployment) != {'qualified','review_ref','runtime_sha256','ffmpeg_sha256','ffprobe_sha256'}
                    or deployment['qualified'] is not True or not isinstance(deployment['review_ref'], str) or not deployment['review_ref']):
                _deny('deployment_unqualified')
            if deploy:
                if hashlib.sha256(Path(media_runtime.__file__).read_bytes()).hexdigest() != deployment['runtime_sha256']:
                    _deny('runtime_changed')
                for binary in ('ffmpeg', 'ffprobe'):
                    path = shutil.which(binary)
                    if not path or hashlib.sha256(Path(path).read_bytes()).hexdigest() != deployment[binary + '_sha256']:
                        _deny('deployment_binary_unavailable')
            if caps is not None and caps != reviewed['limits']:
                _deny('policy_caps_conflict')
            caps = deepcopy(reviewed['limits'])
            clip_id = str(uuid.uuid5(uuid.UUID(workspace_id), c['asset_id']))
            controls.append({'clip_id': clip_id, 'source_id': c['source_id'], 'source_scope': scope_key,
                'source_revision': obs['revision_sequence'], 'source_digest': obs['payload_digest'], 'media_sha256': media_hash,
                'caption_sha256': None, 'language': c['language'], 'modalities': c['modalities'], 'frame_count': c['frame_count']})
            media[clip_id] = deepcopy(asset)
            source_snapshot = sources.setdefault(c['source_id'], {'scope_key': scope_key, 'revision': obs['revision_sequence'], 'payload_digest': obs['payload_digest'],
                'deleted': False, 'available_at': obs['available_at'], 'retention_until': obs['retention_until'],
                'rights': source_rights, 'policy_rights': policy_rights, 'modality_rights': grants,
                'policy_modality_rights': reviewed['modality_rights'],
                'media_bindings': []})
            source_snapshot['media_bindings'].append({'media_sha256': media_hash, 'caption_sha256': None})
            identities.append({'asset': _asset_fingerprint(asset), 'source_id': c['source_id'], 'source_revision': obs['revision_sequence'],
                'source_digest': obs['payload_digest'], 'source_rights': source_rights, 'modality_rights': grants,
                'policy_manifest': contracts.digest(policy['manifest']), 'contract_operations': policy['contract_operations']})
            expiries += [obs['retention_until'], policy['expires_at'], policy['contract_end']]
            expiries += [r[op]['expires_at'] for r in (source_rights, policy_rights) for op in OPS]
            expiries += [g[m]['expires_at'] for g in (grants, reviewed['modality_rights']) for m in c['modalities']]
        expiry = min(expiries, key=contracts.instant)
        if contracts.instant(expiry) <= at: _deny('expired')
        if sum(a['bytes'] for a in media.values()) > caps['max_bytes']: _deny('input_byte_bound')
        runtime = {'schema_version': media_runtime.SCHEMA, 'job_id': str(uuid.uuid4()), 'workspace_id': workspace_id,
                   'actor_id': actor_id or str(uuid.UUID(int=0)), 'scope_key': scope_key, 'decision_cutoff': decision_cutoff,
                   'expires_at': expiry, 'limits': caps, 'clips': controls}
        media_runtime.validate_job(runtime); runtime.pop('job_id')
        fingerprint = contracts.digest({'bindings': identities, 'request': request})
        return {'runtime': runtime, 'media': media, 'fingerprint': fingerprint, 'expires_at': expiry,
                'snapshot': {'workspace_id': workspace_id, 'actor_id': actor_id, 'authorized': True, 'checked_at': now,
                             'valid_until': expiry, 'authorized_source_scopes': [scope_key], 'sources': sources}}

    def enqueue(self, workspace_id, actor_id, clips, *, idempotency_key, cursor=None):
        workspace_id, actor_id = contracts.uuid(workspace_id), contracts.uuid(actor_id)
        if not self.enabled(workspace_id): return {'state':'disabled', 'job_id':None}
        request = _requests(clips)
        if not isinstance(idempotency_key,str) or not 1 <= len(idempotency_key) <= 200: _deny('idempotency_required')
        scope_key = 'workspace:' + workspace_id
        with self.store.transaction(cursor) as cur:
            now = self.clock()
            loaded = self._load(cur, workspace_id, actor_id, request, decision_cutoff=now, deploy=True, write=True)
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(scope_key+'|media-admission',))
            method = method_identity()
            key = 'media:' + contracts.digest([workspace_id, actor_id, idempotency_key])
            cur.execute('SELECT * FROM pr_trend_jobs WHERE scope_key=%s AND idempotency_key=%s', (scope_key,key))
            existing = row(cur)
            result_id = str(uuid.uuid5(uuid.UUID(workspace_id),key))
            if existing:
                if existing['kind'] != KIND: _deny('idempotency_conflict')
                if existing['payload'] and (existing['payload']['request'] != request or existing['payload']['fingerprint'] != loaded['fingerprint']):
                    _deny('idempotency_conflict')
                return {'state': existing['state'], 'job_id':existing['job_id'], 'result_id':result_id, 'replayed':True}
            credit_admission.require_qualified_entry(cur, workspace_id, store=self.store)
            cur.execute("SELECT count(*) FROM pr_trend_jobs WHERE scope_key=%s AND kind=%s AND state IN ('queued','retry_wait','leased','running')",(scope_key,KIND))
            if cur.fetchone()[0] >= 2: _deny('queue_full')
            self.store.ensure_scope(scope_key,cursor=cur)
            recipe = {'schema':BINDING, 'request':request, 'fingerprint':loaded['fingerprint'], 'actor_id':actor_id,
                      'decision_cutoff':now, 'required_operations':list(OPS), 'result_id':result_id}
            binding = self.store.put_manifest(scope_key,[{'scope_key':scope_key,'node_id':sid} for sid in dict.fromkeys(c['source_id'] for c in request)],
                decision_cutoff=now,available_at=now,retention_until=loaded['expires_at'],recipe=recipe,cursor=cur)
            control = {**recipe,'workspace_id':workspace_id,'binding_manifest_id':binding['manifest_id'], 'method':method}
            job = self.jobs.enqueue(scope_key,KIND,control,idempotency_key=key,max_attempts=1,cursor=cur)
            return {'state':job['state'],'job_id':job['job_id'],'result_id':result_id}

    def _current(self, cur, control, *, deploy=False, actor_id=None):
        loaded = self._load(cur,control['workspace_id'],actor_id or control['actor_id'],control['request'],
                            decision_cutoff=control['decision_cutoff'],deploy=deploy,write=deploy)
        if loaded['fingerprint'] != control['fingerprint']: _deny('input_changed')
        self.store.get_manifest('workspace:'+control['workspace_id'],control['binding_manifest_id'],cursor=cur)
        return loaded

    def _stage(self, directory, workspace_id, loaded, authorize, storage):
        """Only the existing authenticated storage adapter; no supplied URLs."""
        files = {}
        for clip in loaded['runtime']['clips']:
            asset = loaded['media'][clip['clip_id']]
            authorize(None)
            credit_admission.require_dispatch(self.store, workspace_id)
            info = storage.object_info(workspace_id,'video',asset['objectName'])
            expected = {'bytes':asset['bytes'],'mime':asset['mime'],'etag':asset['etag']}
            if info != expected: _deny('asset_changed_before_read')
            authorize(None)
            credit_admission.require_dispatch(self.store, workspace_id)
            chunk = storage.read_range(workspace_id,'video',asset['objectName'],0,asset['bytes'])
            data = chunk.get('data')
            if not isinstance(data,bytes) or len(data) != asset['bytes']: _deny('asset_byte_bound')
            if hashlib.sha256(data).hexdigest() != clip['media_sha256']: _deny('asset_digest_mismatch')
            authorize(None)
            credit_admission.require_dispatch(self.store, workspace_id)
            if storage.object_info(workspace_id,'video',asset['objectName']) != info: _deny('asset_changed_during_read')
            name = clip['clip_id']+'.mp4'
            path = Path(directory)/name
            with path.open('xb') as f: f.write(data)
            path.chmod(0o600)
            files[clip['clip_id']] = {'media':name}
        return files

    @staticmethod
    def _pattern(result, loaded):
        """Adapt deterministic results to the existing creative-pattern builder."""
        manifest = result.manifest; now = manifest['computed_at']; clips=[]; sources={}
        for clip in manifest['clips']:
            if clip.get('metadata',{}).get('state') != 'available': continue
            source = loaded['snapshot']['sources'][clip['source_id']]
            common = {'available_at':source['available_at'],'expires_at':manifest['expires_at'], 'evidence_refs':[clip['source_id']]}
            sources[clip['source_id']]={'source_id':clip['source_id'],'scope_key':manifest['scope_key'],
                'available_at':source['available_at'],'expires_at':manifest['expires_at'],'event_at':source['available_at'],
                'time_basis':'source_availability','original':False,'platform':'workspace_supplied_media',
                'rights':{'analysis':True,'creative':True,'llm':False,**{m:v['state']=='available' for m,v in clip['modalities'].items()}}}
            frames = [{**f,**common} for f in clip['modalities']['visual']['items']]
            extracted = {}
            for m,v in clip['modalities'].items():
                extracted[m] = [{'quality':v.get('quality'),**item,**common,'method_version':manifest['method']['version'],
                    **({'start_seconds':item['at_seconds'],'end_seconds':item['at_seconds'],'frame_ref':item['frame_id'],
                        'descriptor':{'width':item['width'],'height':item['height']}} if m=='visual' else {})} for item in v['items']]
            clips.append({**common,'clip_id':clip['clip_id'],'duration_seconds':clip['metadata']['duration_seconds'],
                'size_bytes':loaded['media'][clip['clip_id']]['bytes'],'processing_tokens':0,'processing_seconds':0,'estimated_cost':0,
                'available_modalities':[m for m,v in clip['modalities'].items() if v['state']=='available'],
                'keyframes':frames,'extractions':extracted})
        caps = loaded['runtime']['limits']
        return creative_patterns.build_creative_pattern({'scope_key':manifest['scope_key'],'decision_cutoff':now,'sources':list(sources.values()),'clips':clips,
            'limits':{'max_bytes':caps['max_bytes'],'max_tokens':caps['max_tokens'],'max_processing_seconds':caps['max_processing_seconds'],'max_cost':0}})

    def run(self, scope_key, job_id, *, deadline=None):
        scope_key=contracts.scope(scope_key); job_id=contracts.uuid(job_id)
        if not scope_key.startswith('workspace:') or not self.enabled(scope_key[10:]): return {'state':'disabled'}
        started=time.monotonic()
        if deadline is not None: media_storage.remaining(deadline)
        deadline=min(started+180,deadline) if deadline is not None else started+180
        claim=None
        try:
            with self.store.transaction() as cur:
                cur.execute('SELECT * FROM pr_trend_jobs WHERE scope_key=%s AND job_id=%s',(scope_key,job_id)); saved=row(cur)
                if not saved or saved['kind']!=KIND: _deny('job_unavailable')
                if saved['state'] in ('succeeded','failed_terminal','cancelled','outcome_unknown'):
                    return {'state':saved['state'],'job_id':job_id,'replayed':True}
                control=saved['payload']
                if control['method']!=method_identity(): _deny('method_changed')
                loaded=self._current(cur,control,deploy=True)
                media_storage.remaining(deadline)
                claim=self.jobs.claim('media-local',scope_key=scope_key,kind=KIND,job_id=job_id,lease_seconds=300,cursor=cur)
                if not claim: return {'state':'busy','job_id':job_id}
                claim=self.jobs.start(claim,cursor=cur)
            def authorize(_job):
                media_storage.remaining(deadline)
                if not self.enabled(scope_key[10:]): _deny('disabled')
                with self.store.transaction() as cur:
                    current=self._current(cur,control,deploy=True)
                    self.jobs._fence(cur,claim)
                    media_storage.remaining(deadline)
                    return current['snapshot']
            # All storage transport and decoder work occurs after start commits.
            authorize(None)
            storage=self.storage_factory(getattr(getattr(self.hosted,'assets',None),'storage',None),deadline=deadline)
            with tempfile.TemporaryDirectory(prefix='rafii-trend-media-') as directory:
                files=self._stage(directory,scope_key[10:],loaded,authorize,storage)
                runtime=self.runtime_factory(Path(directory).resolve(),values=self.values,clock=self.clock)
                runtime_job=deepcopy(loaded['runtime']); runtime_job['job_id']=job_id
                runtime_job['limits']['max_processing_seconds']=min(runtime_job['limits']['max_processing_seconds'],media_storage.remaining(deadline))
                result=runtime.execute(runtime_job,files,authorize=authorize)
            media_storage.remaining(deadline)
            if result.manifest['state']!='extracted': _deny('extractor_unavailable')
            with self.store.transaction() as cur:
                if not self.enabled(scope_key[10:]): _deny('disabled')
                current=self._current(cur,control,deploy=True)
                self.jobs._fence(cur,claim)
                media_storage.remaining(deadline)
                at=self.clock(); expiry=min(current['expires_at'],result.manifest['expires_at'],key=contracts.instant)
                if contracts.instant(expiry)<=contracts.instant(at): _deny('expired')
                pattern=self._pattern(result,current)
                document={'extraction':result.manifest,'pattern':pattern,
                          'artifacts':{k:base64.b64encode(v).decode('ascii') for k,v in result.artifacts.items()}}
                document['manifest_digest']=contracts.digest(document)
                codec,chunks=encode_manifest(document)
                sealed=self.store.put_manifest(scope_key,[{'scope_key':scope_key,'node_id':control['binding_manifest_id']}],
                    decision_cutoff=at,available_at=at,retention_until=expiry,
                    recipe={**codec,'schema':RESULT,'control':control,'required_operations':list(OPS)},chunks=chunks,
                    document_digest=document['manifest_digest'],cursor=cur)
                method=control['method']
                self.store.put_method(method['method_id'],method['method_version'],method['artifact_digest'],
                    {'execution':'local_deterministic','semantic_qualification':'unqualified'},cursor=cur)
                thin={'job_id':job_id,'result_id':control['result_id'],'manifest_id':sealed['manifest_id'],
                      'state':'extracted','clip_count':len(result.manifest['clips']), 'qualification':'unqualified'}
                self.store.put_projection({'scope_key':scope_key,'kind':PROJECTION,'object_id':control['result_id'],'revision':1,
                    'manifest_id':sealed['manifest_id'],**{k:method[k] for k in ('method_id','method_version')},
                    'decision_cutoff':at,'available_at':at,'retention_until':expiry,'payload':thin},expected_revision=0,cursor=cur)
                self.jobs.finish_local(claim,cursor=cur)
                media_storage.remaining(deadline)  # Expiration rolls back the complete output transaction.
            return thin
        except Exception:
            if claim:
                try: self.jobs.fail(claim,code='local_media_failed',proven_unbilled=True)
                except contracts.ContractError: pass
            elif 'saved' in locals() and saved and saved['state'] in ('queued','retry_wait'):
                self.jobs.cancel(scope_key,job_id)
            raise

    def read(self, workspace_id, actor_id, result_id):
        workspace_id,actor_id,result_id=map(contracts.uuid,(workspace_id,actor_id,result_id))
        if not self.enabled(workspace_id): _deny('disabled')
        with self.store.transaction() as cur:
            projection=self.store.get_projection(workspace_id,actor_id,PROJECTION,result_id,cursor=cur)
            if not projection or projection['scope_key']!='workspace:'+workspace_id or projection['validity']!='valid': _deny('result_unavailable')
            if not all(projection['policy'].get(k) is True for k in ('display_excerpt','display_link')): _deny('display_denied')
            mid=projection['payload']['manifest_id']
            # Read only bounded control metadata until the independent media
            # grants are revalidated; get_manifest would load the raw chunks.
            cur.execute('SELECT recipe FROM pr_trend_input_manifests WHERE scope_key=%s AND manifest_id=%s',(projection['scope_key'],mid))
            recipe=cur.fetchone()[0]
            if recipe.get('schema')!=RESULT: _deny('result_contract')
            loaded=self._current(cur,recipe['control'],actor_id=actor_id)
            if not all(contracts.permits(s[k],'display_excerpt',s['scope_key'],self.clock())
                       for s in loaded['snapshot']['sources'].values() for k in ('rights','policy_rights')):
                _deny('display_denied')
            return decode_manifest(self.store.get_manifest(projection['scope_key'],mid,cursor=cur))

    def sweep(self, *, limit=100, workspace_id=None):
        """Flags-independent current asset/raw/modality invalidation + canonical purge."""
        if type(limit) is not int or not 1<=limit<=100: _deny('sweep_bound')
        selected_scope = 'workspace:'+contracts.uuid(workspace_id) if workspace_id else None
        invalid = scanned = 0
        with self.store.transaction() as cur:
            # Serialize only sweepers. Stable per-workspace keysets prevent a
            # page of healthy roots from starving later revoked media forever.
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('trend-media-sweep-v1',0))")
            if not cur.fetchone()[0]: return {'invalidated':0,'scanned':0,'state':'busy'}
            cur.execute("""SELECT s.scope_key FROM pr_trend_scopes s
                LEFT JOIN pr_trend_provider_cursors c ON c.scope_key=s.scope_key AND c.provider_id=%s AND c.partition_key=%s
                WHERE s.workspace_id IS NOT NULL AND (%s::text IS NULL OR s.scope_key=%s)
                AND EXISTS(SELECT 1 FROM pr_trend_input_manifests m JOIN pr_trend_nodes n
                    ON(n.scope_key,n.node_id)=(m.scope_key,m.manifest_id)
                    WHERE m.scope_key=s.scope_key AND m.recipe->>'schema'=%s AND n.validity='valid')
                ORDER BY c.updated_at NULLS FIRST,s.scope_key LIMIT 1""",
                (SCAN_PROVIDER,SCAN_PARTITION,selected_scope,selected_scope,BINDING))
            selected = cur.fetchone()
            if selected:
                scope_key = selected[0]
                cur.execute("INSERT INTO pr_trend_provider_cursors(scope_key,provider_id,partition_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                            (scope_key,SCAN_PROVIDER,SCAN_PARTITION))
                cur.execute("SELECT generation,cursor_value FROM pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE",
                            (scope_key,SCAN_PROVIDER,SCAN_PARTITION))
                generation,checkpoint=cur.fetchone()
                after=checkpoint.get('after_manifest_id')
                if after is not None: after=contracts.uuid(after)
            else:
                scope_key=after=None
            cur.execute("""SELECT m.scope_key,m.manifest_id::text,m.recipe FROM pr_trend_input_manifests m JOIN pr_trend_nodes n
                ON(n.scope_key,n.node_id)=(m.scope_key,m.manifest_id) WHERE m.recipe->>'schema'=%s AND n.validity='valid'
                AND m.scope_key=%s AND (%s::uuid IS NULL OR m.manifest_id>%s::uuid)
                ORDER BY m.manifest_id LIMIT %s""",(BINDING,scope_key,after,after,limit+1))
            found=rows(cur); candidates=found[:limit]; scanned=len(candidates)
            for candidate in candidates:
                recipe=candidate['recipe']
                try:
                    loaded=self._load(cur,candidate['scope_key'][10:],None,recipe['request'],decision_cutoff=recipe['decision_cutoff'])
                    if loaded['fingerprint']!=recipe['fingerprint']: _deny('input_changed')
                except (contracts.ContractError,KeyError,TypeError):
                    _revoke(cur,candidate['scope_key'],[candidate['manifest_id']]); invalid+=1
            if selected:
                checkpoint={'after_manifest_id':candidates[-1]['manifest_id'] if len(found)>limit else None}
                cur.execute("""UPDATE pr_trend_provider_cursors SET generation=generation+1,cursor_value=%s::jsonb,
                    updated_at=clock_timestamp() WHERE scope_key=%s AND provider_id=%s AND partition_key=%s AND generation=%s RETURNING generation""",
                    (json.dumps(checkpoint),scope_key,SCAN_PROVIDER,SCAN_PARTITION,generation))
                if not cur.fetchone(): _deny('sweep_cursor_conflict')
        return {'invalidated':invalid,'scanned':scanned,**retention.sweep(self.store,limit=limit)}
