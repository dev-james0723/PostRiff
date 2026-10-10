"""Native, metadata-only Library changes. One workspace transaction owns preview/apply/inverse.

Receipts contain titles, tags and collection identities, never file bytes, extracted text,
signed URLs or model inputs. Task Engine adapters can reuse the cursor methods below;
the durable inverse lives here, not in a second task-specific implementation.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from postriff_alpha.domain import AlphaError

MAX_ASSETS = 20
PREVIEW_SECONDS = 900
UNDO_SECONDS = 86400
MAX_PREVIEW_BYTES = 65536
MAX_RECEIPT_BYTES = 262144


def validate_metadata(body):
    from .library_assets import ASSET_ID, _tags
    if not isinstance(body, dict) or not body or not set(body) <= {'title', 'tags', 'collections'}:
        raise AlphaError('Choose a title, tags or collections to update.')
    result = {}
    if 'title' in body:
        title = body['title']
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160 or '\x00' in title:
            raise AlphaError('Use a title from 1 to 160 characters.')
        result['title'] = title.strip()
    if 'tags' in body:
        result['tags'] = _tags(body['tags'])
    if 'collections' in body:
        values = body['collections']
        if not isinstance(values, list) or len(values) > 30 or any(not isinstance(c, str) or not ASSET_ID.fullmatch(c.replace('-', '')) for c in values):
            raise AlphaError('Choose valid collections.')
        result['collections'] = sorted(set(c.replace('-', '') for c in values))
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class LibraryMetadataChanges:
    def __init__(self, library):
        self.library = library
        self.service = library.service

    def _ready(self, cur):
        cur.execute("SELECT to_regclass('public.pr_library_metadata_changes'),to_regclass('public.pr_library_metadata_versions')")
        if not all(cur.fetchone()):
            raise AlphaError('Library change previews are not available yet.', 503, code='library_metadata_unavailable')

    def _context(self, cur, w, principal):
        from .hosted import MEMBER_COLUMNS
        # Re-read and lock live membership even for a Task Engine caller that already owns
        # the workspace lock. A revoked role cannot use a prepared or replayed receipt.
        cur.execute(f"SELECT w.revision,w.state,{MEMBER_COLUMNS} FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w FOR SHARE OF m,p", (w, principal))
        row = cur.fetchone()
        if not row:
            raise AlphaError('Workspace unavailable.', 403)
        self.library._edit(row)
        state = self.service.ideas._state(row)
        if state.get('accountDeletion') or state.get('accountBlock'):
            raise AlphaError('Workspace changes are unavailable.', 409)
        return row

    def _collections(self, cur, w, ids):
        cur.execute('SELECT replace(id::text,\'-\',\'\'),name FROM public.pr_library_collections WHERE workspace_id=%s AND id=ANY(%s::uuid[]) ORDER BY id FOR SHARE', (w, ids))
        values = [{'id': i, 'name': name} for i, name in cur.fetchall()]
        if len(values) != len(ids):
            raise AlphaError('Collection unavailable. Create a fresh preview.', 409, code='library_metadata_conflict')
        return values

    def _snapshot(self, cur, row, w, ident):
        self.library._exists(cur, row, w, ident)
        # Deliberately select individual metadata columns, never to_jsonb(asset), chunks or storage.
        cur.execute('SELECT display_title,title_source,tags,kind FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s FOR UPDATE', (w, ident))
        normalized = cur.fetchone()
        cur.execute('SELECT display_title,tags FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=%s FOR UPDATE', (w, ident))
        label = cur.fetchone()
        cur.execute("SELECT replace(collection_id::text,'-','') FROM public.pr_library_collection_items WHERE workspace_id=%s AND asset_key=%s ORDER BY collection_id", (w, ident))
        collections = self._collections(cur, w, [r[0] for r in cur.fetchall()])
        cur.execute('SELECT revision FROM public.pr_library_metadata_versions WHERE workspace_id=%s AND asset_key=%s', (w, ident))
        version = cur.fetchone()
        legacy = None if normalized else next(a for a in self.service.ideas._state(row).get('phase2', {}).get('assets', []) if a.get('id') == ident)
        original = {'title': normalized[0], 'titleSource': normalized[1], 'tags': normalized[2]} if normalized else None
        label_value = {'title': label[0], 'tags': label[1]} if label else None
        title = (normalized[0] if normalized else legacy.get('displayTitle') or legacy.get('originalFilename') or '')
        tags = (normalized[2] if normalized else legacy.get('tags', legacy.get('aiTags', []))) or []
        fields = {'title': label[0] or title if label else title, 'tags': label[1] if label else tags, 'collections': collections}
        private = {'label': label_value, 'normalized': original, 'revision': version[0] if version else 0,
                   'legacyRevision': row[0] if legacy is not None else None}
        return {'assetId': ident, 'kind': normalized[3] if normalized else ('video' if str(legacy.get('mime', '')).startswith('video/') else 'image'),
                'fields': fields, 'version': digest({'fields': fields, **private}), '_stored': private}

    def _receipt(self, cur, w, principal, ident):
        from .library_assets import ASSET_ID
        if not isinstance(ident, str) or not ASSET_ID.fullmatch(ident):
            raise AlphaError('Library change unavailable.', 404)
        cur.execute('SELECT status,payload,extract(epoch from expires_at),extract(epoch from undo_expires_at) FROM public.pr_library_metadata_changes WHERE workspace_id=%s AND actor_id=%s AND id=%s FOR UPDATE', (w, principal, ident))
        found = cur.fetchone()
        if not found:
            raise AlphaError('Library change unavailable.', 404)
        return found[0], found[1], float(found[2]), float(found[3]) if found[3] is not None else None

    def _current(self, cur, row, w, entries):
        return [self._snapshot(cur, row, w, e['assetId']) for e in entries]

    def _view(self, ident, status, payload, expires, undo_expires, can_undo=False, reason=None):
        resources = [{'kind': 'library_asset', 'id': e['assetId']} for e in payload['entries']]
        groups = {c['id'] for e in payload['entries'] if 'collections' in e['changes'] for c in e['before']['fields']['collections'] + e['proposed']['collections']}
        resources += [{'kind': 'library_collection', 'id': ident} for ident in sorted(groups)]
        return {'receiptId': ident, 'status': status, 'expiresAt': expires, 'undoExpiresAt': undo_expires,
                'verified': status in ('applied', 'undone'),
                'postDigest': digest(payload['after']) if 'after' in payload else None,
                'checks': [{'name': 'library_metadata_' + ('restored' if status == 'undone' else 'revision_matches'), 'ok': True}] if status in ('applied', 'undone') else [],
                'changedRefs': [{'type': 'library_asset', 'id': e['assetId'], 'change': 'metadata_restored' if status == 'undone' else 'metadata_updated'} for e in payload['entries']] if status in ('applied', 'undone') else [],
                'canUndo': can_undo, 'undoReason': reason, 'affectedResources': resources,
                'entries': [{'assetId': e['assetId'], 'kind': e['before']['kind'], 'current': e['before']['fields'], 'proposed': e['proposed'],
                             'changedFields': list(e['changes'])} for e in payload['entries']]}

    def history(self, w, token):
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            self._ready(cur)
            self._context(cur, w, principal)
            cur.execute("SELECT replace(id::text,'-',''),status,extract(epoch from created_at),jsonb_array_length(payload->'entries'),payload->'entries'->0->'before'->'fields'->>'title' FROM public.pr_library_metadata_changes WHERE workspace_id=%s AND actor_id=%s AND status IN ('applied','undone') ORDER BY applied_at DESC,id DESC LIMIT 10", (w, principal))
            return {'changes': [{'receiptId': i, 'status': status, 'createdAt': float(at), 'assetCount': count, 'firstTitle': title} for i, status, at, count, title in cur.fetchall()]}

    def read(self, w, token, ident):
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            self._ready(cur)
            row = self._context(cur, w, principal)
            status, payload, expires, undo_expires = self._receipt(cur, w, principal, ident)
            return self._result(cur, row, w, ident, status, payload, expires, undo_expires)

    def preview(self, w, token, body):
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            return self.preview_in(cur, w, principal, body)

    def preview_in(self, cur, w, principal, body):
        from .library_assets import ASSET_ID
        from .hosted import throttle
        self._ready(cur)
        row = self._context(cur, w, principal)
        if not isinstance(body, dict) or set(body) != {'changes'} or not isinstance(body['changes'], list) or not 1 <= len(body['changes']) <= MAX_ASSETS:
            raise AlphaError(f'Select from 1 to {MAX_ASSETS} assets to preview.')
        parsed = []
        for item in body['changes']:
            if not isinstance(item, dict) or set(item) != {'assetId', 'changes'} or not isinstance(item['assetId'], str) or not ASSET_ID.fullmatch(item['assetId']):
                raise AlphaError('Choose valid Library assets.')
            parsed.append((item['assetId'], validate_metadata(item['changes'])))
        if len(set(i for i, _ in parsed)) != len(parsed):
            raise AlphaError('Select each asset only once.')
        throttle(cur, f'library-metadata-preview:{w}:{principal}', 60, 3600)
        cur.execute("DELETE FROM public.pr_library_metadata_changes WHERE workspace_id=%s AND actor_id=%s AND status='prepared' AND expires_at<=to_timestamp(%s)", (w, principal, self.service.repository.clock()))
        cur.execute("SELECT count(*) FROM public.pr_library_metadata_changes WHERE workspace_id=%s AND actor_id=%s AND status='prepared'", (w, principal))
        if cur.fetchone()[0] >= 20:
            raise AlphaError('Finish a prepared Library change or wait for its preview to expire.', 429)
        entries = []
        for ident, requested in parsed:
            before = self._snapshot(cur, row, w, ident)
            proposed = {**before['fields'], **requested}
            if 'collections' in requested:
                proposed['collections'] = self._collections(cur, w, requested['collections'])
            # Store only actual differences, so Undo never claims or rewrites an untouched field.
            changes = {k: v for k, v in requested.items() if proposed[k] != before['fields'][k]}
            if changes:
                entries.append({'assetId': ident, 'before': before, 'proposed': proposed, 'changes': changes})
        if not entries:
            raise AlphaError('These details already match the Library.', 409, code='library_metadata_unchanged')
        ident = uuid.uuid4().hex
        payload = {'version': 1, 'entries': entries}
        if len(json.dumps(payload).encode()) > MAX_PREVIEW_BYTES:
            raise AlphaError('This preview has too much metadata. Select fewer assets.', 413)
        # Whole-second deadlines round-trip through PostgreSQL without accepting an expired receipt.
        expires = int(self.service.repository.clock()) + PREVIEW_SECONDS
        cur.execute("INSERT INTO public.pr_library_metadata_changes(id,workspace_id,actor_id,payload,expires_at) VALUES(%s,%s,%s,%s::jsonb,to_timestamp(%s))", (ident, w, principal, json.dumps(payload), expires))
        return self._view(ident, 'prepared', payload, expires, None)

    def apply(self, w, token, body):
        ident = self._request_id(body)
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            return self.apply_in(cur, w, principal, ident)

    @staticmethod
    def _request_id(body):
        if not isinstance(body, dict) or set(body) != {'receiptId'}:
            raise AlphaError('Choose a prepared Library change.')
        return body['receiptId']

    def apply_in(self, cur, w, principal, ident):
        from .hosted import audit
        self._ready(cur)
        row = self._context(cur, w, principal)
        status, payload, expires, undo_expires = self._receipt(cur, w, principal, ident)
        if status != 'prepared':
            return self._result(cur, row, w, ident, status, payload, expires, undo_expires)
        if self.service.repository.clock() >= expires:
            raise AlphaError('This preview expired. Create a fresh preview.', 409, code='library_metadata_expired')
        current = self._current(cur, row, w, payload['entries'])
        for entry, fresh in zip(payload['entries'], current):
            if fresh['version'] != entry['before']['version']:
                raise AlphaError('Library details changed. Create a fresh preview.', 409, code='library_metadata_conflict')
            if 'collections' in entry['changes'] and self._collections(cur, w, entry['changes']['collections']) != entry['proposed']['collections']:
                raise AlphaError('A collection changed. Create a fresh preview.', 409, code='library_metadata_conflict')
        for entry in payload['entries']:
            # Preserve inherited tags when adding the first label row (including collection-only edits).
            cur.execute('INSERT INTO public.pr_library_labels(workspace_id,asset_key,tags) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (w, entry['assetId'], entry['before']['fields']['tags']))
            self.library._write_metadata(cur, w, entry['assetId'], entry['changes'])
        after = self._current(cur, row, w, payload['entries'])
        if any(snapshot['fields'] != entry['proposed'] for snapshot, entry in zip(after, payload['entries'])):
            raise AlphaError('Library changes could not be verified.', 409, code='library_metadata_conflict')
        payload['after'] = after
        if len(json.dumps(payload).encode()) > MAX_RECEIPT_BYTES:
            raise AlphaError('This change has too much metadata. Select fewer assets.', 413)
        undo_expires = int(self.service.repository.clock()) + UNDO_SECONDS
        cur.execute("UPDATE public.pr_library_metadata_changes SET status='applied',payload=%s::jsonb,applied_at=now(),undo_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND id=%s", (json.dumps(payload), undo_expires, w, ident))
        audit(cur, w, principal, 'library.metadata_applied', ident, {'assetIds': [e['assetId'] for e in payload['entries']]})
        return self._view(ident, 'applied', payload, expires, undo_expires, True)

    def _result(self, cur, row, w, ident, status, payload, expires, undo_expires):
        reason = None
        if status == 'applied':
            if self.service.repository.clock() >= undo_expires:
                reason = 'The Undo window has expired.'
            else:
                try:
                    current = self._current(cur, row, w, payload['entries'])
                    if digest(current) != digest(payload['after']):
                        reason = 'Library details changed after Apply.'
                    # A collection removed after Apply must not be silently recreated by Undo.
                    for entry in payload['entries']:
                        self._collections(cur, w, [c['id'] for c in entry['before']['fields']['collections']])
                except AlphaError:
                    reason = 'An affected asset or collection is unavailable.'
        return self._view(ident, status, payload, expires, undo_expires, status == 'applied' and reason is None, reason)

    def current_digest(self, cur, w, ident):
        """Task Engine's content-free CAS witness; its caller already authorized the task."""
        cur.execute('SELECT actor_id::text,payload FROM public.pr_library_metadata_changes WHERE workspace_id=%s AND id=%s', (w, ident))
        found = cur.fetchone()
        if not found:
            raise AlphaError('Library change unavailable.', 404)
        row = self._context(cur, w, found[0])
        return digest(self._current(cur, row, w, found[1]['entries']))

    def undo(self, w, token, body):
        ident = self._request_id(body)
        with self.service.repository.transaction(token, w) as (cur, _, principal):
            return self.undo_in(cur, w, principal, ident)

    def undo_in(self, cur, w, principal, ident, expectedDigest=None, effectKey=None):
        """The single conditional inverse; effectKey is an optional Task Engine idempotency witness."""
        from .hosted import audit
        self._ready(cur)
        row = self._context(cur, w, principal)
        status, payload, expires, undo_expires = self._receipt(cur, w, principal, ident)
        if status == 'undone':
            if effectKey is not None and payload.get('undoEffectKey') != effectKey:
                raise AlphaError('This change was already undone.', 409)
            return self._view(ident, status, payload, expires, undo_expires)
        if status != 'applied':
            raise AlphaError('Apply this change before using Undo.', 409)
        view = self._result(cur, row, w, ident, status, payload, expires, undo_expires)
        if not view['canUndo']:
            raise AlphaError(view['undoReason'], 409, code='library_metadata_undo_conflict')
        if expectedDigest is not None and expectedDigest != digest(payload['after']):
            raise AlphaError('Library details changed after Apply.', 409, code='library_metadata_undo_conflict')
        for entry in payload['entries']:
            before, asset_id = entry['before'], entry['assetId']
            stored = before['_stored']
            if 'collections' in entry['changes']:
                self.library._write_metadata(cur, w, asset_id, {'collections': [c['id'] for c in before['fields']['collections']]})
            if stored['label'] is None:
                cur.execute('DELETE FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=%s', (w, asset_id))
            else:
                cur.execute('UPDATE public.pr_library_labels SET display_title=%s,tags=%s,updated_at=now() WHERE workspace_id=%s AND asset_key=%s', (stored['label']['title'], stored['label']['tags'], w, asset_id))
            if stored['normalized'] is not None:
                original = stored['normalized']
                cur.execute('UPDATE public.pr_library_assets SET display_title=%s,title_source=%s,tags=%s,updated_at=now() WHERE workspace_id=%s AND id=%s', (original['title'], original['titleSource'], original['tags'], w, asset_id))
        restored = self._current(cur, row, w, payload['entries'])
        if any(now['fields'] != entry['before']['fields'] for now, entry in zip(restored, payload['entries'])):
            raise AlphaError('The original Library details could not be restored.', 409, code='library_metadata_undo_conflict')
        payload['undoEffectKey'] = effectKey
        cur.execute("UPDATE public.pr_library_metadata_changes SET status='undone',payload=%s::jsonb,undone_at=now() WHERE workspace_id=%s AND id=%s", (json.dumps(payload), w, ident))
        audit(cur, w, principal, 'library.metadata_undone', ident, {'assetIds': [e['assetId'] for e in payload['entries']]})
        return self._view(ident, 'undone', payload, expires, undo_expires)
