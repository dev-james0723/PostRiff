"""Founder actions (Founder Admin P1/P2, CONTRACTS §8.F; PRD §7.5, §10.2 reconcile, §10.3 admin actions).

Every action is a preview -> confirm pair, executed at most once through the embedded consumer runtime (`app.consumer()`):

* Preview (the action's capability and a fresh second factor, both enforced by http.py/auth.Boundary): validates the
  request, reads the exact target and its current value from the consumer database, computes the effect and records a
  content-free `rafii_control.founder_action_requests` row (068) whose `revision` digests that current value. Nothing
  changes in the consumer database. A preview expires after five minutes.
* Confirm (same capability, a fresh second factor, the preview id and its revision): claims the preview once under a row
  lock, re-reads the target inside the consumer transaction that executes the action and refuses it (STALE_PREVIEW) when
  the target moved since the preview; then the consumer writes its audit kind — `usage.reconciled`
  (billing.Ledger.reconcile_unknown), `credit.adjusted_by_operator` (CreditBook, source founder_goodwill) or
  `account.blocked` / `account.unblocked` (postriff_phase2.operator_actions) — and the request row is finished. http.py
  writes the Control audit rows (authorization and terminal outcome) under the request ids this row records.
* Idempotency: repeating a confirm with the same request id returns the recorded outcome, or resumes an interrupted one
  whose consumer effect is keyed by the action id (so it is applied once); any other reuse of a request id is
  IDEMPOTENCY_CONFLICT. An expired, used or foreign preview, a wrong revision, a moved target, a missing step-up
  (Boundary) or Demo mode (http.py) is refused before any consumer write.

Policy: credit adjustment answers 409 POLICY_DISABLED (credits_not_enabled) while the consumer runtime has credits off; a
refund is an intent record only — execution stays blocked (refund_policy_not_decided) and no confirm route exists.
None of this is a founder tool: the agent has no path to these routes (CONTRACTS §8.0 Agent).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from postriff_alpha.domain import AlphaError
from postriff_phase2 import operator_actions

from . import http
from .auth import ControlError

PREVIEW_SECONDS = 300
LIST_DEFAULT, LIST_MAX = 50, 200
MAX_ACTUAL_USD_MICRO = 100_000_000          # one reservation's provider cost; launch requests are capped at US$1-2
MAX_ADJUST_MILLI = 50_000_000               # 50,000 credits in one manual adjustment
MILLI_STEP = 100
GRANT_EXPIRY_DAYS = (1, 366)                # goodwill grants always expire
MAX_REFUND_MINOR = 100_000_000
TYPED_BLOCK = 'BLOCK'
KINDS = ('reconcile', 'credits_adjust', 'account_block', 'account_unblock', 'refund_intent')
STATUS = {'VALIDATION_FAILED': 400, 'STALE_PREVIEW': 409, 'IDEMPOTENCY_CONFLICT': 409, 'POLICY_DISABLED': 409, 'SCOPE_DENIED': 403,
          'SOURCE_UNAVAILABLE': 503}
_UUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z')
_EVIDENCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._:/#=+-]{0,199}\Z')   # a provider reference (gateway request id); no '@', no prose markup
_APPROVAL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/#-]{0,119}\Z')       # 062 approval_ref
_PAYMENT = re.compile(r'[A-Za-z0-9_]{3,100}\Z')
_CURRENCY = re.compile(r'[a-z]{3}\Z')
_REVISION = re.compile(r'[0-9a-f]{16}\Z')
_TARGET = re.compile(r'[A-Za-z0-9_-]{1,100}\Z')
_ID_PATH = '([A-Za-z0-9_-]{1,80})'


class ActionError(ControlError):
    """A control error with a fixed blocker code (http.py returns it as `blocker`); never free text."""

    def __init__(self, code, status=None, blocker=None):
        super().__init__(code, status or STATUS.get(code, 400))
        self.blocker = blocker


def _invalid(blocker=None, status=400):
    return ActionError('VALIDATION_FAILED', status, blocker)


# --- request validation -------------------------------------------------------------------------------------------------
def _uuid(value, blocker='invalid_id'):
    if not isinstance(value, str) or not _UUID.match(value):
        raise _invalid(blocker)
    return str(uuid.UUID(value))


def _fields(body, required, optional=()):
    if not isinstance(body, dict) or not set(required) <= set(body) or set(body) - set(required) - set(optional):
        raise _invalid('unexpected_fields')
    return body


def _int(value, low, high, blocker):
    if type(value) is not int or not low <= value <= high:
        raise _invalid(blocker)
    return value


def _choice(value, choices, blocker):
    if not isinstance(value, str) or value not in choices:
        raise _invalid(blocker)
    return value


def _instant(value, blocker):
    """An aware ISO 8601 instant -> epoch seconds; a naive stamp is refused rather than guessed."""
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        raise _invalid(blocker)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise _invalid(blocker) from None
    if parsed.tzinfo is None:
        raise _invalid(blocker)
    return parsed.timestamp()


def stamp(value):
    """Epoch seconds -> ISO 8601 UTC ('Z'); None stays None."""
    return None if value is None else datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace('+00:00', 'Z')


def revision_of(kind, core):
    """The preview revision: a digest of the target's current value (what the confirm must still find)."""
    payload = json.dumps({'kind': kind, 'core': core}, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _context(app, principal, request):
    # The ops workspace: the deployment variable, else the founder's stored setting (founder_ops, created from Settings).
    from .founder_ops import resolve
    ops, _source = resolve(getattr(app, 'flags', None) or {}, getattr(getattr(app, 'queries', None), 'store', None), str(principal['operator']['user_id']))
    return {'operator': str(principal['operator']['user_id']), 'opsWorkspace': ops, 'now': float(request['now'])}


def _reconcile_params(body, match, ctx):
    _fields(body, ('requestId', 'workspaceId', 'reservationId', 'outcome', 'actualUsdMicro', 'evidence'))
    evidence = body['evidence'].strip() if isinstance(body['evidence'], str) else None
    if not evidence or not _EVIDENCE.match(evidence):
        raise _invalid('invalid_evidence')
    params = {'workspaceId': _uuid(body['workspaceId']), 'reservationId': _uuid(body['reservationId']),
              'outcome': _choice(body['outcome'], ('completed', 'failed'), 'invalid_outcome'),
              'actualUsdMicro': _int(body['actualUsdMicro'], 0, MAX_ACTUAL_USD_MICRO, 'invalid_amount'), 'evidence': evidence}
    return params, 'reservation', params['reservationId'], params['workspaceId']


def _credit_params(body, match, ctx):
    operation = body.get('operation') if isinstance(body, dict) else None
    if operation == 'grant':
        _fields(body, ('requestId', 'workspaceId', 'operation', 'milliCredits', 'expiresAt', 'reasonCode'))
    elif operation == 'reverse':
        _fields(body, ('requestId', 'workspaceId', 'operation', 'milliCredits', 'grantId', 'reasonCode'))
    else:
        raise _invalid('invalid_operation')
    milli = _int(body['milliCredits'], MILLI_STEP, MAX_ADJUST_MILLI, 'invalid_amount')
    if milli % MILLI_STEP:
        raise _invalid('invalid_amount')
    params = {'workspaceId': _uuid(body['workspaceId']), 'operation': operation, 'milliCredits': milli,
              'reasonCode': _choice(body['reasonCode'], operator_actions.CREDIT_REASON_CODES, 'invalid_reason'), 'expiresAt': None, 'grantId': None}
    if operation == 'grant':
        expires = float(int(_instant(body['expiresAt'], 'invalid_expiry')))
        if not ctx['now'] + GRANT_EXPIRY_DAYS[0] * 86400 <= expires <= ctx['now'] + GRANT_EXPIRY_DAYS[1] * 86400:
            raise _invalid('invalid_expiry')
        params['expiresAt'] = expires
    else:
        params['grantId'] = _uuid(body['grantId'])
    return params, 'workspace', params['workspaceId'], params['workspaceId']


def _account_target(body, match, ctx):
    target_type = _choice(body['targetType'], ('user', 'workspace'), 'invalid_target')
    target = _uuid(match[0] if match else None, 'invalid_target')
    return target_type, target


def _block_params(body, match, ctx):
    _fields(body, ('requestId', 'targetType', 'reasonCode', 'approvalRef'))
    target_type, target = _account_target(body, match, ctx)
    if target_type == 'user' and target == ctx['operator']:
        raise _invalid('cannot_block_operator', 409)
    if target_type == 'workspace' and target == ctx['opsWorkspace']:
        raise _invalid('cannot_block_ops_workspace', 409)
    approval = body['approvalRef']
    if not isinstance(approval, str) or not _APPROVAL.match(approval):
        raise _invalid('invalid_approval_ref')
    params = {'targetType': target_type, 'targetId': target, 'reasonCode': _choice(body['reasonCode'], operator_actions.REASON_CODES, 'invalid_reason'),
              'approvalRef': approval}
    return params, target_type, target, target if target_type == 'workspace' else None


def _unblock_params(body, match, ctx):
    _fields(body, ('requestId', 'targetType', 'reasonCode'))
    target_type, target = _account_target(body, match, ctx)
    params = {'targetType': target_type, 'targetId': target, 'reasonCode': _choice(body['reasonCode'], operator_actions.LIFT_REASON_CODES, 'invalid_reason')}
    return params, target_type, target, target if target_type == 'workspace' else None


def _refund_params(body, match, ctx):
    _fields(body, ('requestId', 'workspaceId', 'paymentIntentId', 'amountMinor', 'currency', 'reasonCode'))
    payment, currency = body['paymentIntentId'], body['currency']
    if not isinstance(payment, str) or not _PAYMENT.match(payment):
        raise _invalid('invalid_payment')
    if not isinstance(currency, str) or not _CURRENCY.match(currency.lower()):
        raise _invalid('invalid_currency')
    params = {'workspaceId': _uuid(body['workspaceId']), 'paymentIntentId': payment, 'amountMinor': _int(body['amountMinor'], 1, MAX_REFUND_MINOR, 'invalid_amount'),
              'currency': currency.lower(), 'reasonCode': _choice(body['reasonCode'], operator_actions.REFUND_REASON_CODES, 'invalid_reason')}
    return params, 'payment', payment, params['workspaceId']


# --- the consumer side ----------------------------------------------------------------------------------------------------
def _from_alpha(error, blocker):
    """A consumer refusal as a control error: its status class and a fixed blocker, never the consumer's sentence."""
    status = getattr(error, 'status', 500)
    if status == 409:
        return ActionError('STALE_PREVIEW', 409, blocker)
    if status in (400, 404):
        return _invalid(blocker, status)
    if status in (402, 403):
        return ActionError('SCOPE_DENIED', 403, blocker)
    return ActionError('SOURCE_UNAVAILABLE', 503, blocker)


def _unique_violation(error):
    return any(cls.__name__ == 'UniqueViolation' for cls in type(error).__mro__)


def _reconcile_core(snapshot):
    return {key: snapshot[key] for key in ('workspaceId', 'reservationId', 'dimension', 'estimatedUsdMicro', 'chargeBatch', 'creditsMaximumMilli', 'unknown', 'settled')}


def _credit_core(snapshot, params, lot):
    rows = snapshot['rows']
    return {'workspaceId': params['workspaceId'], 'policy': snapshot['policy'], 'wallet': snapshot['wallet'], 'creditRows': len(rows),
            'lastCreditRow': rows[-1]['id'] if rows else None, 'lot': lot}


def _block_core(snapshot):
    target = snapshot['target']
    return {'targetType': target['type'], 'targetId': target['id'], 'deleted': target.get('deleted', False),
            'blockId': (snapshot['block'] or {}).get('blockId'), 'frozenWorkspaceIds': sorted(snapshot['frozenWorkspaceIds'])}


class ConsumerActions:
    """The consumer side of every action through the embedded consumer service: one short transaction on the consumer's
    own connection per preview read and per execution (never a Control login, never a credential read here)."""

    def __init__(self, service):
        factory = getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)
        if factory is None:
            raise ActionError('SOURCE_UNAVAILABLE', 503)
        self.service, self.factory = service, factory

    @contextmanager
    def transaction(self):
        with self.factory() as db:
            with db.cursor() as cur:
                yield cur

    # policy gates -----------------------------------------------------------------------------------------------------
    def credits_book(self):
        book = getattr(getattr(self.service, 'ledger', None), 'credits', None)
        if book is None:
            raise ActionError('POLICY_DISABLED', 409, 'credits_not_enabled')
        return book

    @staticmethod
    def _blocks_installed(cur):
        if operator_actions.probe_now(cur) != 'installed':
            raise ActionError('POLICY_DISABLED', 409, 'account_blocks_not_installed')

    # reconcile ----------------------------------------------------------------------------------------------------------
    @staticmethod
    def _waiting(snapshot, stale):
        code = 'STALE_PREVIEW' if stale else 'VALIDATION_FAILED'
        if snapshot is None:
            raise ActionError(code, 409 if stale else 404, 'reservation_not_found')
        if not snapshot['unknown'] or snapshot['settled']:
            raise ActionError(code, 409, 'not_waiting_for_reconciliation')

    def reconcile_view(self, params, ctx):
        with self.transaction() as cur:
            snapshot = operator_actions.reservation_snapshot(cur, params['workspaceId'], params['reservationId'])
        self._waiting(snapshot, stale=False)
        effect = operator_actions.reconcile_effect(snapshot, params['outcome'], params['actualUsdMicro'])
        effect['evidence'] = {'provided': True, 'characters': len(params['evidence'])}
        display = {'target': {'type': 'reservation', 'workspaceId': snapshot['workspaceId'], 'reservationId': snapshot['reservationId'],
                              'runId': snapshot['runId'], 'dimension': snapshot['dimension'], 'provider': snapshot['provider'], 'model': snapshot['model']},
                   'current': {'costState': 'estimated_unknown', 'estimatedUsdMicro': snapshot['estimatedUsdMicro'], 'since': stamp(snapshot['since']),
                               'runStatus': snapshot['runStatus'], 'creditsMaximumMilli': snapshot['creditsMaximumMilli'], 'chargeBatch': snapshot['chargeBatch']},
                   'effect': effect}
        return _reconcile_core(snapshot), display

    def reconcile_execute(self, row, check):
        params, action = row['params'], row['id']
        ledger = getattr(self.service, 'ledger', None)
        if ledger is None:
            raise ActionError('SOURCE_UNAVAILABLE', 503)
        with self.transaction() as cur:
            if not operator_actions.lock_workspace(cur, params['workspaceId']):
                raise ActionError('STALE_PREVIEW', 409, 'workspace_not_found')
            done = operator_actions.reconciled_by(cur, params['workspaceId'], params['reservationId'], action)
            if done is not None:
                return {**done, 'duplicate': True}
            snapshot = operator_actions.reservation_snapshot(cur, params['workspaceId'], params['reservationId'])
            self._waiting(snapshot, stale=True)
            check(_reconcile_core(snapshot))
            try:
                result = operator_actions.reconcile(cur, ledger, params['workspaceId'], params['reservationId'], params['outcome'], params['actualUsdMicro'],
                                                    action_id=action, evidence=params['evidence'])
            except AlphaError as error:
                raise _from_alpha(error, 'reconcile_refused') from None
            return {**result, 'duplicate': False}

    # credits ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _wallet_refusal(snapshot, stale):
        refused = snapshot.get('refused')
        if refused == 'workspace_not_found':
            raise ActionError('STALE_PREVIEW', 409, refused) if stale else _invalid(refused, 404)
        if refused:
            raise ActionError('POLICY_DISABLED', 409, refused)

    @staticmethod
    def _credit_after(book, snapshot, params, stale):
        code, lot = ('STALE_PREVIEW' if stale else 'VALIDATION_FAILED'), None
        if params['operation'] == 'reverse':
            lot = next((dict(item) for item in snapshot['lots'] if item['grantId'] == params['grantId']), None)
            if lot is None:
                raise ActionError(code, 409 if stale else 404, 'grant_not_found')
            credit = {'op': 'reverse', 'grantId': params['grantId'], 'milli': params['milliCredits']}
        else:
            credit = {'op': 'grant', 'milli': params['milliCredits'], 'expiresAt': params['expiresAt']}
        try:
            after = operator_actions.wallet_after(book, snapshot['rows'], credit)
        except ValueError:
            raise ActionError(code, 409, 'reversal_exceeds_grant') from None
        return lot, after

    def credits_view(self, params, ctx):
        book = self.credits_book()
        with self.transaction() as cur:
            snapshot = operator_actions.wallet_snapshot(cur, book, params['workspaceId'])
        self._wallet_refusal(snapshot, stale=False)
        lot, after = self._credit_after(book, snapshot, params, stale=False)
        display = {'target': {'type': 'workspace', 'workspaceId': params['workspaceId'], 'grantId': params['grantId'], 'lot': lot},
                   'current': {'policy': snapshot['policy'], 'wallet': snapshot['wallet'], 'lots': len(snapshot['lots'])},
                   'effect': {'operation': params['operation'], 'milliCredits': params['milliCredits'], 'expiresAt': stamp(params['expiresAt']),
                              'reasonCode': params['reasonCode'], 'source': 'founder_goodwill', 'walletAfter': after, 'consumerAudit': 'credit.adjusted_by_operator'}}
        return _credit_core(snapshot, params, lot), display

    def credits_execute(self, row, check):
        params, action = row['params'], row['id']
        book = self.credits_book()
        with self.transaction() as cur:
            if not operator_actions.lock_workspace(cur, params['workspaceId']):
                raise ActionError('STALE_PREVIEW', 409, 'workspace_not_found')
            entry = operator_actions.credited_by(cur, params['workspaceId'], action)
            if entry is not None:
                return {'entryId': entry, 'operation': params['operation'], 'milliCredits': params['milliCredits'], 'duplicate': True,
                        'consumerAudit': 'credit.adjusted_by_operator'}
            snapshot = operator_actions.wallet_snapshot(cur, book, params['workspaceId'])
            self._wallet_refusal(snapshot, stale=True)
            lot, after = self._credit_after(book, snapshot, params, stale=True)
            check(_credit_core(snapshot, params, lot))
            try:
                result = operator_actions.adjust_credits(cur, book, params['workspaceId'], operation=params['operation'], milli=params['milliCredits'],
                                                         expires_at=params['expiresAt'], grant_id=params['grantId'], reason_code=params['reasonCode'], action_id=action)
            except AlphaError as error:
                raise _from_alpha(error, 'credit_adjustment_refused') from None
            except ValueError:
                raise ActionError('STALE_PREVIEW', 409, 'reversal_exceeds_grant') from None
            return {**result, 'operation': params['operation'], 'milliCredits': params['milliCredits'], 'walletAfter': after}

    # account blocks -----------------------------------------------------------------------------------------------------
    @staticmethod
    def _block_state(snapshot, *, blocked, stale):
        code = 'STALE_PREVIEW' if stale else 'VALIDATION_FAILED'
        if snapshot is None:
            raise ActionError(code, 409 if stale else 404, 'account_not_found')
        if blocked and snapshot['block'] is None:
            raise ActionError(code, 409, 'not_blocked')
        if not blocked and snapshot['block'] is not None:
            raise ActionError(code, 409, 'already_blocked')
        if not blocked and len(snapshot['frozenWorkspaceIds']) > operator_actions.MAX_FROZEN_WORKSPACES:
            raise ActionError(code, 409, 'too_many_workspaces')

    def _account_snapshot(self, params, *, lock=False):
        with self.transaction() as cur:
            self._blocks_installed(cur)
            return operator_actions.block_snapshot(cur, params['targetType'], params['targetId'], lock=lock)

    def block_view(self, params, ctx):
        snapshot = self._account_snapshot(params)
        self._block_state(snapshot, blocked=False, stale=False)
        user = params['targetType'] == 'user'
        display = {'target': snapshot['target'],
                   'current': {'blocked': False},
                   'effect': {'reasonCode': params['reasonCode'], 'approvalRef': params['approvalRef'], 'sessionsRefused': user,
                              'apiTokensRefused': snapshot['activeApiTokens'], 'frozenWorkspaceIds': snapshot['frozenWorkspaceIds'],
                              'publishingAndAutomationsPaused': bool(snapshot['frozenWorkspaceIds']), 'customerCode': operator_actions.CODE,
                              'customerMessage': operator_actions.MESSAGE, 'reversible': True, 'consumerAudit': 'account.blocked'}}
        return _block_core(snapshot), display

    def block_execute(self, row, check):
        params, action = row['params'], row['id']
        with self.transaction() as cur:
            self._blocks_installed(cur)
            done = operator_actions.block_by_action(cur, action)
            if done is not None:
                return {**done, 'duplicate': True, 'consumerAudit': 'account.blocked'}
            snapshot = operator_actions.block_snapshot(cur, params['targetType'], params['targetId'], lock=True)
            self._block_state(snapshot, blocked=False, stale=True)
            check(_block_core(snapshot))
            try:
                return operator_actions.apply_block(cur, target_type=params['targetType'], target_id=params['targetId'],
                                                    frozen_workspace_ids=snapshot['frozenWorkspaceIds'], reason_code=params['reasonCode'],
                                                    approval_ref=params['approvalRef'], operator_id=row['operator_id'], action_id=action)
            except Exception as error:
                if _unique_violation(error):
                    raise ActionError('STALE_PREVIEW', 409, 'already_blocked') from None
                raise

    def unblock_view(self, params, ctx):
        snapshot = self._account_snapshot(params)
        self._block_state(snapshot, blocked=True, stale=False)
        block = snapshot['block']
        display = {'target': snapshot['target'],
                   'current': {'blocked': True, 'blockId': block['blockId'], 'reasonCode': block['reasonCode'], 'blockedAt': stamp(block['blockedAt']),
                               'frozenWorkspaceIds': block['frozenWorkspaceIds']},
                   'effect': {'reasonCode': params['reasonCode'], 'sessionsRestored': params['targetType'] == 'user',
                              'thawedWorkspaceIds': block['frozenWorkspaceIds'], 'consumerAudit': 'account.unblocked'}}
        return {**_block_core(snapshot), 'frozenWorkspaceIds': block['frozenWorkspaceIds']}, display

    def unblock_execute(self, row, check):
        params, action = row['params'], row['id']
        with self.transaction() as cur:
            self._blocks_installed(cur)
            done = operator_actions.lift_by_action(cur, action)
            if done is not None:
                return {'blockId': done['blockId'], 'thawedWorkspaceIds': done['frozenWorkspaceIds'], 'duplicate': True, 'consumerAudit': 'account.unblocked'}
            snapshot = operator_actions.block_snapshot(cur, params['targetType'], params['targetId'], lock=True)
            self._block_state(snapshot, blocked=True, stale=True)
            check({**_block_core(snapshot), 'frozenWorkspaceIds': snapshot['block']['frozenWorkspaceIds']})
            result = operator_actions.lift_block(cur, target_type=params['targetType'], target_id=params['targetId'], block_id=snapshot['block']['blockId'],
                                                 reason_code=params['reasonCode'], operator_id=row['operator_id'], action_id=action)
            if result is None:
                raise ActionError('STALE_PREVIEW', 409, 'not_blocked')
            return result

    # refund intents -----------------------------------------------------------------------------------------------------
    def refund_view(self, params, ctx):
        with self.transaction() as cur:
            snapshot = operator_actions.payment_snapshot(cur, params['workspaceId'], params['paymentIntentId'])
        if snapshot == 'not_configured':
            raise ActionError('POLICY_DISABLED', 409, 'payments_not_configured')
        if snapshot is None:
            raise _invalid('payment_not_found', 404)
        if snapshot['status'] != 'funded':
            raise _invalid('payment_not_settled', 409)
        if snapshot['currency'] != params['currency']:
            raise _invalid('currency_mismatch')
        refundable = max(0, snapshot['paidMinor'] - snapshot['refundedMinor'])
        if params['amountMinor'] > refundable:
            raise _invalid('amount_exceeds_refundable', 409)
        display = {'target': {'type': 'payment', 'workspaceId': params['workspaceId'], 'paymentIntentId': params['paymentIntentId'],
                              'source': snapshot['source'], 'sourceId': snapshot['sourceId'], 'livemode': snapshot['livemode']},
                   'current': {'paidMinor': snapshot['paidMinor'], 'refundedMinor': snapshot['refundedMinor'], 'refunds': snapshot['refunds'],
                               'disputed': snapshot['disputed'], 'currency': snapshot['currency'], 'paidAt': stamp(snapshot['paidAt'])},
                   'effect': {'intent': 'refund', 'amountMinor': params['amountMinor'], 'currency': params['currency'], 'reasonCode': params['reasonCode'],
                              'refundableAfterMinor': refundable - params['amountMinor'], 'executed': False, 'providerRefundCreated': False,
                              'customerNotified': False, 'blocker': 'refund_policy_not_decided'}}
        core = {key: snapshot[key] for key in ('source', 'sourceId', 'paidMinor', 'refundedMinor', 'refunds', 'disputed', 'currency')}
        return core, display


