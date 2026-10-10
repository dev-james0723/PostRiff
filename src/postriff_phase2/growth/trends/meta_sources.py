"""Stored-only public discovery status, independent from owned-account analytics."""
from . import config
from .contracts import instant,iso
from .service import envelope,error,ident
from .store import rows,utcnow,trust_lock

SOURCES=(('instagram','hashtag_discovery','Instagram hashtags'),
         ('threads','keyword_search','Threads keywords'),
         ('facebook','page_public_posts','Facebook public Pages'))
FRESHNESS_SECONDS=900


def source_status(value,*,at):
    if not value:return 'APP_REVIEW_REQUIRED'
    if value.get('revoked_at'):return 'REVOKED'
    if value.get('active') is not True:return 'AUTHORIZATION_REQUIRED'
    latest=value.get('latest_successful_read')
    if not latest or value.get('evidence_kind')!='provider_response' or value.get('third_party') is not True:
        return 'UNVERIFIED'
    age=(instant(at)-instant(latest)).total_seconds()
    if age<0:return 'UNVERIFIED'
    if value.get('next_allowed_at') and instant(value['next_allowed_at'])>instant(at):return 'PAUSED'
    return 'LIVE' if age<=FRESHNESS_SECONDS else 'STALE'


def read(service,workspace_id,token):
    with service.transaction(workspace_id,token) as (_store,cur,_row,_actor,_state,_scopes):
        at=utcnow()
        cur.execute("SELECT to_regclass('public.pr_trend_meta_authorizations') AS installed")
        installed=cur.fetchone()
        installed=installed.get('installed') if isinstance(installed,dict) else installed[0]
        found=[]
        if installed:
            cur.execute('''SELECT DISTINCT ON(a.provider_id,a.operation) a.authorization_id,a.provider_id,a.operation,a.revoked_at,
                postriff_private.trend_meta_authorization_valid(a.authorization_id) AS active,
                a.review->>'verified_at' AS verified_at,a.expires_at,
                sample.available_at AS latest_successful_read,
                sample.provenance->>'evidence_kind' AS evidence_kind,
                sample.provenance->'third_party' AS third_party,h.next_allowed_at
                FROM public.pr_trend_meta_authorizations a
                LEFT JOIN public.pr_trend_source_health h ON h.scope_key='workspace:'||a.workspace_id::text AND h.provider_id=a.provider_id
                LEFT JOIN LATERAL (
                    SELECT o.available_at,o.provenance FROM public.pr_trend_observations o
                    WHERE o.scope_key='workspace:'||a.workspace_id::text AND o.provider_id=a.provider_id
                    AND o.source_policy_version=a.source_policy_version
                    AND o.provenance->>'review_id'=a.authorization_id::text
                    AND o.provenance->>'evidence_kind'='provider_response'
                    AND o.provenance->'third_party'='true'::jsonb
                    AND o.purged_at IS NULL
                    AND postriff_private.trend_node_valid(o.scope_key,o.observation_id)
                    ORDER BY o.available_at DESC LIMIT 1
                ) sample ON true WHERE a.workspace_id=%s ORDER BY a.provider_id,a.operation,a.review->>'verified_at' DESC,a.authorization_id DESC''',(workspace_id,))
            found=rows(cur)
        data=[]
        for provider,operation,label in SOURCES:
            item=next((v for v in found if (v['provider_id'],v['operation'])==(provider,operation)),None)
            state=source_status(item,at=at)
            enabled=config.dispatch_allowed(provider,operation,service.values)
            if state=='LIVE' and not enabled:state='PAUSED'
            data.append(dict(provider=provider,operation=operation,label=label,status=state,
                authorization_id=item['authorization_id'] if item else None,
                latest_successful_read=iso(instant(item['latest_successful_read'])) if item and item['latest_successful_read'] else None,
                expires_at=iso(instant(item['expires_at'])) if item else None,
                dispatch_enabled=enabled,
                coverage='Selected hashtags, queries or reviewed Pages only. Not all public posts.',
                semantic_evaluation='Requires current source rights, workspace consent and model budget.'))
        return envelope(data,at,execution_state='stored_result',limitations=['public_source_permissions_are_separate_from_owned_analytics'])


def revoke(service,workspace_id,token,authorization_id):
    authorization_id=ident(authorization_id)
    with service.transaction(workspace_id,token,'manage_connections') as (_store,cur,_row,_actor,_state,_scopes):
        trust_lock(cur,exclusive=True)
        cur.execute('''UPDATE public.pr_trend_meta_authorizations SET revoked_at=coalesce(revoked_at,clock_timestamp())
            WHERE workspace_id=%s AND authorization_id=%s RETURNING connection_id''',(workspace_id,authorization_id))
        values=rows(cur)
        if not values:raise error('not_found',404)
        cur.execute('''UPDATE public.pr_encrypted_credentials SET revoked_at=coalesce(revoked_at,clock_timestamp()),access_ciphertext='',refresh_ciphertext=NULL,scopes='{}',updated_at=clock_timestamp()
            WHERE workspace_id=%s AND connection_id=%s AND provider=ANY(%s)''',
            (workspace_id,values[0]['connection_id'],['meta_public_threads','meta_public_instagram','meta_public_facebook']))
        return envelope({'authorization_id':authorization_id,'status':'REVOKED'},utcnow(),execution_state='stored_result')
