"""Mission-scoped staging decision listener for an already registered owner.

This worker never seeds a session, creates an owner, overwrites a checkpoint,
retries a model request or treats screen text as a human decision. Default is
read-only. --dispatch enables the existing verified-decision/fence path only.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from .native_decision import (_checkpoint, continue_verified_decision, publish_mission_binding,
                              publish_native_receipt, read_native_work, refresh_guarded_checkpoint)
from .native_transport import DeliveryLedger, SQLiteRecoveryControl
from .recovery import RecoveryBlocked, RecoveryStore
from .restricted_owner import (RestrictedClaudeTransport, RestrictedOwnerClient,
                               private, registration_from, write_private)


class DecisionWorker:
    def __init__(self, canonical_root, store, registration, checkpoint_sha256, guard, transport_factory, *,
                 holder, dispatch_enabled=False, reader=read_native_work, publisher=publish_native_receipt,
                 settler=None, actor_id=None, workspace_id=None, binding_publisher=publish_mission_binding,
                 phone_acceptance=None, clock=time.time):
        self.canonical_root, self.store, self.registration = canonical_root, store, registration
        self.checkpoint_sha256, self.guard, self.transport_factory = checkpoint_sha256, guard, transport_factory
        self.holder, self.dispatch_enabled = holder, dispatch_enabled is True
        self.reader, self.publisher, self.settler, self.clock = reader, publisher, settler, clock
        self.actor_id, self.workspace_id, self.binding_publisher = actor_id, workspace_id, binding_publisher
        self.phone_acceptance = phone_acceptance
        if phone_acceptance is not None and (not self.dispatch_enabled or actor_id is None):
            raise RecoveryBlocked('explicit_staging_phone_arm_required')
        if (actor_id is None) != (workspace_id is None): raise RecoveryBlocked('native_worker_principal_required')
        registration.validate()
        _checkpoint(store, registration, checkpoint_sha256)

    def _saved_receipt(self, effect_key):
        if not self.store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_decision_delivery'").fetchone():
            return None
        row = self.store.db.execute('SELECT state,receipt FROM native_decision_delivery WHERE effect_key=?', (effect_key,)).fetchone()
        if row is None: return None
        return {'state':row['state'], 'receipt':json.loads(row['receipt']) if row['receipt'] else None}

    def once(self):
        status = {'schemaVersion':1, 'observedAt':self.clock(), 'missionId':self.registration.mission_id,
                  'checkpointSha256':self.checkpoint_sha256, 'dispatchEnabled':self.dispatch_enabled,
                  'nativeGuardVerified':False, 'nativeDispatchAttempted':False, 'missionComplete':False}
        try:
            if self.dispatch_enabled and self.actor_id is not None:
                # Genuine Stop hooks may advance continuity. Preserve the old
                # checkpoint and scope, then keep the real cloud attestation
                # fresh enough for report/question construction (30 seconds).
                self.checkpoint_sha256 = refresh_guarded_checkpoint(self.store, self.registration,
                    self.checkpoint_sha256, self.guard, clock=self.clock)
                status['checkpointSha256'] = self.checkpoint_sha256
                self.binding_publisher(self.canonical_root, self.store, self.registration,
                    self.checkpoint_sha256, self.guard, actor_id=self.actor_id,
                    workspace_id=self.workspace_id, clock=self.clock)
                status.update(nativeGuardVerified=True, bindingState='registered')
            if self.phone_acceptance is not None:
                status['phoneAcceptance'] = self.phone_acceptance.once()
            decision = self.reader(self.canonical_root, mission_id=self.registration.mission_id)
            if decision is None: return dict(status, state='listening', cloudQueueState='idle')
            execution = self.store.current_execution(self.registration)
            decision.validate(self.registration, execution)
            status['decisionKey'] = decision.document['effectKey']
            if decision.document['choice'] != 'continue':
                return dict(status, state='human_choice_recorded', choice=decision.document['choice'])
            saved = self._saved_receipt(decision.document['effectKey'])
            if saved is not None:
                # Replay the same immutable upload only while still fresh.
                # An upload outage/crash can never resend a native turn.
                old = saved['receipt']
                if self.dispatch_enabled and isinstance(old, dict) and old.get('executionState') in {'unknown','resumed','turn_started'}:
                    observed = old.get('observedAt')
                    if type(observed) in (int,float) and 0 <= self.clock()-observed <= 30:
                        self.publisher(self.canonical_root, old)
                        return dict(status, state='receipt_reconciled_no_resend', nativeDeliveryState=saved['state'])
                return dict(status, state='already_reserved_no_resend', nativeDeliveryState=saved['state'])
            if not self.dispatch_enabled:
                return dict(status, state='decision_ready_read_only')
            receipt = continue_verified_decision(self.store, self.registration, decision,
                self.checkpoint_sha256, self.guard, self.transport_factory, holder=self.holder,
                reserved_cost_microusd=0, clock=self.clock)
            status.update(nativeGuardVerified=receipt.get('nativeGuardVerified') is True,
                          nativeDispatchAttempted=receipt.get('attemptId') is not None,
                          nativeDeliveryState=receipt['executionState'], receiptSha256=receipt.get('receiptSha256'))
            # Settle a completed restricted-owner turn through the authenticated
            # owner, using its real result and live lease. This is not acceptance.
            if receipt['executionState'] == 'turn_started' and self.settler is not None:
                terminal = self.settler(receipt)
                if (not isinstance(terminal, dict) or terminal.get('state') != 'native_turn_finished'
                        or terminal.get('turnId') != receipt.get('turnId') or terminal.get('missionComplete') is not False):
                    raise RecoveryBlocked('native_terminal_acknowledgment_unverified')
                status['nativeTurnState'] = terminal['state']
            if receipt['executionState'] == 'turn_started' and self.actor_id is not None:
                # A bounded native turn can exceed the cloud's 30-second guard
                # freshness window. Publish a new real owner observation after
                # it returns; never re-date an old attestation or receipt.
                self.binding_publisher(self.canonical_root, self.store, self.registration,
                    self.checkpoint_sha256, self.guard, actor_id=self.actor_id,
                    workspace_id=self.workspace_id, clock=self.clock)
            self.publisher(self.canonical_root, receipt)
            return dict(status, state='receipt_published')
        except RecoveryBlocked as exc:
            reason = str(exc)
            if not re.fullmatch('[a-z][a-z0-9_]{0,100}', reason): reason = 'private_native_worker_failure'
            return dict(status, state='blocked', reason=reason)
        except Exception:
            return dict(status, state='blocked', reason='private_native_worker_failure')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical-root', required=True)
    parser.add_argument('--owner-root', required=True)
    parser.add_argument('--checkpoint-sha', required=True)
    parser.add_argument('--dispatch', action='store_true')
    parser.add_argument('--actor-id')
    parser.add_argument('--workspace-id')
    parser.add_argument('--phone-acceptance-id', help='Explicit one-call staging acceptance UUID; never inferred')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--interval', type=int, default=15)
    args = parser.parse_args()
    if not 15 <= args.interval <= 300 or not re.fullmatch('[0-9a-f]{64}', args.checkpoint_sha):
        parser.error('bounded interval and exact checkpoint SHA required')
    if args.dispatch and not (args.actor_id and args.workspace_id):
        parser.error('exact approved actor and workspace required for dispatch')
    if args.phone_acceptance_id and not args.dispatch:
        parser.error('explicit dispatch and approved one-call scope required')
    canonical = Path(args.canonical_root).resolve(strict=True)
    if canonical != Path.home()/'Documents/James-Agent-Team':
        parser.error('canonical staging configuration root required')
    root = private(Path(args.owner_root), directory=True)
    store = RecoveryStore(str(private(root/'recovery.sqlite3')))
    ledger_path = root/'decision-delivery.sqlite3'
    if ledger_path.exists(): private(ledger_path)
    else:
        import os
        fd = os.open(ledger_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    ledger = DeliveryLedger(str(ledger_path))
    try:
        policy = json.loads(private(root/'policy.json').read_text())
        row = store.db.execute('SELECT body FROM recovery_bindings WHERE mission_id=?', (policy['missionId'],)).fetchone()
        if row is None: raise RecoveryBlocked('genuine_owner_registration_required')
        registration = registration_from(json.loads(row['body']))
        if (registration.worktree, registration.native_session_id, registration.engine, registration.authorization_sha256) != (
                policy['worktree'], policy['sessionId'], 'claude-code', policy['authorizationSha256']):
            raise RecoveryBlocked('owner_registration_policy_mismatch')
        client = RestrictedOwnerClient(root)
        phone = None
        if args.phone_acceptance_id:
            from .phone_acceptance import PhoneAcceptance
            phone = PhoneAcceptance(canonical,root,args.phone_acceptance_id,registration.mission_id)
        def factory(observer):
            return RestrictedClaudeTransport(SQLiteRecoveryControl(store), ledger, client, observer)
        worker = DecisionWorker(canonical, store, registration, args.checkpoint_sha, client, factory,
            holder='decision-worker:'+registration.native_session_id, dispatch_enabled=args.dispatch,
            actor_id=args.actor_id, workspace_id=args.workspace_id,
            phone_acceptance=phone,
            settler=lambda receipt:client.request('settle', {'receipt':receipt}))
        while True:
            status = worker.once()
            write_private(root/'decision-worker-status.json', status)
            print(json.dumps(status), flush=True)
            if not args.serve: break
            time.sleep(args.interval)
    finally:
        ledger.close(); store.close()


if __name__ == '__main__': main()
