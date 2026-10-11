"""Account deletion must fence work before storage I/O and retain honest retry state."""
import json
import time
import uuid
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService


def connection():
    return psycopg.connect('host=127.0.0.1 port=55438 dbname=postgres')


def verify(token):
    return token


verify.auth_time = lambda token, principal: time.time()


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return
    raise AssertionError('accepted while account deletion was pending')


class Identity:
    def __init__(self):
        self.calls = []
    def delete_user(self, principal):
        self.calls.append(principal)
        return True


class Assets:
    def __init__(self):
        self.callback = lambda: None
        self.calls = []
    def remove(self, workspace_id, asset):
        self.calls.append(asset['objectName'])
        self.callback()


identity, assets = Identity(), Assets()
service = HostedWorkspaceService(connection, verify, identity=identity, assets=assets)
principal = str(uuid.uuid4())
with connection() as db:
    db.execute('INSERT INTO auth.users VALUES(%s)', (principal,))
snap = service.bootstrap(principal, 'studio')
wid = snap['workspaceId']
with connection() as db:
    state = db.execute('SELECT state FROM pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]
    state['phase2']['assets'] = [{'id':'asset-synthetic', 'objectName':'synthetic.jpg', 'deleted':False}]
    db.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state),wid))


def inspect_during_storage():
    # Another connection sees the committed fence, before the destructive external step finishes.
    with connection() as db:
        current = db.execute('SELECT state FROM pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]
        assert current.get('accountDeletion', {}).get('status') == 'pending', 'deletion I/O had no durable fence'
    denied(lambda: service.repository.command(wid, principal, snap['revision'], lambda state, actor: state), 409)


assets.callback = inspect_during_storage
result = service.delete_account(wid, principal, 'DELETE')
assert result['workspaceDeleted'] and result['identityDeleted']
assert identity.calls == [principal] and assets.calls == ['synthetic.jpg']
print('PASS deletion fence committed before storage; concurrent mutations denied; final identity result verified')

# Partial storage failure preserves a retryable owner-visible state; no background publishing starts.
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.account_deletion import reconcile_identity
from postriff_phase2.operational_signals import snapshot as signals

def new_account():
    person=str(uuid.uuid4())
    with connection() as db:db.execute('INSERT INTO auth.users VALUES(%s)',(person,))
    created=service.bootstrap(person,'studio')
    space=created['workspaceId']
    with connection() as db:
        current=db.execute('SELECT state FROM pr_workspaces WHERE id=%s',(space,)).fetchone()[0]
        current['phase2']['assets']=[{'id':'synthetic','objectName':'synthetic-retry.jpg'}]
        db.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(current),space))
    return person,space

person,space=new_account()
def storage_failure():raise OSError('synthetic storage unavailable')
assets.callback=storage_failure
denied(lambda:service.delete_account(space,person,'DELETE'),503)
assert service.get(space,person)['state']['accountDeletion']['status']=='pending'
assert PostgresWorker(connection).claim() is None and CampaignWorker(service)._claim() is None
assert signals(connection)['counts']['deletionPending']==1
assets.callback=lambda:None
assert service.delete_account(space,person,'DELETE')['deleted']

# A renewing paid subscription and outstanding unknown cost must not be silently orphaned.
from postriff_phase2.billing import Ledger
from consumer_fixtures import approve_budgets
person,space=new_account();approve_budgets(connection,space)
with connection() as db:
    cur=db.cursor();reservation=Ledger().reserve(cur,space,person,'text_model',1,'unresolved-deletion-test',charge_batch=False)
    Ledger().settle(cur,space,reservation['reservationId'],'unknown')
denied(lambda:service.delete_account(space,person,'DELETE'),409)
with connection() as db:
    Ledger().settle(db.cursor(),space,reservation['reservationId'],'completed',1)
    db.execute("UPDATE pr_subscriptions SET provider='stripe',provider_subscription_id='synthetic-subscription',status='active' WHERE workspace_id=%s",(space,))
denied(lambda:service.delete_account(space,person,'DELETE'),409)
with connection() as db:db.execute('UPDATE pr_subscriptions SET cancel_at_period_end=true WHERE workspace_id=%s',(space,))

# Account deletion cannot strand a second owned workspace.
other_person,other_space=new_account()
with connection() as db:db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(other_space,person))
denied(lambda:service.delete_account(space,person,'DELETE'),409)
with connection() as db:db.execute('DELETE FROM pr_memberships WHERE workspace_id=%s AND user_id=%s',(other_space,person))