def consumer_actions(app):
    """The consumer side for this app: injected by tests as `app.founder_consumer_actions`, otherwise built over the
    embedded consumer runtime (`app.consumer()` answers 503 SOURCE_UNAVAILABLE on the separate mount)."""
    injected = getattr(app, 'founder_consumer_actions', None)
    return injected if injected is not None else ConsumerActions(app.consumer())


# --- founder_action_requests (068) through the restricted session store ------------------------------------------------
_SELECT = ("SELECT id::text AS id,operator_id::text AS operator_id,environment,kind,target_type,target_id,workspace_id::text AS workspace_id,"
           "params,preview,revision,state,request_id::text AS request_id,confirm_request_id::text AS confirm_request_id,"
           "preview_audit_id::text AS preview_audit_id,confirm_audit_id::text AS confirm_audit_id,result,error_code,blocker,"
           "extract(epoch from created_at) AS created_at,extract(epoch from expires_at) AS expires_at,"
           "extract(epoch from confirmed_at) AS confirmed_at,extract(epoch from finished_at) AS finished_at "
           "FROM rafii_control.founder_action_requests")


def _row(row):
    if row is None:
        return None
    out = dict(row)
    for key in ('created_at', 'expires_at', 'confirmed_at', 'finished_at'):
        out[key] = None if out.get(key) is None else float(out[key])
    for key in ('params', 'preview', 'result'):
        out[key] = dict(out.get(key) or {})
    return out


