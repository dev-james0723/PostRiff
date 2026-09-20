"""Tenant/RLS and persisted command coverage for Raffi campaign/suggestion state."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
FOREIGN = "00000000-0000-0000-0000-000000000099"


def connection(): return psycopg.connect(DSN)
def verify(token): return ONE if token == "one" else FOREIGN
verify.session_id = lambda token, principal: "session-planning-0123456789"
verify.auth_time = lambda token, principal: __import__("time").time()

service = HostedWorkspaceService(connection, verify, clock=lambda: 1_800_000_000)
snapshot = service.bootstrap("one", "studio")
workspace_id = snapshot["workspaceId"]
created = service.mutate(workspace_id, "one", snapshot["revision"], "raffi_campaign_create", {"goal": "Promote the autumn concert", "audience": "Local listeners", "facts": {"date": "2027-10-01", "venue": "Hall A"}})
campaign = created["state"]["raffi"]["campaignPlanning"]["campaigns"][0]
previewed = service.mutate(workspace_id, "one", created["revision"], "raffi_recurrence_preview", {"campaignId": campaign["id"], "schedule": {"weekday": "Monday", "localTime": "09:00", "timeZone": "America/New_York"}})
task = previewed["state"]["raffi"]["campaignPlanning"]["recurringTasks"][0]
activated = service.mutate(workspace_id, "one", previewed["revision"], "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True})
assert activated["state"]["raffi"]["campaignPlanning"]["recurringTasks"][0]["status"] == "active"

try:
    service.get(workspace_id, "two")
    raise AssertionError("foreign workspace planning state leaked")
except AlphaError as error:
    assert error.status == 403

for table in ("pr_campaigns", "pr_recurring_tasks", "pr_recurring_occurrences", "pr_suggestions"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (FOREIGN,))
        assert db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (workspace_id,)).fetchone()[0] == 0
        try:
            db.execute(f"DELETE FROM public.{table} WHERE workspace_id=%s", (workspace_id,))
            raise AssertionError(f"browser delete accepted for {table}")
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()

print("PASS: campaign and recurrence persist; owner activation and tenant/RLS boundaries hold")
