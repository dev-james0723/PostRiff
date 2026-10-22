"""PostRiff-owned OAuth transactions and encrypted credential custody (architecture §12.2).

Flow: authenticated `start` → provider consent → PostRiff public callback (redirect only,
never exchanges) → authenticated `complete` (same member, same workspace, single use, PKCE)
→ tokens encrypted at rest → channel + capability rows. Tokens are decrypted only for the
server-side connector worker; they never reach the browser, the agent, or a log.
"""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlparse
from postriff_alpha.domain import AlphaError, clean
from .audience import COMMENT_READ_PROVIDERS
from . import account_pictures
from .permissions import require
from .channels import CAPABILITIES, assisted_matrix, customer_view, set_level, unsupported_matrix, with_youtube_credential_status, youtube_credential_status

TRANSACTION_TTL = 600
PUBLISH_CAPABILITIES = ("publish", "schedule")
NON_EXPIRING_HORIZON = 86400 * 365 * 5


class CredentialVault:
    """Application-layer encryption (Fernet: AES-128-CBC + HMAC-SHA256). Key from server secrets."""
    def __init__(self, key=None):
        self.fernet, self.key_id = None, None
        if key:
            from cryptography.fernet import Fernet
            self.fernet = Fernet(key.encode() if isinstance(key, str) else key)
            self.key_id = hashlib.sha256(key.encode() if isinstance(key, str) else key).hexdigest()[:12]

    @staticmethod
    def generate_key():
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext):
        if not self.fernet:
            raise AlphaError("Connecting accounts isn't available right now.", 503)
        return self.fernet.encrypt(plaintext.encode()).decode(), self.key_id

    def decrypt(self, ciphertext, key_id):
        if not self.fernet:
            raise AlphaError("Connecting accounts isn't available right now.", 503)
        if key_id != self.key_id:
            raise AlphaError("This account needs to be reconnected.", 409)
        from cryptography.fernet import InvalidToken
        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as error:
            raise AlphaError("This account needs to be reconnected.", 409) from error


def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


