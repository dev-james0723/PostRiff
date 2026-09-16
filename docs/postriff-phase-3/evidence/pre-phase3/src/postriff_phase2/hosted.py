"""Hosted boundary candidate. Not mounted by the local launcher.

The caller supplies a connection factory and a server-side verified Auth principal.
No browser may supply the principal. No service key or profile metadata is accepted.
"""
from contextlib import contextmanager
import copy
import io
import json
import time
import zipfile
from postriff_alpha.domain import AlphaError
from postriff_alpha.domain import Store
from .auth import initial_phase2_state
from .contracts import FixtureImages, FixtureSocial, PLANS
from .store import Phase2Store, IN_FLIGHT, find
from .content_types import ensure_content_state, projection as content_projection


class PostgresWorkspaceRepository:
    def __init__(self, connection_factory, verify_session, commands=None):
        self.connection_factory = connection_factory
        self.verify_session = verify_session
        self.commands = commands

    @contextmanager
    def transaction(self, token, workspace_id):
        principal = self.verify_session(token)  # Exact verified auth.users.id, never metadata.
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT w.revision,w.state,m.role FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w", (workspace_id, principal))
                row = cur.fetchone()
                if not row:
                    raise AlphaError("Workspace unavailable.", 403)
                yield cur, row, principal

    def get(self, workspace_id, token):
        with self.transaction(token, workspace_id) as (_, row, _):
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            return {"revision": row[0], "state": copy.deepcopy(state)}

    def command(self, workspace_id, token, revision, trusted_command):
        """trusted_command is application code, never a client-submitted patch."""
        with self.transaction(token, workspace_id) as (cur, row, principal):
            if row[2] not in ('owner', 'editor'):
                raise AlphaError("Read-only membership.", 403)
            if type(revision) is not int or revision != row[0]:
                raise AlphaError("Workspace changed; reload.", 409)
            source = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            state = trusted_command(copy.deepcopy(source), principal)
            if not isinstance(state, dict):
                raise AlphaError("The hosted command returned invalid state.", 500)
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            return {"revision": revision+1, "state": state}

    def mutate(self, workspace_id, token, expected_revision, action, payload):
        if self.commands is None:
            raise AlphaError("Hosted command routing has not been configured.", 503)
        if not isinstance(action, str) or not isinstance(payload, dict):
            raise AlphaError("Expected a structured command.")
        return self.command(workspace_id, token, expected_revision, lambda state, principal: self.commands(state, principal, action, payload))


class _NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AlphaError("This account operation must use the hosted identity service.", 409)


class HostedPhase2Commands:
    """Shared state commands with every SQLite-only shortcut disabled."""
    SERVER_ACTIONS = {
        "logout", "revoke_device", "link_identity", "unlink_identity", "delete_account",
        "media_upload", "media_delete", "channel_add", "channel_verify", "art_generate",
    }

    def __init__(self, clock=time.time):
        self.clock = clock
        self.engine = Phase2Store.__new__(Phase2Store)
        self.engine.clock = clock
        self.engine.social = FixtureSocial()
        self.engine.images = FixtureImages()

    def present(self, state, revision):
        return self.engine._present(state, revision)

    def __call__(self, state, principal, action, payload):
        if not isinstance(action, str) or not isinstance(payload, dict):
            raise AlphaError("Expected a structured command.")
        if state.get("workspace", {}).get("sample"):
            raise AlphaError("Hosted sample workspaces are read-only.", 403)
        ensure_content_state(state)
        if action.startswith("p2_"):
            hosted_action = action[3:]
            if hosted_action in self.SERVER_ACTIONS:
                raise AlphaError("This operation requires its dedicated hosted endpoint.", 409)
            self.engine.apply_phase2(_NoDatabase(), state, hosted_action, payload, {"id": "supabase-session", "user_id": principal})
        else:
            if action in ("generate", "adapt"):
                trial = state["phase2"]["trial"]
                if trial["expiresAt"] <= self.clock() or trial["writingUsed"] >= trial["writingGrant"]:
                    raise AlphaError("The trial has no writing allowance left. Drafts and exports remain available.")
                trial["writingUsed"] += 1
            self.engine._apply(state, action, payload)
            if action in ("generate", "adapt") and state.get("variants"):
                selection = ensure_content_state(state)["selection"]
                variant = state["variants"][-1]
                selected_type = next((item for item in content_projection(state)["catalog"] if item["id"] == selection["contentTypeId"]), None)
                variant.update({"contentTypeId": selection["contentTypeId"], "contentTypeVersion": selection["contentTypeVersion"], "formatId": selection["formatId"], "contentSkillRouteIds": selected_type["skillRouteIds"] if selected_type else []})
            if action in ("variant_edit", "opening"):
                variant = self.engine._variant(state, payload.get("variantId"))
                variant["needsReview"] = True
                previous = variant.pop("uncertaintyReview", {})
                variant["unknowns"] = previous.get("excludedFromDraft", variant["unknowns"])
        self.engine.invalidate(state)
        return state

    def add_asset(self, state, principal, asset):
        if state["membership"]["userId"] != principal or asset.get("data"):
            raise AlphaError("Invalid hosted asset metadata.", 403)
        if any(item["id"] == asset["id"] for item in state["phase2"]["assets"]):
            raise AlphaError("This asset already exists.", 409)
        state["phase2"]["assets"].append(copy.deepcopy(asset))
        return state

    def prepare_asset_delete(self, state, principal, asset_id):
        if state["membership"]["userId"] != principal:
            raise AlphaError("Workspace unavailable.", 403)
        asset = find(state["phase2"]["assets"], asset_id)
        if any(job["state"] in IN_FLIGHT and any(media["id"] == asset_id for media in job["manifest"]["media"]) for job in state["phase2"]["jobs"]):
            raise AlphaError("Reconcile this asset's in-flight jobs before deleting its bytes.")
        asset.update({"deleted": True, "deletionPending": True})
        self.engine.invalidate(state)
        return state

    def finish_asset_delete(self, state, principal, asset_id):
        if state["membership"]["userId"] != principal:
            raise AlphaError("Workspace unavailable.", 403)
        asset = find(state["phase2"]["assets"], asset_id)
        if not asset.get("deletionPending"):
            raise AlphaError("This asset is not pending deletion.", 409)
        asset.pop("objectName", None)
        asset.pop("storagePath", None)
        asset["deletionPending"] = False
        return state

    def upsert_verified_channel(self, state, principal, channel):
        required = {"id", "platform", "account", "accountType", "language", "scopes", "verifiedAt", "expiresAt", "capabilityVersion", "providerAccountId"}
        if state["membership"]["userId"] != principal or set(channel) != required or channel["platform"] not in ("LinkedIn", "Instagram"):
            raise AlphaError("A complete server-verified channel record is required.")
        saved = copy.deepcopy(channel)
        saved.update({"configured": True, "identityVerified": True, "capabilityVerified": True, "revoked": False, "qualification": "server_verified", "evidenceSource": "live_provider", "scenario": None})
        existing = next((item for item in state["phase2"]["channels"] if item["id"] == saved["id"]), None)
        if existing:
            existing.clear()
            existing.update(saved)
        else:
            state["phase2"]["channels"].append(saved)
        self.engine.invalidate(state)
        return state