class ActionStore:
    """Rows of rafii_control.founder_action_requests over rafii_control.store.PostgresStore (session role). Reads are
    environment-wide (068 policy founder_actions_read); writes set the operator GUC transaction-locally, which the insert
    and update policies require, so a founder can never claim another operator's preview."""

    def __init__(self, store):
        self.store, self.environment = store, store.environment

    @contextmanager
    def _operator(self, operator_id):
        with self.store.transaction() as con:
            con.execute("SELECT set_config('rafii_control.operator',%s,true)", (str(operator_id),))
            yield con

    def by_request(self, operator_id, request_id):
        """The row a request id already names, as a preview or as a confirm, in this environment."""
        with self._operator(operator_id) as con:
            row = con.execute(_SELECT + ' WHERE environment=%s AND (request_id=%s OR confirm_request_id=%s) LIMIT 1',
                              (self.environment, request_id, request_id)).fetchone()
        return _row(row)

    def insert_preview(self, row):
        """Insert one preview; (stored row, created). A request id already used by a confirm is a conflict."""
        from psycopg.types.json import Jsonb
        with self._operator(row['operator_id']) as con:
            if con.execute('SELECT 1 FROM rafii_control.founder_action_requests WHERE environment=%s AND confirm_request_id=%s',
                           (self.environment, row['request_id'])).fetchone():
                raise ActionError('IDEMPOTENCY_CONFLICT', 409, 'request_id_used')
            inserted = con.execute(
                'INSERT INTO rafii_control.founder_action_requests(id,operator_id,environment,kind,target_type,target_id,workspace_id,params,preview,revision,'
                "state,request_id,preview_audit_id,blocker,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'previewed',%s,%s,%s,"
                'to_timestamp(%s),to_timestamp(%s)+make_interval(secs=>%s)) ON CONFLICT (request_id) DO NOTHING RETURNING id',
                (row['id'], row['operator_id'], self.environment, row['kind'], row['target_type'], row['target_id'], row['workspace_id'],
                 Jsonb(row['params']), Jsonb(row['preview']), row['revision'], row['request_id'], row['preview_audit_id'], row['blocker'],
                 row['created_at'], row['created_at'], PREVIEW_SECONDS)).fetchone()
            stored = con.execute(_SELECT + ' WHERE environment=%s AND request_id=%s', (self.environment, row['request_id'])).fetchone()
        if stored is None:
            raise ActionError('IDEMPOTENCY_CONFLICT', 409, 'request_id_used')
        return _row(stored), inserted is not None

    def claim(self, operator_id, preview_id, request_id, decide):
        """Lock the preview and let `decide(row or None, id of the row already using request_id or None)` choose:
        it raises to refuse (nothing is written) or returns (outcome, changes); changes confirm the preview."""
        with self._operator(operator_id) as con:
            row = _row(con.execute(_SELECT + ' WHERE id=%s AND environment=%s FOR UPDATE', (preview_id, self.environment)).fetchone())
            if row is not None and row['operator_id'] != str(operator_id):
                row = None
            used = con.execute('SELECT id::text AS id FROM rafii_control.founder_action_requests WHERE environment=%s AND (request_id=%s OR confirm_request_id=%s) LIMIT 1',
                               (self.environment, request_id, request_id)).fetchone()
            outcome, changes = decide(row, used['id'] if used else None)
            if changes:
                con.execute("UPDATE rafii_control.founder_action_requests SET state=%s,confirm_request_id=%s,confirm_audit_id=%s,confirmed_at=to_timestamp(%s) "
                            "WHERE id=%s AND environment=%s AND state='previewed'",
                            (changes['state'], changes['confirm_request_id'], changes['confirm_audit_id'], changes['confirmed_at'], preview_id, self.environment))
                row = _row(con.execute(_SELECT + ' WHERE id=%s AND environment=%s', (preview_id, self.environment)).fetchone())
        return outcome, row

    def finish(self, operator_id, preview_id, state, now, *, result=None, error_code=None, blocker=None):
        from psycopg.types.json import Jsonb
        with self._operator(operator_id) as con:
            con.execute("UPDATE rafii_control.founder_action_requests SET state=%s,result=%s,error_code=%s,blocker=%s,finished_at=to_timestamp(%s) "
                        "WHERE id=%s AND environment=%s AND state='confirmed'",
                        (state, Jsonb(result or {}), error_code, blocker, now, preview_id, self.environment))
            row = con.execute(_SELECT + ' WHERE id=%s AND environment=%s', (preview_id, self.environment)).fetchone()
        return _row(row)

    def recent(self, operator_id, limit, *, kind=None, target_id=None):
        """Recent requests, newest first, or None before 068 is installed (a listing never fails a page)."""
        with self._operator(operator_id) as con:
            if not con.execute("SELECT to_regclass('rafii_control.founder_action_requests') IS NOT NULL AS ready").fetchone()['ready']:
                return None
            rows = con.execute(_SELECT + ' WHERE environment=%s AND (%s::text IS NULL OR kind=%s) AND (%s::text IS NULL OR target_id=%s OR workspace_id::text=%s) '
                               'ORDER BY created_at DESC,id LIMIT %s', (self.environment, kind, kind, target_id, target_id, target_id, int(limit))).fetchall()
        return [_row(row) for row in rows]

    def active_blocks(self, limit=200):
        """Active account blocks through the reader projection (068), or None before it is installed."""
        with self.store.transaction(read=True) as con:
            if not con.execute("SELECT to_regclass('rafii_control.business_account_blocks') IS NOT NULL AS ready").fetchone()['ready']:
                return None
            rows = con.execute('SELECT id,"userId","workspaceId","reasonCode","blockedAt" FROM rafii_control.business_account_blocks WHERE active '
                               'ORDER BY "blockedAt" DESC,id LIMIT %s', (int(limit),)).fetchall()
        return [{'blockId': r['id'], 'userId': r['userId'], 'workspaceId': r['workspaceId'], 'reasonCode': r['reasonCode'],
                 'blockedAt': r['blockedAt'].isoformat() if hasattr(r['blockedAt'], 'isoformat') else r['blockedAt']} for r in rows]

    def expire_stale(self, now, limit=200):
        """Mark previews past their five minutes as expired (bookkeeping for GET /actions; confirms already refuse them)."""
        with self.store.transaction() as con:
            operators = [r['operator_id'] for r in con.execute(
                "SELECT DISTINCT operator_id::text AS operator_id FROM rafii_control.founder_action_requests WHERE environment=%s AND state='previewed' "
                'AND expires_at<=to_timestamp(%s) LIMIT 20', (self.environment, now)).fetchall()]
        expired = 0
        for operator in operators:
            with self._operator(operator) as con:
                expired += max(0, con.execute(
                    "UPDATE rafii_control.founder_action_requests SET state='expired' WHERE id IN (SELECT id FROM rafii_control.founder_action_requests "
                    "WHERE environment=%s AND operator_id=%s AND state='previewed' AND expires_at<=to_timestamp(%s) ORDER BY expires_at LIMIT %s)",
                    (self.environment, operator, now, int(limit))).rowcount)
        return expired


