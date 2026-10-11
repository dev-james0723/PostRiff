"""Exact approved thread parts, same durable Queue; never infer an uncertain child ID."""
import copy
import hashlib
import html
import re
from datetime import datetime

from postriff_alpha.domain import AlphaError
from .mastodon_protocol import discover, validate_status, ID
from .outcomes import valid_receipt_url
from .mastodon_status_text import matches_text


def parts(manifest):
    extra = manifest.get('payload', {}).get('threadParts', [])
    if (not isinstance(extra, list) or len(extra) > 9
            or any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in extra)
            or (extra and (manifest.get('platform') != 'Mastodon' or manifest.get('publishOptions', {}).get('scheduled_at')))):
        raise AlphaError('Choose up to nine additional Mastodon posts, each up to 500 characters, using Rafii-managed scheduling.', 400)
    return [manifest['payload']['text'], *extra]


def child_options(manifest, parent):
    options = {k: v for k, v in (manifest.get('publishOptions') or {}).items() if k not in ('poll', 'quoted_status_id', 'scheduled_at', 'in_reply_to_id')}
    return {**options, 'in_reply_to_id': parent}


def plain_content(value):
    value = re.sub(r'<br\s*/?>', '\n', str(value), flags=re.I)
    value = re.sub(r'</p>\s*<p(?:\s[^>]*)?>', '\n\n', value, flags=re.I)
    return html.unescape(re.sub('<[^>]+>', '', value)).strip()


def matches(value, manifest, refs, index, instance, attachments):
    options = manifest.get('publishOptions') or {}
    parent = options.get('in_reply_to_id') if index == 0 else refs[index - 1]
    media = [a['id'] for a in attachments] if index == 0 else []
    poll = options.get('poll') if index == 0 else None
    actual_poll = value.get('poll')
    if poll:
        if (not isinstance(actual_poll, dict) or actual_poll.get('multiple') is not poll.get('multiple', False)
                or not isinstance(actual_poll.get('options'), list)
                or any(not isinstance(o, dict) for o in actual_poll['options'])
                or [o.get('title') for o in actual_poll['options'] if isinstance(o, dict)] != poll['options']):
            return False
        try:
            created = datetime.fromisoformat(value['created_at'].replace('Z', '+00:00'))
            expires = datetime.fromisoformat(actual_poll['expires_at'].replace('Z', '+00:00'))
            # The API exposes an absolute expiry, not the submitted duration.
            # Allow five seconds of server timestamp rounding/processing skew.
            if not created.tzinfo or not expires.tzinfo or abs((expires - created).total_seconds() - poll['expires_in']) > 5:
                return False
        except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
            return False
    elif actual_poll:
        return False
    quoted_id = options.get('quoted_status_id') if index == 0 else None
    quote = value.get('quote')
    if quoted_id:
        if not isinstance(quote, dict) or quote.get('state') != 'accepted': return False
        nested = quote.get('quoted_status') if isinstance(quote.get('quoted_status'), dict) else {}
        if str(quote.get('quoted_status_id') or nested.get('id') or '') != quoted_id: return False
    elif quote:
        return False
    return (str(value.get('id')) == refs[index]
            and isinstance(value.get('account'), dict)
            and str(value['account'].get('id')) + '@' + instance == manifest['providerAccountId']
            and matches_text(value, parts(manifest)[index], instance, plain_content)
            and value.get('visibility') == options.get('visibility', 'public')
            and (value.get('spoiler_text') or '') == options.get('spoiler_text', '')
            and value.get('sensitive') is options.get('sensitive', False)
            and ('language' not in options or value.get('language') == options['language'])
            and str(value.get('in_reply_to_id') or '') == str(parent or '')
            and [str(a.get('id')) for a in value.get('media_attachments') or [] if isinstance(a, dict)] == media)