# Auth failure is a partial result, not success. Cron retries only the same persisted user, bounded.
now=[time.time()];service.clock=lambda:now[0]
class FailingIdentity:
    def __init__(self):self.calls=[]
    def delete_user(self,principal):
        self.calls.append(principal);raise OSError('synthetic identity unavailable')
failed=FailingIdentity();service.identity=failed
partial=service.delete_account(space,person,'DELETE')
assert not partial['deleted'] and partial['workspaceDeleted'] and not partial['identityDeleted']
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_workspaces WHERE id=%s',(space,)).fetchone()[0]==0
    assert db.execute('SELECT auth_deleted_at FROM pr_account_tombstones WHERE user_id=%s',(person,)).fetchone()[0] is None
assert reconcile_identity(service)['status']=='idle'
now[0]+=61
assert reconcile_identity(service)['status']=='identity_pending'
now[0]+=61
assert reconcile_identity(service)['status']=='identity_pending'
now[0]+=61
assert reconcile_identity(service)['status']=='idle' and failed.calls==[person]*3
# An operator can review and reopen this exact receipt; no new targets are inferred.
with connection() as db:db.execute("UPDATE pr_data_requests SET receipt=jsonb_set(receipt,'{identityAttempts}','2') WHERE id=%s",(partial['receiptId'],))
service.identity=identity
assert reconcile_identity(service)['status']=='completed' and identity.calls[-1]==person
assert reconcile_identity(service)['status']=='idle'
print('PASS storage retry, worker fences, unknown cost, subscription, other ownership, identity partial and bounded recovery')

# Chat-context S31: video storage goes with the account. One ready video (object, poster, frames), one pending and one
# aborted upload, a Library photo whose deletion never finished (`deletionPending`) and a stray object under the prefix:
# nothing is left, and the receipt says storage was deleted only after all of it.
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from test_video_uploads import FakeStorage  # noqa: E402


class VideoAssets:
    """The real kind-aware removal over the fake storage (video, poster and frames)."""
    def __init__(self, storage):
        self.storage = storage

    def remove(self, workspace_id, asset):
        PrivateAssetService.remove(self, workspace_id, asset)


storage = FakeStorage()
service.assets = VideoAssets(storage)
service.identity = identity
person, space = new_account()
video_id, pending_id, aborted_id = 'a' * 32, 'b' * 32, 'c' * 32
for name in (f'{video_id}.mp4', f'{pending_id}.mp4', 'poster.jpg', 'frame-1.jpg', 'gone.jpg', 'stray.mp4'):
    storage.put(name, b'x')
with connection() as db:
    current = db.execute('SELECT state FROM pr_workspaces WHERE id=%s', (space,)).fetchone()[0]
    current['phase2']['assets'] = [
        {'id': video_id, 'mime': 'video/mp4', 'objectName': f'{video_id}.mp4', 'processing': 'ready', 'deleted': False,
         'poster': {'objectName': 'poster.jpg'}, 'frames': [{'objectName': 'frame-1.jpg', 'at': 1.0}]},
        {'id': 'd' * 32, 'mime': 'image/jpeg', 'objectName': 'gone.jpg', 'deleted': True, 'deletionPending': True},
    ]
    db.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(current), space))
    for upload_id, status in ((pending_id, 'pending'), (aborted_id, 'aborted')):
        db.execute("INSERT INTO pr_media_uploads(id,workspace_id,created_by,bucket,object_name,mime,declared_bytes,status,token_expires_at) "
                   "VALUES(%s,%s,%s,'postriff-video',%s,'video/mp4',10,%s,now()+interval '1 hour')", (upload_id, space, person, f'{upload_id}.mp4', status))
result = service.delete_account(space, person, 'DELETE')
deleted = {name for _category, name in storage.deleted}
assert result['deleted'], result
assert storage.objects == {}, sorted(storage.objects)
assert {f'{video_id}.mp4', 'poster.jpg', 'frame-1.jpg', 'gone.jpg', f'{pending_id}.mp4', f'{aborted_id}.mp4', 'stray.mp4'} <= deleted, sorted(deleted)
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_media_uploads WHERE workspace_id=%s', (space,)).fetchone()[0] == 0
    receipt = db.execute("SELECT receipt FROM pr_data_requests WHERE id=%s", (result['receiptId'],)).fetchone()[0]
assert receipt['storageDeleted'] is True, receipt

