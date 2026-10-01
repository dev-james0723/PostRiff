"""Test doubles for the Signature Series slice: an in-memory workspace repository with the PostgreSQL repository's
contract (verified principal per token, active membership row, requirement check, compare-and-swap revision, the
trusted command on a copy, audit/after in the same "transaction", nothing saved when the command raises), plus
workspace builders from the fixed review set (tests/fixtures/product_growth/review_set_v1.json)."""
import contextlib
import copy
import datetime as dt
import json
import pathlib

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.coworker import flags
from postriff_phase2.permissions import Membership, require

ROOT = pathlib.Path(__file__).resolve().parent
REVIEW_SET = json.loads((ROOT / "fixtures/product_growth/review_set_v1.json").read_text())
NOW = dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc).timestamp()
DAY = 86400


def case(case_id):
    return next(c for c in REVIEW_SET["cases"] if c["id"] == case_id)


class Flags:
    """Attach a flag source for one test and restore the previous one."""

    def __init__(self, **values):
        self.values = {name: "1" if on else "" for name, on in values.items()}

    def __enter__(self):
        self.saved = flags._values
        flags.attach(self.values)
        return self

    def __exit__(self, *_exc):
        flags._values = self.saved


class Cursor:
    def __init__(self, log):
        self.log, self.rowcount = log, 1

    def execute(self, sql, params=None):
        self.log.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class Repository:
    def __init__(self):
        self.workspaces, self.tokens, self.sql, self.audits, self.commands = {}, {}, [], [], 0

    def add(self, workspace_id, state, members):
        self.workspaces[workspace_id] = {"revision": 1, "state": state, "members": dict(members)}

    @contextlib.contextmanager
    def transaction(self, token, workspace_id, *, allow_deleting=False):
        user = self.tokens.get(token)
        workspace = self.workspaces.get(workspace_id)
        if user is None:
            raise AlphaError("Verified session required.", 401)
        if workspace is None or user not in workspace["members"]:
            raise AlphaError("Workspace unavailable.", 403)
        row = (workspace["revision"], copy.deepcopy(workspace["state"]), workspace["members"][user], False, False, False, False)
        yield Cursor(self.sql), row, user

    def get(self, workspace_id, token):
        with self.transaction(token, workspace_id) as (_cur, row, _principal):
            return {"revision": row[0], "state": row[1], "membership": Membership.from_row(*row[2:7]).summary()}

    def command(self, workspace_id, token, revision, trusted, requirement="edit", step_up=False, audit_event=None, after=None):
        with self.transaction(token, workspace_id) as (cur, row, principal):
            require(Membership.from_row(*row[2:7]), requirement)
            if type(revision) is not int or revision != row[0]:
                raise AlphaError("Workspace changed; reload.", 409, code="workspace_revision_conflict")
            state = trusted(copy.deepcopy(row[1]), principal)
            workspace = self.workspaces[workspace_id]
            workspace["state"], workspace["revision"] = state, workspace["revision"] + 1
            self.commands += 1
            if audit_event:
                self.audits.append((workspace_id, principal) + tuple(audit_event(state)))
            if after:
                after(cur, state, principal)
            return {"revision": workspace["revision"], "state": state}


class Hosted:
    def __init__(self, repository, clock):
        self.repository, self.clock, self.commands = repository, clock, None


def post(job_id, text, days_old, *, language="en", platform="Threads", reference=None):
    return {"id": job_id, "state": "verified", "providerReference": reference or f"ref-{job_id}", "verification": {"at": NOW - days_old * DAY},
            "manifest": {"platform": platform, "channelId": "acct", "payload": {"text": text, "language": language}}}


def source(source_id, text, *, approved=True, title="Source"):
    facts = [{"id": f"{source_id}-f{i}", "text": line, "approved": approved, "sourceId": source_id, "locator": f"paragraph {i + 1}"}
             for i, line in enumerate(line for line in text.split("\n") if line.strip())]
    return {"id": source_id, "kind": "text", "title": title, "text": text, "fingerprint": f"fp-{source_id}", "active": True, "facts": facts,
            "createdAt": NOW - 3 * DAY, "reviewedAt": "2026-09-28T12:00:00+00:00", "sourcePolicy": "publishable"}


def variant(variant_id, text, *, platform="Threads", language="en"):
    return {"id": variant_id, "text": text, "platform": platform, "language": language, "revision": 1, "sourceIds": [], "unknowns": [], "warnings": [],
            "needsReview": False, "blockedByRetraction": False, "rejected": False}


def workspace(workspace_id="w1"):
    state = initial_state(workspace_id)
    state["phase2"] = {"channels": [], "jobs": [], "reviews": [], "assets": []}
    state["raffi"] = {"campaignPlanning": {"campaigns": [], "recurringTasks": [], "occurrences": []}}
    return state
