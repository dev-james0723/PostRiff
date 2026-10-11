"""YouTube-only published-policy authority. No user input can register legal copy.

Receipts belong to the authenticated holder in one workspace. OAuth pins the
receipt and policy; worker dispatch binds it to the actual credential generation.
The sole compatibility exception is nonpublic, standard, read-only onboarding.
"""
import copy
import re
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from ..api_tokens import is_api_token
from .model import READ


class YouTubePolicyAcceptance:
    def __init__(self, oauth):
        self.oauth, self.repository = oauth, oauth.repository

    def required(self, provider, *, capability='identity', scopes=(), force=False):
        if force and provider is None:
            return True  # Explicit YouTube surfaces fail closed even if unmounted.
        if getattr(provider, 'id', None) != 'youtube':
            return False
        return bool(force or self.oauth.youtube_public_base_url
                    or getattr(provider, 'policy_public_binding', False)
                    or getattr(provider, 'production_reviewed', False)
                    or getattr(provider, 'creator_enabled', False)
                    or getattr(provider, 'authorization_lane', 'standard') != 'standard'
                    or capability not in ('identity', 'posts_read')
                    or set(scopes or ()) - {READ})

    @staticmethod
    def _not_ready():
        return AlphaError('The published YouTube Privacy Policy and Terms are not ready. YouTube access is unavailable.',
                          503, code='youtube_policy_not_ready')

    @staticmethod
    def _acceptance_required():
        return AlphaError('Review and agree to the current published Privacy Policy and Terms before using YouTube.',
                          409, code='youtube_policy_acceptance_required')

    @staticmethod
    def _interactive(token):
        if is_api_token(token):
            raise AlphaError('Sign in to review and accept the YouTube policies yourself.', 403,
                             code='youtube_policy_interactive_required')

    def _current(self, cur):
        cur.execute("SELECT to_regclass('public.pr_youtube_policy_revisions'),"
                    "to_regclass('public.pr_youtube_policy_acceptances'),to_regclass('public.pr_youtube_policy_bindings')")
        schema = cur.fetchone()
        if not schema or not all(schema):
            raise self._not_ready()
        # SHARE prevents a revision switch through this admission transaction.
        cur.execute("""SELECT id::text,privacy_revision,privacy_url,privacy_sha256,
            terms_revision,terms_url,terms_sha256,extract(epoch from published_at)::float8
            FROM public.pr_youtube_policy_revisions
            WHERE is_current AND approved_at<=now() AND published_at<=now() FOR SHARE""")
        row = cur.fetchone()
        if not row:
            raise self._not_ready()
        try:
            origin = urlsplit(self.oauth.youtube_public_base_url or self.oauth.public_base_url)
            for address in (row[2], row[5]):
                parsed = urlsplit(address)
                if (parsed.scheme != 'https' or origin.scheme != 'https' or parsed.netloc != origin.netloc
                        or parsed.username or parsed.password or parsed.query or parsed.fragment
                        or not parsed.path or parsed.path == '/'):
                    raise self._not_ready()
        except ValueError as error:
            raise self._not_ready() from error
        if any(not re.fullmatch('[0-9a-f]{64}', value or '') for value in (row[3], row[6])):
            raise self._not_ready()
        return {'id': row[0], 'privacy': {'revision': row[1], 'url': row[2], 'sha256': row[3]},
                'terms': {'revision': row[4], 'url': row[5], 'sha256': row[6]}, 'publishedAt': row[7]}

    @staticmethod
    def _receipt(cur, workspace, user, policy):
        cur.execute("""SELECT a.id::text,extract(epoch from a.accepted_at)::float8
            FROM public.pr_youtube_policy_acceptances a
            JOIN public.pr_memberships m ON m.workspace_id=a.workspace_id AND m.user_id=a.user_id
            JOIN public.pr_profiles p ON p.user_id=a.user_id
            WHERE a.workspace_id=%s AND a.user_id=%s AND a.policy_id=%s
              AND m.status='active' AND p.deleted_at IS NULL""", (workspace, user, policy['id']))
        row = cur.fetchone()
        return {'id': row[0], 'acceptedAt': row[1], 'policyId': policy['id'],
                'workspaceId': str(workspace), 'userId': str(user)} if row else None

    def require_user(self, cur, workspace, user, token, provider, *, capability='identity', scopes=(), force=False, snapshot=None):
        required = self.required(provider, capability=capability, scopes=scopes, force=force) or snapshot is not None
        if not required:
            return None
        self._interactive(token)
        policy = self._current(cur)
        receipt = self._receipt(cur, workspace, user, policy)
        if not receipt or snapshot is not None and (snapshot.get('policyId') != policy['id']
                or snapshot.get('receiptId') != receipt['id']):
            raise self._acceptance_required()
        return {'policyId': policy['id'], 'receiptId': receipt['id']}

    def status(self, workspace, token):
        with self.repository.transaction(token, workspace) as (cur, _, user):
            provider = self.oauth.providers.get('youtube')
            required = bool(provider and self.required(provider))
            try:
                policy = self._current(cur)
            except AlphaError as error:
                if error.code != 'youtube_policy_not_ready':
                    raise
                return {'ready': False, 'requiredForConnection': required, 'accepted': False,
                        'policy': None, 'receipt': None}
            receipt = self._receipt(cur, workspace, user, policy)
            return {'ready': True, 'requiredForConnection': required, 'accepted': bool(receipt),
                    'policy': policy, 'receipt': receipt}

    def require_pending(self, cur, workspace, user, token, provider, scopes, context):
        snapshot = context.get('policyAcceptance')
        if self.required(provider, scopes=scopes) and not isinstance(snapshot, dict):
            # A legacy in-flight request cannot acquire public authority later.
            raise self._acceptance_required()
        return self.require_user(cur, workspace, user, token, provider, scopes=scopes, snapshot=snapshot)

    def accept(self, workspace, token, body):
        self._interactive(token)
        # Reject body-supplied identity, receipt, timestamp, URL or approval claims.
        if not isinstance(body, dict) or set(body) != {'policyId', 'privacyRevision', 'termsRevision', 'confirmed'} or body['confirmed'] is not True:
            raise AlphaError('Explicitly agree to the displayed published policies.', 400)
        with self.repository.transaction(token, workspace) as (cur, _, user):
            policy = self._current(cur)
            if (body['policyId'] != policy['id'] or body['privacyRevision'] != policy['privacy']['revision']
                    or body['termsRevision'] != policy['terms']['revision']):
                raise self._acceptance_required()
            cur.execute("""INSERT INTO public.pr_youtube_policy_acceptances(workspace_id,user_id,policy_id)
                VALUES(%s,%s,%s) ON CONFLICT(workspace_id,user_id,policy_id) DO NOTHING""", (workspace, user, policy['id']))
            receipt = self._receipt(cur, workspace, user, policy)
            # Renew this holder's established connections only; accepting never
            # claims another person's binding or manufactures legacy OAuth proof.
            cur.execute("""UPDATE public.pr_youtube_policy_bindings b SET receipt_id=%s
                FROM public.pr_youtube_policy_acceptances a
                WHERE b.workspace_id=%s AND a.workspace_id=b.workspace_id
                  AND a.id=b.receipt_id AND a.user_id=%s""", (receipt['id'], workspace, user))
            from ..hosted import audit
            audit(cur, workspace, user, 'youtube.policy_accepted', receipt['id'], {'policyId': policy['id']})
            return {'ready': True, 'requiredForConnection': bool(self.oauth.providers.get('youtube')
                    and self.required(self.oauth.providers['youtube'])), 'accepted': True, 'policy': policy, 'receipt': receipt}

    def bind(self, cur, workspace, connection, snapshot):
        if snapshot is None:
            return
        cur.execute("""INSERT INTO public.pr_youtube_policy_bindings(workspace_id,connection_id,authorization_generation,receipt_id)
            SELECT workspace_id,connection_id,authorization_generation,%s FROM public.pr_encrypted_credentials
            WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL
            ON CONFLICT(workspace_id,connection_id) DO UPDATE
            SET authorization_generation=excluded.authorization_generation,receipt_id=excluded.receipt_id""",
            (snapshot['receiptId'], workspace, connection))

    def assert_connection(self, workspace, connection, provider, *, scopes=(), generation=None, force=False, cur=None):
        if not self.required(provider, scopes=scopes, force=force):
            return
        if cur is None:
            with self.repository.connection_factory() as db, db.cursor() as cursor:
                return self.assert_connection(workspace, connection, provider, scopes=scopes,
                                              generation=generation, force=force, cur=cursor)
        policy = self._current(cur)
        cur.execute("""SELECT b.authorization_generation::text FROM public.pr_youtube_policy_bindings b
            JOIN public.pr_encrypted_credentials c ON c.workspace_id=b.workspace_id AND c.connection_id=b.connection_id
            JOIN public.pr_youtube_policy_acceptances a ON a.workspace_id=b.workspace_id AND a.id=b.receipt_id
            JOIN public.pr_memberships m ON m.workspace_id=a.workspace_id AND m.user_id=a.user_id
            JOIN public.pr_profiles p ON p.user_id=a.user_id
            JOIN public.pr_workspaces w ON w.id=b.workspace_id
            WHERE b.workspace_id=%s AND b.connection_id=%s AND c.provider='youtube' AND c.revoked_at IS NULL
              AND b.authorization_generation=c.authorization_generation AND a.policy_id=%s
              AND m.status='active' AND p.deleted_at IS NULL
              AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'""", (workspace, connection, policy['id']))
        found = cur.fetchone()
        if not found or generation is not None and str(generation) != found[0]:
            raise self._acceptance_required()

    def guarded_provider(self, provider, grant):
        context = grant.get('_youtubePolicyContext')
        if not context:
            return provider
        routed = copy.copy(provider)
        transport = provider.transport
        def guarded(method, url, **kwargs):
            # Revocation is always reachable, including while policies are stale.
            if url != provider.REVOKE:
                self.assert_connection(context['workspace'], context['connection'], provider,
                    scopes=grant.get('scopes', ()), generation=grant.get('authorizationGeneration'), force=context['force'])
            return transport(method, url, **kwargs)
        routed.transport = guarded
        return routed