class HostedWorkspaceService:
    """Compose verified Supabase principals, PostgreSQL state, and private media."""
    def __init__(self, connection_factory, verify_session, assets=None, clock=time.time):
        self.connection_factory = connection_factory
        self.verify_session = verify_session
        self.assets = assets
        self.commands = HostedPhase2Commands(clock)
        self.repository = PostgresWorkspaceRepository(connection_factory, verify_session, self.commands)
        self.clock = clock

    def bootstrap(self, token, plan="studio"):
        if plan not in PLANS:
            raise AlphaError("This plan is not available.")
        principal = self.verify_session(token)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT public.pr_bootstrap(%s,%s)", (principal, plan))
                workspace_id = str(cur.fetchone()[0])
                cur.execute("SELECT w.revision,w.state,t.plan,extract(epoch from t.started_at),extract(epoch from t.expires_at),t.writing_grant,t.writing_used,t.artwork_grant FROM public.pr_workspaces w JOIN public.pr_trials t ON t.workspace_id=w.id WHERE w.id=%s FOR UPDATE OF w", (workspace_id,))
                revision, state, saved_plan, started, expires, writing_grant, writing_used, artwork_grant = cur.fetchone()
                state = json.loads(state) if isinstance(state, str) else state
                if not state or "phase2" not in state:
                    state = initial_phase2_state(workspace_id, principal, "PostRiff member", saved_plan, float(started), execution="hosted-candidate")
                    state["phase2"]["trial"].update({"expiresAt": float(expires), "writingGrant": writing_grant, "writingUsed": writing_used, "artworkSets": artwork_grant})
                    cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
                    revision += 1
        shown = self.commands.present(state, revision)
        return {"workspaceId": workspace_id, **shown, "auth": {"productionAccount": True}}

    def get(self, workspace_id, token):
        saved = self.repository.get(workspace_id, token)
        return self.commands.present(saved["state"], saved["revision"])

    def mutate(self, workspace_id, token, revision, action, payload):
        saved = self.repository.mutate(workspace_id, token, revision, action, payload)
        return self.commands.present(saved["state"], saved["revision"])

    def upload_media(self, workspace_id, token, revision, payload):
        if self.assets is None:
            raise AlphaError("Private media storage is not configured.", 503)
        principal = self.verify_session(token)
        self.repository.get(workspace_id, token)
        asset = self.assets.stage_upload(workspace_id, payload)
        try:
            saved = self.repository.command(workspace_id, token, revision, lambda state, actor: self.commands.add_asset(state, actor, asset))
        except Exception:
            self.assets.remove(workspace_id, asset)
            raise
        return self.commands.present(saved["state"], saved["revision"])

    def delete_media(self, workspace_id, token, revision, asset_id):
        if self.assets is None:
            raise AlphaError("Private media storage is not configured.", 503)
        prepared = self.repository.command(workspace_id, token, revision, lambda state, actor: self.commands.prepare_asset_delete(state, actor, asset_id))
        asset = find(prepared["state"]["phase2"]["assets"], asset_id)
        self.assets.remove(workspace_id, asset)
        finished = self.repository.command(workspace_id, token, prepared["revision"], lambda state, actor: self.commands.finish_asset_delete(state, actor, asset_id))
        return self.commands.present(finished["state"], finished["revision"])

    def media(self, workspace_id, token, asset_id):
        if self.assets is None:
            raise AlphaError("Private media storage is not configured.", 503)
        snapshot = self.repository.get(workspace_id, token)
        asset = find(snapshot["state"]["phase2"]["assets"], asset_id)
        if asset.get("deleted") or not asset.get("objectName"):
            raise AlphaError("This private media object is unavailable.", 404)
        return self.assets.storage.get(workspace_id, "media", asset["objectName"]), asset.get("mime", "application/octet-stream")

    def export(self, workspace_id, token):
        snapshot = self.get(workspace_id, token)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("phase2/workspace.json", json.dumps(snapshot["state"], ensure_ascii=False, indent=2))
            archive.writestr("README.txt", "Private hosted export. It contains drafts and approval records but no access tokens, provider credentials, or media bytes. Export does not publish content.\n")
        return output.getvalue()
