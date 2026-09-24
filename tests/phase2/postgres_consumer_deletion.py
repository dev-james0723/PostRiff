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
