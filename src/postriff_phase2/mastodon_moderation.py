"""Bounded native account-level reports and v2 filters; no administrator API."""
from postriff_alpha.domain import AlphaError
from .mastodon_protocol import ID, version_at_least

ACTIONS = frozenset(('report_account', 'filter_create', 'filter_update', 'filter_delete'))
CONTEXTS = ('home', 'notifications', 'public', 'thread', 'account')


def identifiers(value, limit=20):
    if (not isinstance(value, list) or len(value) > limit
            or any(not isinstance(v, str) or not ID.fullmatch(v) for v in value)
            or len(set(value)) != len(value)):
        raise AlphaError('Choose distinct instance-local numeric IDs, up to20.', 400)
    return value


def report_rules(rows, requested):
    """Bind a violation report to this instance's exact current rule IDs and text."""
    identifiers(requested)
    if not isinstance(rows, list) or len(rows) > 256:
        raise AlphaError('The server returned invalid or oversized instance rules.', 502)
    selected = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('id') not in requested:
            continue
        identifier, text = row['id'], row.get('text')
        if identifier in selected or not isinstance(text, str) or not 1 <= len(text.strip()) <= 4096:
            raise AlphaError('The server returned ambiguous instance rules. Read its current rules again.', 502)
        selected[identifier] = {'id': identifier, 'text': text}
    if set(selected) != set(requested):
        raise AlphaError('A selected instance rule is no longer available. Review the current rules.', 409)
    return [selected[identifier] for identifier in requested]


def spec(action, payload, capabilities):
    target = payload.get('targetId')
    if action != 'filter_create' and (not isinstance(target, str) or not ID.fullmatch(target)):
        raise AlphaError('Choose an instance-local account or filter ID.', 400)
    version = capabilities.get('version')
    if action == 'report_account':
        if not version_at_least(version, (2, 3, 0)):
            raise AlphaError('This report integration requires Mastodon2.3 or later.', 409)
        comment, forward = payload.get('reportComment', ''), payload.get('reportForward', False)
        statuses = identifiers(payload.get('reportStatusIds', []))
        rules = identifiers(payload.get('reportRuleIds', []))
        category = payload.get('reportCategory', 'violation' if rules else 'other')
        if not isinstance(comment, str) or len(comment) > 1000 or type(forward) is not bool:
            raise AlphaError('Use a report reason up to1000 characters and an explicit forwarding choice.', 400)
        if category not in ('other', 'spam', 'violation', 'legal'):
            raise AlphaError('Choose Other, Spam, Rule violation or Illegal content.', 400)
        if (category == 'violation') != bool(rules):
            raise AlphaError('Choose exact instance rule IDs for a Rule violation report only.', 400)
        if category == 'other' and not comment.strip() and not statuses:
            raise AlphaError('Give the report a reason or exact supporting status IDs.', 400)
        if category != 'other' and not version_at_least(version, (3, 5, 0)):
            raise AlphaError('Report categories require Mastodon3.5 or later.', 409)
        if category == 'legal' and not version_at_least(version, (4, 2, 0)):
            raise AlphaError('Illegal-content reports require Mastodon4.2 or later.', 409)
        body = {'account_id': target, 'status_ids': statuses, 'comment': comment, 'forward': forward}
        if version_at_least(version, (3, 5, 0)):
            body['category'] = category
        if rules:
            body['rule_ids'] = rules
        return 'POST', '/api/v1/reports', body, ('write:reports',) + (('read:statuses',) if statuses else ()), 'moderate'
    if not version_at_least(version, (4, 0, 0)):
        raise AlphaError('Server-side V2 filters require Mastodon4.0 or later.', 409)
    path = '/api/v2/filters' + ('' if action == 'filter_create' else '/' + target)
    if action == 'filter_delete':
        return 'DELETE', path, {}, ('read:filters', 'write:filters'), 'moderate'
    value = payload.get('filter')
    if not isinstance(value, dict) or set(value) - {'title', 'context', 'filter_action', 'expires_in', 'keywords_attributes'}:
        raise AlphaError('Choose the supported filter settings only.', 400)
    required = ('title', 'context') if action == 'filter_create' else ()
    if any(k not in value for k in required) or not value:
        raise AlphaError('Choose filter settings; new filters need a title and contexts.', 400)
    body = {}
    if 'title' in value:
        title = value['title']
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
            raise AlphaError('Use a filter title of1–100 characters.', 400)
        body['title'] = title.strip()
    if 'context' in value:
        contexts = value['context']
        if (not isinstance(contexts, list) or not 1 <= len(contexts) <= len(CONTEXTS)
                or any(not isinstance(c, str) or c not in CONTEXTS for c in contexts)
                or len(set(contexts)) != len(contexts)):
            raise AlphaError('Choose distinct supported filter contexts.', 400)
        body['context'] = sorted(contexts)
    if 'filter_action' in value or action == 'filter_create':
        policy = value.get('filter_action', 'warn')
        if policy not in ('warn', 'hide', 'blur') or policy == 'blur' and not version_at_least(version, (4, 4, 0)):
            raise AlphaError('Choose Warn/Hide; Blur requires Mastodon4.4 or later.', 400)
        body['filter_action'] = policy
    if 'expires_in' in value:
        seconds = value['expires_in']
        # Mastodon's Expireable setter uses JSON null to clear expires_at. Omitting
        # this field preserves an existing expiry, so never collapse the two cases.
        if seconds is not None and (type(seconds) is not int or not 60 <= seconds <= 31536000):
            raise AlphaError('Choose 60 seconds to one year, null for no expiry, or omit to keep the current expiry.', 400)
        body['expires_in'] = seconds
    if 'keywords_attributes' in value:
        keywords = value['keywords_attributes']
        if not isinstance(keywords, list) or not 1 <= len(keywords) <= 20:
            raise AlphaError('Choose1–20 keyword changes.', 400)
        body['keywords_attributes'] = []
        seen_ids = set()
        for item in keywords:
            allowed = {'keyword', 'whole_word'} | ({'id', '_destroy'} if action == 'filter_update' else set())
            if not isinstance(item, dict) or set(item) - allowed:
                raise AlphaError('Choose supported keyword changes only.', 400)
            change = {}
            if 'id' in item:
                identifiers([item['id']])
                if item['id'] in seen_ids:
                    raise AlphaError('Change each keyword ID only once per action.', 400)
                seen_ids.add(item['id'])
                change['id'] = item['id']
            if '_destroy' in item:
                if item['_destroy'] is not True or 'id' not in change or set(item) != {'id', '_destroy'}:
                    raise AlphaError('Remove a keyword by its exact ID only.', 400)
                change['_destroy'] = True
            else:
                keyword = item.get('keyword')
                if not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 100 or type(item.get('whole_word', False)) is not bool:
                    raise AlphaError('Use a keyword of1–100 characters and a boolean whole-word choice.', 400)
                change.update(keyword=keyword.strip(), whole_word=item.get('whole_word', False))
            body['keywords_attributes'].append(change)
    return ('POST' if action == 'filter_create' else 'PUT'), path, body, ('read:filters', 'write:filters'), 'moderate'
