"""Fail-closed preview composition; no connection is made while validating configuration."""
import re
from urllib.parse import parse_qs, unquote, urlparse


PRODUCTION_PROJECT_ID = 'prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L'
PRODUCTION_DATABASE_REF = 'buoyhkbodnhzngaotoel'
FORBIDDEN_PROJECT_ID = 'prj_4bfvSc0AC6am9FdknFWcwNYgmcnN'
FORBIDDEN_DATABASE_REF = 'oxacvkhpfgytkepxcaqh'


def production_binding_proof(values):
    """Inspect bindings without opening a database or exposing a connection string."""
    urls = ('POSTRIFF_SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_URL', 'SUPABASE_URL')
    try:
        dsn = urlparse(values.get('POSTRIFF_DATABASE_URL', ''))
    except ValueError:
        raise ValueError('Invalid database binding; no database connection was made.') from None
    username = unquote(dsn.username or '')
    direct = dsn.hostname == 'db.' + PRODUCTION_DATABASE_REF + '.supabase.co' and username == 'postgres'
    pooled = bool(re.fullmatch(r'[a-z0-9.-]+\.pooler\.supabase\.com', dsn.hostname or '')) and username == 'postgres.' + PRODUCTION_DATABASE_REF
    forbidden = (values.get('VERCEL_PROJECT_ID') == FORBIDDEN_PROJECT_ID
        or values.get('POSTRIFF_CONNECTION_TARGET') in (FORBIDDEN_PROJECT_ID, FORBIDDEN_DATABASE_REF)
        or any(FORBIDDEN_DATABASE_REF in str(values.get(key, '')) for key in urls)
        or FORBIDDEN_DATABASE_REF in (dsn.hostname or '') or FORBIDDEN_DATABASE_REF in username)
    if forbidden:
        raise ValueError('Owner directive #179: Rafii X/Mastodon/Telegram cannot use the forbidden staging project or database.')
    bound = (dsn.scheme in ('postgres', 'postgresql') and (direct or pooled)
        and parse_qs(dsn.query).get('sslmode') in (['require'], ['verify-full']))
    expected = 'https://' + PRODUCTION_DATABASE_REF + '.supabase.co'
    identity = all(str(values.get(key, '')).rstrip('/') == expected for key in urls[:2])
    return {'projectId': values.get('VERCEL_PROJECT_ID'),
        'supabaseProjectRef': PRODUCTION_DATABASE_REF if identity else None,
        'databaseProjectRef': PRODUCTION_DATABASE_REF if bound else None,
        'databaseBindingVerified': bool(bound and identity and values.get('VERCEL_PROJECT_ID') == PRODUCTION_PROJECT_ID),
        'databaseConnectionMode': ('transaction_pooler' if pooled and dsn.port == 6543 else 'session_pooler' if pooled else 'direct') if bound else None,
        'databasePort': dsn.port if bound else None,
        'databaseTLS': parse_qs(dsn.query).get('sslmode', [None])[0] if bound else None}


def assert_production_candidate(values):
    proof = production_binding_proof(values)
    if values.get('POSTRIFF_ENVIRONMENT') == 'production-canary' and values.get('POSTRIFF_X_RELEASE_MODE', 'off') not in ('off', 'canary'):
        raise ValueError('Production canary must keep X off or confined to authorized owner workspaces.')
    if str(values.get('CI', '')).lower() in ('true', '1') and not values.get('VERCEL_ENV') and (proof['databaseProjectRef'] or proof['supabaseProjectRef']):
        raise ValueError('Synthetic CI must use a disposable database, never the persistent production service.')
    cloud = values.get('VERCEL_ENV') in ('preview', 'production')
    canary = values.get('POSTRIFF_ENVIRONMENT') == 'production-canary'
    if cloud and (values.get('VERCEL_ENV') == 'production' or canary):
        if not proof['databaseBindingVerified']:
            raise ValueError('Owner directive #179: production candidate requires the canonical Vercel project, production Supabase identity and TLS database binding before connecting.')
        if values.get('POSTRIFF_PRODUCTION_PROJECT_REF') != PRODUCTION_DATABASE_REF:
            raise ValueError('Owner directive #179: pin the canonical production Supabase reference.')
        if values.get('POSTRIFF_API_ORIGIN'):
            raise ValueError('Production candidate API must use this deployment, not a cross-service rewrite.')
    return proof


