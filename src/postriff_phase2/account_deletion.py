"""Durable deletion fence. External storage/auth work never holds a workspace transaction."""
import copy
import json
from postriff_alpha.domain import AlphaError
from .store import IN_FLIGHT, TERMINAL


def _other_owned(cur, workspace_id, principal):
    cur.execute("SELECT 1 FROM public.pr_memberships WHERE user_id=%s AND workspace_id<>%s AND role='owner' AND status='active' LIMIT 1", (principal, workspace_id))
    if cur.fetchone():
        raise AlphaError('Transfer ownership of your other workspaces before deleting this account.', 409)


def delete_account(service, workspace_id, token, confirmation):
    if confirmation != 'DELETE':
        raise AlphaError('Type DELETE to confirm account removal.')
    if service.identity is None:
        raise AlphaError('Hosted account deletion is not configured.', 503)
    principal = service.verify_session(token)
    service.repository.assert_fresh(token, principal)
    # Session lock serializes retries without keeping a transaction open during external I/O.
    with service.connection_factory() as lock_db:
        lock_db.autocommit = True
        with lock_db.cursor() as lock:
            key = 'account-deletion:' + str(principal)
            lock.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))', (key,))
            if not lock.fetchone()[0]:
                raise AlphaError('Account deletion is already running. Check its outcome before retrying.', 409)
            try:
                return _delete(service, workspace_id, principal)
            finally:
                lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))


def _delete(service, workspace_id, principal):
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT w.state,m.role FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w", (workspace_id, principal))
        row = cur.fetchone()
        if not row or row[1] != 'owner':
            raise AlphaError('Workspace unavailable.', 403)
        _other_owned(cur, workspace_id, principal)
        state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if any(job.get('state') in IN_FLIGHT for job in state.get('phase2', {}).get('jobs', [])):
            raise AlphaError('Reconcile in-flight outcomes before deletion; deletion cannot recall a submitted post.', 409)
        cur.execute("SELECT 1 FROM public.pr_agent_runs WHERE workspace_id=%s AND status='running' LIMIT 1", (workspace_id,))
        if cur.fetchone():
            raise AlphaError('Resolve the running draft operation before deleting this workspace.', 409)
        cur.execute("SELECT 1 FROM public.pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' AND r.estimated_usd_micro>0 AND NOT EXISTS(SELECT 1 FROM public.pr_usage_ledger s WHERE s.reservation_id=r.id AND s.cost_state IN ('actual','released')) LIMIT 1", (workspace_id,))
        if cur.fetchone():
            raise AlphaError('Reconcile outstanding model costs before deleting this workspace.', 409)
        cur.execute("SELECT 1 FROM public.pr_subscriptions WHERE workspace_id=%s AND provider<>'fixture' AND provider_subscription_id IS NOT NULL AND status NOT IN ('cancelled','expired') AND NOT cancel_at_period_end", (workspace_id,))
        if cur.fetchone():
            raise AlphaError('Cancel the renewing subscription in Billing before deleting your account.', 409)
        assets = [copy.deepcopy(a) for a in state.get('phase2', {}).get('assets', []) if a.get('objectName') and not a.get('deleted')]
        if assets and service.assets is None:
            raise AlphaError('Private storage deletion is unavailable. No data was deleted.', 503)
        pending = state.get('accountDeletion')
        if not pending:
            receipt_id = service.data_requests.record(cur, workspace_id, principal, 'deletion', 'requested', {'stage':'storage_pending'})
            pending = {'status':'pending', 'requestedBy':str(principal), 'requestedAt':service.clock(), 'receiptId':receipt_id}
            state['accountDeletion'] = pending
            for job in state.get('phase2', {}).get('jobs', []):
                if job.get('state') not in TERMINAL:
                    job.update(state='canceled', cancelRequested=True)
            # These changes independently invalidate preexisting approvals and optional extraction.
            for channel in state.get('phase2', {}).get('channels', []):
                channel.update(revoked=True, configured=False)
            for source in state.get('sources', []):
                source['active'] = False
            state.setdefault('learning', {})['enabled'] = False
            for task in state.get('raffi', {}).get('campaignPlanning', {}).get('recurringTasks', []):
                task['status'] = 'cancelled'
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state),workspace_id))
        receipt_id = pending['receiptId']
    # Retry deletes only the same immutable objects. Storage DELETE treats not-found as success.
    for asset in assets:
        try:
            service.assets.remove(workspace_id, asset)
        except Exception as error:
            raise AlphaError('Deletion is pending. The workspace is frozen; retry deletion to finish private storage cleanup.', 503, code='account_deletion_pending') from error
    # Disconnect grants where supported. Never retain plaintext tokens in receipts or logs.
    revocation_pending = []
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND revoked_at IS NULL', (workspace_id,))
        credentials = cur.fetchall()
    for provider, ciphertext, key_id in credentials:
        try:
            revoked = service.oauth._provider(provider).revoke(service.oauth.vault.decrypt(ciphertext, key_id))
        except Exception:
            revoked = False
        if not revoked and provider not in revocation_pending:
            revocation_pending.append(provider)
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
        current = cur.fetchone()
        if not current or current[0].get('accountDeletion', {}).get('receiptId') != receipt_id:
            raise AlphaError('Deletion state changed; reconcile before continuing.', 409)
        _other_owned(cur, workspace_id, principal)
        cur.execute('SELECT plan,started_at FROM public.pr_trials WHERE workspace_id=%s', (workspace_id,))
        trial = cur.fetchone()
        if not trial:
            raise AlphaError('Deletion trial record is unavailable; reconcile before continuing.', 409)
        cur.execute('INSERT INTO public.pr_account_tombstones(user_id,plan,trial_started_at) VALUES(%s,%s,%s) ON CONFLICT(user_id) DO NOTHING', (principal,trial[0],trial[1]))
        cur.execute("UPDATE public.pr_data_requests SET receipt=%s::jsonb WHERE id=%s", (json.dumps({'stage':'identity_pending', 'identityAttempts':1, 'lastIdentityAttempt':service.clock(), 'workspaceDeleted':True, 'storageDeleted':True, 'providerRevocationPending':revocation_pending}),receipt_id))
        cur.execute('SELECT coalesce(sum(actual_usd_micro),0),count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s', (workspace_id,))
        cost, entries = cur.fetchone()
        cur.execute("UPDATE public.pr_data_requests SET receipt=receipt||%s::jsonb WHERE id=%s", (json.dumps({'knownCostUsdMicro':int(cost), 'ledgerEntries':entries}),receipt_id))
        cur.execute('DELETE FROM public.pr_trials WHERE user_id=%s', (principal,))
        cur.execute('DELETE FROM public.pr_memberships WHERE workspace_id=%s', (workspace_id,))
        cur.execute('DELETE FROM public.pr_profiles WHERE user_id=%s', (principal,))
        cur.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (workspace_id,))
    # A failed identity call cannot undo deleted data. Keep the pending receipt for operator recovery.
    try:
        service.identity.delete_user(principal)  # Success includes an already-absent identity (HTTP 404).
    except Exception:
        return {'deleted':False, 'workspaceDeleted':True, 'identityDeleted':False, 'status':'identity_pending', 'receiptId':receipt_id, 'providerRevocationPending':revocation_pending}
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute('UPDATE public.pr_account_tombstones SET auth_deleted_at=now() WHERE user_id=%s', (principal,))
        cur.execute("UPDATE public.pr_data_requests SET status='completed',completed_at=now(),receipt=receipt||%s::jsonb WHERE id=%s", (json.dumps({'stage':'completed', 'workspaceDeleted':True, 'storageDeleted':True, 'identityDeleted':True, 'providerRevocationPending':revocation_pending}),receipt_id))
    return {'deleted':True, 'workspaceDeleted':True, 'identityDeleted':True, 'trialTombstoneRetained':True, 'receiptId':receipt_id, 'providerRevocationPending':revocation_pending}