class OAuthService:
    def __init__(self, repository, commands, vault, providers, public_base_url, clock=time.time, youtube_public_base_url=None):
        self.repository, self.commands, self.vault, self.clock = repository, commands, vault, clock
        self.providers = providers if providers is not None else {}
        pinterest = self.providers.get('pinterest')
        if pinterest is not None and getattr(pinterest, 'quota_required', False):
            from .pinterest_quota import PinterestQuota
            pinterest.rate_gate = PinterestQuota(repository.connection_factory, pinterest.client_id, pinterest.environment, clock, trial=getattr(pinterest, 'trial_readonly', False) or getattr(pinterest, 'private_trial', False))
            if getattr(pinterest, 'private_trial', False):
                pinterest.private_trial_create_gate = pinterest.rate_gate.reserve_trial_create
                pinterest.private_trial_ack_gate = pinterest.rate_gate.acknowledge_trial_create
                pinterest.private_trial_recover_reference = pinterest.rate_gate.recovered_trial_pin
                pinterest.private_trial_pin_gate = self._pinterest_private_pin_allowed
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.youtube_public_base_url = youtube_public_base_url or None
        self.picture_fetch = account_pictures.fetch_image  # replaced in tests; never reached without a picture URL
        self.identity_admission = None  # hosted service wires durable quota reservation outside workspace locks
        from .youtube.policy_acceptance import YouTubePolicyAcceptance
        self.youtube_policy = YouTubePolicyAcceptance(self)
        from .social_history import SocialHistoryService
        self.history = SocialHistoryService(self)
        mastodon = self.providers.get('mastodon')
        if mastodon is not None and getattr(mastodon, 'id', None) == 'mastodon':
            from .mastodon_connect import ApplicationCache
            mastodon.application_cache = ApplicationCache(self, mastodon)

    def _pinterest_private_pin_allowed(self, pin_id):
        """Only IDs durably returned by an approved intent in this exact active trial."""
        adapter = self.providers.get('pinterest')
        policy = getattr(adapter, 'trial_policy', None)
        if not getattr(adapter, 'private_trial', False) or not getattr(adapter, 'execution_enabled', False):
            return False
        try:
            policy.require(policy.workspace_id, now=self.clock())
            with self.repository.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (policy.workspace_id,))
                row = cur.fetchone()
            state = row[0] if row and isinstance(row[0], dict) else json.loads(row[0]) if row else {}
            if state.get('accountDeletion') or state.get('accountBlock'):
                return False
            data = state.get('phase2') or {}
            for job in data.get('jobs', []):
                manifest = job.get('manifest') or {}
                if (job.get('state') not in ('submitting', 'provider_accepted', 'processing', 'published', 'verifying', 'verified', 'uncertain')
                        or manifest.get('platform') != 'Pinterest' or manifest.get('workspaceId') != policy.workspace_id
                        or manifest.get('actor') != policy.actor_id or manifest.get('providerAccountId') != policy.provider_account_id
                        or (manifest.get('publishOptions') or {}).get('boardId') not in policy.board_ids):
                    continue
                try:
                    policy.require_manifest(manifest, now=self.clock())
                except AlphaError:
                    continue
                recorded = job.get('pinterestTrialPilot') == policy.pilot_id and job.get('providerReference') == pin_id
                if not recorded:
                    recover = getattr(adapter, 'private_trial_recover_reference', None)
                    if not callable(recover) or recover(policy, manifest.get('idempotencyKey')) != pin_id:
                        continue
                channel = next((c for c in data.get('channels', []) if c.get('id') == manifest.get('channelId')), None)
                if channel and not channel.get('revoked') and channel.get('providerAccountId') == policy.provider_account_id:
                    return True
        except AlphaError:
            return False
        except Exception:
            raise AlphaError('Private Trial Pin authorization storage is unavailable.', 503) from None
        return False

    def provider_catalog(self):
        """Secret-free deployment readiness; an unconfigured tile is never an adapter."""
        from .providers import ADAPTERS
        entries = []
        for pid, cls in ADAPTERS.items():
            adapter = self.providers.get(pid)
            issues = []
            diagnostic = getattr(self.providers, 'diagnostics', {}).get(pid, {})
            configuration = diagnostic.get('configurationState', 'configured' if adapter else 'not_configured')
            presence = diagnostic.get('credentialPresence', {'clientId': adapter is not None, 'clientSecret': adapter is not None})
            if adapter is None:
                prefix = f'POSTRIFF_OAUTH_{pid.upper()}_'
                missing = diagnostic.get('missingVariables', [prefix + 'CLIENT_ID', prefix + 'CLIENT_SECRET'])
                pinterest_issue = {
                    'pinterest_trial_expired': 'The approved private Pinterest Trial window has expired. Connections stay closed until a new scoped pilot or public release is explicitly approved. No credential reset is indicated.',
                    'pinterest_trial_configuration_invalid': 'The private Pinterest Trial needs valid server-side workspace, operator, account and bounded expiry settings. Connections stay closed; review the approved pilot configuration.',
                    'pinterest_trial_environment_invalid': 'The private Pinterest Trial API environment and Sandbox setting do not match. Connections stay closed; review the approved environment configuration.',
                    'pinterest_callback_origin_invalid': 'The Pinterest callback origin must be a fixed HTTPS origin without a path, query or fragment. Connections stay closed; review it against the registered callback.',
                }.get(diagnostic.get('configurationIssueCode')) if pid == 'pinterest' else None
                if diagnostic.get('configurationState') == 'sandbox_forbidden_environment':
                    issues.append('TikTok Sandbox OAuth is blocked on Production or a canonical production callback domain. Use a separate HTTPS Preview origin and sandbox credentials.')
                else:
                    issues.append(pinterest_issue or ('Server setup required: configure ' + ' and '.join(missing) + '. These are channel credentials, not app sign-in providers.' if missing else 'The OAuth credential pair contains a blank, whitespace or placeholder value. Correct it in secure server configuration.'))
            if not self.vault.fernet:
                issues.append('Server setup required: POSTRIFF_CREDENTIAL_KEY must protect connected-account tokens.')
            try:
                callback = self.callback_uri(pid)
            except AlphaError:
                callback = None
                issues.append('Set POSTRIFF_PUBLIC_BASE_URL to the fixed HTTPS app origin and register its callback with the provider.')
            if pid == 'pinterest' and diagnostic.get('configurationIssueCode') == 'pinterest_callback_origin_invalid':
                callback = None
            wave = getattr(cls, 'wave', None)
            paused = adapter is not None and (bool(diagnostic.get('operatorDisabled')) if wave else not getattr(adapter, 'execution_enabled', True))
            if paused:
                issues.append('This connector is paused by the operator.')
            feature_enabled = bool(diagnostic.get('featureFlagEnabled', not getattr(cls, 'feature_flag_required', False)))
            if getattr(cls, 'feature_flag_required', False) and not feature_enabled:
                issues.append('This connector is behind its independent server feature flag.')
            contract_verified = bool(getattr(cls, 'oauth_contract_verified', True))
            if not contract_verified:
                issues.append('Current OAuth endpoint details remain behind the provider approval portal; connection stays unavailable until they are independently verified.')
            provider_verified = bool(diagnostic.get('providerVerified'))
            if getattr(cls, 'provider_approval_required', False) and not provider_verified:
                issues.append('Provider application verification is not recorded; connection stays unavailable until the provider approves it.')
            history = pid == 'instagram' or (pid == 'linkedin' and bool(getattr(adapter, 'history_approved', False)))
            connect_ready = adapter is not None and not issues and contract_verified
            reviewed = bool(adapter and adapter.production_reviewed)
            normalized = cls.normalized_capabilities() if getattr(cls, 'wave', None) else None
            if normalized is None:
                legacy = {cap: bool(adapter and adapter.capability_scopes(cap)) for cap in ('identity', 'posts_read', 'publish', 'analytics', 'comments_read', 'reply')}
            else:
                legacy = {
                    'identity': bool(adapter and normalized['identity'] == 'supported' and adapter.capability_scopes('identity')),
                    'posts_read': bool(adapter and normalized['owned_content_read'] == 'supported' and adapter.capability_scopes('posts_read')),
                    'publish': bool(adapter and ((getattr(adapter, 'publisher', None) is None and not getattr(adapter, 'separate_publish_gate', False))
                                                 or diagnostic.get('publishingPermission'))
                                    and any(normalized[key] == 'supported' for key in ('publish_text','publish_image','publish_video'))
                                    and adapter.capability_scopes('publish')),
                    'analytics': bool(adapter and normalized['owned_analytics'] == 'supported' and adapter.capability_scopes('analytics')),
                    'comments_read': bool(adapter and normalized['comments_read'] == 'supported' and adapter.capability_scopes('comments_read')),
                    'reply': bool(adapter and normalized['comments_reply'] == 'supported' and adapter.capability_scopes('reply')),
                }
            if pid == 'pinterest':
                legacy['boards_read'] = bool(adapter and adapter.capability_scopes('boards_read'))
                if getattr(adapter, 'trial_readonly', False):
                    legacy = {key: key in ('identity', 'boards_read') for key in (*legacy, 'boards_read')}
                    # The exact workspace/operator is enforced at every authenticated operation.
                    connect_ready = bool(callback and self.vault.fernet and getattr(adapter, 'execution_enabled', False))
            if pid == 'pinterest' and getattr(adapter, 'private_trial', False):
                connect_ready = bool(callback and self.vault.fernet and getattr(adapter, 'execution_enabled', False))
            requested = list(getattr(cls, 'documented_scopes', ())) or sorted({scope for scopes in cls.SCOPES.values() for scope in scopes})
            if pid == 'pinterest' and getattr(adapter, 'trial_readonly', False):
                requested = sorted(adapter.capability_scopes('boards_read'))
            if pid == 'pinterest' and getattr(adapter, 'private_trial', False):
                requested = sorted({scope for cap in adapter.trial_policy.capabilities for scope in adapter.capability_scopes(cap)})
            if pid == 'mastodon':
                # This release authorizes Connect only. Review/config flags cannot
                # advertise management or publishing from the legacy adapter.
                legacy = {cap: cap == 'identity' and bool(adapter) for cap in legacy}
                requested = list(cls.SCOPES['identity'])
            checklist = {
                'clientIdConfigured': bool(presence.get('clientId')), 'clientSecretConfigured': bool(presence.get('clientSecret')),
                'redirectUriConfigured': callback is not None,
                'providerAppCreated': bool(diagnostic.get('providerAppCreated')), 'providerVerificationStatus': 'verified' if provider_verified else 'not_verified',
                'requestedScopes': requested, 'approvedScopes': list(diagnostic.get('approvedScopes') or []),
                'oauthLiveTest': bool(diagnostic.get('oauthLiveTest')), 'tokenRefreshLiveTest': bool(diagnostic.get('tokenRefreshLiveTest')),
                'webhookVerified': bool(diagnostic.get('webhookVerified')), 'publishingPermission': bool(diagnostic.get('publishingPermission')),
                'analyticsPermission': bool(diagnostic.get('analyticsPermission')), 'commentsPermission': bool(diagnostic.get('commentsPermission')),
                'productionEnabled': bool(diagnostic.get('productionEnabled')) and not paused,
            }
            readiness = configuration if adapter is None else 'paused' if paused else 'configuration_blocked' if not connect_ready else 'identity_connection_available' if reviewed else 'configured_awaiting_provider_review'
            entries.append({'id': pid, 'platform': cls.platform, 'configured': adapter is not None,
                            'connectReady': connect_ready, 'configurationState': configuration, 'credentialPresence': presence,
                            'readinessState': readiness, 'publicConnectionReady': connect_ready and reviewed and not (getattr(adapter, 'trial_readonly', False) or getattr(adapter, 'private_trial', False)), 'liveVerified': False,
                            'reviewStatus': 'operator_declared_reviewed' if reviewed else 'not_confirmed',
                            'reviewNote': 'Review readiness is operator-declared, not independently verified with the platform. Unreviewed apps may be limited to eligible app-role test accounts.',
                            'productionReviewed': reviewed, 'executionPaused': paused,
                            **({'trialReadonly': bool(getattr(adapter, 'trial_readonly', False)), 'privateTrial': bool(getattr(adapter, 'private_trial', False)), 'trialVisibility': 'creator_only' if getattr(adapter, 'private_trial', False) else None} if pid == 'pinterest' else {}),
                            'callbackUri': callback, 'setupIssues': issues, 'commentsReadImplemented': pid in COMMENT_READ_PROVIDERS,
                            'historyAvailableForApp': history,
                            'accountRequirement': (f"Read-only Trial for the approved operator and Pinterest account, using the {'Sandbox' if adapter.sandbox else 'official production'} API."
                                                   if pid == 'pinterest' and getattr(adapter, 'trial_readonly', False) else 'Private account-bound Trial: only individually approved Pins on the configured boards; Trial Pins are creator-only.' if pid == 'pinterest' and getattr(adapter, 'private_trial', False) else cls.account_requirement),
                            'wave': getattr(cls, 'wave', None), 'featureFlagEnabled': feature_enabled,
                            'normalizedCapabilities': normalized, 'readinessChecklist': checklist,
                            'connectKind': cls.connect_kind, 'startInput': cls.start_input, 'hasDestinations': cls.has_destinations,
                            'destinationScope': getattr(cls, 'destination_scope', 'connection'), 'destinationLabel': getattr(cls, 'destination_label', 'Channel'),
                            'capabilities': legacy})
        # Keep explicitly injected/test providers visible without changing their authority.
        for pid, adapter in self.providers.items():
            if pid not in ADAPTERS:
                entries.append({'id': pid, 'platform': adapter.platform, 'configured': True, 'productionReviewed': adapter.production_reviewed,
                                'executionPaused': not getattr(adapter, 'execution_enabled', True),
                                'capabilities': {cap: bool(adapter.capability_scopes(cap)) for cap in ('identity', 'publish', 'analytics', 'comments_read', 'reply')}})
        return entries

    @staticmethod
    def connection_readiness(channel, provider):
        """Independent permissions from the last verified grant, not a live acceptance claim."""
        connected = channel.get('connectionState') in ('read_verified', 'publish_verified')
        provider = provider or {}
        usable = connected and provider.get('configured') and provider.get('connectReady') and not provider.get('executionPaused')
        scopes = set(channel.get('scopes') or [])
        platform = channel.get('platform')
        if platform == 'YouTube':
            return {'connection': 'CONNECTED' if connected else 'NOT_CONNECTED', 'history': 'YOUTUBE_CREATOR_IDENTITY',
                    'publishing': 'YOUTUBE_CAPABILITIES_SEPARATE', 'fullyAvailable': False,
                    'evidence': 'last_verified_grant', 'liveVerified': False}
        from .providers import adapter_class_for_platform
        adapter_class = adapter_class_for_platform(platform)
        read_scope = getattr(adapter_class, 'read_scope', None)
        publish_scope = getattr(adapter_class, 'publish_scope', None)
        history = 'HISTORICAL_IMPORT_UNAVAILABLE'
        publishing = 'PUBLISHING_PERMISSION_UNAVAILABLE'
        if usable:
            if platform == 'LinkedIn' and not provider.get('historyAvailableForApp'):
                history = 'HISTORICAL_IMPORT_AWAITING_PROVIDER_APPROVAL'
            elif read_scope and read_scope in scopes:
                history = 'HISTORICAL_IMPORT_AVAILABLE'
            elif read_scope:
                history = 'HISTORICAL_IMPORT_PERMISSION_UNAVAILABLE'
            if publish_scope and publish_scope in scopes:
                if not provider.get('productionReviewed'):
                    publishing = 'PUBLISHING_AWAITING_PROVIDER_REVIEW'
                elif channel.get('capabilities', {}).get('publish', {}).get('level') == 'Direct':
                    publishing = 'PUBLISHING_AVAILABLE'
        return {'connection': 'CONNECTED' if connected else 'REAUTHORIZATION_REQUIRED' if channel.get('connectionState') in ('token_expired', 'reauthorization_required', 'scope_missing') else 'NOT_CONNECTED',
                'history': history, 'publishing': publishing,
                'fullyAvailable': history == 'HISTORICAL_IMPORT_AVAILABLE' and publishing == 'PUBLISHING_AVAILABLE',
                'evidence': 'last_verified_grant', 'liveVerified': False}

    def _provider(self, provider_id):
        adapter = self.providers.get(provider_id)
        if adapter is None:
            raise AlphaError("This platform isn't available yet.", 404)
        return adapter

    def _youtube_provider(self, lane='standard'):
        """Only configured server adapters select an issuer; a view never supplies one."""
        standard = self._provider('youtube')
        if lane == 'standard':
            return standard
        if lane != 'agentic':
            raise AlphaError('Reconnect through a supported YouTube authorization workflow.', 409, code='youtube_oauth_binding_required')
        adapter = getattr(standard, 'agentic_provider', None)
        if (adapter is None or getattr(adapter, 'authorization_lane', None) != 'agentic'
                or adapter.client_id == standard.client_id):
            raise AlphaError('The separate YouTube AI-agent OAuth client is not configured.', 409, code='youtube_oauth_binding_changed')
        return adapter

    def _provider_for_access(self, provider_id, access_token):
        if provider_id == 'pinterest':
            adapter = self._provider(provider_id)
            # Reject old App/environment custody before a server consumer receives it.
            adapter._bound(access_token, 'at')
            return adapter
        if provider_id != 'youtube':
            return self._provider(provider_id)
        try:
            binding = json.loads(access_token)
        except (ValueError, TypeError):
            binding = {}
        if not isinstance(binding, dict):
            binding = {}
        lane = binding.get('authorizationLane') if binding.get('v') == 2 else 'standard'
        adapter = self._youtube_provider(lane)
        if binding.get('v') == 2:
            if lane == 'standard' and binding.get('clientId') != adapter.client_id:
                legacy = getattr(adapter, 'legacy_provider', None)
                if (legacy is not None and getattr(legacy, 'legacy_refresh_only', False)
                        and getattr(legacy, 'authorization_lane', None) == 'standard'
                        and binding.get('clientId') == legacy.client_id):
                    if not getattr(adapter, 'execution_enabled', True):
                        raise AlphaError('This platform is paused for now. Your post history stays available.', 503)
                    adapter = legacy
            adapter._bound(access_token, 'at')
        return adapter

    def provider_for_grant(self, grant):
        """Server-only routing from protected token custody, never a projected lane."""
        provider = self._provider_for_access(grant['provider'], grant['accessToken'])
        if getattr(provider, 'legacy_refresh_only', False):
            provider.assert_read_scopes(grant.get('scopes'))
        return self.youtube_policy.guarded_provider(provider, grant) if grant['provider'] == 'youtube' else provider

    @staticmethod
    def _pinterest_binding(adapter):
        policy = getattr(adapter, 'trial_policy', None)
        binding = {'clientId': adapter.client_id, 'apiEnvironment': 'sandbox' if adapter.sandbox else 'production',
                'trialReadonly': bool(getattr(adapter, 'trial_readonly', False)),
                'trialAuthority': {key: getattr(policy, key) for key in ('workspace_id', 'actor_id', 'username', 'expires_at')}
                    if policy is not None else None}
        if getattr(adapter, 'private_trial', False):
            binding.update(privateTrial=True, privateAuthority=policy.binding())
        return binding

    def _pinterest_custody(self, cleartext, adapter):
        try:
            context = json.loads(cleartext)
        except (ValueError, TypeError):
            return None
        if (not isinstance(context, dict) or context.get('binding') != self._pinterest_binding(adapter)
                or not isinstance(context.get('pkce'), str) or not 20 <= len(context['pkce']) <= 128):
            return None
        return context

    def _assert_pinterest_context(self, provider_id, workspace_id, principal=None, *, scopes=None):
        if provider_id == 'pinterest':
            self._provider(provider_id).assert_trial_context(workspace_id, principal, scopes=scopes, now=self.clock())

    def provider_for_connection(self, workspace_id, connection_id):
        with self.repository.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL', (workspace_id, connection_id))
            row = cur.fetchone()
        if not row:
            raise AlphaError('Connection unavailable.', 404)
        self._assert_pinterest_context(row[0], workspace_id)
        return self._provider_for_access(row[0], self.vault.decrypt(row[1], row[2]))

    @staticmethod
    def _connection_id(provider_id, account_id, lane='standard'):
        identity = f'{provider_id}:{account_id}' if provider_id != 'youtube' or lane == 'standard' else f'youtube:agentic:{account_id}'
        return hashlib.sha256(identity.encode()).hexdigest()[:32]

    def _admit_identity(self, workspace_id, adapter):
        if getattr(adapter, 'id', None) != 'youtube':
            return
        if callable(self.identity_admission):
            self.identity_admission(workspace_id, adapter)
        elif getattr(adapter, 'real_transport', False):
            raise AlphaError('YouTube identity quota admission is unavailable. No provider request was sent.', 503, code='youtube_capacity_schema')

    @staticmethod
    def youtube_origin_from_environment(values):
        """Server configuration only; preview codes stay on the approved staging origin."""
        override = values.get('POSTRIFF_YOUTUBE_PUBLIC_BASE_URL')
        if override and values.get('VERCEL_ENV') == 'preview':
            approved = (values.get('POSTRIFF_STAGING_PUBLIC_BASE_URL') or '').rstrip('/')
            if not approved or override.rstrip('/') != approved:
                raise AlphaError('YouTube preview callbacks require the exact approved staging HTTPS origin.', 503)
        return override

    def callback_base_url(self, provider_id):
        base = self.youtube_public_base_url if provider_id == 'youtube' and self.youtube_public_base_url else self.public_base_url
        # The opt-in origin is stricter than legacy normalization; malformed configuration
        # fails only the YouTube callback and cannot supply a request-controlled destination.
        if provider_id == 'youtube' and self.youtube_public_base_url:
            if not isinstance(base, str) or any(character.isspace() or ord(character) < 32 for character in base) or '\\' in base:
                raise AlphaError('A fixed public HTTPS origin is required for YouTube OAuth.', 503)
            try:
                dedicated = urlparse(base)
                dedicated.port  # Reject malformed ports before constructing an OAuth redirect.
            except ValueError as error:
                raise AlphaError('A fixed public HTTPS origin is required for YouTube OAuth.', 503) from error
            if (dedicated.path not in ('', '/') or dedicated.username is not None or dedicated.password is not None
                    or '?' in base or '#' in base):
                raise AlphaError('The YouTube OAuth origin must not contain a path, query, fragment or user information.', 503)
            base = base.rstrip('/')
        origin = urlparse(base)
        if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            raise AlphaError("A fixed public HTTPS app origin, without a path or query, is required for OAuth.", 503)
        return base

    def callback_uri(self, provider_id):
        base = self.callback_base_url(provider_id)
        # A provider whose console still lists only an earlier origin keeps that registered callback; the public
        # callback lands on the canonical app origin. An explicit dedicated YouTube origin is registered for
        # its separate clients and intentionally supersedes a legacy provider pin for both authorization lanes.
        pinned = getattr(self.providers.get(provider_id), 'callback_origin', None) if hasattr(self.providers, 'get') else None
        if provider_id == 'youtube' and self.youtube_public_base_url:
            pinned = None
        return f"{pinned or base}/api/oauth/{provider_id}/callback"

    # --- start ----------------------------------------------------------------------
    def start(self, workspace_id, token, provider_id, capability, inputs=None):
        inputs = inputs or {}
        if not isinstance(inputs, dict):
            raise AlphaError('Expected structured connection inputs.', 400)
        lane = inputs.get('authorizationLane', 'standard') if provider_id == 'youtube' else 'standard'
        adapter = self._youtube_provider(lane) if provider_id == 'youtube' else self._provider(provider_id)
        if provider_id == 'mastodon' and capability != 'identity':
            raise AlphaError('Mastodon currently supports account connection only. Publishing and management are not enabled.', 409, code='mastodon_connect_only')
        if provider_id == 'youtube' and (capability == 'autopilot' and lane != 'agentic'
                or lane == 'agentic' and inputs.get('agenticConsent') is not True):
            raise AlphaError('Explicitly approve the separate AI-agent connection before requesting its permissions.', 403, code='youtube_agentic_consent_required')
        if not getattr(adapter, "execution_enabled", True):
            if not getattr(type(adapter), 'wave', None):
                raise AlphaError("This platform is paused for now. Your post history stays available.", 503)
            diagnostic = getattr(self.providers, 'diagnostics', {}).get(provider_id, {})
            if bool(diagnostic.get('operatorDisabled')):
                raise AlphaError("This platform is paused for now. Your post history stays available.", 503)
            if getattr(type(adapter), 'provider_approval_required', False) and not diagnostic.get('providerVerified'):
                raise AlphaError("This connection is waiting for provider application approval.", 409)
            raise AlphaError("This connection is not enabled yet.", 409)
        youtube_features = tuple(adapter.SCOPES) if provider_id == 'youtube' else ('boards_read',) if provider_id == 'pinterest' else ()
        if capability not in (*CAPABILITIES, 'posts_read', *youtube_features) or capability in ("media_types", "webhooks"):
            raise AlphaError("Choose the capability you want to enable.", 400)
        scopes = adapter.capability_scopes(capability)
        if not scopes:
            raise AlphaError(f"{adapter.platform} does not offer '{capability}' through its official API for this app.", 409)
        redirect = self.callback_uri(provider_id)
        # Class attributes, so a mocked adapter keeps the plain redirect path.
        if getattr(type(adapter), "connect_kind", "oauth") != "oauth" or callable(getattr(type(adapter), "begin", None)):
            return self._start_prepared(workspace_id, token, provider_id, adapter, capability, list(scopes), redirect, inputs)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit, throttle
            require(_membership(row), "manage_connections")
            self._assert_pinterest_context(provider_id, workspace_id, principal, scopes=scopes)
            policy_acceptance = self.youtube_policy.require_user(cur, workspace_id, principal, token, adapter,
                capability=capability, scopes=scopes) if provider_id == 'youtube' else None
            if provider_id == 'youtube' and lane == 'agentic':
                require(_membership(row), 'owner')
                self.repository.assert_fresh(token, principal)
            if provider_id == 'youtube' and capability in ('monetary_analytics', 'memberships'):
                require(_membership(row), 'owner')
                self.repository.assert_fresh(token, principal)
                connection = (inputs or {}).get('connectionId')
                if (inputs or {}).get('enableSensitive') is not True or not connection:
                    raise AlphaError('Intentionally enable this sensitive creator capability for the existing channel first.', 403)
                column = 'monetary_authorized' if capability == 'monetary_analytics' else 'memberships_authorized'
                cur.execute('SELECT s.' + column + " FROM public.pr_youtube_settings s JOIN public.pr_encrypted_credentials c ON c.workspace_id=s.workspace_id AND c.connection_id=s.connection_id WHERE s.workspace_id=%s AND s.connection_id=%s AND c.provider='youtube' AND c.revoked_at IS NULL", (workspace_id, connection))
                authorization = cur.fetchone()
                if not authorization or authorization[0] is not True:
                    raise AlphaError('Sensitive creator access is not authorized for this workspace.', 403)
            throttle(cur, f"oauth-start:{workspace_id}", 20, 600)
            state = secrets.token_urlsafe(32)
            verifier, challenge = pkce_pair()
            custody = json.dumps({'pkce': verifier, 'connectionId': (inputs or {}).get('connectionId'),
                                  'clientId': adapter.client_id, 'authorizationLane': getattr(adapter, 'authorization_lane', 'standard'),
                                  'policyAcceptance': policy_acceptance}) if provider_id == 'youtube' else verifier
            if provider_id == 'pinterest':
                custody = json.dumps({'pkce': verifier, 'binding': self._pinterest_binding(adapter)})
            ciphertext, key_id = self.vault.encrypt(custody)
            stored_capability = capability if capability in CAPABILITIES else 'identity'
            cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>%s)) RETURNING id::text", (workspace_id, principal, provider_id, stored_capability, redirect, list(scopes), hashlib.sha256(state.encode()).hexdigest(), ciphertext, key_id, TRANSACTION_TTL))
            transaction_id = cur.fetchone()[0]
            audit(cur, workspace_id, principal, "oauth.started", transaction_id, {"provider": provider_id, "capability": capability, **({'authorizationLane': lane} if provider_id == 'youtube' else {})})
            return {"transactionId": transaction_id, "provider": provider_id, "platform": adapter.platform, "capability": capability, "scopes": list(scopes), "permissionExplanation": adapter.explain(capability), "authorizeUrl": adapter.authorize_url(redirect, state, challenge, scopes), "expiresAt": self.clock() + TRANSACTION_TTL, **({'authorizationLane': lane} if provider_id == 'youtube' else {})}

    def _start_prepared(self, workspace_id, token, provider_id, adapter, capability, scopes, redirect, inputs):
        """Adapters that call out before redirecting (Bluesky PAR, Mastodon app registration) or that connect with a
        posted code (Telegram). Membership is checked before any outbound request and again when recording."""
        from .hosted import _membership, audit, throttle
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "manage_connections")
            throttle(cur, f"oauth-start:{workspace_id}", 20, 600)
            reconnect_id = inputs.get('connectionId') if provider_id == 'mastodon' else None
            if reconnect_id is not None:
                if not isinstance(reconnect_id, str) or not 1 <= len(reconnect_id) <= 128:
                    raise AlphaError('Choose a Mastodon connection to reconnect.', 400)
                cur.execute("SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon'", (workspace_id, reconnect_id))
                if not cur.fetchone():
                    raise AlphaError('Connection unavailable.', 404)
        verifier, challenge = pkce_pair()
        extra, authorize_url = {}, None
        if adapter.connect_kind == "bot_code":
            state = adapter.new_code()
            context = {"kind": adapter.connect_kind}
            extra = {**adapter.connect_instructions(), "code": state}
        elif adapter.connect_kind == "device_code":
            state = secrets.token_urlsafe(32)
            begun = adapter.begin_device(state, scopes)
            context, authorize_url = begun["context"], begun["authorizeUrl"]
            extra = {"code": state, "userCode": begun.get("userCode"), "instructions": begun.get("instructions", [])}
        else:
            state = secrets.token_urlsafe(32)
            spec = adapter.start_input or {}
            value = (inputs or {}).get(spec.get("name")) if isinstance(inputs, dict) else None
            if spec and (not isinstance(value, str) or not 1 <= len(value.strip()) <= 253):
                raise AlphaError(f"Enter your {spec.get('label', 'account')} first.", 400)
            begun = adapter.begin(redirect, state, verifier, challenge, scopes, value.strip() if isinstance(value, str) else None)
            context, authorize_url = begun["context"], begun["authorizeUrl"]
            scopes = begun.get('scopes', scopes)
            if provider_id == 'mastodon' and reconnect_id is not None:
                context['connectionId'] = reconnect_id
        ciphertext, key_id = self.vault.encrypt(json.dumps({"verifier": verifier, **context}))
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "manage_connections")
            cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,capability,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs=>%s)) RETURNING id::text", (workspace_id, principal, provider_id, 'identity' if capability == 'posts_read' else capability, redirect, scopes, hashlib.sha256(state.encode()).hexdigest(), ciphertext, key_id, TRANSACTION_TTL))
            transaction_id = cur.fetchone()[0]
            audit(cur, workspace_id, principal, "oauth.started", transaction_id, {"provider": provider_id, "capability": capability})
        return {"transactionId": transaction_id, "provider": provider_id, "platform": adapter.platform, "capability": capability, "scopes": scopes,
                "permissionExplanation": adapter.explain(capability), "authorizeUrl": authorize_url, "connectKind": adapter.connect_kind,
                "expiresAt": self.clock() + TRANSACTION_TTL, **extra}

    # --- public callback (redirect only) -------------------------------------------
    @staticmethod
    def callback_redirect(web_base_url, provider_id, query):
        """The public callback never exchanges codes; it hands state/code back to the signed-in app."""
        allowed = {k: clean(v, 512) for k, v in query.items() if k in ("state", "code", "error", "error_description", "iss")}
        allowed["provider"] = provider_id
        return f"{web_base_url.rstrip('/')}/channels/connect?{urlencode(allowed)}"

    # --- complete (authenticated exchange) ----------------------------------------
    def complete(self, workspace_id, token, provider_id, state, code, error=None, iss=None):
        if provider_id == 'pinterest':
            # Claim in a separate committed transaction. A failed or ambiguous code
            # exchange must not make the same callback usable again after rollback.
            if not isinstance(state, str) or not 20 <= len(state) <= 128:
                raise AlphaError('Connection request unavailable.', 404)
            from .hosted import _membership, audit
            adapter = self._provider(provider_id)
            if not getattr(adapter, 'execution_enabled', True):
                raise AlphaError('Pinterest is paused. Start again when enabled.', 503)
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(_membership(row), 'manage_connections')
                self._assert_pinterest_context(provider_id, workspace_id, principal)
                cur.execute("SELECT id::text,member_id::text,provider,capability,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE state_hash=%s AND workspace_id=%s FOR UPDATE", (hashlib.sha256(state.encode()).hexdigest(), workspace_id))
                txn = cur.fetchone()
                if not txn or txn[1] != principal or txn[2] != provider_id or txn[9]:
                    raise AlphaError('Connection request unavailable.', 404)
                if txn[8] <= self.clock():
                    raise AlphaError('This connection request expired. Start again.', 409)
                self._assert_pinterest_context(provider_id, workspace_id, principal, scopes=txn[5])
                binding_changed = self._pinterest_custody(self.vault.decrypt(txn[6], txn[7]), adapter) is None
                if binding_changed:
                    cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='mismatch' WHERE id::text=%s", (txn[0],))
                    audit(cur, workspace_id, principal, 'oauth.rejected', txn[0], {'reason': 'configuration_changed'})
                else:
                    cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='exchange_started' WHERE id::text=%s", (txn[0],))
                    audit(cur, workspace_id, principal, 'oauth.exchange_claimed', txn[0], {'provider': provider_id})
            if binding_changed:
                raise AlphaError('Pinterest connection settings changed. Start a new connection request.', 409, code='pinterest_oauth_binding_changed')
            return self._complete(workspace_id, token, provider_id, state, code, error, iss, claimed=txn[0])
        if provider_id == 'mastodon':
            if not isinstance(state, str) or not 20 <= len(state) <= 128:
                raise AlphaError('Connection request unavailable.', 404)
            from .hosted import _membership, audit
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(_membership(row), 'manage_connections')
                cur.execute("SELECT id::text,member_id::text,provider,capability,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE state_hash=%s AND workspace_id=%s FOR UPDATE", (hashlib.sha256(state.encode()).hexdigest(), workspace_id))
                txn = cur.fetchone()
                if not txn or txn[1] != principal or txn[2] != provider_id or txn[9]:
                    raise AlphaError('Connection request unavailable.', 404)
                if txn[8] <= self.clock():
                    raise AlphaError('This connection request expired. Start again.', 409)
                cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='exchange_started' WHERE id::text=%s", (txn[0],))
                audit(cur, workspace_id, principal, 'oauth.exchange_claimed', txn[0], {'provider': provider_id})
            return self._complete(workspace_id, token, provider_id, state, code, error, iss, claimed=txn[0])
        if provider_id != 'youtube':
            return self._complete(workspace_id, token, provider_id, state, code, error, iss)
        if not isinstance(state, str) or not 20 <= len(state) <= 128:
            raise AlphaError('Connection request unavailable.', 404)
        from .hosted import _membership, audit
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), 'manage_connections')
            cur.execute("SELECT id::text,member_id::text,provider,extract(epoch from expires_at),consumed_at IS NOT NULL,verifier_ciphertext,key_id,scopes FROM public.pr_oauth_transactions WHERE workspace_id=%s AND state_hash=%s FOR UPDATE", (workspace_id, hashlib.sha256(state.encode()).hexdigest()))
            txn = cur.fetchone()
            if not txn or txn[1] != principal or txn[2] != provider_id or txn[4]:
                raise AlphaError('Connection request unavailable.', 404)
            if txn[3] <= self.clock():
                raise AlphaError('This connection request expired. Start again.', 409)
            context = json.loads(self.vault.decrypt(txn[5], txn[6]))
            adapter = self._youtube_provider(context.get('authorizationLane', 'standard'))
            if context.get('clientId') != adapter.client_id:
                raise AlphaError('The YouTube OAuth configuration changed. Start again.', 409, code='youtube_oauth_binding_changed')
            if code and not error:
                self.youtube_policy.require_pending(cur, workspace_id, principal, token, adapter, txn[7], context)
            if getattr(adapter, 'authorization_lane', 'standard') == 'agentic':
                require(_membership(row), 'owner')
                self.repository.assert_fresh(token, principal)
            cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='exchange_started' WHERE id::text=%s", (txn[0],))
            audit(cur, workspace_id, principal, 'oauth.exchange_claimed', txn[0], {'provider': provider_id})
        # One-time state stays consumed even if the exchange or channel selection fails.
        if code and not error:
            self._admit_identity(workspace_id, adapter)
        return self._complete(workspace_id, token, provider_id, state, code, error, iss, claimed=txn[0])

    def _complete(self, workspace_id, token, provider_id, state, code, error=None, iss=None, *, claimed=None):
        adapter = self._provider(provider_id)
        bot_code = getattr(type(adapter), "connect_kind", "oauth") == "bot_code"
        device_code = getattr(type(adapter), "connect_kind", "oauth") == "device_code"
        if provider_id != 'youtube' and not getattr(adapter, "execution_enabled", True):
            if not getattr(type(adapter), 'wave', None):
                raise AlphaError("This platform is paused for now. Connect again when it's back.", 503)
            diagnostic = getattr(self.providers, 'diagnostics', {}).get(provider_id, {})
            if bool(diagnostic.get('operatorDisabled')):
                raise AlphaError("This platform is paused for now. Connect again when it's back.", 503)
            if getattr(type(adapter), 'provider_approval_required', False) and not diagnostic.get('providerVerified'):
                raise AlphaError("This connection is waiting for provider application approval.", 409)
            raise AlphaError("This connection is not enabled yet.", 409)
        if not isinstance(state, str) or not 20 <= len(state) <= 128:
            raise AlphaError("Connection request unavailable.", 404)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            self._assert_pinterest_context(provider_id, workspace_id, principal)
            if provider_id == 'pinterest' and claimed:
                cur.execute("SELECT outcome FROM public.pr_oauth_transactions WHERE id::text=%s AND workspace_id=%s AND provider='pinterest' FOR UPDATE", (claimed, workspace_id))
                claim = cur.fetchone()
                if not claim or claim[0] != 'exchange_started':
                    raise AlphaError('Pinterest connection was canceled. Start a new connection request.', 409)
            cur.execute("SELECT id::text,member_id::text,provider,capability,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE state_hash=%s AND workspace_id=%s FOR UPDATE", (state_hash, workspace_id))
            txn = cur.fetchone()
            if not txn:
                raise AlphaError("Connection request unavailable.", 404)
            transaction_id, member_id, provider, capability, redirect, scopes, verifier_ct, key_id, expires_at, consumed = txn
            self._assert_pinterest_context(provider_id, workspace_id, principal, scopes=scopes)
            if (consumed and claimed != transaction_id) or provider != provider_id or member_id != principal:
                cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=coalesce(consumed_at,now()),outcome=coalesce(outcome,'mismatch') WHERE id::text=%s", (transaction_id,))
                audit(cur, workspace_id, principal, "oauth.rejected", transaction_id, {"reason": "mismatch_or_replay"})
                raise AlphaError("Connection request unavailable.", 404)
            if expires_at <= self.clock():
                cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='expired' WHERE id::text=%s", (transaction_id,))
                raise AlphaError("This connection request expired. Start again.", 409)
            if bot_code and not error:
                # The code is claimed by Rafii's bot seeing it in a channel (telegram_webhook), not by a redirect.
                try:
                    context = json.loads(self.vault.decrypt(verifier_ct, key_id))
                except (TypeError, ValueError) as exc:
                    raise AlphaError("Connection request unavailable.", 404) from exc
                if not isinstance(context.get("chat"), dict):
                    return {"connected": False, "reason": "waiting", "pending": True}
            elif device_code and not error:
                try:
                    context = json.loads(self.vault.decrypt(verifier_ct, key_id))
                except (TypeError, ValueError) as exc:
                    raise AlphaError("Connection request unavailable.", 404) from exc
                if not isinstance(context, dict) or context.get("kind") != "device_code":
                    raise AlphaError("Connection request unavailable.", 404)
                result = adapter.poll_device(context)
                if not isinstance(result, dict):
                    raise AlphaError("The provider did not complete this authorization step.", 502)
                if result.get("pending") is True:
                    return {"connected": False, "reason": result.get("reason", "waiting"), "pending": True}
                grant = result.get("grant")
                if not isinstance(grant, dict):
                    raise AlphaError("The provider did not complete this authorization step.", 502)
            elif error or not code:
                cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='denied' WHERE id::text=%s", (transaction_id,))
                audit(cur, workspace_id, principal, "oauth.denied", transaction_id, {"provider": provider_id})
                return {"connected": False, "reason": "denied"}
            cur.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(),outcome='exchanged' WHERE id::text=%s", (transaction_id,))
            verifier = self.vault.decrypt(verifier_ct, key_id)
            if provider_id == 'pinterest':
                context = self._pinterest_custody(verifier, adapter)
                if context is None:
                    raise AlphaError('Pinterest connection settings changed. Start a new connection request.', 409, code='pinterest_oauth_binding_changed')
                verifier = context['pkce']
            youtube_context = {}
            mastodon_context = {}
            if provider_id == 'mastodon':
                try:
                    mastodon_context = json.loads(verifier)
                except (TypeError, ValueError) as error:
                    raise AlphaError('Connection request unavailable.', 404) from error
                if not isinstance(mastodon_context, dict):
                    raise AlphaError('Connection request unavailable.', 404)
            if provider_id == 'youtube' and verifier.startswith('{'):
                youtube_context = json.loads(verifier)
                verifier = youtube_context['pkce']
                adapter = self._youtube_provider(youtube_context.get('authorizationLane', 'standard'))
                if ('clientId' in youtube_context and youtube_context['clientId'] != adapter.client_id
                        or youtube_context.get('authorizationLane', 'standard') != getattr(adapter, 'authorization_lane', 'standard')):
                    raise AlphaError('The YouTube OAuth configuration changed. Start a new connection request.', 409, code='youtube_oauth_binding_changed')
                if getattr(adapter, 'authorization_lane', 'standard') == 'agentic':
                    # Claim and quota admission commit separately. Recheck live
                    # authority under the second workspace lock before exchange.
                    require(_membership(row), 'owner')
                    self.repository.assert_fresh(token, principal)
                if not getattr(adapter, 'execution_enabled', True):
                    raise AlphaError('This YouTube authorization workflow is paused. Start again when enabled.', 503)
            policy_acceptance = self.youtube_policy.require_pending(cur, workspace_id, principal, token, adapter,
                scopes, youtube_context) if provider_id == 'youtube' else None
            if bot_code:
                grant = adapter.grant_from_context(context)
            elif device_code:
                pass
            elif getattr(type(adapter), "requires_issuer", False) is True:
                grant = adapter.exchange(code, verifier, redirect, iss=iss)
            else:
                grant = adapter.exchange(code, verifier, redirect)
            if provider_id == 'youtube':
                # Incremental Google consent can return older, broader permissions.
                # Only the legacy nonpublic READ grant may proceed without policy.
                returned_scopes = grant.get('scopes')
                if not returned_scopes:
                    returned_scopes = adapter.inspect_scopes(grant['accessToken'])
                if not isinstance(returned_scopes, list) or not returned_scopes:
                    raise AlphaError('YouTube permissions could not be verified.', 503, code='youtube_verification_unavailable')
                policy_acceptance = self.youtube_policy.require_pending(cur, workspace_id, principal, token,
                    adapter, returned_scopes, youtube_context)
            identity = adapter.identity(grant["accessToken"])
            if provider_id == 'pinterest':
                bound = json.loads(grant['accessToken'])
                bound['accountId'] = identity['providerAccountId']
                grant['accessToken'] = json.dumps(bound)
            # Requested scopes are not proof of granted scopes. Empty/unknown fails closed.
            if provider_id == 'mastodon' and identity.get('restriction'):
                raise AlphaError('This Mastodon account is inactive or moved. Connect the active account separately; approved posts are not transferred.', 409, code='mastodon_account_restricted')
            reported = grant.get('scopes')
            if (reported is None or (provider_id == 'youtube' and not reported)) and hasattr(adapter, 'inspect_scopes'):
                reported = adapter.inspect_scopes(grant['accessToken'], identity['providerAccountId'])
            if reported is None and hasattr(adapter, 'verify_read_access'):
                # This proves basic read access only; it never supplies requested write scopes.
                reported = adapter.verify_read_access(grant['accessToken'], identity['providerAccountId'])
            granted = sorted(set(reported)) if isinstance(reported, list) and all(isinstance(s, str) for s in reported) else []
            missing = sorted(set(scopes) - set(granted))
            if provider_id == 'youtube':
                from .youtube.model import has_scopes
                missing = sorted(scope for scope in scopes if not has_scopes(granted, (scope,)))
            if provider_id == 'mastodon':
                from .mastodon_protocol import has_scopes
                missing = sorted(scope for scope in scopes if not has_scopes(granted, (scope,)))
            connection_id = self._connection_id(provider_id, identity['providerAccountId'], getattr(adapter, 'authorization_lane', 'standard'))
            if mastodon_context.get('connectionId') and mastodon_context['connectionId'] != connection_id:
                raise AlphaError('You selected a different Mastodon account. Connect it separately; the existing account was not replaced.', 409, code='mastodon_account_changed')
            if youtube_context.get('connectionId') and youtube_context['connectionId'] != connection_id:
                raise AlphaError('You selected a different YouTube channel. Connect it separately; the existing channel was not replaced.', 409, code='youtube_channel_changed')
            from .billing import require_plan_capacity
            require_plan_capacity(cur, workspace_id, "connected_accounts", connection_id)
            access_ct, key_id = self.vault.encrypt(grant["accessToken"])
            refresh_ct = self.vault.encrypt(grant["refreshToken"])[0] if grant.get("refreshToken") else None
            if provider_id == 'youtube' and refresh_ct is None:
                cur.execute("SELECT access_ciphertext,refresh_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
                previous = cur.fetchone()
                if previous and previous[1]:
                    reusable = adapter.reusable_refresh(self.vault.decrypt(previous[0], previous[2]), self.vault.decrypt(previous[1], previous[2]))
                    if reusable:
                        refresh_ct = self.vault.encrypt(reusable)[0]
            expires = self.clock() + float(grant.get("expiresIn") or 0) if grant.get("expiresIn") else None
            # Keep Gmail/Calendar and other consent paths independent of 098.
            consent_generation_sql = ',authorization_generation=gen_random_uuid()' if provider_id == 'youtube' else ''
            cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,refresh_ciphertext,key_id,scopes,access_expires_at,refresh_supported) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s) ON CONFLICT(workspace_id,connection_id) DO UPDATE SET access_ciphertext=excluded.access_ciphertext,refresh_ciphertext=excluded.refresh_ciphertext,key_id=excluded.key_id,scopes=excluded.scopes,access_expires_at=excluded.access_expires_at,refresh_supported=excluded.refresh_supported,revoked_at=NULL" + consent_generation_sql + ",rotated_at=now(),updated_at=now()", (workspace_id, connection_id, provider_id, identity["providerAccountId"], access_ct, refresh_ct, key_id, granted, expires, bool(refresh_ct)))
            if provider_id == 'youtube':
                # This is a genuine identity observation from this new consent.
                # Restore an erased canonical ID only after its exact hashed
                # connection was recomputed above; token refresh never stamps it.
                cur.execute("UPDATE public.pr_encrypted_credentials SET provider_account_id=%s,youtube_identity_ingested_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL RETURNING authorization_generation::text", (identity['providerAccountId'], self.clock(), workspace_id, connection_id))
                consent_generation = cur.fetchone()[0]
                self.youtube_policy.bind(cur, workspace_id, connection_id, policy_acceptance)
            now = self.clock()
            matrix = self._capabilities(adapter, capability, granted, missing, now, grant["accessToken"])
            for name, value in matrix.items():
                cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level=excluded.level,evidence=excluded.evidence,capability_version=excluded.capability_version,verified_at=excluded.verified_at,updated_at=now()", (workspace_id, connection_id, name, value["level"], value["evidence"], value["capabilityVersion"], value["verifiedAt"]))
            audit(cur, workspace_id, principal, "channel.connected", connection_id, {"provider": provider_id, "capability": capability, "missingScopes": missing, "publishLevel": matrix["publish"]["level"]})
            from . import product_events
            # Product taxonomy (PRD §8.6): one event per completed connect flow (the OAuth transaction is the version).
            product_events.record(cur, workspace_id, principal, "channel.connected", connection_id, transaction_id, {"provider": provider_id})
        # A grant that never expires (bot-held access, Mastodon) keeps a far review date instead of a false 30-day expiry.
        horizon = NON_EXPIRING_HORIZON if getattr(adapter, "non_expiring", False) else 86400 * 30
        channel = {"id": connection_id, "platform": adapter.platform, "account": identity.get("handle") or identity["providerAccountId"], "accountType": identity.get("accountType", "member"), "scopes": granted, "verifiedAt": now, "expiresAt": expires or now + horizon, "capabilityVersion": adapter.capability_version, "providerAccountId": identity["providerAccountId"]}
        if provider_id == 'youtube':
            channel['refreshBindingRequired'] = False
            channel['authorizationLane'] = getattr(adapter, 'authorization_lane', 'standard')
            channel['youtubeIdentityIngestedAt'] = now
        snapshot = self.repository.get(workspace_id, token)
        # A disconnect/new consent can commit after token custody but before
        # this workspace save. The same-transaction fence rolls back a stale
        # profile restoration rather than trusting a newly fetched revision.
        def consent_fence(cur, _state, _actor):
            if provider_id == 'youtube':
                self._assert_youtube_generation(cur, workspace_id, connection_id, consent_generation)
            elif provider_id == 'pinterest':
                cur.execute("SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='pinterest' AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
                fresh = cur.fetchone()
                if not fresh or fresh[0] != access_ct:
                    raise AlphaError('Pinterest authorization changed while connecting. Reload and reconnect.', 409)
            if provider_id == 'mastodon':
                self.assert_mastodon_dispatch(cur, workspace_id, connection_id, mastodon_grant)
        mastodon_grant = {'providerAccountId': identity['providerAccountId'], 'scopes': granted,
            '_mastodonCredentialBinding': hashlib.sha256((key_id + '\0' + access_ct).encode()).hexdigest()} if provider_id == 'mastodon' else None
        saved = self.repository.command(workspace_id, token, snapshot["revision"], lambda state, actor: self.commands.upsert_verified_channel(state, actor, channel, capability_verified=not missing and matrix["publish"]["level"] == "Direct"), requirement="manage_connections", **({'after': consent_fence} if provider_id in ('youtube', 'pinterest', 'mastodon') else {}))
        self._keep_picture(workspace_id, token, connection_id, identity, **({'youtube_generation': consent_generation} if provider_id == 'youtube' else {'pinterest_ciphertext': access_ct} if provider_id == 'pinterest' else {'mastodon_grant': mastodon_grant} if provider_id == 'mastodon' else {}))
        return {"connected": True, "connectionId": connection_id, "account": channel["account"], "providerAccountId": identity["providerAccountId"], "confirmAccount": True, "missingScopes": missing, "capabilities": matrix, "revision": saved["revision"]}

    def _keep_picture(self, workspace_id, token, connection_id, identity, *, youtube_generation=None, pinterest_ciphertext=None, mastodon_grant=None):
        """Download outside any transaction, then store: the account's picture for previews (account_pictures.py)."""
        try:
            outcome = account_pictures.picture_from_identity(identity, self.picture_fetch)
        except Exception:  # noqa: BLE001 - runs after the connection is saved; a picture fault must not report it as failed
            return
        if outcome[0] == "unavailable":
            return  # keep whatever picture was stored before
        try:
            with self.repository.transaction(token, workspace_id) as (cur, _, _):
                if youtube_generation is not None:
                    self._assert_youtube_generation(cur, workspace_id, connection_id, youtube_generation)
                if pinterest_ciphertext is not None:
                    cur.execute("SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='pinterest' AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
                    credential = cur.fetchone()
                    if not credential or credential[0] != pinterest_ciphertext:
                        return
                if mastodon_grant is not None:
                    self.assert_mastodon_dispatch(cur, workspace_id, connection_id, mastodon_grant)
                account_pictures.guarded(cur, account_pictures.store, workspace_id, connection_id, outcome)
        except AlphaError:
            pass  # membership ended in between; nothing to decorate

    def picture(self, workspace_id, token, connection_id):
        """The connected account's profile picture as (jpeg, digest); any member of the workspace may see it."""
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            found = account_pictures.guarded(cur, account_pictures.read, workspace_id, connection_id)
        if not found:
            raise AlphaError("This account has no picture.", 404)
        return found

    def _shared_elsewhere(self, cur, workspace_id, connection_id, provider_id):
        """True when revoking this connection would also cut off another unrevoked connection, in any workspace,
        that relies on the same shared remote grant (Rafii's bot in one Discord server or Telegram channel)."""
        adapter = self.providers.get(provider_id)
        if provider_id == 'youtube':
            # Google revocation is project/account-wide, including other OAuth clients.
            # Channel IDs cannot prove whether Brand channels share a Google account.
            # Conservatively defer remote revocation while ANY other Google grant is
            # active; never expose its identity or workspace to this caller.
            cur.execute("SELECT 1 FROM public.pr_encrypted_credentials WHERE provider IN ('youtube','google_business_profile') AND revoked_at IS NULL AND NOT (workspace_id=%s AND connection_id=%s) LIMIT 1", (workspace_id, connection_id))
            if cur.fetchone():
                return True
            cur.execute("SELECT to_regclass('public.pr_connector_credentials')")
            if cur.fetchone()[0]:
                cur.execute("SELECT 1 FROM public.pr_connector_credentials WHERE provider='gmail' AND revoked_at IS NULL LIMIT 1")
                if cur.fetchone():
                    return True
            return False
        if adapter is None or not getattr(type(adapter), "shared_remote", False):
            return False
        cur.execute("SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
        own = cur.fetchone()
        if not own:
            return False
        cur.execute("SELECT 1 FROM public.pr_encrypted_credentials WHERE provider=%s AND provider_account_id=%s AND revoked_at IS NULL AND NOT (workspace_id=%s AND connection_id=%s) LIMIT 1",
                    (provider_id, own[0], workspace_id, connection_id))
        return cur.fetchone() is not None

    # --- destinations (a Discord channel) ------------------------------------------------
    def _member_grant(self, workspace_id, token, connection_id, requirement):
        """(adapter, fresh grant) for a member with `requirement`. The grant comes from token_for_worker, so a
        short-lived token (Pinterest, TikTok, YouTube) is renewed before Rafii asks the provider anything."""
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership
            require(_membership(row), requirement)
            cur.execute("SELECT provider FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, connection_id))
            stored = cur.fetchone()
            if stored:
                self._assert_pinterest_context(stored[0], workspace_id, principal)
        if not stored:
            raise AlphaError("Connection unavailable.", 404)
        grant = self.token_for_worker(workspace_id, connection_id)
        return self.provider_for_grant(grant), grant

    def destinations(self, workspace_id, token, connection_id, board_id=None):
        """Where this account can post: a Discord channel or Facebook Page (chosen once), or a Pinterest board (per Pin)."""
        if board_id is not None and (not isinstance(board_id, str) or not re.fullmatch(r'\d{1,30}', board_id)):
            raise AlphaError('Choose a valid Pinterest board.', 400)
        adapter, grant = self._member_grant(workspace_id, token, connection_id, "approve")
        if board_id is not None:
            if adapter.id != 'pinterest':
                raise AlphaError('Board sections are available only for Pinterest.', 400)
            return {'connectionId': connection_id, 'scope': 'post', 'boardId': board_id,
                    'destinations': adapter.sections(grant['accessToken'], board_id)}
        if not getattr(adapter, "has_destinations", False):
            raise AlphaError("This account has nothing to choose.", 409)
        return {"connectionId": connection_id, "scope": getattr(type(adapter), "destination_scope", "connection"),
                "destinations": adapter.destinations(grant["accessToken"])}

    @contextmanager
    def pinterest_dispatch(self, manifest, access_token, fence, *, trial_pin=None):
        """Serialize the last authorized POST with disconnect and lease takeover.

        Discovery runs outside this lock. A valid create ID is persisted before
        releasing it so a disconnect cannot erase an already-known outcome.
        """
        from .contracts import digest
        adapter = self._provider('pinterest')
        if not getattr(adapter, 'execution_enabled', True):
            raise AlphaError('Pinterest is paused. Nothing was posted.', 503)
        if getattr(adapter, 'trial_readonly', False):
            raise AlphaError('This Pinterest Trial cannot publish or schedule Pins.', 403, code='pinterest_trial_readonly')
        if not isinstance(fence, dict) or not fence.get('leaseId') or not fence.get('leaseOwner'):
            raise AlphaError('Pinterest publication needs an active approved worker lease.', 409)
        workspace_id, connection_id = manifest['workspaceId'], manifest['channelId']
        private = getattr(adapter, 'private_trial', False)
        if private:
            adapter.trial_policy.require_manifest(manifest, now=self.clock())
        with self.repository.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
            row = cur.fetchone()
            state = row[0] if row and isinstance(row[0], dict) else json.loads(row[0]) if row else None
            data = (state or {}).get('phase2') or {}
            channel = next((c for c in data.get('channels', []) if c.get('id') == connection_id), None)
            job = next((j for j in data.get('jobs', []) if j.get('manifest', {}).get('idempotencyKey') == manifest.get('idempotencyKey')), None)
            if (not state or state.get('accountDeletion') or state.get('accountBlock') or not channel or channel.get('revoked')
                    or not job or job.get('state') != 'submitting' or job.get('cancelRequested')
                    or job.get('leaseId') != fence['leaseId'] or job.get('leaseOwner') != fence['leaseOwner']
                    or job.get('leaseUntil', 0) <= self.clock() or job.get('approvalDigest') != digest(manifest)
                    or job.get('manifest') != manifest):
                raise AlphaError('Pinterest approval, account or worker lease changed. Nothing was posted.', 409)
            from .permissions import Membership
            from .billing import require_publishing
            require_publishing(cur, workspace_id, self.clock())
            cur.execute("SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job.get('approvedBy')))
            member = cur.fetchone()
            if (not member or not Membership.from_row(member[0], can_publish=member[1]).allows('approve')
                    or job.get('approvedBy') != manifest.get('actor') or manifest.get('expiresAt', 0) <= self.clock()
                    or not self.commands.engine.current(state, manifest)
                    or self.commands.engine.channel_state(channel) != 'Ready for posting'):
                raise AlphaError('Pinterest publishing authority changed. Review and approve again.', 409)
            cur.execute("SELECT access_ciphertext,key_id,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='pinterest' AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            credential = cur.fetchone()
            if not credential or credential[2] != manifest.get('providerAccountId') or self.vault.decrypt(credential[0], credential[1]) != access_token:
                raise AlphaError('Pinterest authorization changed. Nothing was posted.', 409)
            proof = {}
            if private:
                with adapter.private_trial_dispatch(manifest, trial_pin):
                    yield proof
            else:
                yield proof
            if proof.get('pinId'):
                job['providerReference'] = proof['pinId']
                if private:
                    job['pinterestTrialPilot'] = adapter.trial_policy.pilot_id
                job.setdefault('events', []).append({'at': self.clock(), 'state': job['state'],
                    'execution': manifest.get('execution', 'synthetic'), 'message': 'Pinterest returned a Pin ID; exact provider read-back is pending.'})
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace_id))

    def choose_destination(self, workspace_id, token, connection_id, destination_id):
        # Reject malformed identifiers before decrypting a grant or contacting a provider. Existing hosted
        # destinations are numeric; Google Business Profile uses its documented resource-name shape.
        if not isinstance(destination_id, str) or not (re.fullmatch(r"\d{5,30}", destination_id) or re.fullmatch(r"accounts/[0-9]+/locations/[0-9]+", destination_id)):
            raise AlphaError("Choose where Rafii posts.", 400)
        adapter, grant = self._member_grant(workspace_id, token, connection_id, "manage_connections")
        validator = getattr(adapter, 'valid_destination_id', None)
        valid = validator(destination_id) if callable(validator) else isinstance(destination_id, str) and re.fullmatch(r"\d{5,30}", destination_id)
        if not valid:
            raise AlphaError("Choose where Rafii posts.", 400)
        if not getattr(adapter, "has_destinations", False) or getattr(type(adapter), "destination_scope", "connection") != "connection":
            raise AlphaError("This account's destination is chosen for each post.", 409)
        updated = adapter.with_destination(grant["accessToken"], destination_id)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            cur.execute("SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            stored = cur.fetchone()
            # Compare-and-swap on the grant the choice was based on: a reconnect or a second choice meanwhile wins.
            if not stored or self.vault.decrypt(stored[1], stored[2]) != grant["accessToken"]:
                raise AlphaError("This account changed meanwhile. Reload and choose again.", 409)
            ciphertext, key_id = self.vault.encrypt(updated)
            cur.execute("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND access_ciphertext=%s AND revoked_at IS NULL", (ciphertext, key_id, workspace_id, connection_id, stored[1]))
            if cur.rowcount != 1:
                raise AlphaError("This account changed meanwhile. Reload and choose again.", 409)
            if adapter.id == "google_business_profile":
                state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                channel = next((item for item in state["phase2"]["channels"] if item["id"] == connection_id), None)
                location_name = json.loads(updated).get("locationName")
                if channel is None or not isinstance(location_name, str) or not location_name:
                    raise AlphaError("This Business Profile location needs a fresh connection.", 409)
                channel["account"] = location_name
                now = self.clock()
                matrix = self._capabilities(adapter, "publish", grant["scopes"],
                                            sorted(set(adapter.capability_scopes("publish")) - set(grant["scopes"])), now, updated)
                channel["capabilityVerified"] = matrix["publish"]["level"] == "Direct"
                for name in ("publish", "schedule"):
                    value = matrix[name]
                    cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level=excluded.level,evidence=excluded.evidence,capability_version=excluded.capability_version,verified_at=excluded.verified_at,updated_at=now()",
                                (workspace_id, connection_id, name, value["level"], value["evidence"], value["capabilityVersion"], value["verifiedAt"]))
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s",
                            (json.dumps(state), workspace_id))
            audit(cur, workspace_id, principal, "channel.destination_chosen", connection_id, {"provider": stored[0]})
        return {"connectionId": connection_id, "destinationId": destination_id}

    def creator_info(self, workspace_id, token, connection_id):
        """TikTok's creator info for the composer, fresh each time it renders (Content Sharing Guidelines)."""
        adapter, grant = self._member_grant(workspace_id, token, connection_id, "approve")
        query = getattr(adapter, "creator_info", None)
        if query is None:
            raise AlphaError("This account has no creator settings to read.", 409)
        info = query(grant["accessToken"])
        if not info.get("ok"):
            raise AlphaError("TikTok says this account can't post right now" + (f": {info['message']}" if isinstance(info.get("message"), str) and info["message"] else "."), 409)
        return {key: info[key] for key in ("nickname", "username", "avatarUrl", "privacyLevelOptions", "commentDisabled", "duetDisabled", "stitchDisabled", "maxVideoPostDurationSec")}

    # --- Telegram: Rafii's bot sees a connect code in a channel -------------------------
    def telegram_webhook(self, secret, raw):
        """Public route, authenticated by the secret token Telegram echoes. Always answers ok to Telegram."""
        adapter = self.providers.get("telegram")
        if adapter is None:
            raise AlphaError("This hosted route is unavailable.", 404)
        if not isinstance(secret, str) or not hmac.compare_digest(secret.encode(), adapter.webhook_secret.encode()):
            raise AlphaError("Webhook authorization failed.", 401)
        try:
            update = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {"ok": True}
        seen = adapter.observe(update)
        if not seen or not getattr(adapter, "execution_enabled", True):
            return {"ok": True}
        code, chat, message_id = seen
        claimed = False
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT id::text,verifier_ciphertext,key_id,extract(epoch from expires_at)::float8,consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE state_hash=%s AND provider='telegram' FOR UPDATE", (hashlib.sha256(code.encode()).hexdigest(),))
                found = cur.fetchone()
                if found and not found[4] and found[3] > self.clock():
                    context = json.loads(self.vault.decrypt(found[1], found[2]))
                    # The first channel that shows the code claims it; a copy posted elsewhere later changes nothing.
                    if not isinstance(context.get("chat"), dict):
                        context["chat"] = chat
                        ciphertext, key_id = self.vault.encrypt(json.dumps(context))
                        cur.execute("UPDATE public.pr_oauth_transactions SET verifier_ciphertext=%s,key_id=%s WHERE id::text=%s", (ciphertext, key_id, found[0]))
                        claimed = True
        if claimed:
            adapter.delete_message(chat["id"], message_id)
        return {"ok": True}

    def xiaohongshu_webhook(self, headers, raw):
        """Ingest Xiaohongshu authorization events without exposing tokens or trusting parsed-body signatures."""
        adapter = self.providers.get("xiaohongshu")
        webhook_secret = getattr(adapter, "webhook_secret", None) if adapter is not None else None
        if not webhook_secret:
            raise AlphaError("Webhook unavailable.", 404)
        timestamp = headers.get("timestamp") if isinstance(headers, dict) else None
        signature = headers.get("signature") if isinstance(headers, dict) else None
        event_id = headers.get("eventId") if isinstance(headers, dict) else None
        event_type = headers.get("eventType") if isinstance(headers, dict) else None
        if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{13}", timestamp):
            return {"code": 1002, "msg": "timestamp_expired"}
        now_ms = int(self.clock() * 1000)
        if abs(now_ms - int(timestamp)) > 300_000:
            return {"code": 1002, "msg": "timestamp_expired"}
        from .wave4c_connectors import verify_xiaohongshu_webhook
        if not verify_xiaohongshu_webhook(webhook_secret, timestamp, raw, signature, now_ms=now_ms):
            return {"code": 1001, "msg": "invalid_signature"}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, UnicodeDecodeError):
            return {"code": 1003, "msg": "invalid_payload"}
        if (not isinstance(payload, dict) or not isinstance(event_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id)
                or payload.get("event_id") != event_id or payload.get("event_type") != event_type
                or payload.get("event_time") != int(timestamp)):
            return {"code": 1003, "msg": "invalid_payload"}
        if payload.get("app_id") != adapter.client_id:
            return {"code": 1005, "msg": "unknown_app"}
        if event_type not in ("authorization_revoked", "device_authorization_confirmed"):
            return {"code": 1004, "msg": "unknown_event_type"}
        open_id = payload.get("open_id")
        if event_type == "authorization_revoked" and (not isinstance(open_id, str) or not 1 <= len(open_id) <= 200):
            return {"code": 1003, "msg": "invalid_payload"}
        if event_type == "device_authorization_confirmed" and not re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}", str(payload.get("user_code") or "")):
            return {"code": 1003, "msg": "invalid_payload"}
        try:
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    digest = hashlib.sha256(raw).hexdigest()
                    cur.execute(
                        "INSERT INTO public.pr_social_provider_events(provider,event_id,event_type,payload_digest) "
                        "VALUES('xiaohongshu',%s,%s,%s) ON CONFLICT(provider,event_id) DO NOTHING RETURNING event_id",
                        (event_id, event_type, digest),
                    )
                    if not cur.fetchone():
                        return {"code": 0, "msg": "success"}
                    affected = []
                    if event_type == "authorization_revoked":
                        cur.execute(
                            "SELECT workspace_id::text,connection_id FROM public.pr_encrypted_credentials "
                            "WHERE provider='xiaohongshu' AND provider_account_id=%s AND revoked_at IS NULL FOR UPDATE",
                            (open_id,),
                        )
                        affected = cur.fetchall()
                        for workspace_id, connection_id in affected:
                            cur.execute(
                                "UPDATE public.pr_encrypted_credentials SET access_ciphertext='',refresh_ciphertext=NULL,"
                                "scopes=ARRAY[]::text[],access_expires_at=now(),revoked_at=now(),updated_at=now() "
                                "WHERE workspace_id=%s AND connection_id=%s",
                                (workspace_id, connection_id),
                            )
                            cur.execute(
                                "UPDATE public.pr_channel_capabilities SET level='Unsupported',"
                                "evidence='Xiaohongshu reported that this authorization was revoked.',updated_at=now() "
                                "WHERE workspace_id=%s AND connection_id=%s",
                                (workspace_id, connection_id),
                            )
                            cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
                            row = cur.fetchone()
                            state = json.loads(row[0]) if row and isinstance(row[0], str) else row[0] if row else None
                            if isinstance(state, dict):
                                channel = next((item for item in state.get("phase2", {}).get("channels", [])
                                                if item.get("id") == connection_id), None)
                                if channel is not None:
                                    channel.update({"revoked": True, "identityVerified": False,
                                                    "capabilityVerified": False, "expiresAt": self.clock()})
                                    self.commands.engine.invalidate(state)
                                    cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s",
                                                (json.dumps(state), workspace_id))
                            from .hosted import audit
                            audit(cur, workspace_id, None, "channel.revoked_by_provider", connection_id,
                                  {"provider": "xiaohongshu", "eventId": event_id})
                            from . import product_events
                            # Product taxonomy: a disconnection nobody in the workspace chose (no user; the provider event is the version).
                            product_events.record(cur, workspace_id, None, "channel.disconnected", connection_id,
                                                  hashlib.sha256(str(event_id).encode()).hexdigest()[:16], {"provider": "xiaohongshu", "cause": "provider"})
                    cur.execute(
                        "UPDATE public.pr_social_provider_events SET processed_at=now(),outcome=%s WHERE provider='xiaohongshu' AND event_id=%s",
                        ("revoked" if affected else "acknowledged", event_id),
                    )
            return {"code": 0, "msg": "success"}
        except Exception:  # provider should retry transient database failures; never echo database details
            return {"code": 3001, "msg": "internal_error"}

    # --- Bluesky: public client documents -------------------------------------------------
    def bluesky_document(self, name):
        adapter = self.providers.get("bluesky")
        if adapter is None or name not in ("client-metadata.json", "jwks.json"):
            raise AlphaError("This hosted route is unavailable.", 404)
        return adapter.client_metadata() if name == "client-metadata.json" else adapter.jwks()

    @staticmethod
    def _capabilities(adapter, requested, granted, missing, now, access_token=None):
        """Build the whole matrix from the live grant, not only the last requested slice.

        Incremental Meta OAuth can return a token containing permissions granted in earlier
        rounds. Reconnecting Analytics or Comments must therefore preserve and re-verify the
        other capabilities instead of resetting them to Unsupported. Provider-wide App Review
        and an account-scoped Standard Access grant remain distinct: the latter can prove Direct
        execution only for the exact connected account.
        """
        if getattr(adapter, 'id', None) == 'mastodon':
            from .mastodon_protocol import has_scopes
            matrix = unsupported_matrix()
            if has_scopes(granted, ('read:accounts',)):
                set_level(matrix, 'identity', 'Direct', 'Mastodon account connected. Publishing and management are not enabled.', now, adapter.capability_version)
            return matrix
        if getattr(adapter, 'id', None) == 'youtube':
            from .youtube.model import READ, UPLOAD, MANAGE, ANALYTICS, has_scopes, project_public_gate
            matrix = unsupported_matrix()
            if has_scopes(granted, (READ,)):
                set_level(matrix, 'identity', 'Direct', 'Channel identity resolved; creator capabilities and real acceptance remain separate.', now, adapter.capability_version)
            if getattr(adapter, 'creator_enabled', False):
                for name, required in {'publish': (UPLOAD,), 'analytics': (ANALYTICS,), 'comments_read': (MANAGE,), 'reply': (MANAGE,), 'moderate': (MANAGE,)}.items():
                    if has_scopes(granted, required):
                        set_level(matrix, name, 'Direct', 'Private creator execution authorized; real acceptance is unproven. Open YouTube for independent capability gates.', now, adapter.capability_version)
                if has_scopes(granted, (MANAGE,)) and project_public_gate(adapter):
                    set_level(matrix, 'schedule', 'Direct', 'YouTube-native scheduling; public-upload gates verified, real acceptance remains separate.', now, adapter.capability_version)
            return matrix
        matrix = assisted_matrix() if adapter.assisted_fallback else unsupported_matrix()
        granted_set = set(granted or [])
        account_scoped = bool(getattr(adapter, "account_scoped_direct", False))
        direct_allowed = bool(adapter.production_reviewed or account_scoped)
        set_level(matrix, "identity", "Direct", "Account confirmed.", now, adapter.capability_version)

        publish_scopes = set(adapter.capability_scopes("publish"))
        publish_granted = bool(publish_scopes) and publish_scopes <= granted_set
        publisher_ready = not (
            (getattr(adapter, "publisher", None) is not None or getattr(adapter, "separate_publish_gate", False)) and
            (not getattr(adapter, "publish_live_tested", False) or
             not getattr(adapter, "publishing_permission", False) or
             not getattr(adapter, "write_qualified", lambda _token: True)(access_token))
        )
        if publish_granted and direct_allowed and publisher_ready:
            evidence = "Granted by the provider for this account." if account_scoped and not adapter.production_reviewed else "You approve each post; Rafii publishes it."
            set_level(matrix, "publish", "Direct", evidence, now, adapter.capability_version)
            schedule_scopes = set(adapter.capability_scopes("schedule"))
            if schedule_scopes and schedule_scopes <= granted_set:
                if getattr(adapter, "native_schedule", False):
                    set_level(matrix, "schedule", "Direct", f"Scheduled on {adapter.platform}.", now, adapter.capability_version)
                elif getattr(adapter, "server_schedule", False):
                    set_level(matrix, "schedule", "Direct", "Rafii publishes the approved post at the scheduled time.", now, adapter.capability_version)
                elif adapter.assisted_fallback:
                    set_level(matrix, "schedule", "Assisted", "Rafii prepares the scheduled post; you finish the last step.", now, adapter.capability_version)
        elif requested in PUBLISH_CAPABILITIES:
            if missing:
                set_level(matrix, "publish", "Assisted" if adapter.assisted_fallback else "Unsupported", "Some permissions weren't granted, so you post the last step yourself.", now, adapter.capability_version)
            else:
                set_level(matrix, "publish", "Assisted" if adapter.assisted_fallback else "Unsupported", f"{adapter.platform} hasn't approved Rafii's publishing yet, so you post the last step yourself.", now, adapter.capability_version)

        for name in ("analytics", "comments_read", "reply", "moderate"):
            required = set(adapter.capability_scopes(name))
            if not required or not required <= granted_set:
                continue
            if direct_allowed:
                evidence = "Granted by the provider for this account." if account_scoped and not adapter.production_reviewed else "Granted."
                set_level(matrix, name, "Direct", evidence, now, adapter.capability_version)
            elif name == requested:
                set_level(matrix, name, "Unsupported", f"Waiting for {adapter.platform} to approve Rafii.", now, adapter.capability_version)
        if getattr(adapter, 'id', None) == 'pinterest':
            from .pinterest_analytics import describe
            matrix = describe(matrix, granted, analytics_enabled=getattr(adapter, 'analytics_enabled', False))
            if getattr(adapter, 'private_trial', False):
                for name in ('publish', 'schedule', 'analytics'):
                    if matrix.get(name, {}).get('level') == 'Direct':
                        matrix[name]['evidence'] = 'Private account-bound Trial only; every Pin needs exact approval and Trial Pins are creator-only.'
        return matrix

    # --- read / refresh / disconnect -------------------------------------------------
    def channels(self, workspace_id, token):
        snapshot = self.repository.get(workspace_id, token)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("SELECT connection_id,capability,level,evidence,capability_version,extract(epoch from verified_at) FROM public.pr_channel_capabilities WHERE workspace_id=%s", (workspace_id,))
            rows = cur.fetchall()
            pictures = account_pictures.guarded(cur, account_pictures.digests, workspace_id) or {}
            credentials = youtube_credential_status(cur, [workspace_id])
        matrices = {}
        for connection_id, capability, level, evidence, version, verified in rows:
            matrices.setdefault(connection_id, unsupported_matrix())[capability] = {"level": level, "evidence": evidence, "capabilityVersion": version, "verifiedAt": float(verified) if verified else None}
        now = self.clock()
        catalog = self.provider_catalog()
        by_platform = {provider['platform']: provider for provider in catalog}
        views = [{**customer_view(with_youtube_credential_status(c, credentials.get((workspace_id, c['id']))), matrices.get(c['id'], assisted_matrix()), now), 'pictureDigest': pictures.get(c['id'])} for c in snapshot['state'].get('phase2', {}).get('channels', [])]
        for view in views:
            view['socialReadiness'] = self.connection_readiness(view, by_platform.get(view['platform']))
        for view in views:
            if view.get('platform') == 'Pinterest':
                from .pinterest_analytics import describe
                view['capabilities'] = describe(view.get('capabilities', {}), view.get('scopes', []),
                    analytics_enabled=getattr(self.providers.get('pinterest'), 'analytics_enabled', False))
        return {'channels': views, 'providers': catalog}

    def token_for_worker(self, workspace_id, connection_id, *, youtube_policy_required=False, pinterest_force_refresh=False):
        try:
            return self._token_for_worker(workspace_id, connection_id, youtube_policy_required=youtube_policy_required,
                                          **({'pinterest_force_refresh': True} if pinterest_force_refresh else {}))
        except AlphaError as error:
            if error.code == 'mastodon_authorization_revoked':
                self.mark_mastodon_revoked(workspace_id, connection_id,
                    expected_ciphertext=getattr(error, 'mastodon_observed_ciphertext', None))
            elif error.code == 'youtube_revoked_oauth':
                self.mark_youtube_revoked(workspace_id, connection_id,
                                         expected_ciphertext=getattr(error, 'credential_revocation_ciphertext', None),
                                         expected_generation=getattr(error, 'credential_revocation_generation', None))
            elif error.code in ('youtube_oauth_binding_required', 'youtube_oauth_binding_changed'):
                expected = getattr(error, 'credential_binding_ciphertext', None)
                expected_generation = getattr(error, 'credential_binding_generation', None)
                if expected is not None and expected_generation is not None:
                    # The failed read/refresh transaction has rolled back. Persist only
                    # a reconnect marker, conditional on the exact credential observed;
                    # a concurrent new consent wins and no ciphertext is discarded.
                    with self.repository.connection_factory() as db, db.cursor() as cur:
                        cur.execute("UPDATE public.pr_encrypted_credentials SET refresh_supported=false,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL AND access_ciphertext=%s AND authorization_generation::text=%s", (workspace_id, connection_id, expected, expected_generation))
            raise

    def refresh_pinterest_authorization(self, workspace_id, token, connection_id):
        """Explicit member action. Rotate under existing custody lock; never return credentials."""
        from .hosted import _membership, audit
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), 'manage_connections')
            self.repository.assert_fresh(token, principal)
            cur.execute("SELECT provider,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, connection_id))
            stored = cur.fetchone()
            if not stored or stored[0] != 'pinterest':
                raise AlphaError('This Pinterest connection is unavailable.', 404)
            self._assert_pinterest_context('pinterest', workspace_id, principal, scopes=stored[1])
        grant = self.token_for_worker(workspace_id, connection_id, pinterest_force_refresh=True)
        checked = self.verify(workspace_id, token, connection_id)
        if not checked.get('identityVerified'):
            raise AlphaError('Pinterest authorization changed. Reconnect the expected account.', 409, code='pinterest_reconnect_required')
        with self.repository.transaction(token, workspace_id) as (cur, _, principal):
            audit(cur, workspace_id, principal, 'oauth.authorization_refreshed', connection_id, {'provider': 'pinterest'})
        return {'connectionId': connection_id, 'authorizationRefreshed': True,
                'identityVerified': True, 'expiresAt': grant['expiresAt']}

    def mark_mastodon_revoked(self, workspace_id, connection_id, *, expected_ciphertext):
        """Only a definitive 401 on the exact observed credential removes authority."""
        if not expected_ciphertext:
            return False
        from .hosted import audit
        with self.repository.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
            locked = cur.fetchone()
            if not locked:
                return False
            cur.execute("SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon' AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            current = cur.fetchone()
            if not current or current[0] != expected_ciphertext:
                return False  # Fresh reconnect wins over the old response.
            cur.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,scopes='{}',updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
            cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Mastodon access was rejected. Reconnect this account.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
            state = json.loads(locked[0]) if isinstance(locked[0], str) else locked[0]
            for channel in state.get('phase2', {}).get('channels', []):
                if channel.get('id') == connection_id and channel.get('platform') == 'Mastodon':
                    channel.update(revoked=True, identityVerified=False, capabilityVerified=False, scopes=[],
                        mastodonHealth={'state': 'reauthorization_required', 'reason': 'token_rejected', 'checkedAt': self.clock()})
            self.commands.engine.invalidate(state)
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace_id))
            audit(cur, workspace_id, None, 'mastodon.authorization_revoked', connection_id, {'reason': 'token_rejected'})
        return True

    def mark_youtube_revoked(self, workspace_id, connection_id, *, expected_access_token=None, expected_ciphertext=None, expected_generation=None):
        from .hosted import audit
        from .youtube.journal import purge_authorized_data
        from .youtube.agent import revoke_connection_authority
        # Refresh or an authenticated API response may detect revocation. Purge in a separate commit.
        with self.repository.connection_factory() as db, db.cursor() as cur:
            if (expected_access_token is None and expected_ciphertext is None) or not expected_generation:
                return False  # No observed credential can authorize purging a possibly newer grant.
            # Match consent/disconnect lock order: workspace first, credential second.
            # The exact observed credential still fences a concurrent new grant.
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
            workspace = cur.fetchone()
            if not workspace:
                return False
            state = json.loads(workspace[0]) if isinstance(workspace[0], str) else workspace[0]
            cur.execute("SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            observed = cur.fetchone()
            if not observed or (expected_ciphertext is not None and observed[0] != expected_ciphertext):
                return False
            cur.execute("SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR NO KEY UPDATE", (workspace_id, connection_id))
            generation = cur.fetchone()
            if not generation or generation[0] != expected_generation:
                return False
            if expected_access_token is not None:
                try:
                    current_access = self.vault.decrypt(observed[0], observed[1])
                except AlphaError:
                    return False
                if not hmac.compare_digest(current_access.encode(), expected_access_token.encode()):
                    return False
            cur.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,scopes='{}',updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL", (workspace_id, connection_id))
            changed = cur.rowcount
            cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='YouTube authorization revoked. Reconnect.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
            if changed:
                state_changed = revoke_connection_authority(state, connection_id, None, self.clock(),
                                                            reason='oauth_revoked')
                for channel in state.get('phase2', {}).get('channels', []):
                    if channel.get('id') == connection_id and channel.get('platform') == 'YouTube':
                        state_changed = state_changed or channel.get('revoked') is not True
                        channel['revoked'] = True
                if state_changed:
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                                (json.dumps(state), workspace_id))
                # Remove provider copies after the authority write; the earlier
                # workspace snapshot must never restore erased provider output.
                purge_authorized_data(cur, workspace_id, connection_id)
                audit(cur, workspace_id, None, 'youtube.authorization_revoked', connection_id)
            return bool(changed)

    @contextmanager
    def _credential_errors(self, provider_id, access_ciphertext, authorization_generation=None):
        try:
            yield
        except AlphaError as error:
            if provider_id == 'youtube' and error.code == 'youtube_revoked_oauth':
                error.credential_revocation_ciphertext = access_ciphertext
                error.credential_revocation_generation = authorization_generation
            raise

    def _token_for_worker(self, workspace_id, connection_id, *, youtube_policy_required=False, pinterest_force_refresh=False):
        """Server-only token custody. Instagram renews while valid, never after expiry."""
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                # float8: extract() is numeric (a Decimal) since PostgreSQL 14, and Decimal - float raises TypeError.
                cur.execute("SELECT provider,access_ciphertext,refresh_ciphertext,key_id,extract(epoch from access_expires_at)::float8,refresh_supported,revoked_at IS NOT NULL,scopes,provider_account_id,extract(epoch from coalesce(rotated_at,updated_at,created_at))::float8 FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s FOR UPDATE", (workspace_id, connection_id))
                row = cur.fetchone()
                if not row or row[6]:
                    raise AlphaError("Connection unavailable.", 404)
                self._assert_pinterest_context(row[0], workspace_id, scopes=row[7])
                authorization_generation = None
                if row[0] == 'youtube':
                    # Check schema and capture consent before OAuth transport,
                    # under the same credential lock used for token custody.
                    from .youtube.journal import UploadJournal
                    UploadJournal._schema(cur)
                    cur.execute("SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL", (workspace_id, connection_id))
                    generation = cur.fetchone()
                    if not generation or not generation[0]:
                        raise AlphaError('YouTube authorization is no longer available.', 409, code='youtube_revoked_oauth')
                    authorization_generation = generation[0]
                with self._credential_errors(row[0], row[1], authorization_generation):
                    provider, access_ct, refresh_ct, key_id, expires, refresh_supported, _, scopes, account_id, issued_at = row
                    adapter = self._provider_for_access(provider, self.vault.decrypt(access_ct, key_id))
                    if getattr(adapter, 'legacy_refresh_only', False):
                        adapter.assert_read_scopes(scopes)
                        # Moving old custody must not weaken the active app's policy gate.
                        youtube_policy_required = youtube_policy_required or self.youtube_policy.required(
                            self._provider('youtube'), scopes=scopes)
                    if provider == 'youtube':
                        self.youtube_policy.assert_connection(workspace_id, connection_id, adapter, scopes=scopes,
                            generation=authorization_generation, force=youtube_policy_required, cur=cur)
                    if not getattr(adapter, "execution_enabled", True):
                        raise AlphaError("This platform is paused for now. Your post history stays available.", 503)
                    binding_scopes = None
                    refresh_binding_required = False
                    binder = getattr(type(adapter), 'bind_credentials', None) if provider == 'youtube' else None
                    if binder:
                        previous_access = self.vault.decrypt(access_ct, key_id)
                        previous_refresh = self.vault.decrypt(refresh_ct, key_id) if refresh_ct else None
                        try:
                            bound_access, bound_refresh, binding_scopes = adapter.bind_credentials(previous_access, previous_refresh)
                        except AlphaError as error:
                            if error.code in ('youtube_oauth_binding_required', 'youtube_oauth_binding_changed'):
                                error.credential_binding_ciphertext = access_ct
                                error.credential_binding_generation = authorization_generation
                            raise
                        refresh_binding_required = adapter.refresh_binding_required(bound_access)
                        if refresh_binding_required:
                            refresh_supported = False
                        if bound_access != previous_access or bound_refresh != previous_refresh:
                            access_ct, key_id = self.vault.encrypt(bound_access)
                            refresh_ct = self.vault.encrypt(bound_refresh)[0] if bound_refresh else None
                            cur.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,refresh_ciphertext=%s,key_id=%s,refresh_supported=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s', (access_ct, refresh_ct, key_id, bool(refresh_supported), workspace_id, connection_id))
                    now = self.clock()
                    expired = bool(expires and expires <= now)
                    if provider == 'mastodon' and expired:
                        raise AlphaError('Mastodon access expired. Reconnect this account to authorize Rafii again.', 409, code='reauthorization_required')
                    if provider == 'instagram' and expired:
                        raise AlphaError('Instagram access expired; re-authorization required. Expired long-lived tokens cannot be refreshed.', 409, code='reauthorization_required')
                    # Refresh requires a still-valid token at least 24 hours old.
                    # Unknown age never grants permission to renew; reconnect remains available.
                    renew_instagram = (provider == 'instagram' and expires and 0 < expires - now <= 7 * 86400
                                       and issued_at is not None and now - issued_at >= 86400
                                       and refresh_supported and refresh_ct)
                    # X and Bluesky tokens are short-lived: renew within the adapter's margin, not after a failed call.
                    margin = getattr(type(adapter), "refresh_margin", 0) or 0
                    renew_soon = bool(margin and expires and 0 < expires - now <= margin and refresh_supported and refresh_ct)
                    if expired or renew_instagram or renew_soon or (pinterest_force_refresh and provider == 'pinterest'):
                        if refresh_binding_required:
                            error = AlphaError('Reconnect this YouTube channel once to enable securely bound background access.', 409, code='youtube_oauth_binding_required')
                            error.credential_binding_ciphertext = row[1]
                            error.credential_binding_generation = authorization_generation
                            raise error
                        if not (refresh_supported and refresh_ct):
                            raise AlphaError("Access expired and cannot be refreshed; re-authorization required.", 409)
                        grant = adapter.refresh(self.vault.decrypt(refresh_ct, key_id))
                        binding_scopes = None
                        preserve = getattr(adapter, "preserve_destination", None)
                        if preserve is not None:
                            grant["accessToken"] = preserve(self.vault.decrypt(access_ct, key_id), grant["accessToken"])
                        access_ct, key_id = self.vault.encrypt(grant["accessToken"])
                        new_refresh = self.vault.encrypt(grant["refreshToken"])[0] if grant.get("refreshToken") else self.vault.encrypt(self.vault.decrypt(refresh_ct, row[3]))[0]
                        expires = self.clock() + float(grant.get("expiresIn") or 3600)
                        cur.execute("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,refresh_ciphertext=%s,key_id=%s,access_expires_at=to_timestamp(%s),rotated_at=now(),updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (access_ct, new_refresh, key_id, expires, workspace_id, connection_id))
                    access_token = self.vault.decrypt(access_ct, key_id)
                    inspector = getattr(adapter, "inspect_scopes", None)
                    if inspector:
                        try:
                            reported = binding_scopes if binding_scopes is not None else inspector(access_token, account_id)
                        except AlphaError as error:
                            if provider == 'mastodon' and error.code == 'mastodon_authorization_revoked':
                                error.mastodon_observed_ciphertext = access_ct
                            if provider != 'youtube' or error.code == 'youtube_revoked_oauth':
                                raise
                            raise AlphaError('YouTube permissions could not be verified. Try again when provider verification is available.', 503, code='youtube_verification_unavailable') from error
                        authoritative = isinstance(reported, list) and all(isinstance(s, str) for s in reported)
                        if provider in ('youtube', 'mastodon') and not authoritative:
                            # An unavailable tokeninfo observation is not an empty grant.
                            # Block this request without erasing the last verified scope set.
                            raise AlphaError('Provider permissions could not be verified. Try again when verification is available.', 503,
                                             code=provider + '_verification_unavailable')
                        scopes = reported if authoritative else []
                        if getattr(adapter, 'legacy_refresh_only', False):
                            adapter.assert_read_scopes(scopes)
                        if provider == 'youtube':
                            self.youtube_policy.assert_connection(workspace_id, connection_id, adapter, scopes=scopes,
                                generation=authorization_generation, force=youtube_policy_required, cur=cur)
                        cur.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (scopes, workspace_id, connection_id))
                    return {"provider": provider, "accessToken": access_token, "scopes": list(scopes), "expiresAt": expires, 'providerAccountId': account_id,
                            **({'_mastodonCredentialBinding': hashlib.sha256((key_id + '\0' + access_ct).encode()).hexdigest()} if provider == 'mastodon' else {}),
                            **({'refreshBindingRequired': refresh_binding_required, 'authorizationLane': getattr(adapter, 'authorization_lane', 'standard'),
                                'authorizationGeneration': authorization_generation,
                                '_youtubePolicyContext': {'workspace': workspace_id, 'connection': connection_id,
                                    'force': youtube_policy_required}} if provider == 'youtube' else {})}

    def assert_mastodon_dispatch(self, cur, workspace_id, connection_id, grant, required=()):
        """Fence the exact server-only grant before saving its connected channel state."""
        cur.execute("SELECT provider_account_id,access_ciphertext,key_id,scopes,extract(epoch from access_expires_at)::float8 FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon' AND revoked_at IS NULL FOR SHARE", (workspace_id, connection_id))
        row = cur.fetchone()
        binding = grant.get('_mastodonCredentialBinding') if isinstance(grant, dict) else None
        if (not row or not isinstance(binding, str)
                or not hmac.compare_digest(binding, hashlib.sha256((row[2] + '\0' + row[1]).encode()).hexdigest())
                or row[0] != grant.get('providerAccountId')
                or set(row[3]) != set(grant.get('scopes', []))
                or not set(required).issubset(row[3])
                or (row[4] is not None and row[4] <= self.clock())):
            raise AlphaError('Mastodon authorization changed; no further write is permitted.', 409, code='mastodon_dispatch_authorization_changed')

    def _assert_youtube_generation(self, cur, workspace_id, connection_id, generation):
        if not isinstance(generation, str) or not generation:
            raise AlphaError('YouTube authorization changed during verification.', 409, code='youtube_connection_changed')
        cur.execute("SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR NO KEY UPDATE", (workspace_id, connection_id))
        current = cur.fetchone()
        if not current or current[0] != generation:
            raise AlphaError('YouTube authorization changed during verification.', 409, code='youtube_connection_changed')

    def _stamp_youtube_identity(self, cur, workspace_id, connection_id, grant, identity, now):
        """Fence a genuine identity result against replacement consent, even with the same token."""
        generation = grant.get('authorizationGeneration')
        if not isinstance(generation, str) or not generation:
            raise AlphaError('YouTube authorization changed during identity verification.', 409, code='youtube_connection_changed')
        cur.execute("UPDATE public.pr_encrypted_credentials SET youtube_identity_ingested_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL AND authorization_generation::text=%s AND provider_account_id=%s", (now, workspace_id, connection_id, generation, identity['providerAccountId']))
        if cur.rowcount != 1:
            raise AlphaError('YouTube authorization changed during identity verification.', 409, code='youtube_connection_changed')

    def verify(self, workspace_id, token, connection_id):
        """Re-check identity and scope drift for an existing connection."""
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            cur.execute("SELECT provider,provider_account_id,scopes,access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, connection_id))
            stored = cur.fetchone()
            if not stored:
                raise AlphaError("Connection unavailable.", 404)
            self._assert_pinterest_context(stored[0], workspace_id, principal, scopes=stored[2])
            if stored[0] == 'youtube':
                cur.execute("SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL", (workspace_id, connection_id))
                generation_row = cur.fetchone()
                starting_generation = generation_row[0] if generation_row else None
                adapter = self._provider_for_access('youtube', self.vault.decrypt(stored[3], stored[4]))
                policy_force = (getattr(adapter, 'legacy_refresh_only', False)
                                and self.youtube_policy.required(self._provider('youtube'), scopes=stored[2]))
                self.youtube_policy.require_user(cur, workspace_id, principal, token, adapter, scopes=stored[2], force=policy_force)
        provider_id, account_id, scopes, starting_ciphertext = stored[:4]
        grant = None
        reported = []
        identity = None
        # A read proof (Instagram Login) never observes write scopes. When it sees a strict subset of the stored
        # grant, the grant is kept as stored and trust is not extended, as in reverify_for_worker.
        lower_bound = False
        try:
            grant = self.token_for_worker(workspace_id, connection_id)
            adapter = self.provider_for_grant(grant)
            self._admit_identity(workspace_id, adapter)
            identity = adapter.identity(grant["accessToken"])
            drift = identity["providerAccountId"] != account_id or (provider_id == 'mastodon' and bool(identity.get('restriction')))
            inspected = hasattr(adapter, "inspect_scopes")
            reported = grant["scopes"] if inspected and not drift else []
            if not drift and not inspected and hasattr(adapter, 'verify_read_access'):
                reported = adapter.verify_read_access(grant['accessToken'], account_id)
                lower_bound = bool(reported) and set(reported) < set(scopes)
            changed = set(reported) != set(scopes)
            result = {"connectionId": connection_id, "identityVerified": not drift, "scopes": list(scopes) if lower_bound else reported,
                      "state": "reauthorization_required" if drift else "scope_missing" if not reported else "read_verified" if lower_bound or not changed else "scope_changed",
                      **({'refreshBindingRequired': grant.get('refreshBindingRequired') is True} if provider_id == 'youtube' else {})}
        except AlphaError as error:
            if provider_id == 'mastodon':
                rejected = error.code == 'mastodon_authorization_revoked'
                if rejected:
                    # token_for_worker may already have persisted this exact 401.
                    # A later identity request uses the same observed credential;
                    # neither response may revoke a concurrent replacement consent.
                    self.mark_mastodon_revoked(workspace_id, connection_id,
                        expected_ciphertext=getattr(error, 'mastodon_observed_ciphertext', starting_ciphertext))
                with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                    from .hosted import _membership, audit
                    require(_membership(row), 'manage_connections')
                    cur.execute("SELECT access_ciphertext,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='mastodon' FOR SHARE", (workspace_id, connection_id))
                    observed = cur.fetchone()
                    if (not observed or (rejected and not observed[1])
                            or (not rejected and (observed[1] or observed[0] != starting_ciphertext))):
                        raise AlphaError('Connection changed during verification; reload and verify again.', 409)
                    state = ('reauthorization_required' if rejected else
                             'token_expired' if error.code == 'reauthorization_required' else 'verification_unavailable')
                    audit(cur, workspace_id, principal, 'channel.verified', connection_id, {'state': state})
                # A failed provider observation must not clear previously verified
                # permissions, rewrite identity state or extend its verification age.
                return {'connectionId': connection_id, 'identityVerified': False,
                        'scopes': [] if rejected else list(scopes), 'state': state}
            if provider_id == 'youtube' and error.code in ('youtube_verification_unavailable', 'youtube_oauth_binding_required', 'youtube_oauth_binding_changed', 'youtube_capacity_schema', 'youtube_capacity_delay'):
                # Manual Verify must preserve the same authority as worker revalidation
                # when Google cannot provide an authoritative scope observation.
                with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                    from .hosted import _membership, audit
                    require(_membership(row), 'manage_connections')
                    binding_missing = error.code in ('youtube_oauth_binding_required', 'youtube_oauth_binding_changed')
                    audit(cur, workspace_id, principal, 'channel.verified', connection_id, {'state': 'client_binding_missing' if binding_missing else 'verification_unavailable'})
                return {'connectionId': connection_id, 'identityVerified': False, 'scopes': list(scopes),
                        'state': 'client_binding_missing' if binding_missing else 'verification_unavailable',
                        'refreshBindingRequired': binding_missing}
            # Do not leak provider responses, nor label a transient network failure as token expiry.
            result = {"connectionId": connection_id, "identityVerified": False, "scopes": [], "state": "verification_unavailable"}
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            cur.execute("SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            current = cur.fetchone()
            if not current or (grant and self.vault.decrypt(current[0], current[1]) != grant["accessToken"]) or (not grant and current[0] != starting_ciphertext):
                raise AlphaError("Connection changed during verification; reload and verify again.", 409)
            if provider_id == 'youtube':
                self._assert_youtube_generation(cur, workspace_id, connection_id,
                    grant.get('authorizationGeneration') if grant else starting_generation)
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            channel = next((c for c in state.get("phase2", {}).get("channels", []) if c["id"] == connection_id), None)
            if channel is None:
                raise AlphaError("Connection unavailable.", 404)
            if lower_bound:
                channel["identityVerified"] = True
            else:
                channel.update(scopes=reported, identityVerified=result["identityVerified"], verifiedAt=self.clock())
            if grant:
                channel["expiresAt"] = float(grant["expiresAt"]) if grant["expiresAt"] else channel.get("expiresAt", 0)
                if provider_id == 'youtube':
                    channel['refreshBindingRequired'] = grant.get('refreshBindingRequired') is True
                    channel['authorizationLane'] = grant.get('authorizationLane', 'standard')
                    if identity and result['identityVerified']:
                        self._stamp_youtube_identity(cur, workspace_id, connection_id, grant, identity, self.clock())
                        channel['account'] = identity.get('handle') or identity['providerAccountId']
                        channel['providerAccountId'] = identity['providerAccountId']
                        channel.update(configured=True, revoked=False)
                        channel.pop('youtubeProviderDataRemoved', None)
                        channel['youtubeIdentityIngestedAt'] = self.clock()
            if result["state"] != "read_verified":
                channel["capabilityVerified"] = False
                cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Permissions changed or could not be verified; reconnect and review.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND capability<>'identity'", (workspace_id, connection_id))
            if result["state"] == "reauthorization_required":
                channel["revoked"] = True
            if not lower_bound:
                cur.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (reported, workspace_id, connection_id))
            self.commands.engine.invalidate(state)
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            audit(cur, workspace_id, principal, "channel.verified", connection_id, {"state": result["state"]})
        if provider_id == 'youtube' and grant and result['state'] == 'reauthorization_required':
            self.mark_youtube_revoked(workspace_id, connection_id, expected_access_token=grant['accessToken'], expected_generation=grant.get('authorizationGeneration'))
        if identity and result["identityVerified"]:
            self._keep_picture(workspace_id, token, connection_id, identity, **({'youtube_generation': grant.get('authorizationGeneration')} if provider_id == 'youtube' else {}))
        return result

    # --- worker re-verification (orchestration §5 step 2) ------------------------------
    WORKER_REVERIFIED = "channel.reverified_by_worker"
    COMPOSER_REVERIFIED = "channel.reverified_for_composer"

    def refresh_for_composer(self, workspace_id, token, revision, action, payload):
        """Authenticated age recovery only; never submit or advance a review/approval."""
        if action not in ('p2_review', 'p2_approve', 'p2_approve_many'):
            return
        if not isinstance(payload, dict):
            raise AlphaError('Expected a structured command.')
        from .hosted import _membership, throttle
        from .permissions import STEP_UP_ACTIONS, classify
        from .store import find
        from .contracts import digest
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), classify(action))
            if action in STEP_UP_ACTIONS:
                self.repository.assert_fresh(token, principal)
            if type(revision) is not int or revision != row[0]:
                raise AlphaError('Workspace changed; reload.', 409, code='workspace_revision_conflict')
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            data = state.get('phase2') or {}
            channel_ids = []
            if action == 'p2_review':
                variant = find(state.get('variants', []), payload.get('variantId'))
                channel_ids.append(payload.get('channelId'))
            else:
                reviews = payload.get('reviews') if action == 'p2_approve_many' else [payload]
                if payload.get('confirmed') is not True or not isinstance(reviews, list) or not 1 <= len(reviews) <= 10:
                    raise AlphaError('Explicitly review between one and ten exact destinations.')
                for requested in reviews:
                    if not isinstance(requested, dict):
                        raise AlphaError('Expected exact review IDs and digests.')
                    review = find(data.get('reviews', []), requested.get('reviewId'))
                    manifest = review['manifest']
                    if (review['digest'] != requested.get('digest') or review['digest'] != digest(manifest)
                            or review['status'] not in ('needs_review', 'approved')
                            or manifest['expiresAt'] <= self.clock()
                            or not self.commands.engine.current(state, manifest)):
                        raise AlphaError('This approval is stale. Prepare a new review.', 409)
                    channel_ids.append(manifest['channelId'])
            if any(not isinstance(connection, str) or not connection for connection in channel_ids):
                raise AlphaError('Choose an available channel.')
            channels = [find(data.get('channels', []), connection) for connection in dict.fromkeys(channel_ids)]
            if any(channel.get('platform') == 'YouTube' for channel in channels):
                # The shared composer can use a fresh channel without calling
                # Creator._member or revalidation. Its actual actor must agree too.
                self.youtube_policy.require_user(cur, workspace_id, principal, token,
                    self.providers.get('youtube'), force=True)
            if action == 'p2_review' and ((variant.get('channelId') and variant['channelId'] != channels[0]['id'])
                    or (variant.get('platform') and variant['platform'] != channels[0]['platform'])):
                raise AlphaError('This draft belongs to another channel. Select its channel or prepare a new draft.', 409)
            target = next((channel for channel in channels if self.commands.engine.channel_reverification_due(channel)), None)
            if target is None:
                return
            connection_id = target['id']
            cur.execute("SELECT provider_account_id,refresh_supported,refresh_ciphertext IS NOT NULL AND refresh_ciphertext<>'',extract(epoch from access_expires_at)::float8 FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL", (workspace_id, connection_id))
            credential = cur.fetchone()
            if not credential or (credential[3] is not None and credential[3] <= self.clock() and not (credential[1] and credential[2])):
                raise AlphaError('This YouTube connection needs Google authorization again. Reconnect it before reviewing a post.', 409, code='youtube_reconnect_required')
            if credential[0] != target.get('providerAccountId'):
                raise AlphaError('YouTube channel identity changed. Reload and prepare a new review.', 409, code='youtube_connection_changed')
            # One selected connection per request, regardless of bulk destination count.
            # Counters commit before provider I/O, including unsuccessful observations.
            throttle(cur, f'youtube-composer-workspace:{workspace_id}', 10, 60)
            throttle(cur, f'youtube-composer-channel:{workspace_id}:{connection_id}', 2, 60)
        try:
            result = self._reverify_connection(workspace_id, connection_id,
                authenticated=(token, revision, action), actor=principal, audit_event=self.COMPOSER_REVERIFIED)
        except AlphaError as error:
            if error.status == 404 or error.code == 'youtube_revoked_oauth':
                raise AlphaError('This YouTube connection needs Google authorization again. Reconnect it before reviewing a post.', 409, code='youtube_reconnect_required') from error
            raise
        if result.get('state') == 'verification_unavailable':
            raise AlphaError('YouTube permissions could not be verified. Try again shortly; no post was approved.', 503, code='youtube_verification_unavailable')
        if result.get('state') != 'read_verified' or result.get('ready') is not True:
            raise AlphaError('YouTube permissions or identity changed. Reload and prepare a new review; reconnect if required. No post was approved.', 409, code='youtube_connection_changed')
        raise AlphaError('YouTube connection refreshed. Reload and review the post, then try again. No post was approved.', 409, code='youtube_connection_refreshed')

    @contextmanager
    def _reverification_commit(self, workspace_id, authenticated=None):
        if authenticated is not None:
            from .hosted import _membership
            from .permissions import STEP_UP_ACTIONS, classify
            token, revision, action = authenticated
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(_membership(row), classify(action))
                if action in STEP_UP_ACTIONS:
                    self.repository.assert_fresh(token, principal)
                if type(revision) is not int or revision != row[0]:
                    raise AlphaError('Workspace changed; reload.', 409, code='workspace_revision_conflict')
                yield cur, (row[1],), principal
        else:
            with self.repository.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
                yield cur, cur.fetchone(), None

    def reverify_for_worker(self, workspace_id, connection_id):
        """Re-verify a channel on the worker's own authority, right before an approved post is committed.

        SERVER-SIDE ONLY: there is no session token and no membership check, so this must never be reachable
        from an HTTP route. The publish worker calls it at publishAt - 30 min so the channel stays
        "Ready for posting" (verifiedAt + 3600 >= now) until the post goes out.

        Mirrors verify(): stored credential -> token_for_worker -> identity -> account drift -> live scopes, with
        the same states (read_verified | scope_changed | scope_missing | reauthorization_required |
        verification_unavailable). Differences, all in the worker's favour of doing no harm:
        - It never upgrades authority. capabilityVerified and capability levels only ever go down here; only a
          person reconnecting (complete) restores them.
        - store.current() compares manifest scopes to channel scopes as LISTS, so when the reported set equals
          the channel's set the stored list is kept as is (a provider reordering its scopes must not hold every
          approved job). A different set is stored sorted and takes verify()'s downgrade path. A difference from
          either the credential's or the channel's scopes counts as scope_changed.
        - Provider or network failure, a credential rotated by a person mid-check, a workspace pending deletion,
          or a provider that can only prove a subset of the stored grant (Instagram's verify_read_access proves
          read access, never write scopes) returns verification_unavailable with the channel untouched:
          verifiedAt is not extended and nothing is downgraded.
        - The account picture is not refreshed (that path needs a member session).
        Raises AlphaError 404 only for an unknown or revoked connection. Every outcome is audited with a NULL
        (system) actor. Returns {"connectionId", "state", "ready"}; ready means read_verified and the channel is
        "Ready for posting" now.
        """
        return self._reverify_connection(workspace_id, connection_id)

    def _reverify_connection(self, workspace_id, connection_id, *, authenticated=None, actor=None, audit_event=None):
        """Private shared read proof; foreground callers use refresh_for_composer's permission boundary."""
        from .hosted import audit
        audit_event = audit_event or self.WORKER_REVERIFIED
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT c.provider,c.provider_account_id,w.state FROM public.pr_encrypted_credentials c JOIN public.pr_workspaces w ON w.id=c.workspace_id WHERE c.workspace_id=%s AND c.connection_id=%s AND c.revoked_at IS NULL", (workspace_id, connection_id))
                stored = cur.fetchone()
        if not stored:
            raise AlphaError("Connection unavailable.", 404)
        provider_id, account_id, state = stored
        state = json.loads(state) if isinstance(state, str) else state
        if not any(c.get("id") == connection_id for c in state.get("phase2", {}).get("channels", [])):
            raise AlphaError("Connection unavailable.", 404)

        def unavailable(cur, reason):
            binding_missing = reason in ('youtube_oauth_binding_required', 'youtube_oauth_binding_changed')
            outcome = 'client_binding_missing' if binding_missing else 'verification_unavailable'
            audit(cur, workspace_id, actor, audit_event, connection_id, {"state": outcome, "reason": reason})
            return {"connectionId": connection_id, "state": outcome, "ready": False,
                    **({'refreshBindingRequired': True} if binding_missing else {})}

        if state.get("accountDeletion") or state.get("accountBlock"):
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    return unavailable(cur, "account_deletion_pending")
        lower_bound = False
        try:
            grant = self.token_for_worker(workspace_id, connection_id)
            adapter = self.provider_for_grant(grant)
            self._admit_identity(workspace_id, adapter)
            identity = adapter.identity(grant["accessToken"])
            drift = identity["providerAccountId"] != account_id or (provider_id == 'mastodon' and bool(identity.get('restriction')))
            inspected = hasattr(adapter, "inspect_scopes")
            reported = grant["scopes"] if inspected and not drift else []
            if not drift and not inspected and hasattr(adapter, "verify_read_access"):
                reported = adapter.verify_read_access(grant["accessToken"], account_id)
                lower_bound = True
        except (AlphaError, KeyError, TypeError, ValueError, OSError) as error:
            # Do not leak provider responses, and never turn a transient failure into lost authority.
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    return unavailable(cur, error.code if isinstance(error, AlphaError) and error.code in ('youtube_oauth_binding_required', 'youtube_oauth_binding_changed') else "provider_unavailable")
        reported = list(reported) if isinstance(reported, list) and all(isinstance(s, str) for s in reported) else []
        with self._reverification_commit(workspace_id, authenticated) as (cur, locked, actor):
            cur.execute("SELECT access_ciphertext,key_id,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            current = cur.fetchone()
            if not locked or not current:
                raise AlphaError("Connection unavailable.", 404)
            try:
                same_credential = self.vault.decrypt(current[0], current[1]) == grant["accessToken"]
            except AlphaError:
                same_credential = False
            if not same_credential:
                return unavailable(cur, "credential_rotated")  # a person re-authorized meanwhile; their grant wins
            if provider_id == 'youtube':
                self._assert_youtube_generation(cur, workspace_id, connection_id, grant.get('authorizationGeneration'))
            state = json.loads(locked[0]) if isinstance(locked[0], str) else locked[0]
            if state.get("accountDeletion") or state.get("accountBlock"):
                return unavailable(cur, "account_deletion_pending")
            channel = next((c for c in state.get("phase2", {}).get("channels", []) if c.get("id") == connection_id), None)
            if channel is None:
                raise AlphaError("Connection unavailable.", 404)
            existing, credential_scopes, observed = set(channel.get("scopes") or []), set(current[2] or []), set(reported)
            if lower_bound and observed and observed <= existing and observed <= credential_scopes and not observed == existing == credential_scopes:
                return unavailable(cur, "grant_not_observable")
            changed = observed != credential_scopes or observed != existing
            outcome = "reauthorization_required" if drift else "scope_missing" if not reported else "scope_changed" if changed else "read_verified"
            if observed != existing:
                channel["scopes"] = sorted(observed)
            channel.update(identityVerified=not drift, verifiedAt=self.clock())
            if provider_id == 'mastodon':
                channel['mastodonHealth'] = {'state': outcome, 'checkedAt': self.clock(),
                    **({'reason': identity['restriction']} if identity.get('restriction') else {})}
            if provider_id == 'youtube':
                channel['refreshBindingRequired'] = grant.get('refreshBindingRequired') is True
                channel['authorizationLane'] = grant.get('authorizationLane', 'standard')
                if not drift:
                    self._stamp_youtube_identity(cur, workspace_id, connection_id, grant, identity, self.clock())
                    channel['account'] = identity.get('handle') or identity['providerAccountId']
                    channel['providerAccountId'] = identity['providerAccountId']
                    channel.update(configured=True, revoked=False)
                    channel.pop('youtubeProviderDataRemoved', None)
                    channel['youtubeIdentityIngestedAt'] = self.clock()
            channel["expiresAt"] = float(grant["expiresAt"]) if grant.get("expiresAt") else channel.get("expiresAt", 0)
            if outcome != "read_verified":
                channel["capabilityVerified"] = False
                cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Permissions changed or could not be verified; reconnect and review.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND capability<>'identity'", (workspace_id, connection_id))
            if outcome == "reauthorization_required":
                channel["revoked"] = True
            if observed != credential_scopes:
                cur.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (sorted(observed), workspace_id, connection_id))
            self.commands.engine.invalidate(state)
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            audit(cur, workspace_id, actor, audit_event, connection_id, {"state": outcome})
            ready = outcome == "read_verified" and not channel.get('refreshBindingRequired') and self.commands.engine.channel_state(channel) == "Ready for posting"
        if provider_id == 'youtube' and outcome == 'reauthorization_required':
            self.mark_youtube_revoked(workspace_id, connection_id, expected_access_token=grant['accessToken'], expected_generation=grant.get('authorizationGeneration'))
        return {"connectionId": connection_id, "state": 'client_binding_missing' if channel.get('refreshBindingRequired') else outcome, "ready": ready,
                **({'refreshBindingRequired': True} if channel.get('refreshBindingRequired') else {})}

    def disconnect(self, workspace_id, token, connection_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            from .hosted import _membership, audit
            require(_membership(row), "manage_connections")
            self.repository.assert_fresh(token, principal)
            cur.execute("SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR UPDATE", (workspace_id, connection_id))
            stored = cur.fetchone()
            if not stored:
                raise AlphaError("Connection unavailable.", 404)
            remote = None
            shared = self._shared_elsewhere(cur, workspace_id, connection_id, stored[0])
            if shared:
                remote = False  # another connection still uses Rafii's bot there; removing it would disconnect them too
            else:
                try:
                    access = self.vault.decrypt(stored[1], stored[2])
                    remote = self._provider_for_access(stored[0], access).revoke(access)
                except AlphaError:
                    remote = False
            cur.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
            cur.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Disconnected by the customer.',updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
            from .social_history import revoke_connection_samples
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            revoked_samples = revoke_connection_samples(state, connection_id, principal, self.clock())
            state_changed = bool(revoked_samples)
            pinterest_stop = None
            if stored[0] == 'pinterest':
                # Also fence a callback already claimed before this disconnect.
                # A new explicit connect request after disconnect remains possible.
                cur.execute("UPDATE public.pr_oauth_transactions SET outcome='denied',consumed_at=coalesce(consumed_at,now()) WHERE workspace_id=%s AND provider='pinterest' AND (consumed_at IS NULL OR outcome='exchange_started')", (workspace_id,))
                from .pinterest_safety import revoke_authority
                pinterest_stop = revoke_authority(state, connection_id, self.clock())
                state_changed = True
            if stored[0] == 'mastodon':
                for channel in state.get('phase2', {}).get('channels', []):
                    if channel.get('id') == connection_id and channel.get('platform') == 'Mastodon':
                        state_changed = state_changed or channel.get('revoked') is not True
                        channel['revoked'] = True
                self.commands.engine.invalidate(state)
            if stored[0] == 'youtube':
                from .youtube.agent import revoke_connection_authority
                state_changed = revoke_connection_authority(state, connection_id, principal, self.clock(),
                                                            reason='connection_disconnected') or state_changed
                for channel in state.get('phase2', {}).get('channels', []):
                    if channel.get('id') == connection_id and channel.get('platform') == 'YouTube':
                        state_changed = state_changed or channel.get('revoked') is not True
                        channel['revoked'] = True
            if revoked_samples:
                self.commands.engine.invalidate(state)
                audit(cur, workspace_id, principal, 'voice.connection_samples_revoked', connection_id, {'samples': revoked_samples})
            if state_changed:
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace_id))
            if stored[0] == 'youtube':
                # Purge after any state write from this transaction's earlier
                # snapshot so it cannot restore removed provider output.
                from .youtube.journal import purge_authorized_data
                purge_authorized_data(cur, workspace_id, connection_id)
            account_pictures.guarded(cur, account_pictures.remove, workspace_id, connection_id)
            from .growth.history_import import mark_for_purge
            mark_for_purge(cur, workspace_id, connection_id)   # imported history goes after commit (purge_after_disconnect)
            audit(cur, workspace_id, principal, "channel.disconnected", connection_id, {"remoteRevoked": bool(remote), "remoteRevocationDeferred": shared and stored[0] == 'youtube'})
            from . import product_events
            # Product taxonomy: the connection generation (when it was verified) is the version, pairing it with its connect.
            connected = next((item for item in ((state or {}).get("phase2") or {}).get("channels") or [] if isinstance(item, dict) and item.get("id") == connection_id), {})
            generation = connected.get("verifiedAt")
            product_events.record(cur, workspace_id, principal, "channel.disconnected", connection_id,
                                  int(generation) if isinstance(generation, (int, float)) and not isinstance(generation, bool) and generation > 0 else int(self.clock()),
                                  {"provider": stored[0], "cause": "member"})
        # Outside the transaction that held the workspace row, so it cannot deadlock with the import or metric steps.
        from .growth.history_import import purge_after_disconnect
        purge_after_disconnect(self.repository.connection_factory, workspace_id, connection_id)
        snapshot = self.repository.get(workspace_id, token)
        revision = snapshot["revision"]
        if stored[0] not in ('youtube', 'pinterest', 'mastodon'):
            try:
                saved = self.repository.mutate(workspace_id, token, snapshot["revision"], "p2_channel_disconnect", {"channelId": connection_id})
                revision = saved["revision"]
            except AlphaError:
                revision = snapshot["revision"]  # channel absent from state; credentials are already revoked
        # YouTube, Pinterest and Mastodon state were revoked atomically with their credential. A second
        # mutation here could incorrectly revoke a consent completed meanwhile.
        deferred = shared and stored[0] == 'youtube'
        note = "Local execution access removed; approved jobs for this account are held at the next claim."
        if stored[0] == 'pinterest':
            note = 'Pinterest access removed. Pending jobs were canceled atomically; any request already sent requires reconciliation. Remove Rafii in Pinterest account settings to revoke provider consent.'
        if deferred:
            note += " Google project-wide revocation was deferred to protect other active Google connections. Review Google account permissions to revoke the entire project grant."
        return {"connectionId": connection_id, "disconnected": True, "remoteRevoked": bool(remote), "remoteRevocationDeferred": deferred, "revision": revision, "note": note,
                **(pinterest_stop or {})}
