"""Trusted operator import for Meta PUBLIC grants; deliberately no HTTP/OAuth route.

Meta's reviewed diagnostic example puts input_token in a query string. A safe
body/header diagnostic protocol has not been verified. Accordingly this module
performs NO diagnostic network request and does NOT claim automated verification.
An operator-controlled server evidence repository supplies the raw diagnostic,
separate App Review record, identity binding and consent. Never wire that reader
or this import API to browser JSON, jobs, or a caller-provided `verified` boolean.

Only the encrypted existing CredentialVault persists a token. Provider responses
are transient; stored proof is a minimal derived admission record. Registering a
grant does not enable a source, schedule a job, or establish live public coverage.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import re
from uuid import uuid4

from .. import store as storage
from ..contracts import ContractError, canonical, digest, instant, iso, uuid
from . import meta_public as meta
from .meta_runtime import PUBLIC_CREDENTIALS

DIAGNOSTIC_PROTOCOL_STATE = 'blocked_safe_diagnostic_transport_unverified'
MAX_DIAGNOSTIC_AGE_SECONDS = 900
_REF = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$')
_ID = re.compile(r'^[0-9]{1,40}$')
_HASH = re.compile(r'^[a-f0-9]{64}$')


def _deny(code='meta_operator_evidence_invalid'):
    return ContractError(code)


def _reference(value):
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise _deny()
    return value


def _strings(value):
    if (not isinstance(value, list) or len(value) > 100
            or any(not isinstance(x, str) or not _REF.fullmatch(x) for x in value)
            or len(set(value)) != len(value)):
        raise _deny()
    return tuple(sorted(value))


def _record(value, kind):
    if (not isinstance(value, dict) or value.get('kind') != kind
            or len(canonical(value).encode()) > 32768
            or not _HASH.fullmatch(str(value.get('artifact_sha256', '')))):
        raise _deny()
    _reference(value.get('reviewed_by'))
    return value


def _epoch(value, *, allow_zero=False):
    if type(value) is not int or value < 0 or (value == 0 and not allow_zero):
        raise _deny()
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise _deny() from None


def _bound(record, *, policy, app_id, account_id, fingerprint):
    if any(record.get(key) != expected for key, expected in {
        'provider_id': policy.provider_id, 'operation': policy.operation,
        'app_id': app_id, 'workspace_id': policy.scope_key[10:],
        'account_id': account_id, 'token_fingerprint': fingerprint,
    }.items()):
        raise _deny()


def _policy_rights_bound(record, policy):
    """The token grant cannot enlarge independently reviewed processing rights."""
    expected = {'source_policy_id': policy.id, 'source_policy_version': policy.version,
                'scope_key': policy.scope_key, 'provider_id': policy.provider_id,
                'operation': policy.operation, 'rights_digest': digest(policy.rights)}
    if any(record.get(key) != value for key, value in expected.items()):
        raise _deny('meta_processing_rights_unreviewed')
    ceiling = record.get('max_retention_seconds')
    if (type(ceiling) is not int or not 1 <= ceiling <= 366 * 86400
            or policy.retention_seconds > ceiling):
        raise _deny('meta_retention_unreviewed')


def import_operator_review(*, policy, token, expected_app_id, diagnostic, app_review,
                           consent, app_review_ref, at, authorization_id, selection):
    """Validate trusted server evidence, not arbitrary client claims.

    The operator's identity envelope binds the inspected account to the raw token
    subject. It is an explicit human attestation, not an automated account lookup.
    Every renewal requires fresh diagnostics and a NEW immutable authorization ID.
    """
    try:
        return _import_operator_review(policy=policy, token=token,
            expected_app_id=expected_app_id, diagnostic=diagnostic, app_review=app_review,
            consent=consent, app_review_ref=app_review_ref, at=at,
            authorization_id=authorization_id, selection=selection)
    except ContractError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise _deny() from None


def _import_operator_review(*, policy, token, expected_app_id, diagnostic, app_review,
                            consent, app_review_ref, at, authorization_id, selection):
    uuid(authorization_id)
    if not policy.scope_key.startswith('workspace:'):
        raise _deny()
    uuid(policy.scope_key[10:])
    if not isinstance(expected_app_id, str) or not _ID.fullmatch(expected_app_id):
        raise _deny()
    cap = meta.CAPABILITIES.get((policy.provider_id, policy.operation))
    if cap is None:
        raise _deny()
    diagnostic = _record(diagnostic, 'meta_token_diagnostic')
    review = _record(app_review, 'meta_app_review')
    consent = _record(consent, 'meta_public_consent')
    for artifact in (review, consent):
        _policy_rights_bound(artifact, policy)
    _reference(app_review_ref)
    fingerprint = meta.token_fingerprint(token)
    account = diagnostic.get('account_id')
    if not isinstance(account, str) or not _ID.fullmatch(account):
        raise _deny()
    for record in (diagnostic, consent):
        _bound(record, policy=policy, app_id=expected_app_id, account_id=account,
               fingerprint=fingerprint)
    for key, expected in {'app_id': expected_app_id, 'provider_id': policy.provider_id,
                          'operation': policy.operation,
                          'api_version': diagnostic.get('api_version')}.items():
        if review.get(key) != expected:
            raise _deny()
    now = instant(at)
    captured = instant(diagnostic['captured_at'])
    if not timedelta(0) <= now - captured < timedelta(seconds=MAX_DIAGNOSTIC_AGE_SECONDS):
        raise _deny('meta_diagnostic_stale')
    if (review.get('status') != 'approved'
            or not instant(review['reviewed_at']) <= now < instant(review['expires_at'])
            or consent.get('status') != 'granted'
            or not instant(consent['granted_at']) <= now < instant(consent['expires_at'])):
        raise _deny()
    raw = diagnostic['response']['data']
    if (not isinstance(raw, dict) or raw.get('is_valid') is not True
            or raw.get('app_id') != expected_app_id):
        raise _deny()
    expires = _epoch(raw.get('expires_at'))
    if 'data_access_expires_at' in raw:
        data_expiry = _epoch(raw['data_access_expires_at'], allow_zero=True)
        if raw['data_access_expires_at']:
            expires = min(expires, data_expiry)
    if expires <= now:
        raise _deny('meta_diagnostic_expired')
    if 'issued_at' in raw and _epoch(raw['issued_at'], allow_zero=True) > captured:
        raise _deny()
    scopes = _strings(raw.get('scopes'))
    approved_scopes = _strings(review.get('approved_scopes'))
    features = _strings(review.get('approved_features'))
    identity = diagnostic.get('identity')
    if not isinstance(identity, dict) or identity.get('id') != account:
        raise _deny()
    kind, login = diagnostic.get('account_kind'), diagnostic.get('login_kind')
    subject = diagnostic.get('token_subject_id')
    if policy.provider_id == 'threads':
        if (raw.get('type') != 'USER' or subject != account or raw.get('user_id') != subject
                or kind != 'user' or login != 'threads_login'):
            raise _deny()
    elif policy.provider_id == 'instagram':
        if (raw.get('type') != 'USER' or raw.get('user_id') != subject
                or not isinstance(subject, str) or not _ID.fullmatch(subject)
                or kind not in ('business', 'creator') or login != 'facebook_login'
                or identity.get('account_type') != {'business': 'BUSINESS', 'creator': 'MEDIA_CREATOR'}[kind]
                or not _ID.fullmatch(str(identity.get('linked_page_id', '')))
                or identity.get('token_subject_id') != subject):
            raise _deny()
    else:
        if login != 'facebook_login' or kind not in ('app', 'system_user'):
            raise _deny()
        if kind == 'app':
            if raw.get('type') != 'APP' or account != expected_app_id or subject != expected_app_id:
                raise _deny()
        elif raw.get('type') != 'SYSTEM_USER' or raw.get('user_id') != account or subject != account:
            raise _deny()
    proof_expiry = min(expires, captured + timedelta(seconds=MAX_DIAGNOSTIC_AGE_SECONDS),
                       instant(review['expires_at']), instant(consent['expires_at']),
                       instant(policy.expires_at))
    proof = meta.ReviewProof(review_id=authorization_id, app_id=expected_app_id,
        provider_id=policy.provider_id, operation=policy.operation,
        api_version=diagnostic['api_version'], scope_key=policy.scope_key,
        login_kind=login, account_id=account, account_kind=kind,
        token_fingerprint=fingerprint, verified_scopes=scopes, approved_scopes=approved_scopes,
        approved_features=features, verified_at=iso(captured), expires_at=iso(proof_expiry),
        quota_limit=review['quota_limit'], quota_window_seconds=review['quota_window_seconds'],
        reviewed_page_ids=_strings(review.get('reviewed_page_ids')),
        page_public=review.get('page_public'), page_restricted=review.get('page_restricted'),
        consent_current=True, review_ref=app_review_ref, quota_rule_ref=_reference(review['quota_rule_ref']))
    selection = _selection(policy.provider_id, selection)
    policy.require('retrieve', at)
    meta.validate_review(proof, cap, policy, token, at,
        account_id=selection.get('ig_user_id'), page_id=selection.get('reviewed_page_id'))
    return proof


def _selection(provider, selection):
    expected = {'threads': {'query', 'search_type'}, 'instagram': {'ig_user_id', 'hashtag'},
                'facebook': {'reviewed_page_id'}}[provider]
    if not isinstance(selection, dict) or set(selection) != expected:
        raise _deny('meta_selection_invalid')
    value = dict(selection)
    if provider == 'threads':
        value['query'] = meta._query(value['query'])
        if value['search_type'] not in ('TOP', 'RECENT'):
            raise _deny('meta_selection_invalid')
    elif provider == 'instagram':
        value['hashtag'] = meta._query(value['hashtag'], hashtag=True)
        if not _ID.fullmatch(str(value['ig_user_id'])) or not isinstance(value['ig_user_id'], str):
            raise _deny('meta_selection_invalid')
    elif not isinstance(value['reviewed_page_id'], str) or not _ID.fullmatch(value['reviewed_page_id']):
        raise _deny('meta_selection_invalid')
    return value


def _quota_rules(provider, proof, value, approved):
    names = {'threads': {'threads_keyword_search'},
             'instagram': {'instagram_graph_request', 'instagram_distinct_hashtag_7d'},
             'facebook': {'facebook_public_page_read'}}[provider]
    if (not isinstance(value, dict) or set(value) != names
            or not isinstance(approved, dict) or value != approved):
        raise _deny('meta_quota_rule_unverified')
    result = {}
    for name, rule in value.items():
        if (not isinstance(rule, dict) or set(rule) != {'limit', 'window_seconds'}
                or type(rule['limit']) is not int or type(rule['window_seconds']) is not int
                or not 1 <= rule['limit'] <= 1_000_000
                or not 1 <= rule['window_seconds'] <= 604800):
            raise _deny('meta_quota_rule_unverified')
        if name == 'instagram_distinct_hashtag_7d':
            if (rule['limit'] > 30 or rule['window_seconds'] != 604800
                    or rule['limit'] != proof.quota_limit
                    or rule['window_seconds'] != proof.quota_window_seconds):
                raise _deny('meta_quota_rule_unverified')
        elif provider != 'instagram' and (rule['limit'] != proof.quota_limit
                or rule['window_seconds'] != proof.quota_window_seconds):
            raise _deny('meta_quota_rule_unverified')
        result[name] = dict(rule)
    return result


def _third_party_attestation(provider, review):
    """Human-reviewed exact IDs, never inferred ownership or client selection.

    These fields belong to the same private operator review artifact. They allow
    a runtime to qualify a matching genuine response; they do not make synthetic
    observations live, establish author identity or trigger acquisition.
    """
    sources = review.get('third_party_source_ids', [])
    if not isinstance(sources, list) or len(sources) > 20:
        raise _deny('meta_third_party_attestation_invalid')
    pattern = provider + r':[0-9]{1,40}' + (r'(?:_[0-9]{1,40})?' if provider == 'facebook' else '')
    if (any(not isinstance(value, str) or not re.fullmatch(pattern, value) for value in sources)
            or len(set(sources)) != len(sources)):
        raise _deny('meta_third_party_attestation_invalid')
    if not sources:
        if review.get('third_party_evidence_ref'):
            raise _deny('meta_third_party_attestation_invalid')
        return {}
    return {'third_party_source_ids': list(sources),
            'third_party_evidence_ref': _reference(review.get('third_party_evidence_ref'))}


class MetaPublicControlService:
    """Service-role control plane; caller authenticates any human-facing revoke.

    app_ids and evidence_reader must come from trusted server configuration. The
    reader resolves private operator evidence by opaque reference, never by URL or
    browser-supplied JSON. It must enforce its own custody/access controls. This
    class deliberately offers no start/complete OAuth flow or public registration.
    """
    def __init__(self, store, *, app_ids, evidence_reader, clock=storage.utcnow):
        if (not isinstance(app_ids, dict) or not app_ids
                or any(k not in PUBLIC_CREDENTIALS or not isinstance(v, str)
                       or not _ID.fullmatch(v) for k, v in app_ids.items())
                or not callable(evidence_reader) or not callable(clock)):
            raise _deny('meta_control_configuration_invalid')
        self.store, self.app_ids = store, dict(app_ids)
        self.evidence_reader, self.clock = evidence_reader, clock

    def _read(self, ref):
        _reference(ref)
        try:
            return self.evidence_reader(ref)
        except Exception:
            raise _deny('meta_operator_evidence_unavailable') from None

    def register_connection(self, *, policy, token, diagnostic_ref, app_review_ref,
                            consent_ref, selection, quota_rules, previous_authorization_id=None):
        """Insert encrypted custody and a validated immutable grant atomically.

        This records permission evidence only. A separate, human-approved canary
        must prove genuine third-party public data and the full pipeline before a
        source is activated. No source flag or readiness row is changed here.
        """
        # Snapshot mutable rights before evidence lookup/validation and custody.
        policy = deepcopy(policy)
        at, authorization_id = self.clock(), str(uuid4())
        app_id = self.app_ids.get(policy.provider_id)
        diagnostic, app_review, consent = (self._read(ref) for ref in
            (diagnostic_ref, app_review_ref, consent_ref))
        proof = import_operator_review(policy=policy, token=token, expected_app_id=app_id,
            diagnostic=diagnostic, app_review=app_review, consent=consent,
            app_review_ref=app_review_ref, at=at, authorization_id=authorization_id,
            selection=selection)
        selection = {**_selection(policy.provider_id, selection),
                     **_third_party_attestation(policy.provider_id, app_review),
                     'reviewed_policy': {
                         'policy_id': policy.id, 'version': policy.version,
                         'scope_key': policy.scope_key, 'provider_id': policy.provider_id,
                         'operation': policy.operation, 'rights': deepcopy(policy.rights),
                         'max_retention_seconds': policy.retention_seconds}}
        quota_rules = _quota_rules(policy.provider_id, proof, quota_rules, app_review.get('quota_rules'))
        vault = getattr(self.store, 'meta_vault', None)
        if vault is None:
            raise _deny('meta_credential_custody_unavailable')
        if previous_authorization_id is not None:
            uuid(previous_authorization_id)
        workspace_id = uuid(policy.scope_key[10:])
        connection_id = 'meta-public-' + authorization_id
        with self.store.transaction() as cur:
            # Match authenticated mutation order: workspace before trust/grants.
            # Renewal must not hold the trust fence while waiting for deletion.
            cur.execute('''SELECT id FROM public.pr_workspaces WHERE id=%s
                AND NOT state ? 'accountDeletion' FOR SHARE''', (workspace_id,))
            if not storage.row(cur):
                raise _deny('meta_workspace_unavailable')
            if previous_authorization_id:
                storage.trust_lock(cur, exclusive=True)
                cur.execute('''SELECT * FROM public.pr_trend_meta_authorizations
                    WHERE authorization_id=%s AND workspace_id=%s FOR UPDATE''',
                    (previous_authorization_id, workspace_id))
                previous = storage.row(cur)
                if (not previous or previous.get('revoked_at')
                        or previous.get('provider_id') != policy.provider_id
                        or previous.get('operation') != policy.operation
                        or previous.get('source_policy_version') == policy.version
                        or previous.get('review', {}).get('account_id') != proof.account_id
                        or instant(previous['review']['verified_at']) >= instant(proof.verified_at)):
                    raise _deny('meta_renewal_requires_new_policy_and_diagnostic')
            try:
                ciphertext, key_id = vault.encrypt(token)
            except Exception:
                raise _deny('meta_credential_custody_unavailable') from None
            cur.execute('''INSERT INTO public.pr_encrypted_credentials
                (workspace_id,connection_id,provider,provider_account_id,
                 access_ciphertext,key_id,scopes,access_expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
                (workspace_id, connection_id, PUBLIC_CREDENTIALS[policy.provider_id], proof.account_id,
                 ciphertext, key_id, list(proof.verified_scopes), proof.expires_at))
            cur.execute('''INSERT INTO public.pr_trend_meta_authorizations
                (authorization_id,workspace_id,provider_id,operation,source_policy_version,
                 connection_id,ciphertext_digest,review,selection,quota_rules,consent_at,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (authorization_id, workspace_id, policy.provider_id, policy.operation, policy.version,
                 connection_id, hashlib.sha256(ciphertext.encode()).hexdigest(),
                 storage.bounded_json(asdict(proof)), storage.bounded_json(selection, 32768),
                 storage.bounded_json(quota_rules), consent['granted_at'], proof.expires_at))
            if previous_authorization_id:
                self._revoke(cur, previous, at)
        return {'authorization_id': authorization_id, 'provider_id': policy.provider_id,
                'operation': policy.operation, 'expires_at': proof.expires_at,
                'verification_method': 'operator_evidence_import',
                'diagnostic_protocol_state': DIAGNOSTIC_PROTOCOL_STATE,
                'activation_state': 'awaiting_live_public_read'}

    @staticmethod
    def _revoke(cur, grant, at):
        cur.execute('''UPDATE public.pr_trend_meta_authorizations
            SET revoked_at=coalesce(revoked_at,%s)
            WHERE authorization_id=%s AND workspace_id=%s''',
            (at, grant['authorization_id'], grant['workspace_id']))
        cur.execute('''UPDATE public.pr_encrypted_credentials
            SET revoked_at=coalesce(revoked_at,%s),access_ciphertext='',
                refresh_ciphertext=NULL,scopes='{}',updated_at=clock_timestamp()
            WHERE workspace_id=%s AND connection_id=%s AND provider=%s''',
            (at, grant['workspace_id'], grant['connection_id'], PUBLIC_CREDENTIALS[grant['provider_id']]))

    def revoke_connection(self, *, workspace_id, authorization_id, cursor=None):
        """Service-only; parent route must require current owner/editor membership."""
        uuid(workspace_id)
        uuid(authorization_id)
        with self.store.transaction(cursor) as cur:
            storage.trust_lock(cur, exclusive=True)
            cur.execute('''SELECT * FROM public.pr_trend_meta_authorizations
                WHERE authorization_id=%s AND workspace_id=%s FOR UPDATE''',
                (authorization_id, workspace_id))
            grant = storage.row(cur)
            if not grant or grant.get('provider_id') not in PUBLIC_CREDENTIALS:
                raise _deny('meta_public_authorization_unavailable')
            self._revoke(cur, grant, self.clock())
        return {'authorization_id': authorization_id, 'state': 'revoked'}