def reconcile_identity(service):
    """One bounded retry of an already-authorized, durable deletion; no new deletion scope."""
    if service.identity is None:
        return {'status':'unavailable'}
    with service.connection_factory() as db, db.cursor() as cur:
        cur.execute("""SELECT d.id::text,d.requested_by::text FROM public.pr_data_requests d
          JOIN public.pr_account_tombstones t ON t.user_id=d.requested_by
          WHERE d.kind='deletion' AND d.status='requested' AND d.receipt->>'stage'='identity_pending'
          AND t.auth_deleted_at IS NULL AND coalesce((d.receipt->>'identityAttempts')::int,1)<3
          AND coalesce((d.receipt->>'lastIdentityAttempt')::numeric,0)<%s
          ORDER BY d.requested_at LIMIT 1""", (service.clock()-60,))
        candidate = cur.fetchone()
    if candidate is None:
        return {'status':'idle'}
    receipt_id, principal = candidate
    with service.connection_factory() as lock_db:
        lock_db.autocommit = True
        with lock_db.cursor() as lock:
            key = 'account-deletion:' + principal
            lock.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))', (key,))
            if not lock.fetchone()[0]:
                return {'status':'busy'}
            try:
                with service.connection_factory() as db, db.cursor() as cur:
                    cur.execute("SELECT receipt,status FROM public.pr_data_requests WHERE id=%s FOR UPDATE", (receipt_id,))
                    receipt, status = cur.fetchone()
                    if status != 'requested' or receipt.get('identityAttempts',1)>=3 or receipt.get('lastIdentityAttempt',0)>=service.clock()-60:
                        return {'status':'idle'}
                    receipt.update(identityAttempts=receipt.get('identityAttempts',1)+1, lastIdentityAttempt=service.clock())
                    cur.execute('UPDATE public.pr_data_requests SET receipt=%s::jsonb WHERE id=%s', (json.dumps(receipt),receipt_id))
                try:
                    service.identity.delete_user(principal)
                except Exception:
                    return {'status':'identity_pending'}
                with service.connection_factory() as db, db.cursor() as cur:
                    cur.execute('UPDATE public.pr_account_tombstones SET auth_deleted_at=now() WHERE user_id=%s', (principal,))
                    receipt.update(stage='completed',identityDeleted=True)
                    cur.execute("UPDATE public.pr_data_requests SET status='completed',completed_at=now(),receipt=%s::jsonb WHERE id=%s", (json.dumps(receipt),receipt_id))
                return {'status':'completed', 'count':1}
            finally:
                lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))
