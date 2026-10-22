"""Owner consent, pause fence and bounded retention for Telegram automation."""
from contextlib import contextmanager
from postriff_alpha.domain import AlphaError
from ..permissions import require


DEFAULT = {"paused": True, "approvalPolicy": "always", "allowedConnections": [], "allowedActions": [], "retentionDays": 7, "revision": 0}
ACTIONS = frozenset({"publish"})


def present(row):
    return dict(DEFAULT) if not row else dict(zip(DEFAULT, row))


class TelegramControls:
    def __init__(self, telegram):
        self.telegram, self.repository = telegram, telegram.repository

    def get(self, workspace, token):
        with self.repository.transaction(token, workspace) as (cur, _, _):
            cur.execute("SELECT paused,approval_policy,allowed_connections,allowed_actions,retention_days,revision FROM public.pr_telegram_automation_controls WHERE workspace_id=%s", (workspace,))
            return present(cur.fetchone())

    def set(self, workspace, token, body):
        from ..hosted import _membership, audit
        if not isinstance(body, dict) or set(body) - {"paused", "approvalPolicy", "allowedConnections", "allowedActions", "retentionDays", "confirmed", "revision"}:
            raise AlphaError("Invalid Telegram consent settings.", 400)
        paused, policy = body.get("paused"), body.get("approvalPolicy", "always")
        connections, actions, retention = body.get("allowedConnections", []), body.get("allowedActions", []), body.get("retentionDays", 7)
        if type(paused) is not bool or policy not in ("always", "scoped_auto") or type(retention) is not int or not 1 <= retention <= 90:
            raise AlphaError("Invalid Telegram automation policy.", 400)
        if not isinstance(connections, list) or len(connections) > 100 or any(not isinstance(c, str) or not 8 <= len(c) <= 120 for c in connections):
            raise AlphaError("Select authorized Telegram destinations.", 400)
        if not isinstance(actions, list) or any(not isinstance(a, str) or a not in ACTIONS for a in actions) or len(actions) > 3:
            raise AlphaError("Select supported Telegram automation actions.", 400)
        if not paused and (body.get("confirmed") is not True or not connections or not actions):
            raise AlphaError("Confirm the exact selected destinations and automatic actions.", 403)
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), "owner")
            self.repository.assert_fresh(token, actor)
            cur.execute("SELECT revision FROM public.pr_telegram_automation_controls WHERE workspace_id=%s FOR UPDATE", (workspace,))
            current = cur.fetchone()
            if type(body.get("revision")) is not int or body["revision"] != (current[0] if current else 0):
                raise AlphaError("Telegram settings changed. Review the current settings.", 409)
            if connections:
                cur.execute("SELECT connection_id FROM public.pr_telegram_destinations WHERE workspace_id=%s AND connection_id=ANY(%s) AND revoked_at IS NULL", (workspace, connections))
                if set(connections) != {r[0] for r in cur.fetchall()}:
                    raise AlphaError("A selected Telegram destination is unavailable.", 404)
            cur.execute("INSERT INTO public.pr_telegram_automation_controls(workspace_id,paused,approval_policy,allowed_connections,allowed_actions,retention_days,updated_by) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id) DO UPDATE SET paused=excluded.paused,approval_policy=excluded.approval_policy,allowed_connections=excluded.allowed_connections,allowed_actions=excluded.allowed_actions,retention_days=excluded.retention_days,updated_by=excluded.updated_by,revision=pr_telegram_automation_controls.revision+1,updated_at=now() RETURNING paused,approval_policy,allowed_connections,allowed_actions,retention_days,revision", (workspace, paused, policy, connections, actions, retention, actor))
            value = present(cur.fetchone())
            audit(cur, workspace, actor, "telegram.automation.paused" if paused else "telegram.automation.consented", "", value)
            return value

    @contextmanager
    def dispatch_guard(self, workspace, connection, action, *, human_approved=False):
        # Hold the row through the bounded provider request. A committed pause
        # guarantees no new automated send can begin using an earlier policy.
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT paused,approval_policy,allowed_connections,allowed_actions FROM public.pr_telegram_automation_controls WHERE workspace_id=%s FOR UPDATE", (workspace,))
                row = cur.fetchone()
                if not row or row[0] or connection not in row[2] or action not in row[3]:
                    raise AlphaError("Telegram automation is paused or outside its consent scope.", 409)
                if row[1] == "always" and not human_approved:
                    raise AlphaError("This Telegram action needs human approval.", 403)
                yield

    def prune(self, limit=1000):
        """Worker maintenance: bounded batches; expired content never enters AI context."""
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                count = 0
                for table in ("pr_telegram_messages", "pr_telegram_business_inbox", "pr_telegram_dm_inbox"):
                    cur.execute("DELETE FROM public." + table + " WHERE ctid IN (SELECT m.ctid FROM public." + table + " m LEFT JOIN public.pr_telegram_automation_controls c USING(workspace_id) WHERE m.date < extract(epoch from now() - make_interval(days=>coalesce(c.retention_days,7))) LIMIT %s)", (limit,))
                    count += cur.rowcount
                return {"deleted": count, "batchLimitPerTable": limit}
