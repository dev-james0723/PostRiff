"""Keep the preceding accepted worker running during held-build acceptance.

This opt-in relay is only for authenticated platform cron invocations. It never
follows redirects, reads the old worker's response body, or retries a request.
"""
import re
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from postriff_alpha.domain import AlphaError
from postriff_phase2.social_release import require_production_binding


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send(url, headers):
    request = Request(url, headers=headers, method='GET')
    with build_opener(NoRedirect()).open(request, timeout=55) as response:
        return response.status  # Never read shared production job results.


def preserve_live_cron(environ, values, secret, *, send=None):
    """Caller has already verified CRON_SECRET; configuration remains private."""
    if environ.get('HTTP_USER_AGENT') != 'vercel-cron/1.0':
        return None  # Manual Telegram acceptance never runs a shared worker.
    try:
        require_production_binding(values)
        origin = values.get('POSTRIFF_TELEGRAM_CANARY_LIVE_WORKER_ORIGIN', '')
        parsed = urlparse(origin)
        valid = (values.get('VERCEL_ENV') == 'production'
                 and values.get('POSTRIFF_TELEGRAM_CANARY_ENABLED') == 'true'
                 and parsed.scheme == 'https' and not parsed.username and not parsed.password
                 and not parsed.port and not parsed.path and not parsed.query and not parsed.fragment
                 and re.fullmatch(r'postriff-phase2-private-[a-z0-9]+-jamesau0723-6572s-projects\.vercel\.app', parsed.hostname or '')
                 and parsed.hostname != values.get('VERCEL_URL')
                 and len(secret) >= 16
                 and not environ.get('HTTP_X_POSTRIFF_TELEGRAM_CRON_RELAY'))
        if not valid:
            raise ValueError('Invalid live worker target')
    except (ValueError, TypeError):
        raise AlphaError('The preceding accepted cron worker is unavailable.', 503,
                         code='telegram_live_cron_unavailable') from None
    try:
        status = (send or _send)(origin + '/api/cron/worker', {
            'Authorization': 'Bearer ' + secret,
            'User-Agent': 'vercel-cron/1.0',
            'X-Postriff-Telegram-Cron-Relay': '1',
            **({'X-Vercel-Cron-Schedule': environ['HTTP_X_VERCEL_CRON_SCHEDULE']}
               if environ.get('HTTP_X_VERCEL_CRON_SCHEDULE') == '* * * * *' else {}),
        })
        if status != 200:
            raise ValueError('Upstream not accepted')
    except Exception:
        # Transport errors can contain credentials. An ambiguous call is never retried.
        raise AlphaError('The preceding accepted cron invocation could not be confirmed.', 503,
                         code='telegram_live_cron_uncertain') from None
    return {'state': 'delegated', 'upstreamHttpStatus': 200, 'retried': False}
