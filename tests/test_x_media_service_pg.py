"""Real PostgreSQL + X service/worker/receipt chain; all provider and identity data synthetic."""
import json
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError
from postriff_phase2.x_direct_service import XDirectService
from postriff_phase2.x_direct_cost import XCostController, PRICES
from postriff_phase2 import x_direct_media as media
from test_x_direct_service_pg import DirectServicePostgres, Wire
from test_x_direct_cost import policy
from test_x_media_workflow import Storage, image, video, QUOTES


class MediaWire(Wire):
    def __init__(self):
        super().__init__(); self.media = {}; self.corrupt_attachment = False; self.lose_upload_response = False
    def __call__(self, method, url, **kwargs):
        path = urlsplit(url).path
        if path.startswith('/2/media/'):
            self.calls.append({'method': method, 'path': path, 'bytes': len(kwargs.get('data') or b''), 'body': kwargs.get('body')})
            if self.lose_upload_response: raise TimeoutError('synthetic response lost after upload')
            if method == 'POST' and path in ('/2/media/upload', '/2/media/upload/initialize'):
                rid = str(1880028106020515840 + len(self.media))
                data = {'id': rid, 'media_key': '3_' + rid, 'expires_after_secs': 3600}
                self.media[rid] = dict(data)
                return {'status': 200, 'body': {'data': data}}
            if path.endswith('/append'):
                return {'status': 200, 'body': {'data': {'expires_at': int(time.time() + 3600)}}}
            if path.endswith('/finalize'):
                data = {**self.media[path.split('/')[-2]], 'processing_info': {'state': 'succeeded'}}
                return {'status': 200, 'body': {'data': data}}
            if path == '/2/media/metadata':
                body = kwargs['body']
                return {'status': 200, 'body': {'data': {'id': body['id'], 'associated_metadata': body['metadata']}}}
            raise AssertionError('Unexpected synthetic media request: ' + method + ' ' + path)
        response = super().__call__(method, url, **kwargs)
        if method == 'GET' and path.startswith('/2/tweets/'):
            post = self.posts.get(path.rsplit('/', 1)[-1]) or {}
            ids = (post.get('media') or {}).get('media_ids')
            if ids:
                keys = [self.media[rid]['media_key'] for rid in ids]
                response['body']['data']['attachments'] = {'media_keys': ['3_999'] if self.corrupt_attachment else keys}
        return response