# Upload rows with no storage configured: refused before anything is deleted (the account stays whole).
person, space = new_account()
service.assets = Assets()
with connection() as db:
    db.execute("INSERT INTO pr_media_uploads(id,workspace_id,created_by,bucket,object_name,mime,declared_bytes,status,token_expires_at) "
               "VALUES(%s,%s,%s,'postriff-video',%s,'video/mp4',10,'pending',now()+interval '1 hour')", ('e' * 32, space, person, 'e' * 32 + '.mp4'))
denied(lambda: service.delete_account(space, person, 'DELETE'), 503)
assert service.get(space, person)['state'].get('accountDeletion') is None
print('PASS video objects, posters, frames, pending/aborted uploads, a deletionPending asset and the prefix are deleted before the workspace; no storage, no deletion')


# Document page previews occupy the media category, separately from Library originals.
# Exercise the account route with persisted pages and older/unregistered objects;
# a partial delete must retain the exact rows and pending receipt until a safe retry.
from postriff_phase2.library_preview import VERSION  # noqa: E402
from postriff_phase2.video_uploads import VideoPolicy  # noqa: E402


class CategoryStorage:
    def __init__(self):
        self.bucket = 'postriff-private'
        self.video_bucket = VideoPolicy().bucket
        self.file_bucket = 'postriff-library'
        self.objects, self.deleted = {}, []
        self.fail_key = None

    def delete(self, workspace, category, name):
        key = (workspace, category, name)
        if key == self.fail_key:
            raise AlphaError('Synthetic page deletion unavailable.', 502)
        self.deleted.append(key)
        self.objects.pop(key, None)  # Already absent is the real adapter's successful retry case.

    def list_prefix(self, prefix, bucket=None):
        workspace, category = prefix.split('/')
        assert category in ('video', 'file', 'media', 'artwork'), category
        expected = self.video_bucket if category == 'video' else self.file_bucket if category == 'file' else self.bucket
        assert bucket is None or bucket == expected, (category, bucket, expected)
        return [f'{prefix}/{name}' for space, kind, name in self.objects
                if space == workspace and kind == category]


page_storage = CategoryStorage()
page_identity = Identity()
page_service = HostedWorkspaceService(connection, verify, identity=page_identity, assets=VideoAssets(page_storage))
page_person, foreign_person = str(uuid.uuid4()), str(uuid.uuid4())
with connection() as db:
    db.execute('INSERT INTO auth.users VALUES(%s),(%s)', (page_person, foreign_person))
page_space = page_service.bootstrap(page_person, 'studio')['workspaceId']
foreign_space = page_service.bootstrap(foreign_person, 'studio')['workspaceId']
page_id, foreign_id = uuid.uuid4().hex, uuid.uuid4().hex
page_sha = 'a' * 64
preview_asset = {'id': page_id, 'sha256': page_sha}
page_names = [page_service.library._preview_object(preview_asset, n) for n in (1, 2)]
page_original = page_id + '.pdf'
stale_page = 'f' * 32 + '-' + 'e' * 64 + '.jpg'
stray_original = 'e' * 32 + '.pdf'
thumbnail = {'version': VERSION, 'page': 2, 'pageCount': 2, 'objectName': page_names[0],
             'state': 'ready', 'pages': {'1': {'width': 600, 'height': 800}, '2': {'width': 600, 'height': 800}}}
with connection() as db:
    for asset_id, space, person in ((page_id, page_space, page_person), (foreign_id, foreign_space, foreign_person)):
        db.execute("INSERT INTO pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,sha256,bucket,object_name,processing_status,provenance) "
                   "VALUES(%s,%s,%s,'synthetic.pdf','document','application/pdf','pdf',7,%s,'postriff-library',%s,'ready',%s::jsonb)",
                   (asset_id, space, person, page_sha, page_original, json.dumps({'thumbnail': thumbnail})))
    db.execute("INSERT INTO pr_library_chunks(asset_id,workspace_id,ordinal,text) VALUES(%s,%s,0,'synthetic extracted text')", (page_id, page_space))
for space in (page_space, foreign_space):
    for category, name in (('file', page_original), ('file', stray_original), ('media', page_names[0]),
                           ('media', page_names[1]), ('media', stale_page)):
        page_storage.objects[(space, category, name)] = b'private fixture bytes'
foreign_objects = {key: value for key, value in page_storage.objects.items() if key[0] == foreign_space}
page_storage.fail_key = (page_space, 'media', page_names[1])
denied(lambda: page_service.delete_account(page_space, page_person, 'DELETE'), 503)
pending = page_service.get(page_space, page_person)['state']['accountDeletion']
receipt_id = pending['receiptId']
assert pending['status'] == 'pending' and page_identity.calls == []
assert (page_space, 'file', page_original) not in page_storage.objects
assert page_storage.fail_key in page_storage.objects
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_library_assets WHERE workspace_id=%s', (page_space,)).fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM pr_library_chunks WHERE workspace_id=%s', (page_space,)).fetchone()[0] == 1
    receipt, status = db.execute('SELECT receipt,status FROM pr_data_requests WHERE id=%s', (receipt_id,)).fetchone()