def action_store(app):
    """One ActionStore per app over its restricted session store (`app.founder_action_store` when tests inject one)."""
    store = getattr(app, 'founder_action_store', None)
    if store is None:
        base = getattr(getattr(app, 'queries', None), 'store', None)
        if base is None or not hasattr(base, 'transaction'):
            raise ActionError('SOURCE_UNAVAILABLE', 503)
        store = app.founder_action_store = ActionStore(base)
    return store


# --- protocol ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Spec:
    kind: str
    validate: Callable
    view: str
    execute: str | None = None
    path_target: bool = False
    typed: str | None = None
    blocker: str | None = None
    ready: str | None = None


RECONCILE = Spec('reconcile', _reconcile_params, 'reconcile_view', 'reconcile_execute')
CREDITS = Spec('credits_adjust', _credit_params, 'credits_view', 'credits_execute', ready='credits_book')
BLOCK = Spec('account_block', _block_params, 'block_view', 'block_execute', path_target=True, typed=TYPED_BLOCK)
UNBLOCK = Spec('account_unblock', _unblock_params, 'unblock_view', 'unblock_execute', path_target=True)
REFUND = Spec('refund_intent', _refund_params, 'refund_view', blocker='refund_policy_not_decided')


def effective_state(row, now):
    if row['state'] == 'previewed' and row['expires_at'] is not None and float(row['expires_at']) <= float(now):
        return 'expired'
    return row['state']


