"""Server-owned Meta public grants. No token, query or destination comes from a job.

A public authorization refers to the existing encrypted credential vault and one
immutable source policy. Every admission re-reads it; returned bearer tokens are
short-lived local values, never stored in a registry or queue. Provider quota
reservations commit before I/O and are not refunded after uncertain failures.
"""
from dataclasses import fields
import hashlib
import hmac

from .. import store as storage
from ..contracts import ContractError, digest, instant, uuid
from ..policy import SourcePolicy
from . import meta_public as meta

PUBLIC_CREDENTIALS = {p: 'meta_public_' + p for p in ('threads', 'instagram', 'facebook')}
JOB_KEYS = frozenset({'operation', 'max_items', 'seconds', 'budget_keys',
                     'reservation_microusd', 'coverage_epoch'})


def _denied():
    return ContractError('meta_public_authorization_unavailable')


def load_authorization(store, authorization_id, policy, *, at, cursor=None):
    """Revalidate encrypted custody and the exact public operation, with commit locks."""
    if (store is None or not policy.scope_key.startswith('workspace:')
            or not getattr(store, 'meta_vault', None)):
        raise _denied()
    uuid(authorization_id)
    with store.transaction(cursor) as cur:
        storage.trust_lock(cur)
        cur.execute('''SELECT a.*, c.provider AS credential_provider,
            c.provider_account_id AS credential_account_id,c.scopes AS credential_scopes,
            c.access_ciphertext,c.key_id,c.access_expires_at,c.revoked_at AS credential_revoked_at,
            postriff_private.trend_meta_authorization_valid(a.authorization_id) AS active
            FROM public.pr_trend_meta_authorizations a
            JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id)
            JOIN public.pr_workspaces w ON w.id=a.workspace_id
            WHERE a.authorization_id=%s AND a.workspace_id=%s
            AND a.provider_id=%s AND a.operation=%s AND a.source_policy_version=%s
            AND NOT w.state ? 'accountDeletion' FOR SHARE OF a,c''',
            (authorization_id,policy.scope_key[10:],policy.provider_id,policy.operation,policy.version))
        value=storage.row(cur)
        if (not value or value.get('active') is not True
                or value.get('authorization_id') != authorization_id
                or value.get('workspace_id') != policy.scope_key[10:]
                or value.get('provider_id') != policy.provider_id
                or value.get('operation') != policy.operation
                or value.get('source_policy_version') != policy.version
                or value.get('credential_provider') != PUBLIC_CREDENTIALS.get(policy.provider_id)
                or value.get('revoked_at') or value.get('credential_revoked_at')
                or not value.get('consent_at') or instant(value['consent_at']) > instant(at)
                or not value.get('access_expires_at')
                or instant(value['access_expires_at']) <= instant(at)
                or instant(value['expires_at']) <= instant(at)):
            raise _denied()
        ciphertext=value.get('access_ciphertext')
        if (not isinstance(ciphertext,str) or not ciphertext or
                not hmac.compare_digest(hashlib.sha256(ciphertext.encode()).hexdigest(),
                                        str(value.get('ciphertext_digest','')))):
            raise _denied()
        proof_data=value.get('review')
        if not isinstance(proof_data,dict): raise _denied()
        proof_data=dict(proof_data)
        for key in ('verified_scopes','approved_scopes','approved_features','reviewed_page_ids'):
            if not isinstance(proof_data.get(key),list): raise _denied()
            proof_data[key]=tuple(proof_data[key])
        try:
            proof=meta.ReviewProof(**proof_data)
            if (proof.review_id != authorization_id or proof.scope_key != policy.scope_key
                    or proof.provider_id != policy.provider_id or proof.operation != policy.operation
                    or proof.account_id != value['credential_account_id']
                    or set(proof.verified_scopes) != set(value['credential_scopes'])
                    or instant(proof.expires_at) > instant(value['access_expires_at'])
                    or not instant(proof.verified_at) <= instant(at) < instant(proof.expires_at)
                    or (instant(at)-instant(proof.verified_at)).total_seconds() > 900):
                raise _denied()
            try:
                token=store.meta_vault.decrypt(ciphertext,value['key_id'])
            except Exception:
                raise _denied() from None
            if not hmac.compare_digest(meta.token_fingerprint(token),proof.token_fingerprint):
                raise _denied()
            selection=value.get('selection')
            reviewed_policy={'policy_id':policy.id,'version':policy.version,'scope_key':policy.scope_key,
                'provider_id':policy.provider_id,'operation':policy.operation,'rights':policy.rights,
                'max_retention_seconds':policy.retention_seconds}
            if not isinstance(selection,dict) or selection.get('reviewed_policy') != reviewed_policy:
                raise _denied()
            # Collector validation is also performed by the adapter immediately before I/O.
            meta.validate_review(proof,meta.CAPABILITIES[policy.provider_id,policy.operation],
                policy,token,at,account_id=selection.get('ig_user_id'),page_id=selection.get('reviewed_page_id'))
        except (ValueError,TypeError,KeyError,AttributeError):
            raise _denied() from None
        return value,proof,token


