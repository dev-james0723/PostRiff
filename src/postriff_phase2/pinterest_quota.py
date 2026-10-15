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
