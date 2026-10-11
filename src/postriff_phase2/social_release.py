"""Issue #179: reject forbidden infrastructure before network or database access.

These are non-secret owner-approved deployment identities. Local/disposable CI
tests remain unbound; a Vercel release must prove the real production binding.
"""
import re
import shlex
from urllib.parse import parse_qs, unquote, urlparse

PRODUCTION_PROJECT = 'prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L'
PRODUCTION_REF = 'buoyhkbodnhzngaotoel'
PRODUCTION_URL = 'https://' + PRODUCTION_REF + '.supabase.co'
FORBIDDEN_PROJECT = 'prj_4bfvSc0AC6am9FdknFWcwNYgmcnN'
FORBIDDEN_REF = 'oxacvkhpfgytkepxcaqh'


def reject_forbidden_bindings(values):
    # Check every binding alias, including URI-encoded and keyword-style DSNs.
    # Errors name the variable, never echo its value or a credential.
    names = {'VERCEL_PROJECT_ID', 'POSTRIFF_VERCEL_PROJECT_ID',
             'POSTRIFF_SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_URL', 'SUPABASE_URL',
             'POSTRIFF_DATABASE_URL', 'DATABASE_URL', 'PGHOST', 'PGUSER',
             'POSTRIFF_PRODUCTION_PROJECT_REF', 'POSTRIFF_STAGING_PROJECT_REF'}
    for name in names:
        value = unquote(str(values.get(name, ''))).lower()
        if FORBIDDEN_PROJECT.lower() in value or FORBIDDEN_REF in value:
            raise ValueError('Issue #179 blocks X/Mastodon/Telegram release: forbidden infrastructure in ' + name + '.')


def database_binding(dsn):
    """Return only host/user/TLS metadata, retaining no password in the result."""
    if not isinstance(dsn, str):
        return '', '', ''
    try:
        if '://' in dsn:
            parsed = urlparse(dsn)
            if parsed.scheme not in ('postgres', 'postgresql'):
                return '', '', ''
            return parsed.hostname or '', unquote(parsed.username or ''), (parse_qs(parsed.query).get('sslmode') or [''])[0]
        parts = dict(word.split('=', 1) for word in shlex.split(dsn))
        return parts.get('host', ''), parts.get('user', ''), parts.get('sslmode', '')
    except (TypeError, ValueError):
        return '', '', ''


def require_production_binding(values):
    reject_forbidden_bindings(values)
    project = values.get('VERCEL_PROJECT_ID') or values.get('POSTRIFF_VERCEL_PROJECT_ID')
    if project != PRODUCTION_PROJECT:
        raise ValueError('Issue #179: release requires the verified postriff-phase2-private Vercel project.')
    for name in ('POSTRIFF_SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_URL'):
        if str(values.get(name, '')).rstrip('/') != PRODUCTION_URL:
            raise ValueError('Issue #179: production Supabase binding is missing or mismatched in ' + name + '.')
    host, user, tls = database_binding(values.get('POSTRIFF_DATABASE_URL'))
    direct = host == 'db.' + PRODUCTION_REF + '.supabase.co' and user == 'postgres'
    pooler = bool(re.fullmatch(r'[a-z0-9.-]+\.pooler\.supabase\.com', host)) and user == 'postgres.' + PRODUCTION_REF
    if not (direct or pooler) or tls not in ('require', 'verify-full'):
        raise ValueError('Issue #179: production database DSN binding is unknown, mismatched, or lacks required TLS.')
    return {'projectId': project, 'databaseRef': PRODUCTION_REF, 'status': 'PASS_BINDING_ONLY'}
