#!/usr/bin/env bash
# Targeted Automation regression; disposable cloud SQL and synthetic writer/provider.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB cloud execution.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ]; then echo 'Cloud-only validation.' >&2; exit 64; fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests
if [ "${1:-}" = oauth-discovery-only ]; then
  "$TREND_VISUAL_TEST_PYTHON" -m unittest test_mastodon_management.ProtocolTests
  "$TREND_VISUAL_TEST_PYTHON" - <<'PY'
import json
from datetime import datetime, timezone
from postriff_phase2.mastodon_protocol import discover
from postriff_phase2.social_connectors import MastodonProvider

for host in ('mastodon.social', 'mstdn.social'):
    origin = 'https://' + host
    provider = MastodonProvider('https://app.example')
    transport = provider.transport
    calls = []
    metadata = {}
    allowed = {origin + path for path in ('/api/v2/instance', '/api/v1/instance',
                                         '/.well-known/oauth-authorization-server')}
    def public_read(method, url, **kwargs):
        assert method == 'GET' and url in allowed and not kwargs, 'Unexpected discovery action'
        response = transport(method, url)
        calls.append({'method': method, 'url': url, 'status': response.get('status')})
        if url.endswith('/.well-known/oauth-authorization-server'):
            metadata.update(response.get('body') or {})
        return response
    capabilities = discover(public_read, provider._server(host))
    assert capabilities['pkce'] and set(provider.SCOPES['publish']) <= set(capabilities['scopesSupported'])
    print(json.dumps({'event': 'real_public_oauth_discovery', 'observedAt': datetime.now(timezone.utc).isoformat(),
        'instance': host, 'version': capabilities['version'], 'issuer': metadata['issuer'],
        'authorizationEndpoint': metadata['authorization_endpoint'], 'tokenEndpoint': metadata['token_endpoint'],
        's256Advertised': 'S256' in metadata['code_challenge_methods_supported'],
        'publishScopesAdvertised': True, 'requests': calls, 'oauthClientRegistered': False,
        'ownerIdentityVerified': False, 'actualGrantedScopes': 'NOT_VERIFIED', 'actualS256Flow': 'NOT_RUN'}))
PY
  exit 0
fi
pg_major=16
case "${1:-}" in youtube-disconnect-only|release-preflight-only|management-after134-only) pg_major=17 ;; esac
if [ ! -x "/usr/lib/postgresql/$pg_major/bin/initdb" ]; then
  sudo -n apt-get -qq update
  if [ "$pg_major" = 17 ]; then
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-common
    sudo -n /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  fi
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install "postgresql-$pg_major"
fi
export POSTRIFF_PG_BIN="/usr/lib/postgresql/$pg_major/bin"
case "${1:-}" in
  management-after134-only)
    export POSTRIFF_MASTODON_AFTER134_FIXTURE=1
    "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_disposable_postgres.py tests/phase2/postgres_mastodon_management.py tests/phase2/postgres_mastodon_automation.py
    # Its own cluster: earlier suites consume the shared per-instance admission buckets the scale counts depend on.
    "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_disposable_postgres.py tests/phase2/postgres_mastodon_scale.py ;;
  youtube-disconnect-only) "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_youtube_workspace_provider_data ;;
  release-preflight-only) "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_consumer_migrations postgres_mastodon_automation_legacy ;;
  sql-only) "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_mastodon_management ;;
  '')
    "$TREND_VISUAL_TEST_PYTHON" -m unittest test_postriff_time_savings test_youtube_workspace_provider_data test_mastodon_management test_agent_runtime test_mastodon_threads test_mastodon_publishing test_hosted_wave1_connectors
    "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_time_savings postgres_mastodon_automation postgres_mastodon_management ;;
  *) echo 'Unknown validation mode.' >&2; exit 64 ;;
esac