def advance(provider, grant, manifest, progress, save, result, now):
    """One child per worker turn; each intent/acceptance commits before continuing."""
    from .mastodon_publishing import backoff
    refs, texts = progress['threadReferences'], parts(manifest)
    if len(refs) >= len(texts):
        save('provider_accepted')
        return result('provider_accepted', 'All approved thread parts have saved IDs. Each part still needs account read-back.')
    if progress.get('retryAt', 0) > now():
        return result('processing', 'Waiting for the saved thread cooldown; no child was resent.')
    session = provider.session(grant['accessToken'])
    index = len(refs)
    capabilities = discover(provider.transport, session['instance'])
    body = validate_status(texts[index], child_options(manifest, refs[-1]), (), capabilities, now=now())
    # Recheck the accepted parent still belongs to the exact account before attaching a child.
    parent = provider.api(session, 'GET', '/api/v1/statuses/' + refs[-1])
    value = parent.get('body') if isinstance(parent.get('body'), dict) else {}
    if parent.get('status') in (429, 500, 502, 503, 504):
        count = progress.get('retryCount', 0)
        if count >= 20: return result('held', 'Parent lookup retries exhausted. Existing thread parts were retained.')
        progress.update(retryCount=count + 1, retryAt=backoff(parent, now(), count, manifest['idempotencyKey']))
        save('thread_wait')
        return result('processing', 'Parent lookup is waiting for the server cooldown. No child was sent.')
    if parent.get('status') != 200 or not matches(value, manifest, refs, index - 1, session['instance'], progress['attachments']):
        return result('held', 'The accepted thread parent could not be verified. Existing posts were retained; no child was sent.')
    save('thread_publish_attempted', external=True)
    response = provider.api(session, 'POST', '/api/v1/statuses', headers={'Idempotency-Key': hashlib.sha256((manifest['idempotencyKey'] + ':part:' + str(index)).encode()).hexdigest()}, body=body)
    value = response.get('body') if isinstance(response.get('body'), dict) else {}
    accepted = str(value.get('id', ''))
    if response.get('status') == 200 and ID.fullmatch(accepted) and accepted not in refs:
        refs.append(accepted); progress['retryCount'] = 0; progress.pop('retryAt', None)
        save('thread_wait' if len(refs) < len(texts) else 'provider_accepted')
        return result('processing' if len(refs) < len(texts) else 'provider_accepted', 'The approved child ID was saved. Earlier parts remain on Mastodon; publication verification is separate.')
    if response.get('status') == 429:
        count = progress.get('retryCount', 0)
        if count >= 20: return result('held', 'Thread cooldown checks exhausted. Existing parts were retained; review before continuing.')
        progress.update(retryCount=count + 1, retryAt=backoff(response, now(), count, manifest['idempotencyKey']))
        save('thread_wait')
        return result('processing', 'Mastodon refused this unsent child due to throttling. Existing IDs remain saved.')
    if response.get('status') in (400, 401, 403, 404, 422):
        return result('held', 'Mastodon refused this child. Already accepted parts remain; correct and review before continuing.')
    return result('uncertain', 'This child may have been published. Its committed intent blocks automatic resend; inspect the accepted thread.')


def reconcile(provider, grant, manifest, progress, checkpoint, now):
    """One bounded GET per turn, no writes; every known part must be read back."""
    from .mastodon_publishing import backoff
    refs, texts = progress.get('threadReferences', []), parts(manifest)
    reference = progress.get('reference')
    def result(state, message):
        return {'state': state, 'reference': reference, 'progress': copy.deepcopy(progress), 'confirmed': message}
    if progress['stage'] != 'provider_accepted' or len(refs) != len(texts):
        return result('uncertain', 'The thread has a partial or unknown child outcome. No further child will be automatically sent.')
    if progress.get('retryAt', 0) > now(): return result('processing', 'Waiting for the known thread lookup cooldown.')
    index = progress.get('threadVerified', 0)
    if index < len(refs):
        session = provider.session(grant['accessToken'])
        response = provider.api(session, 'GET', '/api/v1/statuses/' + refs[index])
        value = response.get('body') if isinstance(response.get('body'), dict) else {}
        if response.get('status') in (429, 500, 502, 503, 504):
            count = progress.get('retryCount', 0)
            if count >= 20: return result('held', 'Thread lookup retries exhausted. Inspect the saved IDs; nothing was resent.')
            progress.update(retryCount=count + 1, retryAt=backoff(response, now(), count, manifest['idempotencyKey']))
            checkpoint(copy.deepcopy(progress), before_external=False)
            return result('processing', 'Thread read-back is waiting for the server cooldown; no write was resent.')
        if response.get('status') != 200 or not matches(value, manifest, refs, index, session['instance'], progress['attachments']):
            return result('uncertain', 'A saved thread part no longer matches its approved account/content/parent/media. Nothing was resubmitted.')
        if index == 0 and valid_receipt_url(value.get('url'), 'Mastodon', manifest['providerAccountId']): progress['threadRootUrl'] = value['url']
        progress['threadVerified'] = index + 1; progress['retryCount'] = 0; progress.pop('retryAt', None)
        checkpoint(copy.deepcopy(progress), before_external=False)
    if progress.get('threadVerified') != len(refs):
        return result('processing', 'Verified one saved thread part; remaining parts await bounded account lookup.')
    receipt = result('verified', 'Every approved thread part was read back on the connected instance. Fediverse delivery is not guaranteed.')
    receipt['verification'] = 'provider_lookup'
    if progress.get('threadRootUrl'): receipt['url'] = progress['threadRootUrl']
    return receipt