assert status == 'requested' and receipt['stage'] == 'storage_pending' and not receipt.get('storageDeleted')
assert {key: value for key, value in page_storage.objects.items() if key[0] == foreign_space} == foreign_objects
page_storage.fail_key = None
page_result = page_service.delete_account(page_space, page_person, 'DELETE')
assert page_result['deleted'] and page_result['receiptId'] == receipt_id
assert page_identity.calls == [page_person]
assert not any(key[0] == page_space for key in page_storage.objects), page_storage.objects
assert page_storage.objects == foreign_objects
assert all(key[0] == page_space for key in page_storage.deleted), page_storage.deleted
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_library_assets WHERE workspace_id=%s', (page_space,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM pr_library_chunks WHERE workspace_id=%s', (page_space,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM pr_library_assets WHERE workspace_id=%s', (foreign_space,)).fetchone()[0] == 1
    receipt, status = db.execute('SELECT receipt,status FROM pr_data_requests WHERE id=%s', (receipt_id,)).fetchone()
assert status == 'completed' and receipt['storageDeleted'] and receipt['identityDeleted']
print('PASS account deletion removes multi-page Library previews and stale workspace file/media objects; partial failure retains rows and receipt, retry is idempotent, foreign workspace survives')


# A preview that has rendered but has not stored its immutable object must keep
# deletion behind the workspace lock through the write and provenance commit.
# PostgreSQL connections and account deletion are real; renderer/storage/identity
# are controlled synthetic adapters, with no external provider or customer data.
import hashlib  # noqa: E402
import threading  # noqa: E402
from unittest.mock import patch  # noqa: E402


class BlockingPreviewStorage(CategoryStorage):
    def __init__(self):
        super().__init__()
        self.put_started = threading.Event()
        self.release_put = threading.Event()
        self.put_finished = threading.Event()

    def object_info(self, workspace, category, name):
        raw = self.objects[(workspace, category, name)]
        return {'bytes': len(raw), 'mime': 'application/pdf', 'etag': 'synthetic-preview-etag'}

    def get_bounded(self, workspace, category, name, limit):
        raw = self.objects[(workspace, category, name)]
        assert len(raw) <= limit
        return raw

    def put_immutable(self, workspace, category, name, raw, mime):
        assert category == 'media' and mime == 'image/jpeg' and 1 <= len(raw) <= 8 * 1024 * 1024
        self.put_started.set()
        if not self.release_put.wait(10):
            raise TimeoutError('Synthetic preview write barrier timed out')
        key = (workspace, category, name)
        if key in self.objects:
            raise AlphaError('Synthetic immutable preview already exists.', 409)
        self.objects[key] = raw
        self.put_finished.set()

    def signed_url(self, workspace, category, name):
        return f'https://storage.example.invalid/{workspace}/{category}/{name}'


race_tag = uuid.uuid4().hex
preview_app, deletion_app = 'preview-' + race_tag, 'deletion-' + race_tag


def race_connection():
    app = deletion_app if threading.current_thread().name == deletion_app else preview_app
    return psycopg.connect('host=127.0.0.1 port=55438 dbname=postgres', application_name=app,
                          options='-c statement_timeout=15000')


race_storage, race_identity = BlockingPreviewStorage(), Identity()
race_service = HostedWorkspaceService(race_connection, verify, identity=race_identity, assets=VideoAssets(race_storage))
race_person, race_foreign_person = str(uuid.uuid4()), str(uuid.uuid4())
with connection() as db:
    db.execute('INSERT INTO auth.users VALUES(%s),(%s)', (race_person, race_foreign_person))
race_space = race_service.bootstrap(race_person, 'studio')['workspaceId']
race_foreign_space = race_service.bootstrap(race_foreign_person, 'studio')['workspaceId']
race_id, race_foreign_id = uuid.uuid4().hex, uuid.uuid4().hex
race_raw = b'%PDF-synthetic bounded preview source'
race_sha = hashlib.sha256(race_raw).hexdigest()
race_original = race_id + '.pdf'
race_preview = race_service.library._preview_object({'id': race_id, 'sha256': race_sha})
with connection() as db:
    for asset_id, space, person in ((race_id, race_space, race_person),
                                    (race_foreign_id, race_foreign_space, race_foreign_person)):
        db.execute("INSERT INTO pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,sha256,etag,bucket,object_name,processing_status) "
                   "VALUES(%s,%s,%s,'synthetic-race.pdf','document','application/pdf','pdf',%s,%s,'synthetic-preview-etag','postriff-library',%s,'ready')",
                   (asset_id, space, person, len(race_raw), race_sha, race_original))
for space in (race_space, race_foreign_space):
    race_storage.objects[(space, 'file', race_original)] = race_raw
race_storage.objects[(race_foreign_space, 'media', race_preview)] = b'foreign private preview'
race_foreign_objects = {k: v for k, v in race_storage.objects.items() if k[0] == race_foreign_space}
race_results, race_errors = {}, {}
delete_started, delete_finished = threading.Event(), threading.Event()


def render_race(raw, extension, page):
    assert (raw, extension, page) == (race_raw, 'pdf', 1)
    return {'image': b'\xff\xd8synthetic-raster', 'width': 600, 'height': 800,
            'text': 'Synthetic page', 'pageCount': 1, 'page': 1}


def preview_race():
    try:
        race_results['preview'] = race_service.library.viewer_page(race_space, race_person, race_id, 1)
    except Exception as error:
        race_errors['preview'] = error


def deletion_race():
    delete_started.set()
    try:
        race_results['deletion'] = race_service.delete_account(race_space, race_person, 'DELETE')
    except Exception as error:
        race_errors['deletion'] = error
    finally:
        delete_finished.set()


preview_thread = threading.Thread(target=preview_race, name=preview_app, daemon=True)
delete_thread = threading.Thread(target=deletion_race, name=deletion_app, daemon=True)
with patch('postriff_phase2.library_preview.render_isolated', side_effect=render_race):
    preview_thread.start()
    try:
        assert race_storage.put_started.wait(5), ('preview did not reach write barrier', race_errors)
        delete_thread.start()
        assert delete_started.wait(5)
        # Observe an actual database wait on the preview transaction, not a sleep
        # or an adapter callback that could hide an already-completed deletion.
        blocked_by_preview = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not delete_finished.is_set():
            with connection() as db:
                blocked_by_preview = bool(db.execute(
                    "SELECT 1 FROM pg_stat_activity d JOIN pg_stat_activity p ON p.pid=ANY(pg_blocking_pids(d.pid)) "
                    "WHERE d.application_name=%s AND p.application_name=%s AND d.wait_event_type='Lock' "
                    "AND d.query LIKE 'SELECT w.state,m.role%%FOR UPDATE OF w'",
                    (deletion_app, preview_app)).fetchone())
            if blocked_by_preview:
                break
            time.sleep(0.01)
        assert blocked_by_preview, ('deletion did not wait for preview workspace lock', race_results, race_errors)
        assert not delete_finished.is_set() and not race_storage.put_finished.is_set()
        assert race_identity.calls == [] and race_storage.deleted == []
        with connection() as db:
            current = db.execute('SELECT state FROM pr_workspaces WHERE id=%s', (race_space,)).fetchone()[0]
            assert not current.get('accountDeletion'), current
            assert db.execute("SELECT count(*) FROM pr_data_requests WHERE workspace_id=%s AND kind='deletion'", (race_space,)).fetchone()[0] == 0
    finally:
        race_storage.release_put.set()
        preview_thread.join(10)
        if delete_thread.ident is not None:
            delete_thread.join(10)
assert not preview_thread.is_alive() and not delete_thread.is_alive(), 'synthetic race threads did not finish'
assert race_errors == {}, race_errors
assert race_storage.put_finished.is_set() and race_results['preview']['pageCount'] == 1
assert race_results['deletion']['deleted'] and race_identity.calls == [race_person]
assert (race_space, 'media', race_preview) in race_storage.deleted
assert race_storage.objects == race_foreign_objects
assert all(k[0] == race_space for k in race_storage.deleted), race_storage.deleted
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_workspaces WHERE id=%s', (race_space,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM pr_library_assets WHERE workspace_id=%s', (race_space,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM pr_library_assets WHERE workspace_id=%s', (race_foreign_space,)).fetchone()[0] == 1
    receipt, status = db.execute('SELECT receipt,status FROM pr_data_requests WHERE id=%s', (race_results['deletion']['receiptId'],)).fetchone()
assert status == 'completed' and receipt['storageDeleted'] and receipt['identityDeleted']
print('PASS account deletion waits for the preview write/provenance transaction before purging its object; completed receipt has no own objects and foreign workspace remains intact')