def _confirm_path(row):
    if row['kind'] == 'reconcile':
        return '/api/control/v2/usage/reconcile/confirm'
    if row['kind'] == 'credits_adjust':
        return '/api/control/v2/actions/credits/confirm'
    if row['kind'] in ('account_block', 'account_unblock'):
        return f"/api/control/v2/actions/accounts/{row['target_id']}/{'block' if row['kind'] == 'account_block' else 'unblock'}/confirm"
    return None


def public_action(row, now):
    """The founder-facing view of one request row: ids, state, the preview it showed and the outcome. Never the params
    (the reconcile evidence reference stays in the row and the consumer audit)."""
    preview, state = row['preview'], effective_state(row, now)
    confirm = None
    if not row['blocker'] and _confirm_path(row):
        confirm = {'method': 'POST', 'path': _confirm_path(row), 'expiresAt': stamp(row['expires_at']),
                   'requires': ['fresh_second_factor'] + (['typed_confirmation'] if row['kind'] == 'account_block' else []),
                   'typedConfirmation': TYPED_BLOCK if row['kind'] == 'account_block' else None}
    return {'previewId': row['id'], 'kind': row['kind'], 'state': state, 'revision': row['revision'], 'targetType': row['target_type'],
            'targetId': row['target_id'], 'workspaceId': row['workspace_id'], 'target': preview.get('target'), 'current': preview.get('current'),
            'effect': preview.get('effect'), 'result': row['result'] or None, 'errorCode': row['error_code'], 'blocker': row['blocker'],
            'execution': {'allowed': not row['blocker'], 'blocker': row['blocker']}, 'confirm': confirm if state == 'previewed' else None,
            'createdAt': stamp(row['created_at']), 'expiresAt': stamp(row['expires_at']), 'confirmedAt': stamp(row['confirmed_at']),
            'finishedAt': stamp(row['finished_at'])}