def isolated_environment(values):
    result = dict(values)
    assert_production_candidate(result)
    if result.get('VERCEL_ENV') != 'preview':
        return result
    if result.get('POSTRIFF_ENVIRONMENT') == 'production-canary':
        if result.get('POSTRIFF_X_RELEASE_MODE', 'off') not in ('off', 'canary'):
            raise ValueError('Production canary must keep X off or confined to authorized owner workspaces.')
        return result
    if result.get('POSTRIFF_ENVIRONMENT') != 'staging':
        raise ValueError('Preview requires the explicit staging environment.')
    staging = result.get('POSTRIFF_STAGING_PROJECT_REF', '')
    production = result.get('POSTRIFF_PRODUCTION_PROJECT_REF', '')
    if not all(re.fullmatch(r'[a-z0-9]{20}', ref) for ref in (staging, production)) or staging == production:
        raise ValueError('Preview requires distinct pinned staging and production project references.')
    expected = 'https://' + staging + '.supabase.co'
    if result.get('POSTRIFF_SUPABASE_URL', '').rstrip('/') != expected or result.get('NEXT_PUBLIC_SUPABASE_URL', '').rstrip('/') != expected:
        raise ValueError('Preview identity and storage must match the pinned staging project.')
    dsn = urlparse(result.get('POSTRIFF_DATABASE_URL', ''))
    direct = dsn.hostname == 'db.' + staging + '.supabase.co' and unquote(dsn.username or '') == 'postgres'
    pooler = bool(re.fullmatch(r'[a-z0-9.-]+\.pooler\.supabase\.com', dsn.hostname or '')) and unquote(dsn.username or '') == 'postgres.' + staging
    if dsn.scheme not in ('postgres', 'postgresql') or not (direct or pooler) or parse_qs(dsn.query).get('sslmode') not in (['require'], ['verify-full']):
        raise ValueError('Preview database must use TLS and match the pinned staging project.')
    origin = result.get('POSTRIFF_PUBLIC_BASE_URL', '').rstrip('/')
    approved = result.get('POSTRIFF_STAGING_PUBLIC_BASE_URL', '').rstrip('/')
    parsed = urlparse(origin)
    if not approved or origin != approved or parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Preview callbacks require the exact approved staging HTTPS origin.')
    # A shared staging alias can point at another branch. Once OAuth is configured,
    # its codes must return to this candidate, never that other deployment.
    oauth_configured = any(value for name, value in result.items()
                           if name.startswith('POSTRIFF_OAUTH_') and name.endswith(('CLIENT_ID', 'CLIENT_SECRET')))
    candidate_origins = {'https://' + result[name] for name in ('VERCEL_BRANCH_URL', 'VERCEL_URL') if result.get(name)}
    if oauth_configured and origin not in candidate_origins:
        raise ValueError('OAuth preview callbacks must use this deployment URL or its own Git branch URL.')
    if result.get('POSTRIFF_API_ORIGIN'):
        raise ValueError('Preview API rewrites must use the same deployment, not an external origin.')
    stripe = result.get('STRIPE_SECRET_KEY', '')
    if stripe and not stripe.startswith(('sk_test_', 'rk_test_')):
        raise ValueError('Preview billing accepts test-mode credentials only.')
    # Secrets must be deliberately bound to this staging release, never inherited from production.
    # The review manifest contains hashes, not secrets; authorizing its deployment remains external.
    import hashlib
    import json
    try:
        pins = json.loads(result.get('POSTRIFF_STAGING_SECRET_SHA256', '{}'))
    except (ValueError, TypeError) as error:
        raise ValueError('Staging secret fingerprints must be a JSON object.') from error
    if not isinstance(pins, dict):
        raise ValueError('Staging secret fingerprints must be a JSON object.')
    names = {'POSTRIFF_SUPABASE_SECRET_KEY', 'POSTRIFF_CREDENTIAL_KEY', 'CRON_SECRET', 'STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET', 'AI_GATEWAY_API_KEY', 'RESEND_API_KEY',
             'RESEND_WEBHOOK_SECRET', 'POSTRIFF_VAPID_PRIVATE_KEY', 'POSTRIFF_NOTIFICATION_SIGNING_KEY',
             'RAFII_PHONE_ENCRYPTION_KEY','TWILIO_AUTH_TOKEN', 'DIAL_API_KEY', 'DIAL_AUDIO_SIGNING_SECRET',
             'DIAL_WEBHOOK_SIGNING_SECRET', 'DIAL_VERIFICATION_SECRET'}
    names.update(key for key in result if key.startswith('POSTRIFF_OAUTH_') and key.endswith(('CLIENT_ID', 'CLIENT_SECRET')))
    for name in names:
        value = result.get(name)
        if value and pins.get(name) != hashlib.sha256(value.encode()).hexdigest():
            raise ValueError('Preview contains an unpinned staging credential: ' + name)
    # Research/CLI have independent egress and credentials; neither is part of this deployment candidate.
    if result.get('POSTRIFF_RESEARCH', '0') != '0' or result.get('POSTRIFF_LOCAL_CLI', '0') != '0':
        raise ValueError('Preview research and local CLI must remain disabled.')
    result['POSTRIFF_RESEARCH'] = '0'
    result['POSTRIFF_LOCAL_CLI'] = '0'
    # Rafii coworker features that reach an outside service (email, push, the public web) stay off in preview.
    egress = ('RAFII_NOTIFICATIONS_V2_ENABLED', 'RAFII_WEB_PUSH_ENABLED', 'RAFII_RESEARCH_BROKER_ENABLED', 'RAFII_LISTENING_ENABLED',
              'RAFII_PHONE_OUTBOUND_ENABLED', 'RAFII_PHONE_INBOUND_ENABLED', 'RAFII_PHONE_SCHEDULED_ENABLED', 'RAFII_PHONE_PROACTIVE_ENABLED', 'RAFII_PHONE_VERIFICATION_ENABLED',
              'RAFII_SMS_ENABLED', 'RAFII_SMS_ESCALATION_ENABLED',
              'RAFII_ACTIVE_SCOUT_ENABLED', 'RAFII_JEV_SCOUT_ENABLED', 'RAFII_SCOUT_STRONG_MODEL_ESCALATION_ENABLED',
              'RAFII_MULTIMODAL_ENRICHMENT_ENABLED', 'RAFII_WATCH_IT_LOCAL_ADAPTER_ENABLED',
              'RAFII_TREND_PROVIDER_OPERATIONS_ENABLED', 'RAFII_TREND_MODEL_ENRICHMENT_ENABLED',
              'RAFII_TREND_NOTIFICATIONS_ENABLED', 'RAFII_TREND_MULTIMODAL_ENABLED')
    if any(str(result.get(name, '')).strip().lower() in ('1', 'true', 'yes', 'on') for name in egress):
        raise ValueError('Preview Rafii notifications, web push, research and listening must remain disabled.')
    for name in egress:
        result[name] = ''
    # Growth Phase 0 reaches Meta (metric reads, history import) and the paid AI Gateway (Post Doctor).
    growth = ('POSTRIFF_METRIC_READS','POSTRIFF_HISTORY_IMPORT','POSTRIFF_GROWTH','POSTRIFF_POST_DOCTOR','POSTRIFF_GENOME','POSTRIFF_PUBLIC_POST_DOCTOR')
    if any(str(result.get(name, '')).strip().lower() in ('1', 'true', 'yes', 'on') for name in growth):
        raise ValueError('Preview growth metric reads, history import and Post Doctor must remain disabled.')
    for name in growth:
        result[name] = ''
    return result