class MetaCollector:
    def __init__(self,store,authorization_id,*,clock=None,transport=None):
        self.store,self.authorization_id=store,authorization_id
        self.clock=clock or storage.utcnow
        self.transport=transport
        self.http_attempts=0

    def _http_start(self):
        self.http_attempts += 1

    def assert_current(self,policy,at,*,cursor=None):
        load_authorization(self.store,self.authorization_id,policy,at=at,cursor=cursor)

    def reserve(self,policy,name,key,units):
        if units != 1 or type(units) is not int: raise ContractError('meta_quota_invalid')
        with self.store.transaction() as cur:
            at=self.clock()
            value,proof,_=load_authorization(self.store,self.authorization_id,policy,at=at,cursor=cur)
            rule=(value.get('quota_rules') or {}).get(name)
            if (not isinstance(rule,dict) or set(rule)!={'limit','window_seconds'}
                    or type(rule['limit']) is not int or not 1<=rule['limit']<=1_000_000
                    or type(rule['window_seconds']) is not int or not 1<=rule['window_seconds']<=604800):
                raise ContractError('meta_quota_rule_unverified')
            expected={'threads_keyword_search':policy.scope_key,
                      'instagram_graph_request':policy.scope_key,
                      'facebook_public_page_read':value['selection'].get('reviewed_page_id')}
            distinct=name=='instagram_distinct_hashtag_7d'
            if distinct:
                hashtag=meta._query(value['selection'].get('hashtag'),hashtag=True).casefold()
                if key.casefold()!=proof.account_id+':'+hashtag or rule['limit']!=proof.quota_limit or rule['limit']>30 or rule['window_seconds']!=proof.quota_window_seconds or rule['window_seconds']!=604800:
                    raise ContractError('meta_quota_domain_mismatch')
            elif name!='instagram_graph_request' and (rule['limit'] != proof.quota_limit or rule['window_seconds'] != proof.quota_window_seconds):
                raise ContractError('meta_quota_rule_unverified')
            elif name not in expected or key != expected[name]:
                raise ContractError('meta_quota_domain_mismatch')
            # The same app/account cannot escape provider limits through another workspace.
            # Bucket identity does not include configurable policy/review versions.
            bucket=digest([policy.provider_id,proof.app_id,proof.account_id,name])
            subject=digest(key.casefold()) if distinct else digest([self.authorization_id,at,uuid4()])
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('meta-quota:'+bucket,))
            cur.execute('''SELECT count(DISTINCT subject_digest) AS used,
                bool_or(subject_digest=%s) AS repeated FROM public.pr_trend_meta_quota_events
                WHERE bucket_digest=%s AND reserved_at>clock_timestamp()-make_interval(secs=>%s)''',
                (subject,bucket,rule['window_seconds']))
            used=storage.row(cur)
            if used['used']>=rule['limit'] and not (distinct and used['repeated']):
                raise ContractError('meta_provider_quota_exhausted')
            cur.execute('''INSERT INTO public.pr_trend_meta_quota_events
                (bucket_digest,subject_digest,authorization_id,rule_ref)
                VALUES(%s,%s,%s,%s)''',(bucket,subject,self.authorization_id,proof.quota_rule_ref))
        return True

    def __call__(self,*,policy,cursor,now,payload,reservation_microusd):
        self.http_attempts=0
        if not isinstance(payload,dict) or set(payload)-JOB_KEYS:
            raise ContractError('meta_job_override_forbidden')
        if payload.get('operation',policy.operation)!=policy.operation:
            raise ContractError('meta_job_override_forbidden')
        value,proof,token=load_authorization(self.store,self.authorization_id,policy,at=self.clock())
        common=dict(policy=policy,review=proof,token=token,received_at=now,available_at=now,
            coverage_epoch=payload['coverage_epoch'],enabled=True,entitlement_current=True,
            quota_reserve=lambda name,key,units:self.reserve(policy,name,key,units),
            limit=payload['max_items'],cursor=cursor or None,transport=self.transport,
            reservation_microusd=reservation_microusd,on_http_start=self._http_start)
        selection=value['selection']
        if policy.provider_id=='threads':
            result=meta.collect_threads_keyword(**common,query=selection['query'],search_type=selection['search_type'])
        elif policy.provider_id=='instagram':
            result=meta.collect_instagram_hashtag(**common,ig_user_id=selection['ig_user_id'],hashtag=selection['hashtag'])
        else:
            result=meta.collect_facebook_public_page(**common,reviewed_page_id=selection['reviewed_page_id'])
        self.assert_current(policy,self.clock())
        # Only separately reviewed third-party samples can qualify a source LIVE.
        # APIs that omit authors remain unknown; synthetic transports never qualify.
        reviewed=set(selection.get('third_party_source_ids',()))
        for observation in result.observations:
            if (observation['provenance'].get('evidence_kind')=='provider_response'
                    and observation['source_identity'] in reviewed):
                observation['provenance']['third_party']=True
                observation['provenance']['third_party_evidence_ref']=selection['third_party_evidence_ref']
        return result


def uuid4():
    from uuid import uuid4 as create
    return str(create())


def binding(store,manifest,contract_version):
    identity=(manifest.get('provider_id'),manifest.get('operation'))
    if identity not in meta.CAPABILITIES or contract_version!=meta.PROTOCOL:
        return None
    try:
        policy=SourcePolicy(**{f.name:manifest[f.name] for f in fields(SourcePolicy) if f.name in manifest})
        collector=MetaCollector(store,manifest['meta_authorization_id'])
        collector.assert_current(policy,storage.utcnow())
        return meta.CAPABILITIES[identity],collector
    except (ContractError,TypeError,ValueError,KeyError,AttributeError):
        return None
    except Exception as exc:
        if getattr(exc,'sqlstate',None) in ('42P01','42883','42703'): return None
        raise