def _preview(app, principal, request, spec):
    ctx = _context(app, principal, request)
    body = request['body'] if isinstance(request['body'], dict) else {}
    adapter = None
    if spec.ready:   # a policy gate (credits off) answers before anything else, whatever the body says
        adapter = consumer_actions(app)
        getattr(adapter, spec.ready)()
    request_id = _uuid(body.get('requestId'), 'invalid_request_id')
    params, target_type, target_id, workspace_id = spec.validate(body, request['match'], ctx)
    store = action_store(app)
    existing = store.by_request(ctx['operator'], request_id)
    if existing is not None:
        if (existing['request_id'] != request_id or existing['operator_id'] != ctx['operator'] or existing['kind'] != spec.kind
                or existing['target_id'] != target_id or existing['params'] != params):
            raise ActionError('IDEMPOTENCY_CONFLICT', 409, 'request_id_used')
        return {'action': public_action(existing, ctx['now']), 'replayed': True}
    adapter = adapter or consumer_actions(app)
    core, display = getattr(adapter, spec.view)(params, ctx)
    row = {'id': str(uuid.uuid4()), 'operator_id': ctx['operator'], 'kind': spec.kind, 'target_type': target_type, 'target_id': target_id,
           'workspace_id': workspace_id, 'params': params, 'preview': display, 'revision': revision_of(spec.kind, core), 'request_id': request_id,
           'preview_audit_id': str(uuid.UUID(request['requestId'])), 'blocker': spec.blocker, 'created_at': ctx['now']}
    stored, created = store.insert_preview(row)
    if not created and (stored['kind'] != spec.kind or stored['operator_id'] != ctx['operator'] or stored['params'] != params):
        raise ActionError('IDEMPOTENCY_CONFLICT', 409, 'request_id_used')
    return {'action': public_action(stored, ctx['now']), 'replayed': not created}