class DirectMediaPostgres(DirectServicePostgres):
    def setUp(self):
        super().setUp()
        self.wire = MediaWire(); self.provider.transport = self.wire
        self.storage = Storage(); self.service.assets = SimpleNamespace(storage=self.storage)
        self.cost = XCostController(self.repo.connection_factory,
            policy(app_budget_micros=10_000_000, workspace_budget_micros=10_000_000,
                   app_request_limit=1000, workspace_request_limit=1000,
                   allowed_price_keys=frozenset(PRICES) | media.MEDIA_PRICE_KEYS,
                   media_prices=tuple(sorted(QUOTES.items()))), 'synthetic-media-' + uuid.uuid4().hex)
        self.cost.activate('synthetic:media-only-fixture')
        self.engine = XDirectService(self.service, self.cost)
        with self.repo.connection_factory() as db:
            db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s",
                       (json.dumps({'phase2': {'assets': [image(), video()]}}), self.ws))
    def media_preview(self, asset=None, alt=''):
        return self.preview({'asset_id': (asset or image())['id'], 'alt_text': alt}, operation='media.upload')
    def upload_image(self, alt=''):
        item = self.media_preview(alt=alt); self.approve(item)
        for _ in range(2 if alt else 1): self.engine.dispatch_one()
        stored = self.row(item)
        self.assertEqual(stored['state'], 'verified', stored.get('reason'))
        return item, stored['progress']['media']['id']

    def test_media_approval_upload_then_post_exact_attachment_readback(self):
        item = self.media_preview(alt='Printed score')
        self.assertEqual(self.wire.calls, []); self.approve(item)
        self.assertEqual(self.engine.dispatch_one()['state'], 'queued')
        self.assertEqual(self.engine.dispatch_one()['state'], 'verified')
        upload = self.row(item); self.assertEqual(len(upload['receipts']), 2)
        rid = upload['progress']['media']['id']
        post = self.preview({'text': 'Approved media post', 'media': {'media_ids': [rid]}})
        self.approve(post)
        self.assertEqual(self.engine.dispatch_one()['state'], 'accepted')
        self.assertEqual(self.engine.dispatch_one()['state'], 'verified')
        stored = self.row(post)
        self.assertEqual(stored['receipts'][-1]['mediaKeys'], [self.wire.media[rid]['media_key']])
        self.assertNotIn('synthetic-access', json.dumps(upload['receipts']))

    def test_unconfirmed_upload_and_foreign_asset_do_not_send(self):
        item = self.media_preview()
        with self.assertRaises(AlphaError):
            self.engine.approve(self.ws, self.session, self.conn, item['id'], {'digest': item['digest'], 'confirmed': False})
        with self.assertRaises(AlphaError): self.media_preview({'id': 'f' * 32})
        self.assertEqual(self.wire.calls, [])

    def test_source_deletion_after_approval_blocks_upload(self):
        item = self.media_preview(); self.approve(item)
        with self.repo.connection_factory() as db:
            db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,assets,0,deleted}','true') WHERE id=%s", (self.ws,))
        self.engine.dispatch_one()
        self.assertEqual(self.row(item)['state'], 'held'); self.assertEqual(self.wire.calls, [])

    def test_video_steps_survive_worker_restart_and_cancel_retains_receipts(self):
        item = self.media_preview(video()); self.approve(item)
        self.assertEqual(self.engine.dispatch_one()['state'], 'queued')  # initialize
        self.engine = XDirectService(self.service, self.cost)
        self.assertEqual(self.engine.dispatch_one()['state'], 'queued')  # first chunk
        self.engine.cancel(self.ws, self.session, self.conn, item['id'])
        self.assertFalse(self.engine.dispatch_one()['selected'])
        stored = self.row(item)
        self.assertEqual(stored['state'], 'canceled'); self.assertEqual(len(stored['receipts']), 2)
        self.assertEqual(len(self.wire.calls), 2)

    def test_video_completes_through_official_chunk_paths(self):
        item = self.media_preview(video()); self.approve(item)
        for state in ('queued', 'queued', 'queued', 'verified'):
            self.assertEqual(self.engine.dispatch_one()['state'], state)
        self.assertEqual([c['path'].rsplit('/', 1)[-1] for c in self.wire.calls], ['initialize', 'append', 'append', 'finalize'])
        self.assertEqual(len(self.row(item)['receipts']), 4)

    def test_unknown_upload_never_retries(self):
        item = self.media_preview(); self.approve(item); self.wire.lose_upload_response = True
        self.assertEqual(self.engine.dispatch_one()['state'], 'uncertain')
        for _ in range(3): self.assertFalse(self.engine.dispatch_one()['selected'])
        self.assertEqual(len(self.wire.calls), 1)

    def test_unowned_or_expired_media_and_late_schedule_rejected(self):
        item, rid = self.upload_image()
        with self.assertRaises(AlphaError): self.preview({'text': 'No', 'media': {'media_ids': ['999']}})
        with self.assertRaises(AlphaError): self.preview({'text': 'Too late', 'media': {'media_ids': [rid]}}, scheduleAt=time.time() + 7200)
        with self.repo.connection_factory() as db:
            db.execute("UPDATE public.pr_x_direct_operations SET progress=jsonb_set(progress,'{media,expiresAt}','0') WHERE workspace_id=%s AND id=%s", (self.ws, item['id']))
        with self.assertRaises(AlphaError): self.preview({'text': 'Expired', 'media': {'media_ids': [rid]}})
        self.assertEqual(len(self.wire.calls), 1)

    def test_wrong_attachment_receipt_is_uncertain_not_republished(self):
        _, rid = self.upload_image()
        post = self.preview({'text': 'Approved', 'media': {'media_ids': [rid]}}); self.approve(post)
        self.assertEqual(self.engine.dispatch_one()['state'], 'accepted')
        self.wire.corrupt_attachment = True
        self.assertEqual(self.engine.dispatch_one()['state'], 'uncertain')
        self.assertFalse(self.engine.dispatch_one()['selected'])
        self.assertEqual(sum(c['path'] == '/2/tweets' for c in self.wire.calls), 1)

    def test_pricing_change_never_reuses_upload_approval(self):
        item = self.media_preview(); self.approve(item)
        changed = {**QUOTES, 'media_upload': QUOTES['media_upload'] + 1}
        self.cost.policy = replace(self.cost.policy, media_prices=tuple(sorted(changed.items())))
        self.engine.dispatch_one()
        self.assertIn(self.row(item)['state'], ('held', 'queued'))
        self.assertEqual(self.wire.calls, [])

    def test_overview_lists_only_this_workspaces_safe_assets_and_ready_uploads(self):
        view = self.engine.overview(self.ws, self.session, self.conn)
        self.assertEqual({a['id'] for a in view['mediaAssets']}, {image()['id'], video()['id']})
        self.assertFalse(any('objectName' in a or 'storagePath' in a for a in view['mediaAssets']))
        self.assertEqual(view['uploadedMedia'], [])
        _, rid = self.upload_image()
        view = self.engine.overview(self.ws, self.session, self.conn)
        self.assertEqual([m['id'] for m in view['uploadedMedia']], [rid])
        self.assertEqual(view['uploadedMedia'][0]['mime'], 'image/jpeg')

    def test_provider_identifier_migration_adds_x_without_allowing_other_single_letters(self):
        from pathlib import Path
        with self.repo.connection_factory() as db:
            db.execute("CREATE TABLE IF NOT EXISTS public.pr_oauth_transactions(provider text NOT NULL CONSTRAINT pr_oauth_transactions_provider_check CHECK(length(provider) BETWEEN 2 AND 40))")
        with self.repo.connection_factory() as db:
            db.execute(Path('migrations/postriff/135_x_oauth_provider_identifier.sql').read_text())
        for value in ('x', 'linkedin', 'threads'):
            with self.repo.connection_factory() as db:
                db.execute('INSERT INTO public.pr_oauth_transactions(provider) VALUES(%s)', (value,))
        for value in ('', 'y', 'z' * 41):
            with self.repo.connection_factory() as db:
                with self.assertRaises(self.psycopg.errors.CheckViolation):
                    db.execute('INSERT INTO public.pr_oauth_transactions(provider) VALUES(%s)', (value,))

    def test_media_tco_suffix_requires_exact_own_post_and_media_key(self):
        import copy
        from postriff_phase2.x_direct_executor import reconcile_post
        _, rid = self.upload_image()
        post = self.preview({'text': 'Approved score', 'media': {'media_ids': [rid]}}); self.approve(post)
        self.assertEqual(self.engine.dispatch_one()['state'], 'accepted')
        stored = self.row(post); receipt = stored['receipts'][0]; post_id = receipt['resourceId']
        short = 'https://t.co/scoreLink'
        text = 'Approved score ' + short
        data = {'id': post_id, 'author_id': '123', 'text': text,
                'attachments': {'media_keys': [self.wire.media[rid]['media_key']]},
                'entities': {'urls': [{'start': 15, 'end': len(text), 'url': short,
                    'expanded_url': 'https://x.com/synthetic/status/' + post_id + '/photo/1',
                    'media_key': self.wire.media[rid]['media_key']}]}}
        with self.repo.connection_factory() as db, db.cursor() as cur:
            credential = self.engine._credential(cur, self.ws, self.conn)
            saved = {k: v for k, v in stored['request'].items() if k not in __import__('postriff_phase2.x_direct_service', fromlist=['REQUEST_EVIDENCE_FIELDS']).REQUEST_EVIDENCE_FIELDS}
            request = self.engine._normalize(self.ws, self.conn, credential, saved, cur)
        grant = {**self.oauth.token_for_worker(self.ws, self.conn), 'workspaceId': self.ws,
                 'connectionId': self.conn, 'verifiedMedia': credential['mediaAccess']}
        for wrong in (False, True):
            response = copy.deepcopy(data)
            if wrong: response['entities']['urls'][0]['media_key'] = '3_999'
            self.wire.answers = [{'status': 200, 'body': {'data': response}}]
            with self.engine.request_context(self.ws, self.conn, 'posts.create'):
                result = reconcile_post(request, self.provider, grant, receipt, now=time.time())
            self.assertEqual(result['state'], 'uncertain' if wrong else 'verified')

    def test_expired_upload_after_post_acceptance_does_not_block_receipt_readback(self):
        item, rid = self.upload_image()
        post = self.preview({'text': 'Already accepted', 'media': {'media_ids': [rid]}}); self.approve(post)
        self.assertEqual(self.engine.dispatch_one()['state'], 'accepted')
        with self.repo.connection_factory() as db:
            db.execute("UPDATE public.pr_x_direct_operations SET progress=jsonb_set(progress,'{media,expiresAt}','0') WHERE workspace_id=%s AND id=%s", (self.ws, item['id']))
            db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,assets,0,deleted}','true') WHERE id=%s", (self.ws,))
        self.assertEqual(self.engine.dispatch_one()['state'], 'verified')
        self.assertEqual(sum(c['path'] == '/2/tweets' for c in self.wire.calls), 1)
