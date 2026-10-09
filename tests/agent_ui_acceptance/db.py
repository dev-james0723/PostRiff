"""Before/after counters on the disposable acceptance database (psycopg; the harness's own loopback cluster only).

`snapshot(workspace_id)` captures everything a UI request could change: the business record (workspace revision + state
digest), audit, messages, runs, ledger and attempt rows, and the agent-UI tables. `delta(before, after)` is what a check
asserts on: a refused write must leave every business counter unchanged; an applied action changes them exactly once.
Setup helpers write fixtures (memberships, expiry, fault arms) — assertions never read through a privilege the API lacks.
"""
from __future__ import annotations

import json

BUSINESS = ("workspace_revision", "workspace_state", "audit", "messages", "agent_runs", "jobs", "approvals")
SPEND = ("ledger_reserve", "ledger_settle", "ledger_unknown", "ledger_release", "ai_calls")
UI = ("ui_artifacts", "ui_revisions", "ui_attempts", "ui_events", "ui_actions", "ui_actions_done", "ui_activations", "ui_activations_used")


def _connect(dsn):
    import psycopg
    return psycopg.connect(dsn, client_encoding="utf8", autocommit=True)


class Db:
    def __init__(self, dsn: str):
        if not dsn.startswith("host=127.0.0.1 ") and not dsn.startswith("host=localhost "):
            raise ValueError("acceptance counters run against the loopback disposable database only")
        self.dsn = dsn
        self._tables = None

    def one(self, sql, *params):
        with _connect(self.dsn) as db:
            row = db.execute(sql, params).fetchone()
        return row

    def all(self, sql, *params):
        with _connect(self.dsn) as db:
            return db.execute(sql, params).fetchall()

    def run(self, sql, *params):
        with _connect(self.dsn) as db:
            db.execute(sql, params)

    def tables(self) -> set:
        if self._tables is None:
            self._tables = {r[0] for r in self.all("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
        return self._tables

    def _count(self, table, where="workspace_id=%s", *params):
        if table not in self.tables():
            return None
        return self.one(f"SELECT count(*) FROM public.{table} WHERE {where}", *params)[0]

    def snapshot(self, workspace_id: str) -> dict:
        w = str(workspace_id)
        rev = self.one("SELECT revision, md5(state::text) FROM public.pr_workspaces WHERE id=%s", w)
        out = {"workspace_revision": rev[0] if rev else None, "workspace_state": rev[1] if rev else None,
               "audit": self._count("pr_audit_events", "workspace_id=%s", w), "messages": self._count("pr_messages", "workspace_id=%s", w),
               "agent_runs": self._count("pr_agent_runs", "workspace_id=%s", w), "jobs": self._count("pr_jobs", "workspace_id=%s", w),
               "approvals": self._count("pr_approvals", "workspace_id=%s", w)}
        for kind in ("reserve", "settle", "release"):
            out[f"ledger_{kind}"] = self._count("pr_usage_ledger", "workspace_id=%s AND kind=%s", w, kind)
        out["ledger_unknown"] = self._count("pr_usage_ledger", "workspace_id=%s AND cost_state='estimated_unknown'", w)
        out["ai_calls"] = self._count("pr_ai_call_events", "workspace_id=%s", w)
        out["ui_artifacts"] = self._count("pr_ui_artifacts", "workspace_id=%s", w)
        out["ui_revisions"] = self._count("pr_ui_revisions", "workspace_id=%s", w)
        out["ui_attempts"] = self._count("pr_ui_attempts", "workspace_id=%s", w)
        out["ui_events"] = self._count("pr_ui_events", "workspace_id=%s", w)
        out["ui_actions"] = self._count("pr_ui_actions", "workspace_id=%s", w)
        out["ui_actions_done"] = self._count("pr_ui_actions", "workspace_id=%s AND state='done'", w)
        out["ui_activations"] = self._count("pr_ui_activations", "workspace_id=%s", w)
        out["ui_activations_used"] = self._count("pr_ui_activations", "workspace_id=%s AND used_at IS NOT NULL", w)
        return out

    @staticmethod
    def delta(before: dict, after: dict) -> dict:
        out = {}
        for key, value in after.items():
            old = before.get(key)
            if isinstance(value, int) and isinstance(old, int):
                if value != old:
                    out[key] = value - old
            elif value != old:
                out[key] = "changed"
        return out

    @staticmethod
    def business_changes(delta: dict) -> dict:
        return {k: v for k, v in delta.items() if k in BUSINESS or k in ("ui_actions_done",)}

    @staticmethod
    def spend_changes(delta: dict) -> dict:
        return {k: v for k, v in delta.items() if k in SPEND}

    # --- fixtures (setup only) ------------------------------------------------------------------------------------------
    def add_member(self, workspace_id, user_id, role):
        self.run("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active') "
                 "ON CONFLICT (workspace_id,user_id) DO UPDATE SET role=excluded.role, status='active'", str(workspace_id), str(user_id), role)

    def set_member_status(self, workspace_id, user_id, status):
        self.run("UPDATE public.pr_memberships SET status=%s WHERE workspace_id=%s AND user_id=%s", status, str(workspace_id), str(user_id))

    def expire(self, principal, expired=True):
        self.run("CREATE TABLE IF NOT EXISTS public.agent_ui_acceptance_expired(principal uuid primary key)")
        if expired:
            self.run("INSERT INTO public.agent_ui_acceptance_expired VALUES(%s) ON CONFLICT DO NOTHING", str(principal))
        else:
            self.run("DELETE FROM public.agent_ui_acceptance_expired WHERE principal=%s", str(principal))

    def arm_fault(self, workspace_id, fault: str, count: int = 1):
        """Fault injection read by serve.py's provider stand-in (tests only): malformed | truncated | no_usage | slow | error."""
        self.run("CREATE TABLE IF NOT EXISTS public.agent_ui_acceptance_faults(workspace_id uuid, fault text, remaining int, armed_at timestamptz default now())")
        self.run("DELETE FROM public.agent_ui_acceptance_faults WHERE workspace_id=%s", str(workspace_id))
        if fault:
            self.run("INSERT INTO public.agent_ui_acceptance_faults(workspace_id,fault,remaining) VALUES(%s,%s,%s)", str(workspace_id), fault, count)

    def artifact(self, artifact_id):
        if "pr_ui_artifacts" not in self.tables():
            return None
        row = self.one("SELECT row_to_json(a) FROM public.pr_ui_artifacts a WHERE id=%s", str(artifact_id))
        return row[0] if row else None

    def attempts(self, artifact_id):
        if "pr_ui_attempts" not in self.tables():
            return []
        return [r[0] for r in self.all("SELECT row_to_json(t) FROM public.pr_ui_attempts t WHERE artifact_id=%s ORDER BY created_at", str(artifact_id))]

    def ledger_for(self, reservation_id):
        return [r[0] for r in self.all("SELECT row_to_json(l) FROM public.pr_usage_ledger l WHERE reservation_id::text=%s OR id::text=%s ORDER BY at",
                                       str(reservation_id), str(reservation_id))]

    def ledger_rows(self, workspace_id, like):
        return [r[0] for r in self.all("SELECT row_to_json(l) FROM public.pr_usage_ledger l WHERE workspace_id=%s AND idempotency_key LIKE %s ORDER BY at",
                                       str(workspace_id), like)]

    def dump(self, value) -> str:
        return json.dumps(value, default=str, sort_keys=True)