def _decide(spec, *, request_id, revision, target_id, audit_id, now):
    """The confirm rules over the locked preview row. Refusals raise before anything is written."""
    def decide(row, used_by):
        if row is None:
            raise _invalid('preview_not_found', 404)
        if row['confirm_request_id'] == request_id:
            return ('replay' if row['state'] in ('executed', 'failed') else 'resume'), None
        if used_by is not None:
            raise ActionError('IDEMPOTENCY_CONFLICT', 409, 'request_id_used')
        if row['kind'] != spec.kind or (target_id is not None and row['target_id'] != target_id):
            raise _invalid('preview_mismatch')
        if row['blocker']:
            raise ActionError('POLICY_DISABLED', 409, row['blocker'])
        if row['state'] != 'previewed':
            raise ActionError('STALE_PREVIEW', 409, 'preview_' + row['state'])
        if float(row['expires_at']) <= now:
            raise ActionError('STALE_PREVIEW', 409, 'preview_expired')
        if revision != row['revision']:
            raise ActionError('STALE_PREVIEW', 409, 'revision_mismatch')
        return 'claimed', {'state': 'confirmed', 'confirm_request_id': request_id, 'confirm_audit_id': audit_id, 'confirmed_at': now}
    return decide


def _replayed(row, now):
    if row['state'] == 'failed':
        raise ActionError(row['error_code'] or 'SOURCE_UNAVAILABLE', None, row['blocker'])
    return {'action': public_action(row, now), 'replayed': True}


def _confirm(app, principal, request, spec):
    ctx = _context(app, principal, request)
    body = request['body'] if isinstance(request['body'], dict) else {}
    _fields(body, ('previewId', 'revision', 'requestId') + (('confirmation',) if spec.typed else ()))
    preview_id, request_id = _uuid(body['previewId'], 'invalid_preview_id'), _uuid(body['requestId'], 'invalid_request_id')
    revision = body['revision']
    if not isinstance(revision, str) or not _REVISION.match(revision):
        raise _invalid('invalid_revision')
    if spec.typed and body['confirmation'] != spec.typed:
        raise _invalid('typed_confirmation_required')
    target_id = _uuid(request['match'][0] if request['match'] else None, 'invalid_target') if spec.path_target else None
    store = action_store(app)
    adapter = consumer_actions(app)         # 503 before anything is claimed when there is no consumer runtime
    if spec.ready:
        getattr(adapter, spec.ready)()      # e.g. credits switched off since the preview: refused, the preview stays unused
    outcome, row = store.claim(ctx['operator'], preview_id, request_id,
                               _decide(spec, request_id=request_id, revision=revision, target_id=target_id,
                                       audit_id=str(uuid.UUID(request['requestId'])), now=ctx['now']))
    if outcome == 'replay':
        return _replayed(row, ctx['now'])

    def check(core):
        if revision_of(row['kind'], core) != row['revision']:
            raise ActionError('STALE_PREVIEW', 409, 'target_changed')

    try:
        result = getattr(adapter, spec.execute)(row, check)
    except ActionError as error:
        store.finish(ctx['operator'], preview_id, 'failed', ctx['now'], error_code=error.code, blocker=error.blocker)
        raise
    except Exception:
        # Unknown outcome (connection lost mid-commit, ...): the row stays 'confirmed'; the same request id resumes it and the
        # consumer effect, keyed by the action id, is applied at most once.
        raise ActionError('SOURCE_UNAVAILABLE', 503, 'outcome_unknown_retry_same_request') from None
    finished = store.finish(ctx['operator'], preview_id, 'executed', ctx['now'], result=result)
    return {'action': public_action(finished, ctx['now']), 'replayed': outcome == 'resume' and bool(result.get('duplicate'))}


# --- route handlers (http.register_route: fn(app, principal, request)) ------------------------------------------------------
def reconcile_preview(app, principal, request):
    return _preview(app, principal, request, RECONCILE)


