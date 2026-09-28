"""Bounded local ingestion-to-receipt pipeline using the durable TrendStore.

Called only by trusted workers: ``TrendOutbox.consume(claim, pipeline.consume)``.
No HTTP/model/provider dispatch or method promotion. All effects share the outbox
transaction. Pure IDs remain inside sealed artifacts; UUID5 IDs address SQL rows.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit

from . import contracts, metrics, methods, receipts, clustering, membership
from .store import TrendStorageError, bounded_json, row, rows, utcnow

OBSERVATION_FIELDS = tuple(sorted(metrics.OBSERVATION_KEYS | {'time_basis','provenance','deletion_key','schema_version'}))
CONSUMER = 'trend.pipeline.v1'


def uuid_map(scope_key, namespace, pure_id):
    contracts.scope(scope_key)
    if namespace not in {'topic','episode','receipt','manifest','membership','snapshot','projection','run','association'}:
        raise ValueError('unknown_identity_namespace')
    return str(uuid5(NAMESPACE_URL, 'rafii:trend:v1:' + contracts.canonical([scope_key,namespace,pure_id])))


def implementation_methods():
    """Bind immutable configurations to the actual local executable source graph."""
    names = {'normalization':'metrics','deduplication':'metrics','clustering':'membership','baseline':'baselines',
             'momentum':'momentum','lifecycle':'lifecycle','confidence':'confidence'}
    root = Path(__file__).parent
    common = {name:hashlib.sha256((root/(name+'.py')).read_bytes()).hexdigest()
              for name in ('contracts','metrics','methods','receipts','clustering','embeddings','membership','pipeline','service')}
    result = []
    for name, module in names.items():
        code = {**common, module:hashlib.sha256((root/(module+'.py')).read_bytes()).hexdigest()}
        implementation_digest = contracts.digest(code)
        result.append(methods.make_method(name,'candidate-'+implementation_digest[:16],
                      implementation_digest=implementation_digest,config={},algorithm_id=receipts.ALGORITHMS[name]))
    return sorted(result,key=lambda artifact:artifact['name'])


def encode_manifest(manifest):
    """Bounded, digest-checked full document, not an ID-only display sample."""
    serialized = contracts.canonical(manifest)
    if len(serialized.encode()) > 8_000_000:
        raise TrendStorageError('pipeline_manifest_byte_limit')
    # UTF-8/JSON escaping can expand characters; measure the actual JSON chunk.
    chunks = []; current = ''
    for start in range(0,len(serialized),8000):
        fragment = serialized[start:start+8000]
        proposed = current + fragment
        if len(contracts.canonical({'json':proposed}).encode()) > 48000 and current:
            chunks.append({'json':current});current=fragment
        else: current=proposed
    if current: chunks.append({'json':current})
    if len(chunks)>512: raise TrendStorageError('pipeline_manifest_chunk_limit')
    return {'codec':'json-fragments-v1','pure_manifest_digest':manifest['manifest_digest'],'chunk_count':len(chunks)},chunks


def decode_manifest(stored):
    recipe = stored['recipe']
    if recipe.get('codec') != 'json-fragments-v1' or len(stored['chunks']) != recipe.get('chunk_count'):
        raise TrendStorageError('manifest_codec_mismatch')
    fragments=[]
    for expected,chunk in enumerate(stored['chunks']):
        if chunk['ordinal'] != expected or contracts.digest(chunk['payload']) != chunk['digest']:
            raise TrendStorageError('manifest_chunk_mismatch')
        fragments.append(chunk['payload']['json'])
    result=json.loads(''.join(fragments))
    computed=contracts.digest({k:v for k,v in result.items() if k!='manifest_digest'})
    if computed != result['manifest_digest'] or computed != recipe['pure_manifest_digest'] or stored['document_digest'] != computed:
        raise TrendStorageError('manifest_document_mismatch')
    durable=contracts.digest({'inputs':stored['inputs'],'recipe':recipe,'chunks':[c['digest'] for c in stored['chunks']]})
    if durable != stored['digest']: raise TrendStorageError('manifest_storage_digest_mismatch')
    return result


def representative_evidence(manifest, *, limit=5):
    """Stable, author-diverse original-language examples with independent grants."""
    cutoff=manifest['recipe']['decision_cutoff']
    members=membership.resolve_memberships(manifest['membership_revisions'],cutoff,
        observations=manifest['source_revisions'],source_policies=manifest['policy_versions'])
    member_ids={m['observation_id'] for m in members if m['episode_id']==manifest['recipe']['episode_id']}
    specs=manifest['recipe']['window_specs'];start=min(contracts.instant(w['start']) for w in specs);end=max(contracts.instant(w['end']) for w in specs)
    candidates=[o for o in manifest['source_revisions'] if o['observation_id'] in member_ids and o['event_at']
                and start<=contracts.instant(o['event_at'])<end and not o['payload'].get('is_repost')]
    ordered=sorted(candidates,key=lambda o:(o['event_at'],o['observation_id']))
    selected=[];authors=set()
    for diverse in (True,False):
        for o in ordered:
            if any(x['observation_id']==o['observation_id'] for x in selected):continue
            author=(o['provider_id'],o['payload'].get('author_key') or o['observation_id'])
            if diverse and author in authors:continue
            selected.append(o);authors.add(author)
            if len(selected)>=limit:break
        if len(selected)>=limit:break
    output=[]
    for o in selected:
        p=o['payload'];policies=manifest['policy_versions']
        text_ok=metrics.source_policy_allowed(o,policies,cutoff,'display_excerpt')
        link_ok=metrics.source_policy_allowed(o,policies,cutoff,'display_link')
        url=p.get('canonical_url') or p.get('url')
        parsed=urlsplit(url) if isinstance(url,str) else None
        url=url if link_ok and parsed and parsed.scheme=='https' and parsed.hostname and not parsed.username else None
        output.append({'id':o['observation_id'],'scope_key':o['scope_key'],'platform':p['platform'],'language':p['language'],
            'excerpt':p.get('text','')[:800] if text_ok else None,'url':url,'observed_at':o['event_at'],
            'expires_at':o['retention_until'],'rights':deepcopy(o['rights'])})
    return output


def _platform_states(view, platform):
    return [{'platform':platform,'coverage':deepcopy(view['coverage']),'inferred':deepcopy(view['inferred']),
             'cohort_qualified':False,'method_state':'shadow'}]


class _CandidateIndex:
    """Cheap inverted lexical retrieval bounds expensive pair decisions."""
    def __init__(self, limit):
        self.limit=limit;self.records={};self.tokens={};self.native={}

    def add(self, observation):
        oid=observation['observation_id'];self.records[oid]=observation
        self.native[(observation['provider_id'],observation['source_identity'])]=oid
        for token in clustering.text_features(observation['payload'].get('text',''),observation['payload'].get('language'))['tokens']:
            self.tokens.setdefault(token,set()).add(oid)

    def get(self, observation):
        features=clustering.text_features(observation['payload'].get('text',''),observation['payload'].get('language'))
        counts={}
        for token in features['tokens']:
            for oid in self.tokens.get(token,()): counts[oid]=counts.get(oid,0)+1
        def comparable(oid):
            other=self.records[oid]
            if any(observation['payload'].get(k)!=other['payload'].get(k) for k in ('platform','language','community')): return False
            if observation['event_at'] and other['event_at']:
                return abs((contracts.instant(observation['event_at'])-contracts.instant(other['event_at'])).total_seconds())<=48*3600
            return False
        ordered=sorted((oid for oid in counts if comparable(oid)),key=lambda oid:(-counts[oid],oid))
        exact=self.native.get((observation['provider_id'],observation['source_identity']))
        if exact: ordered=[exact]+[oid for oid in ordered if oid!=exact]
        return [self.records[oid] for oid in ordered[:self.limit]]


def _coverage(event, comparison, start, end, *, truncated=False):
    p=event['payload']; completeness=p.get('completeness','unknown')
    completeness={'complete':'complete_within_scope'}.get(completeness,completeness)
    if completeness not in {'complete_within_scope','partial','truncated','gap','unknown'}: completeness='unknown'
    # Batch completeness alone is not a completeness assertion for an hourly frame.
    interval = p.get('coverage_interval') or {}
    if completeness=='complete_within_scope' and not (interval.get('start') and interval.get('end')
        and contracts.instant(interval['start']) <= contracts.instant(start)
        and contracts.instant(interval['end']) >= contracts.instant(end)):
        completeness='partial'
    if truncated: completeness='truncated'
    return {'availability':'available','representation':'owned_posts' if comparison['evidence_kind']=='owned_post' else 'sampled_posts',
            'completeness':completeness,'breadth':'unknown','scope_ref':comparison['query_digest'],
            'coverage_epoch':comparison['coverage_epoch'],'scope':event['scope_key'],
            'latest_successful_read':p['decision_cutoff'],'freshness_deadline':None,
            'sources':[{'platform':comparison['platform'],'availability':'available','reason':None}]}


class TrendPipeline:
    def __init__(self, store, *, clock=utcnow, max_observations=1000, max_candidate_pairs=20, max_episodes=20, max_new_memberships=100):
        if not 1<=max_observations<=1000 or not 1<=max_candidate_pairs<=100 or not 1<=max_episodes<=20 or not 1<=max_new_memberships<=1000:
            raise ValueError('pipeline_bounds')
        self.store,self.clock=store,clock
        self.max_observations,self.max_candidate_pairs,self.max_episodes=max_observations,max_candidate_pairs,max_episodes
        self.max_new_memberships=max_new_memberships

    def _policies(self, cur, scope_key, sources, at):
        output=[]
        for provider,version in sorted({(o['provider_id'],o['source_policy_version']) for o in sources}):
            # Also checks provider contract validity, scope enabled and current revocation.
            p=self.store._policy(cur,scope_key,provider,version,'derive_metrics',at=at)
            self.store._policy(cur,scope_key,provider,version,'retain_derivatives',at=at)
            manifest=deepcopy(p['manifest'])
            manifest.update(scope_key=scope_key,provider_id=provider,version=version,rights=p['rights'],
                            effective_at=p['valid_from'],expires_at=p['expires_at'],readiness=p['readiness'],revoked_at=p['revoked_at'])
            output.append(manifest)
        return output

    def _sources(self, cur, event):
        p=event['payload'];cutoff=contracts.instant(p['decision_cutoff'])
        start=contracts.iso(cutoff.replace(minute=0,second=0,microsecond=0)-timedelta(days=28,hours=3))
        columns=','.join('o.'+key for key in OBSERVATION_FIELDS)
        # MATERIALIZED is deliberate: the recursive current-rights predicate must
        # run at most max_observations+1 times, never once per retained source.
        storage_op="""CASE WHEN o.kind='aggregate_metric' THEN 'store_metrics'
            WHEN coalesce(o.payload->>'text','')<>'' THEN 'store_raw' ELSE 'retrieve' END"""
        permitted="""postriff_private.trend_permits(o.rights,"""+storage_op+""",o.scope_key)
            AND EXISTS(SELECT 1 FROM public.pr_trend_source_policies sp
                JOIN public.pr_trend_provider_contracts pc ON(pc.provider_id,pc.version)=(sp.provider_id,sp.provider_contract_version)
                WHERE(sp.scope_key,sp.provider_id,sp.version)=(o.scope_key,o.provider_id,o.source_policy_version)
                AND pc.version=o.provider_contract_version AND """+storage_op+"""=ANY(sp.operations)
                AND """+storage_op+"""=ANY(pc.operations)
                AND postriff_private.trend_permits(sp.rights,"""+storage_op+""",o.scope_key))"""
        # SQL040's current-trust function checks retrieval/derivation. Storage
        # grants are independent: denied source content must not leave this query.
        checks=""", gated AS MATERIALIZED (SELECT o.*,
            (postriff_private.trend_node_valid(o.scope_key,o.observation_id) AND """+permitted+""") AS current_valid,
            NOT EXISTS(SELECT 1 FROM public.pr_trend_observations newer WHERE newer.scope_key=o.scope_key
                AND newer.provider_id=o.provider_id AND newer.source_identity_digest=o.source_identity_digest
                AND newer.available_at<=%s AND newer.revision_sequence>o.revision_sequence) AS latest_known
            FROM candidates o) SELECT """+','.join('CASE WHEN current_valid THEN '+key+' END AS '+key for key in OBSERVATION_FIELDS)+""",
            current_valid,latest_known FROM gated"""
        cur.execute('''WITH candidates AS MATERIALIZED (SELECT '''+columns+''',o.source_identity_digest
            FROM public.pr_trend_observations o WHERE o.scope_key=%s AND o.provider_id=%s AND o.available_at<=%s
            AND (o.event_at>=%s OR (o.event_at IS NULL AND o.received_at>=%s))
            ORDER BY o.available_at,o.revision_sequence,o.observation_id LIMIT %s) '''+checks,
            (event['scope_key'],p['provider_id'],p['decision_cutoff'],start,start,self.max_observations+1,p['decision_cutoff']))
        found=rows(cur)
        truncated=len(found)>self.max_observations or any(not r['current_valid'] for r in found)
        def allowed(records):
            return [{k:r[k] for k in OBSERVATION_FIELDS} for r in records if r['current_valid'] and r['latest_known']]
        records=allowed(found)[:self.max_observations]
        wanted=set(p['observation_ids'])
        if wanted-set(o['observation_id'] for o in records):
            cur.execute('''WITH candidates AS MATERIALIZED (SELECT '''+columns+''',o.source_identity_digest
                FROM public.pr_trend_observations o WHERE o.scope_key=%s AND o.provider_id=%s
                AND o.observation_id=ANY(%s::uuid[]) AND o.available_at<=%s) '''+checks,
                (event['scope_key'],p['provider_id'],sorted(wanted),p['decision_cutoff'],p['decision_cutoff']))
            triggered=rows(cur)
            truncated |= any(not r['current_valid'] for r in triggered)
            triggering=allowed(triggered);remaining=[o for o in records if o['observation_id'] not in wanted]
            records=(triggering+remaining)[:self.max_observations]
        return sorted(records,key=lambda o:(contracts.instant(o['available_at']),o['revision_sequence'],o['observation_id'])),truncated

    def _memberships(self, cur, scope_key, cutoff, sources):
        # Native digests and UUID equality use040's existing indexes; casting the
        # observation column to text would prevent its composite primary-key lookup.
        native=[hashlib.sha256(o['source_identity'].encode()).hexdigest() for o in sources]
        cur.execute('''WITH candidates AS MATERIALIZED (
            SELECT p.payload,p.projection_id,p.available_at,p.scope_key FROM public.pr_trend_projections p
            JOIN public.pr_trend_observations o ON o.scope_key=p.scope_key AND o.observation_id=(p.payload->>'observation_id')::uuid
            WHERE p.scope_key=%s AND p.kind='membership' AND p.available_at<=%s
            AND o.source_identity_digest=ANY(%s::text[]) AND o.provider_id=ANY(%s::text[])
            ORDER BY p.available_at,p.projection_id LIMIT %s)
            SELECT candidates.*,postriff_private.trend_node_valid(scope_key,projection_id) AS current_valid FROM candidates''',
            (scope_key,cutoff,sorted(set(native)),sorted({o['provider_id'] for o in sources}),self.max_observations+1))
        found=rows(cur)
        if len(found)>self.max_observations: raise TrendStorageError('pipeline_membership_bound')
        return [{**r['payload'],'available_at':r['available_at']} for r in found if r['current_valid']]

    @staticmethod
    def _input_groups(scope_key, sources, members):
        groups = [('source', sorted({o['observation_id'] for o in sources})),
                  ('membership', sorted({uuid_map(scope_key,'membership',m['event_id']) for m in members}))]
        return [(kind,[{'scope_key':scope_key,'node_id':node} for node in ids[start:start+1000]])
                for kind,ids in groups for start in range(0,len(ids),1000)]

    def _member_nodes(self, cur, scope_key, members, cutoff):
        expected={uuid_map(scope_key,'membership',m['event_id']):m for m in members}
        if not expected:return []
        if len(expected)>1000:raise TrendStorageError('pipeline_membership_bound')
        cur.execute("""SELECT p.projection_id,p.payload,p.available_at,p.retention_until
            FROM public.pr_trend_projections p WHERE p.scope_key=%s AND p.kind='membership'
            AND p.projection_id=ANY(%s::uuid[])""",(scope_key,sorted(expected)))
        found=rows(cur)
        if len(found)!=len(expected):raise TrendStorageError('receipt_membership_node_missing')
        for item in found:
            if (contracts.instant(item['available_at'])>contracts.instant(cutoff)
                or {**item['payload'],'available_at':item['available_at']}!=expected[item['projection_id']]):
                raise TrendStorageError('receipt_membership_node_mismatch')
        return found

    def _dependency_anchors(self, cur, scope_key, sources, members, cutoff, retain):
        """Seal both kinds of inputs within Store's1000-reference manifest bound.

        Membership projections carry their exact method foreign keys and source
        dependencies. Their full event recipes remain in the root document.
        """
        nodes=self._member_nodes(cur,scope_key,members,cutoff)
        retain=min([retain]+[n['retention_until'] for n in nodes],key=contracts.instant)
        anchors=[];created=False;available=[]
        for kind,inputs in self._input_groups(scope_key,sources,members):
            recipe={'schema':'rafii.trend-dependency-anchor.v1','kind':kind,'input_digest':contracts.digest(inputs)}
            mid=uuid_map(scope_key,'manifest','dependency-anchor:'+contracts.digest([recipe,retain]))
            cur.execute('SELECT available_at FROM public.pr_trend_nodes WHERE scope_key=%s AND node_id=%s',(scope_key,mid))
            existing=row(cur)
            if existing:
                saved=self.store.get_manifest(scope_key,mid,cursor=cur)
                if saved['recipe']!=recipe or saved['inputs']!=inputs:
                    raise TrendStorageError('immutable_dependency_anchor_conflict')
                available.append(existing['available_at'])
            else:
                self.store.put_manifest(scope_key,inputs,decision_cutoff=cutoff,available_at=cutoff,
                    retention_until=retain,manifest_id=mid,recipe=recipe,document_digest=recipe['input_digest'],cursor=cur)
                created=True
                cur.execute('SELECT available_at FROM public.pr_trend_nodes WHERE scope_key=%s AND node_id=%s',(scope_key,mid))
                available.append(row(cur)['available_at'])
            anchors.append({'manifest_id':mid,**recipe})
        # Acquisition cutoff stays frozen. A newly sealed live dependency anchor
        # is known only after its authoritative insertion timestamp.
        if created and not self.store.offline_replay:
            cur.execute('SELECT clock_timestamp() AS cutoff');available.append(row(cur)['cutoff'])
        cutoff=contracts.iso(max([contracts.instant(cutoff)]+[contracts.instant(t) for t in available]))
        return anchors,cutoff,retain

    def _verify_dependencies(self, cur, scope_key, stored, manifest):
        members=manifest['membership_revisions'];cutoff=manifest['recipe']['decision_cutoff']
        nodes=self._member_nodes(cur,scope_key,members,cutoff)
        expected=self._input_groups(scope_key,manifest['source_revisions'],members)
        anchors=stored['recipe'].get('dependency_anchors',[])
        if len(anchors)!=len(expected):raise TrendStorageError('receipt_dependency_binding_mismatch')
        cur.execute('SELECT node_id,available_at,retention_until FROM public.pr_trend_nodes WHERE scope_key=%s AND node_id=ANY(%s::uuid[])',
            (scope_key,[stored['manifest_id']]+[a['manifest_id'] for a in anchors]))
        metadata={n['node_id']:n for n in rows(cur)}
        if len(metadata)!=1+len(anchors):raise TrendStorageError('receipt_dependency_binding_mismatch')
        if any(contracts.instant(n['retention_until'])<contracts.instant(metadata[stored['manifest_id']]['retention_until']) for n in nodes):
            raise TrendStorageError('receipt_membership_retention_mismatch')
        root_inputs=[{'scope_key':scope_key,'node_id':a['manifest_id']} for a in anchors]
        if stored['inputs']!=root_inputs:raise TrendStorageError('receipt_dependency_binding_mismatch')
        edges={(stored['manifest_id'],scope_key,i['node_id']) for i in root_inputs}
        for anchor,(kind,inputs) in zip(anchors,expected):
            recipe={'schema':'rafii.trend-dependency-anchor.v1','kind':kind,'input_digest':contracts.digest(inputs)}
            if {k:v for k,v in anchor.items() if k!='manifest_id'}!=recipe:
                raise TrendStorageError('receipt_dependency_binding_mismatch')
            saved=self.store.get_manifest(scope_key,anchor['manifest_id'],cursor=cur)
            if (saved['inputs']!=inputs or saved['recipe']!=recipe or saved['document_digest']!=recipe['input_digest']
                    or contracts.instant(metadata[anchor['manifest_id']]['available_at'])>contracts.instant(cutoff)):
                raise TrendStorageError('receipt_dependency_binding_mismatch')
            edges.update((anchor['manifest_id'],scope_key,i['node_id']) for i in inputs)
        cur.execute('''SELECT node_id,input_scope_key,input_node_id FROM public.pr_trend_dependencies
            WHERE scope_key=%s AND node_id=ANY(%s::uuid[])''',
            (scope_key,[stored['manifest_id']]+[a['manifest_id'] for a in anchors]))
        if {(e['node_id'],e['input_scope_key'],e['input_node_id']) for e in rows(cur)}!=edges:
            raise TrendStorageError('receipt_dependency_binding_mismatch')

    def _register(self, cur):
        artifacts=implementation_methods()
        for artifact in artifacts:
            self.store.put_method('trend.'+artifact['name'],artifact['version'],artifact['artifact_digest'],artifact,cursor=cur)
        bundle_digest=contracts.digest(artifacts);version='candidate-'+bundle_digest[:16]
        self.store.put_method('trend.pipeline',version,bundle_digest,{'artifacts':artifacts},cursor=cur)
        return artifacts,{'method_id':'trend.pipeline','method_version':version,'artifact_digest':bundle_digest}

    def consume(self, cur, event):
        """Transactional outbox effect; never acknowledge a partially committed result."""
        if event.get('event_type')!='trend.ingested': return {'state':'ignored','reason':'different_event_type'}
        scope_key=contracts.scope(event['scope_key']);contracts.uuid(event['event_id'])
        p=event['payload'];cutoff=contracts.iso(contracts.instant(p['decision_cutoff']));now=self.clock()
        if contracts.instant(cutoff)>contracts.instant(now): raise TrendStorageError('pipeline_future_cutoff')
        if not isinstance(p.get('observation_ids'),list) or len(p['observation_ids'])>self.max_observations:
            raise TrendStorageError('pipeline_input_bound')
        for oid in p['observation_ids']: contracts.uuid(oid)
        pending=p.get('pending_observation_indices',list(range(len(p['observation_ids']))))
        if (not isinstance(pending,list) or len(pending)>len(p['observation_ids'])
            or any(type(i) is not int or not 0<=i<len(p['observation_ids']) for i in pending)
            or len(set(pending))!=len(pending) or len(set(p['observation_ids']))!=len(p['observation_ids'])):
            raise TrendStorageError('pipeline_pending_bound')
        pending_ids={p['observation_ids'][i] for i in pending}
        if not p.get('provider_id') or not p.get('coverage_epoch'): raise TrendStorageError('pipeline_frame_required')
        # Serialize this scope's incremental membership revisions, not other scopes.
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('trend-pipeline|'+scope_key,))
        run_id=uuid_map(scope_key,'run',event['event_id'])
        cur.execute("SELECT payload FROM public.pr_trend_projections WHERE scope_key=%s AND kind='pipeline_run' AND object_id=%s",(scope_key,run_id))
        previous=row(cur)
        if previous: return {**previous['payload'],'replayed':True}
        sources,truncated=self._sources(cur,event)
        if not sources: return {'state':'suppressed','reason':'no_current_sources','receipts':[]}
        if sum(len(contracts.canonical(o).encode()) for o in sources)>4_000_000: raise TrendStorageError('pipeline_source_byte_bound')
        policies=self._policies(cur,scope_key,sources,now)
        if any(not metrics.source_policy_allowed(o,policies,now,'retain_derivatives') for o in sources):
            raise TrendStorageError('pipeline_derivative_rights_denied')
        latest=metrics.latest_revisions(sources,cutoff)
        eligible=[o for o in latest if o['kind'] in ('raw_post','owned_post') and o['operation']!='delete'
                  and metrics.source_policy_allowed(o,policies,now) and o['coverage_epoch']==p['coverage_epoch']]
        if not eligible: return {'state':'suppressed','reason':'no_eligible_posts','receipts':[]}
        artifacts,bundle=self._register(cur)
        retain=min([o['retention_until'] for o in sources]+[p['expires_at'] for p in policies],key=contracts.instant)
        if contracts.instant(retain)<=contracts.instant(now): raise TrendStorageError('pipeline_inputs_expired')
        known=self._memberships(cur,scope_key,now,sources)
        current={e['observation_id']:e for e in membership.resolve_memberships(known,now)}
        revision=max((e['revision_sequence'] for e in known),default=0)
        episode_map={e['episode_id']:e.get('topic_id') for e in known}
        candidates=_CandidateIndex(self.max_candidate_pairs)
        for candidate in sources:
            if candidate['observation_id'] in current and candidate['operation']!='delete': candidates.add(candidate)
        cur.execute('''SELECT EXISTS(SELECT 1 FROM public.pr_trend_observations o
            WHERE o.scope_key=%s AND o.observation_id=ANY(%s::uuid[]) AND (o.operation='delete' OR EXISTS(
              SELECT 1 FROM public.pr_trend_deletion_tombstones t WHERE (t.scope_key,t.provider_id,t.source_identity_digest)=
              (o.scope_key,o.provider_id,o.source_identity_digest)))) AS deleted''',(scope_key,sorted(pending_ids)))
        deletion_event=row(cur)['deleted']
        affected=sorted({m['episode_id'] for m in current.values() if m['observation_id'] in {o['observation_id'] for o in eligible}}) if deletion_event else []
        target_episodes=set(affected[:self.max_episodes]); deferred=[]; new_memberships=0
        for observation in eligible:
            oid=observation['observation_id']
            if oid not in pending_ids: continue
            if oid in current and current[oid]['input_revision_identity']==observation['revision_identity']:
                episode=current[oid]['episode_id']
                if episode not in target_episodes and len(target_episodes)>=self.max_episodes:
                    deferred.append(oid);continue
                target_episodes.add(episode);continue
            if new_memberships>=self.max_new_memberships:
                deferred.append(oid);continue
            pairs=clustering.candidate_pairs(observation,candidates.get(observation),decision_cutoff=now,limit=self.max_candidate_pairs,source_policies=policies)
            match=next((pair for pair in pairs if pair['decision']=='same_conversation'),None)
            native=next((m for m in current.values() if m.get('provider_id')==observation['provider_id'] and m.get('source_identity')==observation['source_identity']),None)
            if native:
                episode_id=native['episode_id'];topic_id=native['topic_id']
                feature_digest=contracts.digest({'native_source_revision':[observation['provider_id'],observation['source_identity']]})
            elif match:
                assigned=current[match['candidate_id']];episode_id=assigned['episode_id'];topic_id=assigned['topic_id']
                feature_digest=match['feature_digest']
            else:
                payload=observation['payload'];features=clustering.text_features(payload.get('text',''),payload.get('language'))
                ids=clustering.conversation_ids(entity_keys=payload.get('entity_keys',[]),topic_key=[observation['provider_id'],payload['platform'],payload.get('language','und'),features['tokens']],
                    episode_anchor=[observation['source_identity'],observation['revision_identity']],pattern_text=payload.get('text',''),
                    language=payload.get('language','und'),scope_key=scope_key)
                topic_id,episode_id=ids['topic_id'],ids['episode_id'];feature_digest=contracts.digest(features)
            if episode_id not in target_episodes and len(target_episodes)>=self.max_episodes:
                deferred.append(oid);continue
            target_episodes.add(episode_id);episode_map[episode_id]=topic_id;revision+=1;new_memberships+=1
            proposal={'scope_key':scope_key,'provider_id':observation['provider_id'],'source_identity':observation['source_identity'],'observation_id':oid,'input_revision_identity':observation['revision_identity'],
                      'episode_id':episode_id,'topic_id':topic_id,'operation':'assign','revision_sequence':revision,
                      'available_at':now,'decided_at':now,'method_version':clustering.METHOD_VERSION,'feature_digest':feature_digest}
            proposal['event_id']='membership_'+contracts.digest(proposal)
            member_id=uuid_map(scope_key,'membership',proposal['event_id'])
            source_manifest=self.store.put_manifest(scope_key,[{'scope_key':scope_key,'node_id':oid}],
                decision_cutoff=cutoff,available_at=now,retention_until=retain,
                manifest_id=uuid_map(scope_key,'manifest',proposal['event_id']+':source'),cursor=cur)
            self.store.put_projection({'scope_key':scope_key,'kind':'membership','object_id':member_id,'projection_id':member_id,
                'revision':1,'manifest_id':source_manifest['manifest_id'],**bundle,'decision_cutoff':cutoff,
                'available_at':now,'retention_until':retain,'payload':proposal},cursor=cur)
            known.append(proposal);current[oid]=proposal;candidates.add(observation)
        if not target_episodes: return {'state':'suppressed','reason':'no_eligible_membership','receipts':[]}
        # Re-read database-stamped membership availability. The decision never uses
        # newly created memberships at the earlier ingestion/acquisition cutoff.
        decision_cutoff=self.clock()
        known=self._memberships(cur,scope_key,decision_cutoff,sources)
        decision_cutoff=contracts.iso(max([contracts.instant(decision_cutoff)]+[contracts.instant(e['available_at']) for e in known]))
        source_ids={o['observation_id'] for o in sources}
        recipe_members=[e for e in known if e.get('observation_id') in source_ids]
        anchors,decision_cutoff,retain=self._dependency_anchors(cur,scope_key,sources,recipe_members,decision_cutoff,retain)
        outputs=[]
        for episode_id in sorted(target_episodes):
            members=[e for e in membership.resolve_memberships(known,decision_cutoff) if e['episode_id']==episode_id]
            member_ids={m['observation_id'] for m in members}
            examples=[o for o in eligible if o['observation_id'] in member_ids]
            if not examples: continue
            exemplar=examples[0];payload=exemplar['payload'];policy=next(pp for pp in policies if pp['version']==exemplar['source_policy_version'])
            comparison={'scope_key':scope_key,'provider_id':p['provider_id'],'metric_definition_id':'original-post-v1',
                'query_digest':p.get('query_digest') or contracts.digest([scope_key,p['provider_id'],p['coverage_epoch'],policy.get('operation')]),
                'evidence_kind':exemplar['kind'],'audience_scope':scope_key,'sampling_method':'bounded_provider_sample',
                'platform':payload['platform'],'language':payload.get('language','und'),'community':payload.get('community','unknown'),
                'inclusion_rules_digest':contracts.digest({'version':'original-v1','source_policy_version':exemplar['source_policy_version']}),
                'time_basis':'provider_event','coverage_epoch':p['coverage_epoch'],'baseline_timezone':'UTC'}
            end=contracts.instant(cutoff).replace(minute=0,second=0,microsecond=0)
            def spec(start):
                start,end_at=contracts.iso(start),contracts.iso(start+timedelta(hours=1))
                return {'start':start,'end':end_at,'comparison_scope':comparison,
                        'coverage':_coverage(event,comparison,start,end_at,truncated=truncated or bool(deferred))}
            window_specs=[spec(end-timedelta(hours=n)) for n in (3,2,1)]
            baseline_specs=[spec(end-timedelta(hours=1,days=7*n)) for n in (4,3,2,1)]
            trend_id=uuid_map(scope_key,'topic',episode_map[episode_id])
            cur.execute("SELECT r.payload,r.receipt_id,r.decision_cutoff FROM public.pr_trend_projections p JOIN public.pr_trend_trust_receipts r ON(r.scope_key,r.receipt_id)=(p.scope_key,p.receipt_id) WHERE p.scope_key=%s AND p.kind='trend' AND p.object_id=%s ORDER BY p.revision DESC LIMIT 1",(scope_key,trend_id))
            previous_receipt=row(cur);lineage={}
            if previous_receipt and previous_receipt['payload'].get('pure_receipt'):
                old=previous_receipt['payload']['pure_receipt']
                old_window=old['calculated']['current_window']
                if old_window=={'start':window_specs[-1]['start'],'end':window_specs[-1]['end']} and old['decision_cutoff']==decision_cutoff and old.get('supersedes_receipt_id'):
                    lineage={k:old[k] for k in ('supersedes_receipt_id','correction_reason','original_decision_cutoff')}
                elif old_window=={'start':window_specs[-1]['start'],'end':window_specs[-1]['end']} and contracts.instant(old['decision_cutoff'])<contracts.instant(decision_cutoff):
                    reason='source_deletion' if deletion_event else 'late_revision' if any(o['revision_sequence']>1 for o in examples) else ('continued_membership' if old['coverage']['completeness']=='truncated' else 'late_observation')
                    lineage={'supersedes_receipt_id':old['receipt_id'],'correction_reason':reason,
                             'original_decision_cutoff':old.get('original_decision_cutoff') or old['decision_cutoff']}
            if deletion_event and previous_receipt and not lineage:
                prior=previous_receipt['payload'].get('pure_receipt') or {}
                lineage={'supersedes_receipt_id':prior.get('receipt_id','durable_receipt:'+previous_receipt['receipt_id']),
                         'correction_reason':'source_deletion','original_decision_cutoff':prior.get('original_decision_cutoff') or previous_receipt['decision_cutoff']}
            pack=receipts.create_receipt(observations=sources,membership_events=recipe_members,window_specs=window_specs,
                baseline_window_specs=baseline_specs,source_policies=policies,method_artifacts=artifacts,scope_key=scope_key,
                trend_id=episode_map[episode_id],episode_id=episode_id,decision_cutoff=decision_cutoff,computed_at=decision_cutoff,
                execution_state='offline_replay' if self.store.offline_replay else 'local_computation',**lineage)
            pure,manifest=pack['receipt'],pack['manifest']
            trend_id=uuid_map(scope_key,'topic',episode_map[episode_id]);rid=uuid_map(scope_key,'receipt',pure['receipt_id'])
            cur.execute('SELECT * FROM public.pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope_key,rid))
            existing_receipt=row(cur)
            if existing_receipt:
                if existing_receipt['payload'].get('pure_receipt')!=pure:
                    raise TrendStorageError('immutable_receipt_conflict')
                verification=self._verify(cur,scope_key,rid)
                value={'scope_key':scope_key,'manifest_id':existing_receipt['manifest_id'],**bundle,
                    'decision_cutoff':decision_cutoff,'available_at':decision_cutoff,'retention_until':retain,
                    'receipt_id':rid,'payload':existing_receipt['payload']}
                outputs.append({'trend_id':trend_id,'episode_id':uuid_map(scope_key,'episode',episode_id),'receipt_id':rid,'verification_state':verification['state']})
                continue
            recipe,chunks=encode_manifest(manifest)
            recipe['dependency_anchors']=anchors
            persisted=self.store.put_manifest(scope_key,[{'scope_key':scope_key,'node_id':a['manifest_id']} for a in anchors],
                decision_cutoff=decision_cutoff,available_at=decision_cutoff,retention_until=retain,
                manifest_id=uuid_map(scope_key,'manifest',manifest['manifest_digest']),recipe=recipe,chunks=chunks,
                document_digest=manifest['manifest_digest'],cursor=cur)
            trend_id=uuid_map(scope_key,'topic',episode_map[episode_id]);rid=uuid_map(scope_key,'receipt',pure['receipt_id'])
            from .service import build_trend_payload, build_receipt_payload
            title=' '.join(clustering.text_features(payload.get('text',''),payload.get('language'))['tokens'][:12])[:300]
            view=build_trend_payload(pure,trend_id=trend_id,episode_id=uuid_map(scope_key,'episode',episode_id),scope_key=scope_key,
                evidence=representative_evidence(manifest),canonical_topic=title,expires_at=retain,method_bundle={'method_id':bundle['method_id'],'version':bundle['method_version']})
            view['platform_states']=_platform_states(view,payload['platform'])
            stored_receipt={**deepcopy(view), **build_receipt_payload(pure,trend_id=trend_id,method_bundle={'method_id':bundle['method_id'],'version':bundle['method_version']}),'schema':pure['schema'],'receipt_id':rid,'trend_id':trend_id,
                            'pure_receipt':pure,'pure_receipt_digest':contracts.digest(pure),'input_manifest_digest':manifest['manifest_digest'],
                            'topic_source_id':exemplar['observation_id'],
                            'supersedes_id':previous_receipt['receipt_id'] if pure['supersedes_receipt_id'] and previous_receipt else None,
                            'correction_reason':pure['correction_reason'],'original_decision_cutoff':pure['original_decision_cutoff'],'replay_mode':pure['replay_mode']}
            stored_receipt['trust_receipt_id']=rid
            membership_refs=[item for kind,items in self._input_groups(scope_key,[],manifest['membership_revisions']) for item in items]
            stored_receipt['membership_dependency_digest']=contracts.digest(membership_refs)
            stored_receipt['membership_dependency_count']=len(membership_refs)
            value={'scope_key':scope_key,'manifest_id':persisted['manifest_id'],**bundle,'decision_cutoff':decision_cutoff,
                   'available_at':decision_cutoff,'retention_until':retain,'receipt_id':rid,'payload':stored_receipt}
            self.store.put_receipt(value,cursor=cur)
            verification=self._verify(cur,scope_key,rid)
            # Even pending/failed measurements have a stored evidence-only card;
            # the service rechecks receipt state and strips calculated fields.
            cur.execute("SELECT coalesce(max(revision),0)+1 AS revision FROM public.pr_trend_projections WHERE scope_key=%s AND kind='trend' AND object_id=%s",(scope_key,trend_id))
            projection_revision=row(cur)['revision']
            view.update(trust_receipt_id=rid,verification_state=verification['state'],platform=payload['platform'],language=payload.get('language','und'),stage=None)
            self.store.put_projection({**value,'kind':'trend','object_id':trend_id,'revision':projection_revision,
                'projection_id':uuid_map(scope_key,'projection',pure['receipt_id']+':trend'),'payload':view},cursor=cur)
            for snapshot in manifest['normalized_inputs']['windows']+manifest['baseline_snapshots']:
                sid=uuid_map(scope_key,'snapshot',snapshot['snapshot_id'])
                cur.execute("SELECT payload FROM public.pr_trend_projections WHERE scope_key=%s AND kind='metric_snapshot' AND object_id=%s",(scope_key,sid))
                existing=row(cur)
                snapshot_view={k:v for k,v in snapshot.items() if k!='source_revision_refs'}
                snapshot_view.update(source_revision_refs_count=len(snapshot['source_revision_refs']),
                    source_revision_refs_digest=contracts.digest(snapshot['source_revision_refs']),
                    snapshot_document_digest=contracts.digest(snapshot),full_snapshot_in_manifest=True)
                if existing:
                    if existing['payload'] not in (snapshot,snapshot_view): raise TrendStorageError('immutable_snapshot_conflict')
                    continue
                self.store.put_projection({**value,'kind':'metric_snapshot','object_id':sid,'revision':1,
                    'projection_id':uuid_map(scope_key,'projection',snapshot['snapshot_id']),'payload':snapshot_view},cursor=cur)
            outputs.append({'trend_id':trend_id,'episode_id':uuid_map(scope_key,'episode',episode_id),'receipt_id':rid,'verification_state':verification['state']})
        associations=[]
        for output in outputs:
            if output['verification_state']=='verified':
                associations.extend(self._associate(cur,scope_key,output,bundle,limit=min(3,20-len(associations))))
            if len(associations)>=20:break
        if deferred:
            from .outbox import TrendOutbox
            TrendOutbox(self.store).enqueue(scope_key,'pipeline-continuation:'+contracts.digest([event['event_id'],deferred]),'trend.ingested',
                {**p,'pending_observation_indices':[i for i,oid in enumerate(p['observation_ids']) if oid in set(deferred)]},cursor=cur)
        result={'state':'complete','associations':associations,'receipts':outputs,'deferred_count':len(deferred),'truncated':truncated,'decision_cutoff':decision_cutoff,'replayed':False}
        if outputs:
            self.store.put_projection({**value,'kind':'pipeline_run','object_id':run_id,'revision':1,
                'projection_id':run_id,'payload':result},cursor=cur)
        return result


    def _associate(self, cur, scope_key, output, bundle, *, limit):
        """Explicit lexical-only links; no topic/episode merge or global lifecycle."""
        if limit<=0:return []
        cur.execute('SELECT * FROM public.pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s',(scope_key,output['receipt_id']))
        current=row(cur);manifest=decode_manifest(self.store.get_manifest(scope_key,current['manifest_id'],cursor=cur))
        source=next(o for o in manifest['source_revisions'] if o['observation_id']==current['payload']['topic_source_id'])
        cur.execute('SELECT clock_timestamp() AS cutoff');at=row(cur)['cutoff']
        cur.execute("""SELECT DISTINCT ON(p.object_id) p.* FROM public.pr_trend_projections p
            WHERE p.scope_key=%s AND p.kind='trend' AND p.object_id<>%s AND p.available_at<=%s
            AND p.payload->>'platform'<>%s AND postriff_private.trend_node_valid(p.scope_key,p.projection_id)
            ORDER BY p.object_id,p.revision DESC LIMIT 20""",(scope_key,output['trend_id'],at,source['payload']['platform']))
        candidates=rows(cur);edges=[]
        for candidate in candidates:
            cur.execute("SELECT * FROM public.pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s AND verification_state='verified'",(scope_key,candidate['receipt_id']))
            other=row(cur)
            if not other:continue
            other_manifest=decode_manifest(self.store.get_manifest(scope_key,other['manifest_id'],cursor=cur))
            exemplar=next((o for o in other_manifest['source_revisions'] if o['observation_id']==other['payload'].get('topic_source_id')),None)
            if not exemplar or exemplar['payload']['language']!=source['payload']['language']:continue
            policies=self._policies(cur,scope_key,[source,exemplar],at)
            pair=clustering.compare_pair(source,exemplar,decision_cutoff=at,source_policies=policies)
            shared=set(clustering.text_features(source['payload']['text'])['tokens']) & set(clustering.text_features(exemplar['payload']['text'])['tokens'])
            entity_words=set()
            for item in (source,exemplar):
                for entity in item['payload'].get('entity_keys',[]):entity_words.update(clustering.text_features(entity)['tokens'])
            if pair['decision']!='same_conversation' or len(shared-entity_words)<3:continue
            receipt_ids=sorted([current['receipt_id'],other['receipt_id']])
            edge_id=uuid_map(scope_key,'association',contracts.digest(receipt_ids))
            cur.execute("SELECT 1 FROM public.pr_trend_projections WHERE scope_key=%s AND kind='topic_association' AND object_id=%s",(scope_key,edge_id))
            if cur.fetchone():edges.append(edge_id);continue
            expiry=min(current['payload']['expires_at'],other['payload']['expires_at'],key=contracts.instant)
            refs=[{'scope_key':scope_key,'node_id':rid} for rid in receipt_ids]
            recipe={'edge_type':'lexical_topic_association','receipt_ids':receipt_ids,'evidence_refs':[source['observation_id'],exemplar['observation_id']],
                    'feature_digest':pair['feature_digest'],'features':pair['features'],'mode':'lexical_only','semantic_qualification':'unqualified',
                    'topic_ids':sorted([output['trend_id'],candidate['object_id']]),'episode_ids':sorted([output['episode_id'],candidate['payload']['episode_id']]),
                    'platforms':sorted([source['payload']['platform'],exemplar['payload']['platform']]),'available_at':at,'method_version':bundle['method_version']}
            stored=self.store.put_manifest(scope_key,refs,decision_cutoff=at,available_at=at,retention_until=expiry,recipe=recipe,cursor=cur)
            self.store.put_projection({'scope_key':scope_key,'kind':'topic_association','object_id':edge_id,'revision':1,
                'manifest_id':stored['manifest_id'],**bundle,'decision_cutoff':at,'available_at':at,'retention_until':expiry,
                'payload':recipe},cursor=cur)
            edges.append(edge_id)
            if len(edges)>=limit:break
        return edges

    def _verify(self, cur, scope_key, receipt_id):
        cur.execute('SELECT * FROM public.pr_trend_trust_receipts WHERE scope_key=%s AND receipt_id=%s FOR UPDATE',(scope_key,receipt_id))
        saved=row(cur)
        if not saved: raise TrendStorageError('receipt_unavailable')
        stored=self.store.get_manifest(scope_key,saved['manifest_id'],cursor=cur)
        manifest=decode_manifest(stored);payload=saved['payload'];pure=payload['pure_receipt']
        if contracts.digest(pure)!=payload['pure_receipt_digest']: raise TrendStorageError('receipt_seal_mismatch')
        now=self.clock();policies=self._policies(cur,scope_key,manifest['source_revisions'],now)
        registry={}
        for artifact in implementation_methods():
            cur.execute('SELECT artifact_digest,qualification,revoked_at FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s',('trend.'+artifact['name'],artifact['version']))
            registered=row(cur)
            if registered and registered['artifact_digest']==artifact['artifact_digest'] and registered['qualification']!='withdrawn' and not registered['revoked_at']:
                registry=methods.register_method(registry,artifact)
        verification=receipts.verify_receipt(pure,manifest,registry,at=now,current_policies=policies)
        if verification['state']!='verified':
            cur.execute('UPDATE public.pr_trend_trust_receipts SET verification_state=%s,verification_record=%s WHERE scope_key=%s AND receipt_id=%s',
                        (verification['state'],bounded_json(verification),scope_key,receipt_id))
            return verification
        try:
            membership_refs=[item for kind,items in self._input_groups(scope_key,[],manifest['membership_revisions']) for item in items]
            if (type(payload.get('membership_dependency_count')) is not int
                    or payload['membership_dependency_count']!=len(membership_refs)
                    or payload.get('membership_dependency_digest')!=contracts.digest(membership_refs)):
                raise TrendStorageError('receipt_membership_binding_missing_or_mismatched')
            self._verify_dependencies(cur,scope_key,stored,manifest)
        except TrendStorageError as error:
            verification={'state':'mismatch','reason':str(error)}
            cur.execute('UPDATE public.pr_trend_trust_receipts SET verification_state=%s,verification_record=%s WHERE scope_key=%s AND receipt_id=%s',
                ('mismatch',bounded_json(verification),scope_key,receipt_id))
            return verification
        # Verify the numerical wire projection too, not only the embedded raw seal.
        from .service import build_trend_payload, build_receipt_payload
        source=next((o for o in manifest['source_revisions'] if o['observation_id']==payload['topic_source_id']),None)
        if source is None: raise TrendStorageError('topic_evidence_missing')
        title=' '.join(clustering.text_features(source['payload'].get('text',''),source['payload'].get('language'))['tokens'][:12])[:300]
        expected=build_trend_payload(pure,trend_id=payload['trend_id'],episode_id=payload['episode_id'],scope_key=scope_key,
            evidence=representative_evidence(manifest),canonical_topic=title,expires_at=payload['expires_at'],
            method_bundle={'method_id':saved['method_id'],'version':saved['method_version']})
        expected['platform_states']=_platform_states(expected,source['payload']['platform'])
        if any(expected[k]!=payload[k] for k in ('observed','calculated','coverage','inferred','canonical_topic','recipe_digest','evidence','platform_states')):
            cur.execute("UPDATE public.pr_trend_trust_receipts SET verification_state='mismatch' WHERE scope_key=%s AND receipt_id=%s",(scope_key,receipt_id))
            return {'state':'mismatch','reason':'wire_projection_mismatch'}
        bundle_digest=contracts.digest(manifest['method_artifacts'])
        return self.store.record_verification(scope_key,receipt_id,recomputed_digest=contracts.digest(payload),
            input_manifest_digest=stored['digest'],method_artifact_digest=bundle_digest,cursor=cur)

    def verify_pending(self, *, limit=20):
        if type(limit) is not int or not 1<=limit<=20: raise ValueError('verification_limit')
        with self.store.transaction() as cur:
            cur.execute("SELECT scope_key,receipt_id FROM public.pr_trend_trust_receipts WHERE verification_state='pending' ORDER BY decision_cutoff,receipt_id LIMIT %s FOR UPDATE SKIP LOCKED",(limit,))
            pending=rows(cur);result=[]
            for item in pending:
                # Per-receipt savepoints prevent one expired item aborting the page.
                cur.execute('SAVEPOINT trend_verify_one')
                try: state=self._verify(cur,item['scope_key'],item['receipt_id'])['state']
                except (ValueError,KeyError,TypeError):
                    cur.execute('ROLLBACK TO SAVEPOINT trend_verify_one')
                    cur.execute("SELECT * FROM public.pr_trend_projections WHERE scope_key=%s AND kind='receipt' AND receipt_id=%s ORDER BY revision DESC LIMIT 1",(item['scope_key'],item['receipt_id']))
                    projection=row(cur)
                    # Failed decoding/arithmetic means mismatch; deletion/expiry/
                    # revocation are independent current dependency states.
                    status=self.store._status(cur,projection) if projection else {}
                    state=status.get('verification_state','mismatch')
                    if state in ('pending','verified'): state='mismatch'
                    cur.execute('UPDATE public.pr_trend_trust_receipts SET verification_state=%s WHERE scope_key=%s AND receipt_id=%s',(state,item['scope_key'],item['receipt_id']))
                cur.execute('RELEASE SAVEPOINT trend_verify_one')
                result.append({**item,'state':state})
            return {'verified':sum(r['state']=='verified' for r in result),'results':result}
