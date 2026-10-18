"""Conservative durable Pinterest budgets. No in-memory counter or token is authority."""
import hashlib
import time
from postriff_alpha.domain import AlphaError


class PinterestQuota:
    def __init__(self, connection_factory, client_id, environment, clock=time.time, *, trial=False):
        self.connection_factory, self.clock = connection_factory, clock
        self.trial = trial
        self.app = hashlib.sha256(f'{environment}:{client_id}'.encode()).hexdigest()

    def __call__(self, method, path, account_id=None):
        write = method not in ('GET', 'HEAD') and '/oauth/token' not in path
        minute = int(self.clock() // 60) * 60
        budgets = [(self.app + ':all', minute, 1000)]
        if self.trial:
            # Rafii pilot cap: 100/day, below Pinterest Trial's 1000/day universal cap.
            # At most 200 across two UTC dates in any rolling day. Counts token calls too.
            budgets.insert(0, (self.app + ':trial-day', int(self.clock() // 86400) * 86400, 100))
        if write:
            if not account_id:
                raise AlphaError('Pinterest publishing needs a freshly verified account binding.', 409)
            account = hashlib.sha256(str(account_id).encode()).hexdigest()
            budgets += [(self.app + ':write', minute, 100), (self.app + ':account:' + account, minute, 100)]
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                for key, window, limit in budgets:
                    cur.execute('INSERT INTO public.pr_pinterest_rate_budgets(budget_key,window_start,used) VALUES(%s,%s,1) '
                        'ON CONFLICT(budget_key,window_start) DO UPDATE SET used=pr_pinterest_rate_budgets.used+1 '
                        'WHERE pr_pinterest_rate_budgets.used<%s RETURNING used', (key, window, limit))
                    if not cur.fetchone():
                        raise AlphaError('Pinterest request budget reached. Wait before trying again.', 429, code='pinterest_rate_limited')
        except AlphaError:
            raise
        except Exception as error:
            raise AlphaError('Pinterest rate-budget storage is unavailable. Publishing is paused.', 503, code='pinterest_quota_unavailable') from error


    def _trial_identifiers(self, policy, intent, *, require_active=True):
        if require_active:
            policy.require(policy.workspace_id)
        if not isinstance(intent, str) or not 1 <= len(intent) <= 256:
            raise AlphaError('The private Trial intent is invalid.', 403, code='pinterest_trial_denied')
        import json
        try:
            scope = hashlib.sha256(json.dumps(policy.binding(), sort_keys=True).encode()).hexdigest()
            authority = hashlib.sha256((self.app + ':' + scope).encode()).hexdigest()
            intent_hash = hashlib.sha256(intent.encode()).hexdigest()
            expiry = policy.expires_at
            if type(expiry) is not int or expiry <= 0:
                raise ValueError('expiry')
        except (AttributeError, TypeError, ValueError):
            raise AlphaError('Private Trial authority is unavailable.', 503, code='pinterest_quota_unavailable') from None
        return scope, authority, intent_hash, expiry

    def reserve_trial_create(self, policy, intent):
        """Commit max2/pilot, max1/intent and a prepared response row before provider I/O.

        The independent transaction is never refunded by the workspace transaction.
        Missing journal schema fails closed and rolls back both tentative rate counters.
        """
        scope, authority, intent_hash, expiry = self._trial_identifiers(policy, intent)
        budgets = [(self.app + ':private:' + scope, 2), (self.app + ':intent:' + scope + ':' + intent_hash, 1)]
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                for key, limit in budgets:
                    cur.execute('INSERT INTO public.pr_pinterest_rate_budgets(budget_key,window_start,used) VALUES(%s,%s,1) '
                        'ON CONFLICT(budget_key,window_start) DO UPDATE SET used=pr_pinterest_rate_budgets.used+1 '
                        'WHERE pr_pinterest_rate_budgets.used<%s RETURNING used', (key, expiry, limit))
                    if not cur.fetchone():
                        raise AlphaError('This private Trial create intent or its two-attempt budget was already consumed. Reconcile; do not resubmit.',
                                         409, code='pinterest_trial_intent_consumed')
                cur.execute('INSERT INTO public.pr_pinterest_trial_intents(authority_hash,intent_hash,expires_at) '
                            'VALUES(%s,%s,to_timestamp(%s))', (authority, intent_hash, expiry))
        except AlphaError:
            raise
        except Exception:
            raise AlphaError('Private Trial attempt storage is unavailable.', 503, code='pinterest_quota_unavailable') from None

    def acknowledge_trial_create(self, policy, intent, pin_id):
        """Persist only a prepared exact intent's known response ID, including after expiry.

        This local evidence write grants no provider action and cannot create a row,
        replace an ID, move authority or extend expiry. Repeating the same ID is safe.
        """
        import re
        if not isinstance(pin_id, str) or not re.fullmatch(r'[0-9]{5,30}', pin_id):
            raise AlphaError('Pinterest returned an invalid Pin reference.', 502, code='pinterest_trial_journal_invalid')
        _, authority, intent_hash, expiry = self._trial_identifiers(policy, intent, require_active=False)
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute('UPDATE public.pr_pinterest_trial_intents SET pin_id=%s '
                            'WHERE authority_hash=%s AND intent_hash=%s AND expires_at=to_timestamp(%s) '
                            'AND (pin_id IS NULL OR pin_id=%s) RETURNING pin_id',
                            (pin_id, authority, intent_hash, expiry, pin_id))
                row = cur.fetchone()
                if not row:
                    raise AlphaError('The private Trial response does not match a prepared intent.', 409,
                                     code='pinterest_trial_journal_conflict')
                return row[0]
        except AlphaError:
            raise
        except Exception:
            raise AlphaError('Private Trial response storage is unavailable.', 503, code='pinterest_quota_unavailable') from None

    def recovered_trial_pin(self, policy, intent):
        """Read this active authority's exact prepared response; never discover arbitrary Pins."""
        import re
        _, authority, intent_hash, expiry = self._trial_identifiers(policy, intent)
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT pin_id,expires_at>clock_timestamp() FROM public.pr_pinterest_trial_intents '
                            'WHERE authority_hash=%s AND intent_hash=%s AND expires_at=to_timestamp(%s)',
                            (authority, intent_hash, expiry))
                row = cur.fetchone()
                if not row:
                    return None
                if row[1] is not True:
                    raise AlphaError('This private Pinterest Trial has expired.', 403, code='pinterest_trial_denied')
                if row[0] is None:
                    return None
                if not isinstance(row[0], str) or not re.fullmatch(r'[0-9]{5,30}', row[0]):
                    raise AlphaError('Private Trial response storage is unavailable.', 503, code='pinterest_quota_unavailable')
                return row[0]
        except AlphaError:
            raise
        except Exception:
            raise AlphaError('Private Trial response storage is unavailable.', 503, code='pinterest_quota_unavailable') from None