def reconcile_confirm(app, principal, request):
    return _confirm(app, principal, request, RECONCILE)


def credits_preview(app, principal, request):
    return _preview(app, principal, request, CREDITS)


def credits_confirm(app, principal, request):
    return _confirm(app, principal, request, CREDITS)


def block_preview(app, principal, request):
    return _preview(app, principal, request, BLOCK)


def block_confirm(app, principal, request):
    return _confirm(app, principal, request, BLOCK)


def unblock_preview(app, principal, request):
    return _preview(app, principal, request, UNBLOCK)


def unblock_confirm(app, principal, request):
    return _confirm(app, principal, request, UNBLOCK)


def refund_preview(app, principal, request):
    """Records a refund intent (refunds.prepare). Execution is blocked until the refund policy is decided."""
    return _preview(app, principal, request, REFUND)


def list_actions(app, principal, request):
    """GET /actions (audit.read): recent founder action requests and the active account blocks. Demo has none."""
    now = float(request['now'])
    if request['mode'] == 'demo':
        return {'mode': 'demo', 'actions': [], 'activeBlocks': [], 'reason': 'demo_not_simulated', '_dataState': 'unavailable'}
    query = request['query'] or {}
    raw = query.get('limit', [None])[0]
    if raw is None:
        limit = LIST_DEFAULT
    elif not raw.isdigit() or not 1 <= int(raw) <= LIST_MAX:
        raise _invalid('invalid_limit')
    else:
        limit = int(raw)
    kind = query.get('kind', [None])[0]
    if kind is not None and kind not in KINDS:
        raise _invalid('invalid_kind')
    target = query.get('targetId', [None])[0]
    if target is not None and not _TARGET.match(target):
        raise _invalid('invalid_target')
    store = action_store(app)
    rows = store.recent(str(principal['operator']['user_id']), limit + 1, kind=kind, target_id=target)
    blocks = store.active_blocks()
    return {'mode': 'live', 'actions': [public_action(row, now) for row in (rows or [])[:limit]], 'truncated': len(rows or []) > limit, 'limit': limit,
            'actionsState': 'measured' if rows is not None else 'not_installed',
            'activeBlocks': blocks or [], 'activeBlocksState': 'measured' if blocks is not None else 'not_installed',
            'policies': {'creditsEnabled': _credits_enabled(app), 'refundExecution': {'allowed': False, 'blocker': 'refund_policy_not_decided'}}}


def _credits_enabled(app):
    """Whether credit adjustment could run (the consumer runtime has credits on): True, False, or None when unknown. A
    listing reads this so the page can disable the action with its reason instead of sending a request that fails."""
    try:
        consumer_actions(app).credits_book()
        return True
    except ActionError as error:
        return False if error.code == 'POLICY_DISABLED' else None
    except Exception:  # noqa: BLE001 - no consumer runtime here (separate mount, unconfigured): unknown, never an error
        return None


# --- cron stage (founder_cron.register_stage) ---------------------------------------------------------------------------------
def retention_stage(fstore, service, values, now):
    """Expire unconfirmed previews (Control bookkeeping) and, hourly, purge lifted blocks past their 400-day retention
    (consumer). Bounded; never raises into the tick."""
    summary = {}
    try:
        base = getattr(fstore, 'store', None)
        summary['expiredPreviews'] = ActionStore(base).expire_stale(now) if base is not None and hasattr(base, 'transaction') else None
    except Exception as error:  # noqa: BLE001 - one stage never breaks the founder tick
        summary['expiredPreviews'] = {'status': 'unavailable', 'error': type(error).__name__}
    try:
        if int(float(now) // 60) % 60 != 7:
            summary['blockRetention'] = {'status': 'skipped'}
        else:
            factory = getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)
            if factory is None:
                summary['blockRetention'] = {'status': 'not_configured'}
            else:
                with factory() as db:
                    with db.cursor() as cur:
                        summary['blockRetention'] = operator_actions.purge_lifted(cur)
    except Exception as error:  # noqa: BLE001
        summary['blockRetention'] = {'status': 'unavailable', 'error': type(error).__name__}
    return summary


# --- registration (CONTRACTS §8.0: routes from the slice module, not the shared dispatch) --------------------------------------
_ACTION = {'step_up': True, 'budget': 'founder.action'}
http.register_route('POST', r'/usage/reconcile/preview', 'usage.reconcile', 'founder_actions', 'reconcile_preview', **_ACTION)
http.register_route('POST', r'/usage/reconcile/confirm', 'usage.reconcile', 'founder_actions', 'reconcile_confirm', **_ACTION)
http.register_route('POST', r'/actions/credits/preview', 'credits.adjust', 'founder_actions', 'credits_preview', **_ACTION)
http.register_route('POST', r'/actions/credits/confirm', 'credits.adjust', 'founder_actions', 'credits_confirm', **_ACTION)
http.register_route('POST', r'/actions/accounts/' + _ID_PATH + r'/block/preview', 'accounts.block', 'founder_actions', 'block_preview', **_ACTION)
http.register_route('POST', r'/actions/accounts/' + _ID_PATH + r'/block/confirm', 'accounts.block', 'founder_actions', 'block_confirm', **_ACTION)
http.register_route('POST', r'/actions/accounts/' + _ID_PATH + r'/unblock/preview', 'accounts.block', 'founder_actions', 'unblock_preview', **_ACTION)
http.register_route('POST', r'/actions/accounts/' + _ID_PATH + r'/unblock/confirm', 'accounts.block', 'founder_actions', 'unblock_confirm', **_ACTION)
http.register_route('POST', r'/actions/refunds/preview', 'refunds.prepare', 'founder_actions', 'refund_preview', **_ACTION)
http.register_route('GET', r'/actions', 'audit.read', 'founder_actions', 'list_actions')

try:
    from . import founder_cron
except Exception:  # noqa: BLE001 - the routes above must not depend on the cron slice importing cleanly
    founder_cron = None
if founder_cron is not None and not any(name == 'account_block_retention' for name, _ in founder_cron.STAGES):
    founder_cron.register_stage('account_block_retention', retention_stage)
