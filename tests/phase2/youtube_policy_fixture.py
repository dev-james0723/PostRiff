"""Synthetic policies in disposable CI only. Never imports or accepts real legal copy."""
import os
import sys
from uuid import uuid4


def register_synthetic_policy(connection, origin, *, replace=False):
    assert sys.platform.startswith('linux') and os.environ.get('CI', '').lower() in ('1', 'true')
    with connection() as db:
        assert db.info.host == '127.0.0.1' and db.info.dbname == 'postgres'
        rows = db.execute("SELECT id::text,privacy_url,approval_reference FROM public.pr_youtube_policy_revisions WHERE is_current").fetchall()
        assert all(row[2] == 'SYNTHETIC CI ONLY - NOT OWNER APPROVAL' for row in rows)
        if rows and rows[0][1] == origin + '/privacy' and not replace:
            return rows[0][0]
        db.execute('UPDATE public.pr_youtube_policy_revisions SET is_current=false WHERE is_current')
        identifier = str(uuid4())
        db.execute("""INSERT INTO public.pr_youtube_policy_revisions(id,privacy_revision,privacy_url,privacy_sha256,
            terms_revision,terms_url,terms_sha256,approved_by,approval_reference,approved_at,published_at,is_current)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'synthetic-fixture','SYNTHETIC CI ONLY - NOT OWNER APPROVAL',now(),now(),true)""",
            (identifier, 'SYNTHETIC-privacy-' + identifier, origin + '/privacy', 'a'*64,
             'SYNTHETIC-terms-' + identifier, origin + '/terms', 'b'*64))
        return identifier


def accept_synthetic_policy(service, workspace, token):
    status = service.oauth.youtube_policy.status(workspace, token)
    assert status['ready'] and status['policy']['privacy']['revision'].startswith('SYNTHETIC-')
    policy = status['policy']
    return service.oauth.youtube_policy.accept(workspace, token, {'policyId': policy['id'],
        'privacyRevision': policy['privacy']['revision'], 'termsRevision': policy['terms']['revision'], 'confirmed': True})
