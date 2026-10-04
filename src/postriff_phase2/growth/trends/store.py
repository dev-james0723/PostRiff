"""Durable trend storage. No network, provider dispatch, workspace blob storage or implicit rights.

Public reads require an authenticated actor. Worker writes require trusted server code.
Every method accepts cursor= to participate in the caller's existing transaction.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import math
import uuid as uuidlib

from psycopg.types.json import Jsonb
from .contracts import (ContractError, canonical, digest, instant, iso, permits, scope,
                        uuid, validate_observation, validate_rights, VERIFICATION_STATES)


class TrendStorageError(ContractError):
    pass


# Match observation admission. Metadata and licensed aggregate evidence do not
# acquire a raw-content requirement merely by sharing a provider.
STORAGE_PERMISSION_SQL = """CASE WHEN o.kind='aggregate_metric' THEN 'store_metrics'
    WHEN coalesce(o.payload->>'text','')<>'' THEN 'store_raw' ELSE 'retrieve' END"""


def utcnow():
    return iso(datetime.now(timezone.utc))


def identity_digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def json_value(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, uuidlib.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def row(cur):
    value = cur.fetchone()
    if value is None:
        return None
    return json_value(value if isinstance(value, dict) else dict(zip([c.name for c in cur.description], value)))


def rows(cur):
    names = [c.name for c in cur.description]
    return [json_value(v if isinstance(v, dict) else dict(zip(names, v))) for v in cur.fetchall()]


def bounded_json(value, size=65536):
    if not isinstance(value, dict) or len(canonical(value).encode()) > size:
        raise TrendStorageError('payload_limit')
    return Jsonb(value)


def trust_lock(cur, *, exclusive=False):
    """Serialize accepted mutations with insertion of previously absent tombstones.

    Row locks below also cover direct policy/entitlement revocation. The advisory
    lock covers phantom source/author tombstones which cannot yet be row-locked.
    """
    fn = 'pg_advisory_xact_lock' if exclusive else 'pg_advisory_xact_lock_shared'
    cur.execute('SELECT '+fn+"(hashtextextended('trend-trust-mutation',0))")


def aggregate_payload(payload):
    """Allow only known numeric aggregate fields across an excerpt/link-denied boundary.

    Neither arbitrary nested strings nor provider-controlled dictionary keys are
    safe merely because they sit under a field named metrics or coverage.
    """
    wrappers = {'metrics','calculated','observed','counts','coverage','window',
                'mention_rate','discovery_rate','growth','acceleration','velocity'}
    numbers = {'value','delta','elapsed_hours','window_hours','received_count','qualifying_original_count',
               'discovery_count','excluded_count','copy_redundancy_count','known_creator_count',
               'known_author_post_count','unknown_author_fraction','creator_entropy','effective_creators',
               'concentration_effective_creators','largest_creator_share','eligible_count','classified_count'}
    enums = {'unit':{'posts','posts/hour','discoveries/hour','fraction','count','hours','percent'},
             'availability':{'available','unavailable','unknown'},
             'completeness':{'complete_within_scope','partial','unknown','gapped'},
             'data_state':{'qualified','insufficient','unknown'}}
    result = {}
    for key,value in payload.items():
        if key in wrappers and isinstance(value,dict):
            result[key] = aggregate_payload(value)
        elif key in numbers and (value is None or type(value) in (int,float) and math.isfinite(value)):
            result[key] = value
        elif key in enums and isinstance(value,str) and value in enums[key]:
            result[key] = value
    return result


class TrendStore:
    def __init__(self, connection_factory, *, offline_replay=False, hosted=None):
        self.connection_factory = connection_factory
        self.offline_replay = offline_replay
        # Trusted server binding, never a workspace blob or client plan label.
        # Unbound stores retain saved/manual reads but cannot admit paid I/O.
        self.hosted = hosted

    @contextmanager
    def transaction(self, cursor=None):
        if cursor is not None:
            yield cursor
        else:
            with self.connection_factory() as db, db.transaction(), db.cursor() as cur:
                yield cur

    def _actor(self, cur, workspace_id, actor_id, write=False):
        workspace_id, actor_id = uuid(workspace_id), uuid(actor_id)
        cur.execute("""SELECT m.role FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
            JOIN public.pr_workspaces w ON w.id=m.workspace_id
            WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL
            AND NOT w.state ? 'accountDeletion' FOR SHARE OF m,p,w""", (workspace_id, actor_id))
        found = row(cur)
        if not found or (write and found['role'] not in ('owner', 'editor')):
            raise TrendStorageError('workspace_access_denied')
        return workspace_id, actor_id

    def authorized_scopes(self, workspace_id, actor_id, *, cursor=None):
        with self.transaction(cursor) as cur:
            wid, _ = self._actor(cur, workspace_id, actor_id)
            cur.execute("""SELECT s.scope_key FROM public.pr_trend_scopes s WHERE s.enabled AND
                (s.workspace_id=%s OR (s.workspace_id IS NULL AND EXISTS(SELECT 1 FROM public.pr_trend_entitlements e
                WHERE e.workspace_id=%s AND e.scope_key=s.scope_key AND e.revoked_at IS NULL
                AND e.expires_at>clock_timestamp() AND 'retrieve'=ANY(e.operations)))) ORDER BY s.scope_key""", (wid, wid))
            return [r['scope_key'] for r in rows(cur)]

    def scope_signature(self, workspace_id, actor_id, *, cursor=None):
        with self.transaction(cursor) as cur:
            scopes = self.authorized_scopes(workspace_id, actor_id, cursor=cur)
            cur.execute('SELECT scope_key,operations,expires_at,revoked_at FROM public.pr_trend_entitlements WHERE workspace_id=%s ORDER BY scope_key', (workspace_id,))
            return digest({'scopes': scopes, 'entitlements': rows(cur)})

    def ensure_scope(self, scope_key, *, cursor=None):
        scope(scope_key)
        wid = scope_key[10:] if scope_key.startswith('workspace:') else None
        with self.transaction(cursor) as cur:
            cur.execute('INSERT INTO public.pr_trend_scopes(scope_key,workspace_id) VALUES(%s,%s) ON CONFLICT DO NOTHING', (scope_key, wid))
        return scope_key

    def grant_entitlement(self, workspace_id, scope_key, operations, expires_at, *, cursor=None):
        scope(scope_key); uuid(workspace_id); instant(expires_at)
        if not scope_key.startswith('shared:') or not operations or not set(operations) <= {'retrieve', 'derive_metrics', 'share_across_workspaces'}:
            raise TrendStorageError('invalid_entitlement')
        with self.transaction(cursor) as cur:
            cur.execute("""INSERT INTO public.pr_trend_entitlements(workspace_id,scope_key,operations,expires_at)
                VALUES(%s,%s,%s,%s) ON CONFLICT(workspace_id,scope_key) DO UPDATE SET
                operations=excluded.operations,expires_at=excluded.expires_at,revoked_at=NULL""", (workspace_id, scope_key, operations, expires_at))

    def register_contract(self, provider_id, version, operations, valid_from, expires_at, manifest=None, *, cursor=None):
        instant(valid_from); instant(expires_at)
        manifest = manifest or {}
        with self.transaction(cursor) as cur:
            cur.execute("""INSERT INTO public.pr_trend_provider_contracts(provider_id,version,operations,valid_from,expires_at,manifest)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING version""", (provider_id,version,operations,valid_from,expires_at,bounded_json(manifest)))
            if not row(cur):
                cur.execute('SELECT operations,valid_from,expires_at,manifest FROM public.pr_trend_provider_contracts WHERE provider_id=%s AND version=%s', (provider_id, version))
                existing = row(cur)
                if existing != {'operations': operations, 'valid_from': iso(instant(valid_from)), 'expires_at': iso(instant(expires_at)), 'manifest': manifest}:
                    raise TrendStorageError('immutable_contract_conflict')

    def register_policy(self, policy, *, provider_contract_version, cursor=None):
        p = asdict(policy) if is_dataclass(policy) else dict(policy)
        scope(p['scope_key']); validate_rights(p['rights'])
        operations = [name for name, grant in p['rights'].items() if grant['state']=='allow']
        start = p.get('effective_at', p.get('valid_from'))
        instant(start); instant(p['expires_at'])
        with self.transaction(cursor) as cur:
            self.ensure_scope(p['scope_key'], cursor=cur)
            cur.execute("""INSERT INTO public.pr_trend_source_policies
                (scope_key,provider_id,version,provider_contract_version,operations,rights,readiness,valid_from,expires_at,max_retention_seconds,manifest)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING version""",
                (p['scope_key'],p['provider_id'],p['version'],provider_contract_version,operations,bounded_json(p['rights']),
                 p.get('readiness','access_pending'),start,p['expires_at'],p['retention_seconds'],bounded_json(p)))
            if not row(cur):
                cur.execute('SELECT manifest,provider_contract_version FROM public.pr_trend_source_policies WHERE scope_key=%s AND provider_id=%s AND version=%s', (p['scope_key'],p['provider_id'],p['version']))
                old = row(cur)
                if old['manifest'] != p or old['provider_contract_version'] != provider_contract_version:
                    raise TrendStorageError('immutable_policy_conflict')

    def _policy(self, cur, scope_key, provider_id, version, permission='retrieve', at=None):
        trust_lock(cur)
        at = at or utcnow()
        cur.execute("""SELECT p.*,c.revoked_at AS contract_revoked,c.valid_from AS contract_start,c.expires_at AS contract_end,
            c.operations AS contract_operations,c.available_at AS contract_available_at,c.manifest AS contract_manifest FROM public.pr_trend_source_policies p
            JOIN public.pr_trend_provider_contracts c ON (c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
            JOIN public.pr_trend_scopes s USING(scope_key) WHERE p.scope_key=%s AND p.provider_id=%s AND p.version=%s
            AND s.enabled FOR SHARE OF p,c,s""", (scope_key,provider_id,version))
        p = row(cur)
        if (not p or p['revoked_at'] or p['contract_revoked'] or p['readiness']!='ready'
            or not instant(p['valid_from']) <= instant(at) < instant(p['expires_at'])
            or not instant(p['contract_start']) <= instant(at) < instant(p['contract_end'])
            or permission not in p['contract_operations'] or not permits(p['rights'],permission,scope_key,at)):
            raise TrendStorageError('source_policy_denied')
        if not self.offline_replay:
            available = max(instant(p['available_at']),instant(p['contract_available_at']))
            if available>instant(at):
                raise TrendStorageError('source_policy_not_yet_available')
            # Pure recomputation consumes this manifest; caller-supplied review
            # dates cannot substitute for durable policy/contract availability.
            p['manifest'] = {**p['manifest'],'available_at':iso(available)}
        return p

    def put_observation(self, observation, *, cursor=None):
        o = validate_observation(observation)
        with self.transaction(cursor) as cur:
            if not self.offline_replay:
                cur.execute('SELECT clock_timestamp() AS available_at')
                o['available_at'] = row(cur)['available_at']
                if instant(o['received_at'])>instant(o['available_at']):
                    raise TrendStorageError('future_received_at')
            if o['operation']=='delete':
                from .revocation import revoke_source
                return revoke_source(self,o['scope_key'],o['provider_id'],o['source_identity'],
                    deletion_sequence=o['revision_sequence'],reason_code='provider_delete',purge_deadline=o['retention_until'],cursor=cur)
            now = utcnow(); p = self._policy(cur,o['scope_key'],o['provider_id'],o['source_policy_version'],at=now)
            author = o['payload'].get('author_key')
            if author:
                author_hash = identity_digest(author)
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('trend-author|'+o['provider_id']+'|'+author_hash,))
                cur.execute('SELECT 1 FROM public.pr_trend_author_tombstones WHERE provider_id=%s AND author_digest=%s',(o['provider_id'],author_hash))
                if cur.fetchone():
                    raise TrendStorageError('author_deleted')
            from .providers.registry import contract_runtime_version
            if contract_runtime_version(p['provider_contract_version'], p.get('contract_manifest') or {}) != o['provider_contract_version']:
                raise TrendStorageError('provider_contract_mismatch')
            if not permits(o['rights'],'retrieve',o['scope_key'],now):
                raise TrendStorageError('source_right_not_permitted')
            permission = 'store_metrics' if o['kind']=='aggregate_metric' else 'store_raw' if o['payload'].get('text') else 'retrieve'
            if (permission not in p['operations'] or permission not in p['contract_operations']
                or not permits(o['rights'],permission,o['scope_key'],now) or not permits(p['rights'],permission,o['scope_key'],now)):
                raise TrendStorageError('source_storage_denied')
            if instant(o['retention_until']) > instant(p['expires_at']) or (instant(o['retention_until'])-instant(o['received_at'])).total_seconds()>p['max_retention_seconds']:
                raise TrendStorageError('retention_exceeds_policy')
            key = identity_digest(o['source_identity'])
            # Same source lock orders deletion-before-create and competing revisions.
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (o['scope_key']+'|'+o['provider_id']+'|'+key,))
            cur.execute('SELECT 1 FROM public.pr_trend_deletion_tombstones WHERE scope_key=%s AND provider_id=%s AND source_identity_digest=%s', (o['scope_key'],o['provider_id'],key))
            if cur.fetchone():
                raise TrendStorageError('source_deleted')
            cur.execute('SELECT observation_id,payload_digest,revision_sequence FROM public.pr_trend_observations WHERE scope_key=%s AND provider_id=%s AND source_identity_digest=%s AND revision_identity=%s', (o['scope_key'],o['provider_id'],key,o['revision_identity']))
            prior = row(cur)
            if prior:
                if prior['payload_digest'] != o['payload_digest'] or prior['revision_sequence'] != o['revision_sequence']:
                    raise TrendStorageError('observation_identity_collision')
                return {'observation_id':prior['observation_id'],'inserted':False}
            self._node(cur,o['scope_key'],o['observation_id'],'observation',o['available_at'],o['retention_until'])
            pld = o['payload']; is_aggregate = o['kind']=='aggregate_metric'
            columns = ('scope_key','observation_id','provider_id','source_identity','source_identity_digest','revision_identity','revision_sequence',
                'kind','operation','event_at','received_at','available_at','retention_until','coverage_epoch','source_policy_version','provider_contract_version',
                'rights','payload','payload_digest','schema_version','time_basis','provenance','deletion_key','native_item_id','author_key','author_status','canonical_url',
                'aggregate_start','aggregate_end','metric_id','metric_unit','metric_value','metric_null_reason','population','aggregation_semantics')
            values = [o.get(k) for k in columns[:16]] + [bounded_json(o['rights']),bounded_json(pld),o['payload_digest'],o['schema_version'],o['time_basis'],bounded_json(o['provenance']),o['deletion_key'],
                pld.get('native_id'),pld.get('author_key'),pld.get('author_status'),pld.get('canonical_url'),
                pld.get('window_start') if is_aggregate else None,pld.get('window_end') if is_aggregate else None,
                pld.get('metric_definition') if is_aggregate else None,pld.get('unit') if is_aggregate else None,pld.get('value') if is_aggregate else None,
                pld.get('null_reason') if is_aggregate else None,pld.get('population') if is_aggregate else None,pld.get('aggregation_semantics') if is_aggregate else None]
            values[4] = key
            cur.execute('INSERT INTO public.pr_trend_observations('+','.join(columns)+') VALUES('+','.join(['%s']*len(columns))+')',values)
            cur.execute("""INSERT INTO public.pr_trend_source_heads(scope_key,provider_id,source_identity_digest,revision_sequence,observation_id)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(scope_key,provider_id,source_identity_digest) DO UPDATE SET
                revision_sequence=excluded.revision_sequence,observation_id=excluded.observation_id
                WHERE pr_trend_source_heads.revision_sequence<excluded.revision_sequence""", (o['scope_key'],o['provider_id'],key,o['revision_sequence'],o['observation_id']))
            return {'observation_id':o['observation_id'],'inserted':True,'available_at':o['available_at']}

    def _node(self, cur, scope_key, node_id, kind, available_at, retention_until):
        scope(scope_key); uuid(node_id); instant(available_at); instant(retention_until)
        cur.execute('INSERT INTO public.pr_trend_nodes(scope_key,node_id,node_kind,available_at,retention_until) VALUES(%s,%s,%s,%s,%s)', (scope_key,node_id,kind,available_at,retention_until))

    def add_dependency(self, scope_key, node_id, input_scope_key, input_node_id, *, cursor=None):
        with self.transaction(cursor) as cur:
            cur.execute('INSERT INTO public.pr_trend_dependencies(scope_key,node_id,input_scope_key,input_node_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(scope_key,node_id,input_scope_key,input_node_id))

    def put_manifest(self, scope_key, inputs, *, decision_cutoff, available_at, retention_until, manifest_id=None,
                     recipe=None, chunks=(), document_digest=None, cursor=None):
        if not inputs or len(inputs)>1000:
            raise TrendStorageError('manifest_input_limit')
        manifest_id = uuid(manifest_id or uuidlib.uuid4())
        inputs = [{'scope_key':scope(x['scope_key']),'node_id':uuid(x.get('node_id',x.get('observation_id')))} for x in inputs]
        recipe = recipe or {}
        bounded_json(recipe)
        if len(chunks)>512:
            raise TrendStorageError('manifest_chunk_limit')
        for chunk in chunks:
            bounded_json(chunk)
        manifest_hash = digest({'inputs':inputs,'recipe':recipe,'chunks':[digest(c) for c in chunks]})
        if len({(x['scope_key'],x['node_id']) for x in inputs}) != len(inputs):
            raise TrendStorageError('duplicate_manifest_input')
        with self.transaction(cursor) as cur:
            trust_lock(cur)
            if not self.offline_replay:
                cur.execute('SELECT clock_timestamp() AS available_at')
                available_at = row(cur)['available_at']
            self._node(cur,scope_key,manifest_id,'manifest',available_at,retention_until)
            cur.execute('INSERT INTO public.pr_trend_input_manifests(scope_key,manifest_id,digest,decision_cutoff,input_count,recipe,document_digest) VALUES(%s,%s,%s,%s,%s,%s,%s)',(scope_key,manifest_id,manifest_hash,decision_cutoff,len(inputs),bounded_json(recipe),document_digest))
            for ordinal,chunk in enumerate(chunks):
                cur.execute('INSERT INTO public.pr_trend_manifest_chunks(scope_key,manifest_id,ordinal,digest,payload) VALUES(%s,%s,%s,%s,%s)',(scope_key,manifest_id,ordinal,digest(chunk),bounded_json(chunk)))
            for ordinal, item in enumerate(inputs):
                cur.execute('SELECT available_at,retention_until,postriff_private.trend_node_valid(scope_key,node_id) AS valid FROM public.pr_trend_nodes WHERE scope_key=%s AND node_id=%s FOR SHARE',(item['scope_key'],item['node_id']))
                n = row(cur)
                if not n or not n['valid'] or instant(n['available_at'])>instant(decision_cutoff) or instant(retention_until)>instant(n['retention_until']):
                    raise TrendStorageError('manifest_input_invalid')
                self.add_dependency(scope_key,manifest_id,item['scope_key'],item['node_id'],cursor=cur)
                cur.execute('INSERT INTO public.pr_trend_manifest_inputs(scope_key,manifest_id,ordinal,input_scope_key,input_node_id) VALUES(%s,%s,%s,%s,%s)',(scope_key,manifest_id,ordinal,item['scope_key'],item['node_id']))
            cur.execute('SELECT postriff_private.trend_node_valid(%s,%s) AS valid',(scope_key,manifest_id))
            if not row(cur)['valid'] or not self._storage_current(cur,scope_key,manifest_id):
                raise TrendStorageError('manifest_dependency_rights_denied')
            return {'scope_key':scope_key,'manifest_id':manifest_id,'digest':manifest_hash,'document_digest':document_digest}

    def get_manifest(self, scope_key, manifest_id, *, cursor=None):
        """Trusted worker API, not a browser endpoint. All current dependency rights are rechecked."""
        with self.transaction(cursor) as cur:
            cur.execute('SELECT m.*,postriff_private.trend_node_valid(scope_key,manifest_id) AS valid FROM public.pr_trend_input_manifests m WHERE scope_key=%s AND manifest_id=%s',(scope_key,manifest_id))
            manifest = row(cur)
            if not manifest or not manifest['valid'] or not self._storage_current(cur,scope_key,manifest_id):
                raise TrendStorageError('manifest_unavailable')
            cur.execute('SELECT input_scope_key AS scope_key,input_node_id AS node_id FROM public.pr_trend_manifest_inputs WHERE scope_key=%s AND manifest_id=%s ORDER BY ordinal',(scope_key,manifest_id))
            manifest['inputs'] = rows(cur)
            cur.execute('SELECT ordinal,digest,payload FROM public.pr_trend_manifest_chunks WHERE scope_key=%s AND manifest_id=%s ORDER BY ordinal',(scope_key,manifest_id))
            manifest['chunks'] = rows(cur)
            return manifest

    def _storage_current(self, cur, scope_key, node_id):
        """Current independent storage grants, including full recipe ancestors."""
        cur.execute(f'''WITH RECURSIVE a(scope_key,node_id) AS (
            SELECT %s::text,%s::uuid UNION SELECT d.input_scope_key,d.input_node_id
            FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
            SELECT NOT EXISTS(SELECT 1 FROM a JOIN public.pr_trend_observations o
                ON(o.scope_key,o.observation_id)=(a.scope_key,a.node_id)
                JOIN public.pr_trend_source_policies p ON(p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
                JOIN public.pr_trend_provider_contracts c ON(c.provider_id,c.version)=(o.provider_id,o.provider_contract_version)
                CROSS JOIN LATERAL (SELECT {STORAGE_PERMISSION_SQL} AS permission) grant_op
                WHERE NOT grant_op.permission=ANY(p.operations) OR NOT grant_op.permission=ANY(c.operations)
                 OR NOT postriff_private.trend_permits(o.rights,grant_op.permission,o.scope_key)
                 OR NOT postriff_private.trend_permits(p.rights,grant_op.permission,o.scope_key)) AS allowed''',(scope_key,node_id))
        return row(cur)['allowed']

    def put_method(self, method_id, version, artifact_digest, config, *, qualification='shadow', cursor=None):
        if qualification!='shadow':
            raise TrendStorageError('method_requires_explicit_promotion')
        with self.transaction(cursor) as cur:
            cur.execute('INSERT INTO public.pr_trend_method_versions(method_id,version,artifact_digest,config,qualification) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING version',(method_id,version,artifact_digest,bounded_json(config),qualification))
            if not row(cur):
                cur.execute('SELECT artifact_digest,config FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s',(method_id,version))
                if row(cur)!={'artifact_digest':artifact_digest,'config':config}:
                    raise TrendStorageError('immutable_method_conflict')

    def _derived(self, cur, value, node_id, kind):
        trust_lock(cur)
        if not self.offline_replay:
            cur.execute('SELECT clock_timestamp() AS available_at')
            value['available_at'] = row(cur)['available_at']
        self._node(cur,value['scope_key'],node_id,kind,value['available_at'],value['retention_until'])
        cur.execute("""SELECT n.available_at,n.retention_until,m.decision_cutoff,postriff_private.trend_node_valid(n.scope_key,n.node_id) AS valid
            FROM public.pr_trend_input_manifests m JOIN public.pr_trend_nodes n ON(n.scope_key,n.node_id)=(m.scope_key,m.manifest_id)
            WHERE m.scope_key=%s AND m.manifest_id=%s FOR SHARE OF m,n""", (value['scope_key'],value['manifest_id']))
        manifest = row(cur)
        if (not manifest or not manifest['valid'] or instant(manifest['decision_cutoff'])>instant(value['decision_cutoff'])
            or instant(value['retention_until'])>instant(manifest['retention_until'])):
            raise TrendStorageError('derived_manifest_invalid')
        cur.execute('SELECT qualification,revoked_at FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s FOR SHARE',(value['method_id'],value['method_version']))
        method = row(cur)
        if not method or method['revoked_at'] or method['qualification']=='withdrawn':
            raise TrendStorageError('method_unavailable')
        self.add_dependency(value['scope_key'],node_id,value['scope_key'],value['manifest_id'],cursor=cur)
        if not self._storage_current(cur,value['scope_key'],node_id):
            raise TrendStorageError('derived_storage_rights_denied')

    def record_verification(self, scope_key, receipt_id, *, recomputed_digest, input_manifest_digest,
                            method_artifact_digest, cursor=None):
        """Persist the trusted recomputation result, bound to stored immutable inputs and method.

        Caller must invoke the canonical offline verifier; a payload's status is never evidence.
        """
        with self.transaction(cursor) as cur:
            cur.execute('''SELECT r.payload,r.manifest_id,m.digest,v.artifact_digest,
                postriff_private.trend_node_valid(r.scope_key,r.receipt_id) AS valid
                FROM public.pr_trend_trust_receipts r JOIN public.pr_trend_input_manifests m
                ON(m.scope_key,m.manifest_id)=(r.scope_key,r.manifest_id)
                JOIN public.pr_trend_method_versions v ON(v.method_id,v.version)=(r.method_id,r.method_version)
                WHERE r.scope_key=%s AND r.receipt_id=%s FOR UPDATE OF r''',(scope_key,receipt_id))
            r = row(cur)
            if not r:
                raise TrendStorageError('receipt_unavailable')
            state = 'verified' if (r['valid'] and self._storage_current(cur,scope_key,receipt_id) and digest(r['payload'])==recomputed_digest
                and r['digest']==input_manifest_digest and r['artifact_digest']==method_artifact_digest) else 'mismatch'
            record = {'receipt_digest':recomputed_digest,'manifest_digest':input_manifest_digest,
                      'method_artifact_digest':method_artifact_digest,'state':state}
            cur.execute('UPDATE public.pr_trend_trust_receipts SET verification_state=%s,verification_record=%s,verified_at=clock_timestamp() WHERE scope_key=%s AND receipt_id=%s',
                        (state,bounded_json(record),scope_key,receipt_id))
            return record

    def put_receipt(self, value, *, cursor=None):
        v = dict(value); receipt_id = uuid(v.get('receipt_id') or uuidlib.uuid4())
        if v['payload'].get('schema')!='rafii.trend-trust-receipt.v2':
            raise TrendStorageError('receipt_schema_required')
        with self.transaction(cursor) as cur:
            self._derived(cur,v,receipt_id,'receipt')
            cur.execute('INSERT INTO public.pr_trend_trust_receipts(scope_key,receipt_id,schema_version,manifest_id,method_id,method_version,decision_cutoff,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(v['scope_key'],receipt_id,v['payload']['schema'],v['manifest_id'],v['method_id'],v['method_version'],v['decision_cutoff'],bounded_json(v['payload'])))
            self.put_projection({**v,'kind':'receipt','object_id':receipt_id,'revision':v.get('revision',1),'receipt_id':receipt_id},cursor=cur)
        return receipt_id

    def put_projection(self, value, *, expected_revision=None, cursor=None):
        v = dict(value); pid = uuid(v.get('projection_id') or uuidlib.uuid4()); uuid(v['object_id'])
        if type(v['revision']) is not int or v['revision']<1:
            raise TrendStorageError('invalid_projection_revision')
        with self.transaction(cursor) as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                (v['scope_key']+'|projection|'+v['kind']+'|'+v['object_id'],))
            cur.execute('SELECT * FROM public.pr_trend_projections WHERE scope_key=%s AND kind=%s AND object_id=%s AND revision=%s',
                (v['scope_key'],v['kind'],v['object_id'],v['revision']))
            prior = row(cur)
            if prior:
                keys = ('manifest_id','receipt_id','method_id','method_version','payload','context_digest','draft_id')
                if any(prior[k]!=v.get(k) for k in keys) or instant(prior['decision_cutoff'])!=instant(v['decision_cutoff']) or instant(prior['retention_until'])!=instant(v['retention_until']):
                    raise TrendStorageError('projection_revision_conflict')
                if self._status(cur,prior)['validity']!='valid':
                    raise TrendStorageError('projection_unavailable')
                return prior['projection_id']
            if expected_revision is not None:
                if type(expected_revision) is not int or expected_revision<0 or v['revision']!=expected_revision+1:
                    raise TrendStorageError('projection_revision_conflict')
                cur.execute('SELECT coalesce(max(revision),0) AS revision FROM public.pr_trend_projections WHERE scope_key=%s AND kind=%s AND object_id=%s',
                    (v['scope_key'],v['kind'],v['object_id']))
                if row(cur)['revision']!=expected_revision:
                    raise TrendStorageError('projection_revision_conflict')
            self._derived(cur,v,pid,'projection')
            if v.get('receipt_id'):
                self.add_dependency(v['scope_key'],pid,v['scope_key'],v['receipt_id'],cursor=cur)
            cur.execute("""INSERT INTO public.pr_trend_projections(scope_key,kind,object_id,revision,projection_id,manifest_id,receipt_id,
                method_id,method_version,decision_cutoff,available_at,retention_until,payload,context_digest,draft_id,draft_revision)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (v['scope_key'],v['kind'],v['object_id'],v['revision'],pid,v['manifest_id'],v.get('receipt_id'),v['method_id'],v['method_version'],v['decision_cutoff'],v['available_at'],v['retention_until'],bounded_json(v['payload']),v.get('context_digest'),v.get('draft_id'),str(v['draft_revision']) if v.get('draft_revision') is not None else None))
        return pid

    def _status(self, cur, p):
        return self._statuses(cur,[p])[(p['scope_key'],p['projection_id'])]

    def _statuses(self, cur, projections):
        """Revalidate one bounded page in two queries, without cross-request caches."""
        if not projections:
            return {}
        scopes=[p['scope_key'] for p in projections]; ids=[p['projection_id'] for p in projections]
        cur.execute(f"""WITH RECURSIVE a(root_scope,root_id,scope_key,node_id) AS (
            SELECT s,n,s,n FROM unnest(%s::text[],%s::uuid[]) roots(s,n) UNION
            SELECT a.root_scope,a.root_id,d.input_scope_key,d.input_node_id
            FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
            SELECT a.root_scope,a.root_id,n.validity,n.retention_until,n.available_at,o.rights,o.scope_key AS source_scope,p.rights AS policy_rights,
             p.operations AS policy_operations,c.operations AS contract_operations,{STORAGE_PERMISSION_SQL} AS storage_permission,
             p.revoked_at,p.expires_at AS policy_expiry,p.readiness,c.revoked_at AS contract_revoked,c.expires_at AS contract_expiry,
             r.payload ? 'pure_receipt' AS pipeline_receipt,
             r.payload->>'membership_dependency_digest' AS membership_dependency_digest,
             r.payload->'membership_dependency_count' AS membership_dependency_count,
             EXISTS(SELECT 1 FROM public.pr_trend_deletion_tombstones t WHERE(t.scope_key,t.provider_id,t.source_identity_digest)=
             (o.scope_key,o.provider_id,o.source_identity_digest)) AS deleted
            FROM a JOIN public.pr_trend_nodes n USING(scope_key,node_id)
            LEFT JOIN public.pr_trend_observations o ON(o.scope_key,o.observation_id)=(a.scope_key,a.node_id)
            LEFT JOIN public.pr_trend_source_policies p ON(p.scope_key,p.provider_id,p.version)=(o.scope_key,o.provider_id,o.source_policy_version)
            LEFT JOIN public.pr_trend_provider_contracts c ON(c.provider_id,c.version)=(o.provider_id,o.provider_contract_version)
            LEFT JOIN public.pr_trend_trust_receipts r ON(r.scope_key,r.receipt_id)=(a.scope_key,a.node_id)""",(scopes,ids))
        by_root={(p['scope_key'],p['projection_id']):[] for p in projections}
        for a in rows(cur):
            by_root[(a['root_scope'],a['root_id'])].append(a)
        cur.execute('''SELECT p.scope_key,p.projection_id,
            postriff_private.trend_node_valid(p.scope_key,p.projection_id) AS valid,
            m.qualification,m.revoked_at AS method_revoked,r.verification_state
            FROM unnest(%s::text[],%s::uuid[]) roots(s,n)
            JOIN public.pr_trend_projections p ON(p.scope_key,p.projection_id)=(roots.s,roots.n)
            LEFT JOIN public.pr_trend_method_versions m ON(m.method_id,m.version)=(p.method_id,p.method_version)
            LEFT JOIN public.pr_trend_trust_receipts r ON(r.scope_key,r.receipt_id)=(p.scope_key,p.receipt_id)''',(scopes,ids))
        current={(r['scope_key'],r['projection_id']):r for r in rows(cur)}
        now=utcnow(); result={}
        for key,ancestors in by_root.items():
            state=current.get(key,{})
            permissions={name:bool(ancestors) for name in ('display_excerpt','display_link','derive_metrics','retain_derivatives','llm_process')}
            for a in ancestors:
                if a['source_scope']:
                    for name in permissions:
                        permissions[name] &= permits(a['rights'],name,a['source_scope'],now) and permits(a['policy_rights'],name,a['source_scope'],now)
            validity,verification='valid','pending'
            if any(a['deleted'] for a in ancestors):
                validity,verification='deleted','inputs_deleted'
            elif any(a['revoked_at'] or a['contract_revoked'] or a['validity']=='revoked' for a in ancestors):
                validity,verification='revoked','policy_revoked'
            elif any(instant(a['retention_until'])<=instant(now) or (a['policy_expiry'] and instant(a['policy_expiry'])<=instant(now)) or (a['contract_expiry'] and instant(a['contract_expiry'])<=instant(now)) for a in ancestors):
                validity,verification='expired','inputs_expired'
            elif any(a['validity']=='stale' for a in ancestors):
                validity,verification='stale','pending'
            elif (not state.get('valid') or not permissions['derive_metrics'] or not permissions['retain_derivatives']
                or any(a['source_scope'] and (a['storage_permission'] not in a['policy_operations']
                    or a['storage_permission'] not in a['contract_operations']
                    or not permits(a['rights'],a['storage_permission'],a['source_scope'],now)
                    or not permits(a['policy_rights'],a['storage_permission'],a['source_scope'],now)) for a in ancestors)):
                validity,verification='revoked','policy_revoked'
            if not state.get('qualification') or state['qualification']=='withdrawn' or state['method_revoked']:
                validity,verification='method_unavailable','method_unavailable'
            elif validity=='valid' and any(a['pipeline_receipt'] and (
                type(a['membership_dependency_count']) is not int or not 0<=a['membership_dependency_count']<=1000
                or not isinstance(a['membership_dependency_digest'],str)
                or len(a['membership_dependency_digest'])!=64
                or any(c not in '0123456789abcdef' for c in a['membership_dependency_digest'])
                or (a['membership_dependency_count']==0 and a['membership_dependency_digest']!=digest([]))) for a in ancestors):
                # A legacy pure receipt was verified without the membership DAG seal.
                # Reverification must establish that binding before any descendant read.
                validity,verification='method_unavailable','method_unavailable'
            elif validity=='valid':
                verification=state['verification_state'] or 'pending'
            result[key]={'validity':validity,'verification_state':verification,'policy':permissions}
        return result

    def _projection_row(self, cur, p, state=None):
        state = state or self._status(cur,p)
        payload = p['payload'] if state['validity']=='valid' else None
        if payload is not None and (not state['policy']['display_excerpt'] or not state['policy']['display_link']):
            # No arbitrary free text passes an aggregate-only boundary. Keep only typed numeric/coverage fields.
            payload = aggregate_payload(payload)
        return {k:p[k] for k in ('scope_key','kind','object_id','revision','available_at')} | {
            'expires_at':p['retention_until'],'method_bundle':{'method_id':p['method_id'],'version':p['method_version']},
            **state,'payload':payload,'projection_id':p['projection_id'],'receipt_id':p['receipt_id']}

    def list_projections(self, workspace_id, actor_id, *, kind='trend', limit=20, before=None, as_of=None, filters=None, method_bundle=None, cursor=None):
        if type(limit) is not int or not 1<=limit<=100:
            raise TrendStorageError('invalid_page_limit')
        as_of = iso(instant(as_of or utcnow())); filters = filters or {}
        if set(filters)-{'platform','language','stage','scope_key','object_id','query','platforms','languages','stages','regions','niches','since','until'}:
            raise TrendStorageError('invalid_projection_filter')
        with self.transaction(cursor) as cur:
            scopes = self.authorized_scopes(workspace_id,actor_id,cursor=cur)
            where = ['p.scope_key=ANY(%s)','p.kind=%s','p.available_at<=%s',
                'NOT EXISTS(SELECT 1 FROM public.pr_trend_projections newer WHERE (newer.scope_key,newer.kind,newer.object_id)=(p.scope_key,p.kind,p.object_id) AND newer.revision>p.revision AND newer.available_at<=%s)',
                'postriff_private.trend_node_valid(p.scope_key,p.projection_id)']
            params = [scopes,kind,as_of,as_of]
            for name, value in sorted(filters.items()):
                if name=='query':
                    if not isinstance(value,str) or len(value)>256:
                        raise TrendStorageError('invalid_projection_query')
                    where.append("to_tsvector('simple',coalesce(p.payload->>'canonical_topic','')) @@ plainto_tsquery('simple',%s)"); params.append(value)
                    continue
                if name in ('since','until'):
                    instant(value)
                    where.append('p.available_at'+('>=' if name=='since' else '<=')+'%s'); params.append(value)
                    continue
                if name in ('platforms','languages','stages','regions','niches'):
                    if not isinstance(value,list) or len(value)>30 or any(not isinstance(x,str) or len(x)>100 for x in value):
                        raise TrendStorageError('invalid_projection_filter')
                    singular = {'platforms':'platform','languages':'language','stages':'stage','regions':'region','niches':'niche'}[name]
                    where.append('p.payload->>%s=ANY(%s)'); params.extend([singular,value])
                    continue
                if name in ('scope_key','object_id'):
                    where.append('p.'+name+'=%s'); params.append(value)
                else:
                    where.append('p.payload->>%s=%s'); params.extend([name,str(value)])
            if method_bundle:
                if isinstance(method_bundle,str):
                    parts = method_bundle.rsplit('@',1)
                    if len(parts)!=2:
                        raise TrendStorageError('invalid_method_bundle')
                    method_bundle = dict(zip(('method_id','version'),parts))
                where.extend(['p.method_id=%s','p.method_version=%s']); params.extend([method_bundle['method_id'],method_bundle['version']])
            if before:
                if not isinstance(before,(list,tuple)) or len(before)!=4:
                    raise TrendStorageError('invalid_page_key')
                instant(before[0]); uuid(before[1]); scope(before[3])
                where.append('(p.available_at,p.object_id,p.revision,p.scope_key)<(%s::timestamptz,%s::uuid,%s::bigint,%s)'); params.extend(before)
            # Bounded DB page; no Python scan of the full corpus.
            cur.execute('SELECT p.* FROM public.pr_trend_projections p WHERE '+' AND '.join(where)+' ORDER BY p.available_at DESC,p.object_id DESC,p.revision DESC,p.scope_key DESC LIMIT %s',params+[limit+1])
            found = rows(cur); page = found[:limit]
            states=self._statuses(cur,page)
            projected = [self._projection_row(cur,p,states[(p['scope_key'],p['projection_id'])]) for p in page]
            key = [page[-1]['available_at'],page[-1]['object_id'],page[-1]['revision'],page[-1]['scope_key']] if len(found)>limit and page else None
            return {'items':[p for p in projected if p['validity']=='valid'],'next_key':key,'as_of':as_of}

    def get_projection(self, workspace_id, actor_id, kind, object_id, *, revision=None, as_of=None, cursor=None):
        uuid(object_id); as_of = iso(instant(as_of or utcnow()))
        with self.transaction(cursor) as cur:
            scopes = self.authorized_scopes(workspace_id,actor_id,cursor=cur)
            args = [scopes,kind,object_id,as_of]; extra = ''
            if revision is not None:
                extra = ' AND revision=%s'; args.append(revision)
            cur.execute('SELECT * FROM public.pr_trend_projections WHERE scope_key=ANY(%s) AND kind=%s AND object_id=%s AND available_at<=%s'+extra+' ORDER BY revision DESC,scope_key LIMIT 1',args)
            found = row(cur)
            return self._projection_row(cur,found) if found else None

    def projection_status(self, workspace_id, actor_id, kind, object_id, *, revision=None, as_of=None, cursor=None):
        found = self.get_projection(workspace_id,actor_id,kind,object_id,revision=revision,as_of=as_of,cursor=cursor)
        return {k:v for k,v in found.items() if k!='payload'} if found else None

    def lock_dependencies(self, workspace_id, actor_id, bindings, *, cursor):
        """Lock then validate bindings for an authenticated mutation in the SAME transaction.

        Returns current safe metadata. Bindings are {kind, object_id, revision}.
        Locks last until the caller commits/rolls back. Call before domain writes;
        time-based expiry must still be checked immediately before those writes.
        """
        if cursor is None or not isinstance(bindings,(list,tuple)) or not 1<=len(bindings)<=100:
            raise TrendStorageError('mutation_bindings_required')
        cur = cursor
        trust_lock(cur)
        self._actor(cur,workspace_id,actor_id,write=True)
        cur.execute('SELECT scope_key FROM public.pr_trend_entitlements WHERE workspace_id=%s ORDER BY scope_key FOR SHARE',(workspace_id,)); cur.fetchall()
        results = []
        for binding in sorted(bindings,key=lambda b:(b['kind'],str(b['object_id']),b.get('revision') or 0)):
            found = self.get_projection(workspace_id,actor_id,binding['kind'],binding['object_id'],revision=binding.get('revision'),cursor=cur)
            if not found:
                raise TrendStorageError('projection_unavailable')
            # Serialize against the exact append key used by put_projection.
            # Re-read the head after waiting: a newer revision may have committed
            # between the preliminary lookup and acquisition of this lock.
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                (found['scope_key']+'|projection|'+found['kind']+'|'+found['object_id'],))
            cur.execute('SELECT max(revision) AS revision FROM public.pr_trend_projections WHERE scope_key=%s AND kind=%s AND object_id=%s',
                (found['scope_key'],found['kind'],found['object_id']))
            if row(cur)['revision']!=found['revision']:
                raise TrendStorageError('projection_revision_conflict')
            cur.execute('''WITH RECURSIVE a(scope_key,node_id) AS (SELECT %s::text,%s::uuid UNION
                SELECT d.input_scope_key,d.input_node_id FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
                SELECT n.scope_key,n.node_id FROM public.pr_trend_nodes n JOIN a USING(scope_key,node_id)
                ORDER BY n.scope_key,n.node_id FOR SHARE OF n''',(found['scope_key'],found['projection_id']))
            nodes = rows(cur)
            for n in nodes:
                cur.execute('SELECT scope_key FROM public.pr_trend_scopes WHERE scope_key=%s FOR SHARE',(n['scope_key'],)); cur.fetchall()
                cur.execute('SELECT provider_id,source_policy_version FROM public.pr_trend_observations WHERE scope_key=%s AND observation_id=%s FOR SHARE',(n['scope_key'],n['node_id']))
                observation = row(cur)
                if observation:
                    self._policy(cur,n['scope_key'],observation['provider_id'],observation['source_policy_version'])
                cur.execute('''SELECT v.method_id FROM public.pr_trend_method_versions v WHERE EXISTS (
                    SELECT 1 FROM public.pr_trend_projections p WHERE p.scope_key=%s AND p.projection_id=%s
                    AND (p.method_id,p.method_version)=(v.method_id,v.version)) OR EXISTS (
                    SELECT 1 FROM public.pr_trend_trust_receipts r WHERE r.scope_key=%s AND r.receipt_id=%s
                    AND (r.method_id,r.method_version)=(v.method_id,v.version)) ORDER BY v.method_id,v.version FOR SHARE''',
                    (n['scope_key'],n['node_id'],n['scope_key'],n['node_id'])); cur.fetchall()
            found = self.projection_status(workspace_id,actor_id,binding['kind'],binding['object_id'],revision=binding.get('revision'),cursor=cur)
            if not found or found['validity']!='valid':
                raise TrendStorageError('projection_unavailable')
            results.append(found)
        return results

    def get_opportunity(self, workspace_id, actor_id, object_id, *, revision=None, as_of=None, cursor=None):
        return self.get_projection(workspace_id,actor_id,'opportunity',object_id,revision=revision,as_of=as_of,cursor=cursor)

    def get_receipt(self, workspace_id, actor_id, object_id, *, revision=None, as_of=None, cursor=None):
        return self.get_projection(workspace_id,actor_id,'receipt',object_id,revision=revision,as_of=as_of,cursor=cursor)

    def put_watch(self, workspace_id, actor_id, payload, *, idempotency_key, cursor=None):
        with self.transaction(cursor) as cur:
            wid, actor = self._actor(cur,workspace_id,actor_id,write=True)
            cur.execute('SELECT * FROM public.pr_trend_watches WHERE workspace_id=%s AND idempotency_key=%s FOR UPDATE',(wid,idempotency_key))
            prior = row(cur)
            if prior:
                if prior['payload']!=payload:
                    raise TrendStorageError('idempotency_conflict')
                return prior
            watch_id = str(uuidlib.uuid5(uuidlib.UUID(wid),'trend-watch:'+idempotency_key))
            cur.execute('INSERT INTO public.pr_trend_watches(workspace_id,watch_id,idempotency_key,created_by,payload) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *',(wid,watch_id,idempotency_key,actor,bounded_json(payload,16384)))
            saved = row(cur)
            if not saved:
                cur.execute('SELECT * FROM public.pr_trend_watches WHERE workspace_id=%s AND idempotency_key=%s',(wid,idempotency_key)); saved = row(cur)
                if saved['payload']!=payload:
                    raise TrendStorageError('idempotency_conflict')
            return saved

    def list_watches(self, workspace_id, actor_id, *, cursor=None):
        with self.transaction(cursor) as cur:
            self._actor(cur,workspace_id,actor_id)
            cur.execute('SELECT * FROM public.pr_trend_watches WHERE workspace_id=%s ORDER BY created_at,watch_id LIMIT 200',(workspace_id,))
            return rows(cur)

    def delete_watch(self, workspace_id, actor_id, watch_id, *, expected_revision=None, idempotency_key=None, cursor=None):
        with self.transaction(cursor) as cur:
            self._actor(cur,workspace_id,actor_id,write=True)
            cur.execute('SELECT * FROM public.pr_trend_watches WHERE workspace_id=%s AND watch_id=%s FOR UPDATE',(workspace_id,uuid(watch_id)))
            old = row(cur)
            if not old:
                return None
            if not old['enabled'] and (idempotency_key is None or old['deletion_key']==idempotency_key):
                return old
            if expected_revision is not None and old['revision']!=expected_revision:
                raise TrendStorageError('watch_revision_conflict')
            cur.execute('UPDATE public.pr_trend_watches SET enabled=false,revision=revision+1,deletion_key=%s WHERE workspace_id=%s AND watch_id=%s RETURNING *',(idempotency_key,workspace_id,uuid(watch_id)))
            return row(cur)

    def decide_opportunity(self, workspace_id, actor_id, object_id, *, revision, decision, idempotency_key, result=None, cursor=None):
        with self.transaction(cursor) as cur:
            self.lock_dependencies(workspace_id,actor_id,[{'kind':'opportunity','object_id':object_id,'revision':revision}],cursor=cur)
            self._actor(cur,workspace_id,actor_id,write=True)
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(workspace_id)+'|opportunity|'+str(object_id),))
            p = self.get_opportunity(workspace_id,actor_id,object_id,revision=revision,cursor=cur)
            if not p or p['validity']!='valid' or p['scope_key']!='workspace:'+str(workspace_id):
                raise TrendStorageError('opportunity_unavailable')
            cur.execute('SELECT * FROM public.pr_trend_opportunity_decisions WHERE workspace_id=%s AND (idempotency_key=%s OR (object_id=%s AND revision=%s AND decision=%s))',(workspace_id,idempotency_key,object_id,revision,decision))
            existing = row(cur)
            if existing:
                if (existing['object_id'],existing['revision'],existing['decision'])!=(object_id,revision,decision):
                    raise TrendStorageError('idempotency_conflict')
                return existing
            p = self.get_opportunity(workspace_id,actor_id,object_id,revision=revision,cursor=cur)
            if not p or p['validity']!='valid' or p['scope_key']!='workspace:'+str(workspace_id):
                raise TrendStorageError('opportunity_unavailable')
            cur.execute("""INSERT INTO public.pr_trend_opportunity_decisions(workspace_id,scope_key,object_id,revision,idempotency_key,decision,actor_id,result)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(workspace_id,p['scope_key'],object_id,revision,idempotency_key,decision,actor_id,bounded_json(result or {})))
            return row(cur)
