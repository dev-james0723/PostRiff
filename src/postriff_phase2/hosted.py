"""Hosted boundary candidate. Not mounted by the local launcher.

The caller supplies a connection factory and a server-side verified Auth principal.
No browser may supply the principal. No service key or profile metadata is accepted.
"""
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import re
import secrets
import time
import zipfile
import zoneinfo
from postriff_alpha.domain import AlphaError
from postriff_alpha.domain import Store
from postriff_alpha import profiles
from .auth import initial_phase2_state
from .contracts import FixtureImages, FixtureSocial, PLANS, digest
from .store import Phase2Store, IN_FLIGHT, find
from .content_types import ensure_content_state, projection as content_projection
from .permissions import Membership, ROLES, STEP_UP_ACTIONS, STEP_UP_WINDOW, classify, require, validate_grant
from .channels import connection_state
from . import campaigns, locales, memory, research, source_policy, suggestions, voice_analysis, voice_sources
from .ideas import IdeasService

MEMBER_COLUMNS = "m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections"
# What the profile page shows about each workspace: its name, plan, owner and how the members split
# by role. Every value is derived from rows the member may already see; nothing here is per-member.
WORKSPACE_SUMMARY_COLUMNS = (
    "coalesce(w.state->'workspace'->>'name',''),"
    "(SELECT pt.plan FROM public.pr_subscriptions s JOIN public.pr_plan_terms pt ON pt.id=s.plan_terms_id WHERE s.workspace_id=w.id AND s.status IN ('active','past_due','grace')),"
    "(SELECT t.plan FROM public.pr_trials t WHERE t.workspace_id=w.id ORDER BY t.started_at LIMIT 1),"
    "(SELECT o.user_id::text FROM public.pr_memberships o WHERE o.workspace_id=w.id AND o.role='owner' AND o.status='active' ORDER BY o.updated_at LIMIT 1),"
    "(SELECT coalesce(op.display_name,'') FROM public.pr_memberships o JOIN public.pr_profiles op ON op.user_id=o.user_id WHERE o.workspace_id=w.id AND o.role='owner' AND o.status='active' ORDER BY o.updated_at LIMIT 1),"
    "(SELECT coalesce(jsonb_object_agg(c.role,c.n),'{}'::jsonb) FROM (SELECT role,count(*) AS n FROM public.pr_memberships WHERE workspace_id=w.id AND status='active' GROUP BY role) c)"
)
INVITATION_TTL = 7 * 86400
MAX_PENDING_INVITATIONS = 25
PROFILE_NAME_MAX = 80
# Person-level preferences (migration 011). A BCP-47-shaped language tag, and an IANA zone the
# server itself can resolve, so a stored zone never breaks scheduling later.
LOCALE_TAG = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,4})?(?:-[A-Z]{2})?$")
ZONE_NAME = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+){0,2}$")


def known_zone(name):
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _membership(row):
    return Membership.from_row(*row[2:7])


def workspace_summary(name, subscription_plan, trial_plan, owner_id, owner_name, counts):
    """Shape the WORKSPACE_SUMMARY_COLUMNS tail of a row. A workspace is on a paid plan only while a
    subscription is live; otherwise it is a trial of `trialPlan`."""
    counts = counts if isinstance(counts, dict) else {}
    return {
        "name": name or "My workspace",
        "plan": subscription_plan if subscription_plan in ("studio", "assist") else "trial",
        "trialPlan": trial_plan if trial_plan in ("studio", "assist") else None,
        "owner": {"userId": owner_id, "displayName": owner_name or ""} if owner_id else None,
        "memberCounts": {role: int(counts.get(role, 0) or 0) for role in ROLES},
    }


def bucket(scope):
    return hashlib.sha256(scope.encode()).hexdigest()


def throttle(cur, scope, limit, window_seconds):
    """Fixed-window counter keyed by a hashed scope. Raises 429 above the limit."""
    cur.execute(
        "INSERT INTO public.pr_auth_throttle(bucket,window_start,count) VALUES(%s,now(),1) "
        "ON CONFLICT(bucket) DO UPDATE SET "
        "count=CASE WHEN public.pr_auth_throttle.window_start < now()-make_interval(secs=>%s) THEN 1 ELSE public.pr_auth_throttle.count+1 END, "
        "window_start=CASE WHEN public.pr_auth_throttle.window_start < now()-make_interval(secs=>%s) THEN now() ELSE public.pr_auth_throttle.window_start END "
        "RETURNING count",
        (bucket(scope), window_seconds, window_seconds),
    )
    if cur.fetchone()[0] > limit:
        raise AlphaError("Too many attempts. Wait a minute and try again.", 429)


def audit(cur, workspace_id, actor, kind, subject="", meta=None):
    """Content-free, append-only. Never pass prompts, post bodies, tokens, or emails."""
    cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,%s,%s,%s,%s::jsonb)", (workspace_id, actor, kind, subject[:200], json.dumps(meta or {})))


class PostgresWorkspaceRepository:
    def __init__(self, connection_factory, verify_session, commands=None, clock=time.time):
        self.connection_factory = connection_factory
        self.verify_session = verify_session
        self.commands = commands
        self.clock = clock
        # (cur, workspace_id, before, after, principal) hooks run inside command(), after the state is saved.
        self.effects = []
        from .api_tokens import ApiTokens
        self.api_tokens = ApiTokens(self)

    @contextmanager
    def transaction(self, token, workspace_id, *, allow_deleting=False):
        from .api_tokens import is_api_token
        api_grant = self.api_tokens.resolve(token, workspace_id) if is_api_token(token) else None
        principal = api_grant["createdBy"] if api_grant else self.verify_session(token)  # Verified identity only.
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"SELECT w.revision,w.state,{MEMBER_COLUMNS} FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w", (workspace_id, principal))
                row = cur.fetchone()
                if not row:
                    # Same status and message whether the workspace is foreign or nonexistent.
                    raise AlphaError("Workspace unavailable.", 403)
                state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                if state.get('accountDeletion') and not (allow_deleting and row[2] == 'owner'):
                    raise AlphaError('Account deletion is pending. Only deletion can continue.', 409, code='account_deletion_pending')
                if api_grant:
                    self.api_tokens.validate(cur, token, workspace_id)  # Lock the live grant through this transaction.
                yield cur, row, principal

    def assert_fresh(self, token, principal):
        """Step-up: the session must have been verified by sign-in within the window."""
        from .api_tokens import is_api_token
        if is_api_token(token):
            raise AlphaError("An interactive sign-in is required.", 403, code="step_up_required")
        auth_time = getattr(self.verify_session, "auth_time", None)
        verified_at = auth_time(token, principal) if auth_time else 0
        if self.clock() - float(verified_at or 0) > STEP_UP_WINDOW:
            raise AlphaError("Sign in again to confirm this sensitive action.", 403, code="step_up_required")

    def get(self, workspace_id, token):
        with self.transaction(token, workspace_id, allow_deleting=True) as (_, row, _):
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            return {"revision": row[0], "state": copy.deepcopy(state), "membership": _membership(row).summary()}

    def command(self, workspace_id, token, revision, trusted_command, requirement="edit", step_up=False, audit_event=None, after=None):
        """trusted_command is application code, never a client-submitted patch. `audit_event(state)` returns
        (kind, subject, meta) for decisions that belong in the audit log, recorded in the same transaction.
        `after(cur, state, principal)` runs last, for rows that must change together with the state."""
        with self.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), requirement)
            if step_up:
                self.assert_fresh(token, principal)
            if type(revision) is not int or revision != row[0]:
                raise AlphaError("Workspace changed; reload.", 409, code="workspace_revision_conflict")
            source = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            state = trusted_command(copy.deepcopy(source), principal)
            if not isinstance(state, dict):
                raise AlphaError("The hosted command returned invalid state.", 500)
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            if audit_event:
                audit(cur, workspace_id, principal, *audit_event(state))
            for effect in self.effects:
                effect(cur, workspace_id, source, state, principal)
            if after:
                after(cur, state, principal)
            return {"revision": revision+1, "state": state, "membership": _membership(row).summary()}

    def mutate(self, workspace_id, token, expected_revision, action, payload):
        if self.commands is None:
            raise AlphaError("Hosted command routing has not been configured.", 503)
        if not isinstance(action, str) or not isinstance(payload, dict):
            raise AlphaError("Expected a structured command.")
        audit_event = (lambda state: ("memory.egress_decided", "cloud", {"cloud": memory.egress(state).get("cloud") is True})) if action == memory.EGRESS_ACTION else None
        if action == research.CONSENT_ACTION:
            audit_event = lambda state: ("research.egress_decided", "web", {"web": research.consent(state).get("web") is True})
        after = None
        if action in ("p2_review", "p2_approve", "p2_approve_many", "raffi_run_commit"):
            from .billing import require_publishing
            after = lambda cur, state, principal: require_publishing(cur, workspace_id, self.clock())
        return self.command(workspace_id, token, expected_revision, lambda state, principal: self.commands(state, principal, action, payload), requirement=classify(action), step_up=action in STEP_UP_ACTIONS, audit_event=audit_event, after=after)


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
        # Hosted entitlement checks use live SQL, including paid plans after the original trial ends.
        self.engine.hosted_entitlements = True
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
        if source_policy.apply_policy_action(state, action, payload, principal, self.clock()):
            source_policy.stamp(state)
            self.engine.invalidate(state)
            return state
        if memory.apply_memory_action(state, action, payload, principal, self.clock()):
            return state
        if locales.apply_language_action(state, action, payload, principal, self.clock()):
            return state
        if research.apply_research_action(state, action, payload, principal, self.clock()):
            return state
        if voice_analysis.apply_action(state, action, payload, principal, self.clock()):
            self.engine.invalidate(state)
            return state
        if action.startswith("voice_sample"):
            voice_sources.apply_action(state, action, payload, principal, self.clock())
            source_policy.stamp(state)
            self.engine.invalidate(state)
            return state
        if action.startswith("raffi_campaign_") or action.startswith("raffi_recurrence_") or action == "raffi_run_decide":
            campaigns.apply_action(state, action, payload, principal, self.clock())
            return state
        if action == "raffi_run_commit":
            from . import publisher
            publisher.commit(self.engine, state, principal, payload, self.clock())
            source_policy.stamp(state)
            self.engine.invalidate(state)
            return state
        if action.startswith("raffi_suggestion_"):
            suggestions.apply_action(state, action, payload, principal, self.clock())
            return state
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
        source_policy.stamp(state)
        self.engine.invalidate(state)
        return state

    @staticmethod
    def _require_mutable_media(state):
        # Live edit permission is enforced by repository.command, not the bootstrap creator.
        if state.get("workspace", {}).get("sample"):
            raise AlphaError("Hosted sample workspaces are read-only.", 403, code="sample_read_only")

    def add_asset(self, state, principal, asset):
        self._require_mutable_media(state)
        if asset.get("data"):
            raise AlphaError("Invalid hosted asset metadata.", 403)
        if any(item["id"] == asset["id"] for item in state["phase2"]["assets"]):
            raise AlphaError("This asset already exists.", 409)
        state["phase2"]["assets"].append(copy.deepcopy(asset))
        return state

    def prepare_asset_delete(self, state, principal, asset_id):
        self._require_mutable_media(state)
        asset = find(state["phase2"]["assets"], asset_id)
        if any(job["state"] in IN_FLIGHT and any(media["id"] == asset_id for media in job["manifest"]["media"]) for job in state["phase2"]["jobs"]):
            raise AlphaError("Reconcile this asset's in-flight jobs before deleting its bytes.")
        asset.update({"deleted": True, "deletionPending": True})
        self.engine.invalidate(state)
        return state

    def finish_asset_delete(self, state, principal, asset_id):
        self._require_mutable_media(state)
        asset = find(state["phase2"]["assets"], asset_id)
        if not asset.get("deletionPending"):
            raise AlphaError("This asset is not pending deletion.", 409)
        asset.pop("objectName", None)
        asset.pop("storagePath", None)
        asset["deletionPending"] = False
        return state

    SERVER_VERIFIED_PLATFORMS = ("LinkedIn", "Instagram", "Threads", "Facebook", "X", "YouTube", "TikTok", "Pinterest", "Bluesky", "Mastodon")

    def upsert_verified_channel(self, state, principal, channel, capability_verified=True):
        required = {"id", "platform", "account", "accountType", "scopes", "verifiedAt", "expiresAt", "capabilityVersion", "providerAccountId"}
        # `language` is optional: records from before per-channel languages still carry it (languages plan §6).
        if set(channel) - {"language"} != required or channel["platform"] not in self.SERVER_VERIFIED_PLATFORMS:
            raise AlphaError("A complete server-verified channel record is required.")
        saved = copy.deepcopy(channel)
        # identityVerified comes from the provider identity endpoint; capabilityVerified only when
        # publish scopes were granted to a production-reviewed app (see OAuthService._capabilities).
        saved.update({"configured": True, "identityVerified": True, "capabilityVerified": bool(capability_verified), "revoked": False, "qualification": "server_verified", "evidenceSource": "live_provider", "scenario": None})
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
    def __init__(self, connection_factory, verify_session, assets=None, clock=time.time, identity=None, vault=None, providers=None, public_base_url=None, audience_transport=None, billing_provider=None, mailer=None, ideas_runtime=None, image_runtime=None, email_lookup=None, credits_enabled=False, credit_purchases_enabled=False):
        self.connection_factory = connection_factory
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.verify_session = verify_session
        self.assets = assets
        self.commands = HostedPhase2Commands(clock)
        self.repository = PostgresWorkspaceRepository(connection_factory, verify_session, self.commands, clock)
        self.clock = clock
        self.identity = identity
        # principal -> verified email, or None. Defaults to the identity admin; the dev harness supplies its own.
        self.email_lookup = email_lookup
        self.ideas = IdeasService(self.repository, self.commands, clock=clock, image_runtime=image_runtime, assets=assets)
        if ideas_runtime is not None:
            # A paid server-side route sits next to the deterministic preview when the service knows
            # several runtimes; a single-runtime service uses it as the only route.
            if hasattr(self.ideas, "runtimes"):
                self.ideas.runtimes.append(ideas_runtime)
            else:
                self.ideas.runtime = ideas_runtime
        from .oauth import CredentialVault, OAuthService
        from .billing import Billing, Ledger
        from .privacy import DataRequests
        from .audience import AudienceService
        self.oauth = OAuthService(self.repository, self.commands, vault or CredentialVault(None), providers or {}, public_base_url, clock)
        # Chat cards say where an automation can really publish (capabilities.publish_route); set live by hosted_app.
        self.publishing_live = False
        self.ideas.service_ref = self
        self.ledger = Ledger(credits_enabled=credits_enabled, clock=clock)
        self.ideas.ledger = self.ledger
        self.billing = Billing(provider=billing_provider, ledger=self.ledger, clock=clock)
        from .credit_purchases import CreditPurchases
        self.credit_purchases = CreditPurchases(self.ledger._credit_book, self.billing.provider, clock) if self.billing.provider.id == "stripe" else None
        self.credit_purchases_enabled = credit_purchases_enabled and credits_enabled
        from .email import Mailer, NullTransport, Reminders
        # Unconfigured deployments get a recording NullTransport: business actions never depend on email.
        self.mailer = mailer or Mailer(NullTransport(), "Rafii <no-reply@postriff.invalid>", self.public_base_url or "https://postriff.invalid")
        self.reminders = Reminders(self.mailer, self._email_for, clock=clock)
        self.data_requests = DataRequests(self.repository, clock)
        self.audience = AudienceService(self.repository, self.oauth, clock, transport=audience_transport)
        from .learning_service import HostedLearning
        # Preference learning: every command's implied events are captured in that command's transaction.
        self.learning = HostedLearning(connection_factory, clock)
        self.repository.effects.append(self.learning.capture)
        from .planning_store import sync as sync_planning
        self.repository.effects.append(sync_planning)
        self.ideas.learning = self.learning
        from .site_agent.service import SiteAgentService
        # The site-wide Rafii panel: the same conversations, runs, events and approval paths as Home (site agent spec §4.2).
        self.site_agent = SiteAgentService(self)

    # --- usage, privacy, analytics (Milestone D) -------------------------------------
    def usage(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            view = self.ledger.usage_view(cur, workspace_id)
            view["lifecycle"] = self.billing.lifecycle(cur, workspace_id, self.clock())
            view["billing"] = self.billing.availability(cur, workspace_id)
            view["membership"] = _membership(row).summary()
            if not _membership(row).allows("owner"):
                view["budget"] = None
                for entry in view["ledger"]:
                    entry.pop("estimatedUsdMicro", None)
                    entry.pop("actualUsdMicro", None)
                view["billing"]["checkoutAvailable"] = False
                view["billing"]["portalAvailable"] = False
            return view

    def billing_webhook(self, signature, body):
        notice = None
        with self.connection_factory() as db:
            with db.cursor() as cur:
                credits = self.credit_purchases.process_webhook(cur, signature, body) if self.credit_purchases else None
                if credits is not None: return credits
                result = self.billing.process_webhook(cur, signature, body)
                if result.get("outcome") == "applied":
                    notice = self._billing_notice(cur, result)
        # The address lookup and the email are network calls: only after the billing change is committed
        # and every row lock is released.
        if notice:
            result["notification"] = self._deliver_billing_notice(notice)
        return result

    # --- live billing (Stripe) and transactional email ------------------------------------
    def _email_for(self, user_id):
        """Owner/inviter address from Supabase Auth for a single send (D16); None when unavailable."""
        lookup = self.email_lookup or getattr(self.identity, "email_for", None)
        if lookup is None:
            return None
        try:
            return lookup(user_id)
        except AlphaError:
            return None

    def _app_url(self, path, default):
        """Absolute URL on this deployment. Clients may only supply a relative path; never a host."""
        if not self.public_base_url:
            raise AlphaError("The public base URL is not configured.", 503)
        path = default if path in (None, "") else path
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "://" in path or "\\" in path or len(path) > 512 or any(ord(c) < 32 for c in path):
            raise AlphaError("Return paths must be relative to this app.", 400)
        return self.public_base_url + path

    def _live_provider(self):
        provider = self.billing.provider
        if getattr(provider, "id", "") != "stripe":
            raise AlphaError("Billing isn't available yet.", 503)
        return provider

    def billing_checkout(self, workspace_id, token, plan_terms_id, success_path=None, cancel_path=None):
        """Owner-only. Only 'active' plan terms bound to a provider price are purchasable (D3).
        Nothing is written until the provider's webhook confirms the subscription."""
        provider = self._live_provider()
        if not isinstance(plan_terms_id, str) or not 1 <= len(plan_terms_id) <= 64:
            raise AlphaError("Choose a plan.")
        success = self._app_url(success_path, "/app/account/billing?checkout=success")
        cancel = self._app_url(cancel_path, "/app/account/billing?checkout=cancelled")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "owner")
            throttle(cur, f"checkout:{workspace_id}", 5, 60)
            cur.execute("SELECT status,provider_price_id FROM public.pr_plan_terms WHERE id=%s", (plan_terms_id,))
            terms = cur.fetchone()
            if not terms or terms[0] != "active" or not terms[1]:
                raise AlphaError("This plan is not yet available for purchase.", 409)
            cur.execute("SELECT provider_customer_id,status FROM public.pr_subscriptions WHERE workspace_id=%s AND provider=%s", (workspace_id, provider.id))
            existing = cur.fetchone()
            if existing and existing[1] in ("active", "past_due", "grace"):
                raise AlphaError("This workspace already has a subscription. Change it from the billing portal.", 409)
            customer_id = existing[0] if existing else None
            audit(cur, workspace_id, principal, "billing.checkout_started", plan_terms_id)
        customer_email = None if customer_id else self._email_for(principal)
        if not customer_id and not customer_email:
            raise AlphaError("Your account email could not be resolved for checkout.", 502)
        key = digest({"checkout": workspace_id, "plan": plan_terms_id, "hour": int(self.clock() // 3600)})
        return provider.create_checkout_session(workspace_id=workspace_id, plan_terms_id=plan_terms_id, price_id=terms[1], success_url=success, cancel_url=cancel, customer_id=customer_id, customer_email=customer_email, idempotency_key=key)

    def billing_credit_packs(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, actor):
            if not self.credit_purchases_enabled or not self.credit_purchases or not _membership(row).allows("owner"):
                return {"available": False, "packs": []}
            packs = self.credit_purchases.packs(cur, workspace_id)
            return {"available": bool(packs), "packs": packs}

    def billing_credit_checkout(self, workspace_id, token, pack_id, request_id):
        if not self.credit_purchases_enabled or not self.credit_purchases:
            raise AlphaError("Credit purchases are not enabled.", 503)
        success = self._app_url(None, "/app/account/billing?creditCheckout=returned")
        cancel = self._app_url(None, "/app/account/billing?creditCheckout=cancelled")
        with self.repository.transaction(token, workspace_id) as (cur, row, actor):
            require(_membership(row), "owner")
            throttle(cur, "credit-checkout:" + workspace_id, 5, 60)
            order = self.credit_purchases.prepare_order(cur, workspace_id, actor, pack_id, request_id)
            if order.get("status") == "funded": return {"orderId": order["orderId"], "status": "funded", "url": None}
            if order["url"]: return {"orderId": order["orderId"], "url": order["url"]}
            cur.execute("SELECT price_id FROM public.pr_credit_orders WHERE id::text=%s", (order["orderId"],))
            price = cur.fetchone()[0]
        email = self._email_for(actor)
        if not email: raise AlphaError("The account email could not be resolved for checkout.", 502)
        session = self.billing.provider.create_credit_checkout_session(order_id=order["orderId"], workspace_id=workspace_id, price_id=price, customer_email=email, success_url=success, cancel_url=cancel)
        with self.repository.transaction(token, workspace_id) as (cur, row, actor):
            require(_membership(row), "owner")
            self.credit_purchases.attach_checkout(cur, workspace_id, order["orderId"], session)
        return {"orderId": order["orderId"], **session}

    def billing_portal(self, workspace_id, token, return_path=None):
        """Owner-only. The provider-hosted portal handles payment method, plan change, cancellation and invoices."""
        provider = self._live_provider()
        return_url = self._app_url(return_path, "/app/account/billing")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "owner")
            throttle(cur, f"portal:{workspace_id}", 5, 60)
            cur.execute("SELECT provider_customer_id FROM public.pr_subscriptions WHERE workspace_id=%s AND provider=%s", (workspace_id, provider.id))
            existing = cur.fetchone()
            if not existing or not existing[0]:
                raise AlphaError("No billing account yet. Start a subscription first.", 409)
            audit(cur, workspace_id, principal, "billing.portal_opened")
            customer_id = existing[0]
        return provider.create_portal_session(customer_id=customer_id, return_url=return_url)

    def run_reminders(self):
        """Cron entry: trial reminder sweep (deduped in pr_notifications)."""
        with self.connection_factory() as db:
            with db.cursor() as cur:
                return self.reminders.run(cur)

    def _billing_notice(self, cur, result):
        """One owner email per applied billing event, deduped in pr_notifications; never changes the webhook outcome."""
        kind = {"subscription.activated": "subscription_activated", "invoice.payment_failed": "payment_failed"}.get(result.get("type"))
        workspace_id = result.get("workspaceId")
        if not kind or not workspace_id or not self.public_base_url:
            return None
        cur.execute("SELECT m.user_id::text FROM public.pr_memberships m WHERE m.workspace_id=%s AND m.role='owner' AND m.status='active' ORDER BY m.updated_at LIMIT 1", (workspace_id,))
        owner = cur.fetchone()
        if not owner:
            return None
        cur.execute("INSERT INTO public.pr_notifications(workspace_id,user_id,kind,dedupe_key) VALUES(%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id::text", (workspace_id, owner[0], kind, f"{kind}:{result['eventId']}"))
        inserted = cur.fetchone()
        if not inserted:
            return {"kind": kind, "sent": False, "reason": "duplicate"}
        if kind == "subscription_activated":
            from .billing import plan_display_label
            cur.execute("SELECT p.label FROM public.pr_subscriptions s JOIN public.pr_plan_terms p ON p.id=s.plan_terms_id WHERE s.workspace_id=%s", (workspace_id,))
            label = cur.fetchone()
            detail = plan_display_label(label[0] if label else None)
        else:
            cur.execute("SELECT extract(epoch from grace_until) FROM public.pr_subscriptions WHERE workspace_id=%s", (workspace_id,))
            grace = cur.fetchone()
            detail = float(grace[0]) if grace and grace[0] else self.clock() + 7 * 86400
        return {"kind": kind, "pending": True, "notificationId": inserted[0], "owner": owner[0], "detail": detail}

    def _deliver_billing_notice(self, notice):
        """Sends a notice recorded by `_billing_notice`, outside any transaction; marks it sent after."""
        if not notice.get("pending"):
            return notice
        address = self._email_for(notice["owner"])
        if not address:
            return {"kind": notice["kind"], "sent": False, "reason": "no address"}
        billing_url = f"{self.public_base_url}/app/account/billing"
        if notice["kind"] == "subscription_activated":
            outcome = self.mailer.subscription_activated(address, notice["detail"], billing_url)
        else:
            outcome = self.mailer.payment_failed(address, notice["detail"], billing_url)
        if outcome.get("sent"):
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute("UPDATE public.pr_notifications SET sent=true WHERE id=%s", (notice["notificationId"],))
        return {"kind": notice["kind"], "sent": bool(outcome.get("sent"))}

    def data_request(self, workspace_id, token, kind, payload):
        from . import privacy
        if kind == "export":
            raw = self.export(workspace_id, token)
            receipt = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "contents": "drafts, sources, approvals, receipts; no tokens or media bytes"}
            with self.repository.transaction(token, workspace_id) as (cur, _, principal):
                request_id = self.data_requests.record(cur, workspace_id, principal, "export", "completed", receipt)
                audit(cur, workspace_id, principal, "data.exported", request_id, {"bytes": len(raw)})
            return {"requestId": request_id, "kind": "export", "status": "completed", "receipt": receipt}
        if kind == "diagnostics":
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                package = privacy.diagnostics_package(state, payload.get("consent"), workspace_id)
                request_id = self.data_requests.record(cur, workspace_id, principal, "diagnostics", "completed", {"fields": sorted(package["counts"])})
                audit(cur, workspace_id, principal, "data.diagnostics", request_id)
            return {"requestId": request_id, "kind": "diagnostics", "status": "completed", "package": package}
        if kind == "deletion":
            with self.repository.transaction(token, workspace_id) as (cur, row, principal):
                require(_membership(row), "owner")
                request_id = self.data_requests.record(cur, workspace_id, principal, "deletion", "requested", {"note": "Complete with DELETE /account; in-flight publications must be reconciled first."})
            return {"requestId": request_id, "kind": "deletion", "status": "requested", "next": "DELETE /api/workspaces/{id}/account with confirmation DELETE"}
        if kind == "retraction":
            saved = self.mutate(workspace_id, token, payload.get("expectedRevision"), "retract_source", {"sourceId": payload.get("sourceId")})
            with self.repository.transaction(token, workspace_id) as (cur, _, principal):
                request_id = self.data_requests.record(cur, workspace_id, principal, "retraction", "completed", {"sourceId": payload.get("sourceId"), "dependentVariantsBlocked": sum(1 for v in saved["state"]["variants"] if v.get("blockedByRetraction"))})
            return {"requestId": request_id, "kind": "retraction", "status": "completed", "revision": saved["revision"]}
        raise AlphaError("Choose export, diagnostics, retraction, or deletion.")

    def analytics(self, workspace_id, token):
        from . import insights
        snapshot = self.repository.get(workspace_id, token)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            result = insights.summary(cur, workspace_id, snapshot["state"].get("phase2", {}).get("jobs", []), self.clock())
        connections = snapshot["state"].get("phase2", {}).get("channels", [])
        result["connections"] = [{"id": c["id"], "platform": c["platform"], "account": c["account"], "analytics": "unavailable — connect with the analytics capability" if c["platform"] in ("LinkedIn",) else "available after a verified publication"} for c in connections]
        result["state"] = "limited"
        return result

    def _session_id(self, token, principal):
        session_id = getattr(self.verify_session, "session_id", None)
        return session_id(token, principal) if session_id else None

    def _touch_session(self, cur, principal, session_id, client_label=""):
        """Record the session; True when this is its first sighting (a sign-in on a device we had not seen)."""
        if not session_id:
            return False
        # xmax is 0 on a freshly inserted row and non-zero on the version an ON CONFLICT update wrote.
        cur.execute("INSERT INTO public.pr_sessions(user_id,session_id,client_label) VALUES(%s,%s,%s) ON CONFLICT(user_id,session_id) DO UPDATE SET last_seen=now(), client_label=CASE WHEN excluded.client_label='' THEN public.pr_sessions.client_label ELSE excluded.client_label END RETURNING (xmax = 0)", (principal, session_id, (client_label or "")[:40]))
        row = cur.fetchone()
        return bool(row and row[0])

    def _alert_new_device(self, principal, session_id, client_label):
        """After a session's first sighting: one email, only if the person turned the alert on. The
        audit line records the attempt either way, so the account history shows it."""
        if not self.public_base_url:
            return
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT alert_new_device FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL", (principal,))
                row = cur.fetchone()
                if not row or not row[0]:
                    return
                address = self._email_for(principal)
                outcome = self.mailer.new_device(address, client_label or "an unrecognised device", self.clock(), f"{self.public_base_url}/app/account/profile") if address else {"sent": False}
                audit(cur, None, principal, "session.alerted", session_id or "", {"sent": bool(outcome.get("sent"))})

    def _present(self, saved):
        shown = self.commands.present(saved["state"], saved["revision"])
        shown["membership"] = saved.get("membership")
        return shown

    def bootstrap(self, token, plan="studio", client=None, client_label=""):
        if plan not in PLANS:
            raise AlphaError("This plan is not available.")
        if client:
            with self.connection_factory() as db:
                with db.cursor() as cur:
                    throttle(cur, f"verify:{client}", 30, 60)
        principal = self.verify_session(token)
        created = False
        with self.connection_factory() as db:
            with db.cursor() as cur:
                throttle(cur, f"verify-user:{principal}", 60, 60)
                cur.execute("SELECT public.pr_bootstrap(%s,%s)", (principal, plan))
                workspace_id = str(cur.fetchone()[0])
                cur.execute(f"SELECT w.revision,w.state,t.plan,extract(epoch from t.started_at),extract(epoch from t.expires_at),t.writing_grant,t.writing_used,t.artwork_grant,{MEMBER_COLUMNS} FROM public.pr_workspaces w JOIN public.pr_trials t ON t.workspace_id=w.id JOIN public.pr_memberships m ON m.workspace_id=w.id AND m.user_id=%s WHERE w.id=%s FOR UPDATE OF w", (principal, workspace_id))
                revision, state, saved_plan, started, expires, writing_grant, writing_used, artwork_grant, *member = cur.fetchone()
                state = json.loads(state) if isinstance(state, str) else state
                if not state or "phase2" not in state:
                    state = initial_phase2_state(workspace_id, principal, "Rafii member", saved_plan, float(started), execution="hosted-candidate")
                    state["phase2"]["trial"].update({"expiresAt": float(expires), "writingGrant": writing_grant, "writingUsed": writing_used, "artworkSets": artwork_grant})
                    cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
                    revision += 1
                    audit(cur, workspace_id, principal, "workspace.created", "", {"plan": saved_plan})
                    created = True
                self._touch_session(cur, principal, self._session_id(token, principal), client_label)
        if created and self.public_base_url:
            address = self._email_for(principal)
            if address:
                self.mailer.welcome(address, f"{self.public_base_url}/app")
        shown = self.commands.present(state, revision)
        return {"workspaceId": workspace_id, **shown, "membership": Membership.from_row(*member).summary(), "auth": {"productionAccount": True}}

    def get(self, workspace_id, token):
        return self._present(self.repository.get(workspace_id, token))

    def mutate(self, workspace_id, token, revision, action, payload):
        if action == 'voice_profile_analyze' and isinstance(payload, dict) and payload.get('route', 'local-rules') != 'local-rules':
            from .voice_ai import HostedVoiceAnalysis
            return HostedVoiceAnalysis(self).run(workspace_id, token, revision, payload)
        return self._present(self.repository.mutate(workspace_id, token, revision, action, payload))

    # --- Workspaces, members, invitations, sessions, audit (architecture spec 8, 9, 21) ---

    def workspaces(self, token):
        principal = self.verify_session(token)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"SELECT m.workspace_id::text,{MEMBER_COLUMNS},extract(epoch from w.created_at),{WORKSPACE_SUMMARY_COLUMNS} FROM public.pr_memberships m JOIN public.pr_workspaces w ON w.id=m.workspace_id JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL ORDER BY w.created_at", (principal,))
                rows = cur.fetchall()
        return {"workspaces": [{"workspaceId": row[0], "membership": Membership.from_row(*row[1:6]).summary(), "createdAt": float(row[6]), **workspace_summary(*row[7:13])} for row in rows]}

    def leave_workspace(self, workspace_id, token):
        """A member removes their own access. The owner cannot leave: ownership moves first."""
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            if _membership(row).role == "owner":
                raise AlphaError("Transfer ownership before leaving this workspace.", 409)
            cur.execute("UPDATE public.pr_memberships SET status='revoked',updated_at=now() WHERE workspace_id=%s AND user_id=%s AND status='active'", (workspace_id, principal))
            if cur.rowcount != 1:
                raise AlphaError("Workspace unavailable.", 403)
            audit(cur, workspace_id, principal, "member.left")
        return {"workspaceId": workspace_id, "status": "left"}

    # --- the signed-in person: identity, second factor, channels across workspaces ---------

    def me(self, token, client_label=""):
        principal = self.verify_session(token)
        aal = getattr(self.verify_session, "aal", None)
        session_id = self._session_id(token, principal)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                fresh = self._touch_session(cur, principal, session_id, client_label)
                cur.execute("SELECT coalesce(p.display_name,''),extract(epoch from e.enforced_at),coalesce(p.time_zone,''),coalesce(p.locale,''),coalesce(p.alert_new_device,false) FROM public.pr_profiles p LEFT JOIN public.pr_mfa_enforcement e ON e.user_id=p.user_id WHERE p.user_id=%s AND p.deleted_at IS NULL", (principal,))
                row = cur.fetchone()
        if fresh:
            self._alert_new_device(principal, session_id, client_label)
        display_name, enforced_at, time_zone, locale, alert_new_device = row if row else ("", None, "", "", False)
        return {
            "userId": principal,
            "displayName": display_name,
            "sessionId": session_id,
            # `available` is false for identities without assurance levels (the dev harness).
            "mfa": {"available": aal is not None, "enforced": enforced_at is not None, "enforcedAt": float(enforced_at) if enforced_at else None, "aal": aal(token, principal) if aal else None},
            # Empty strings mean "follow the device"; the browser fills them in.
            "preferences": {"timeZone": time_zone, "locale": locale, "alertNewDevice": bool(alert_new_device)},
        }

    def update_profile(self, token, changes):
        """PATCH /api/me: the display name and person-level preferences. Only the keys present change."""
        if not isinstance(changes, dict):
            raise AlphaError("Nothing to update.")
        columns = {}
        if "displayName" in changes:
            name = changes["displayName"]
            if not isinstance(name, str) or len(name) > PROFILE_NAME_MAX or any(ord(c) < 32 for c in name):
                raise AlphaError(f"Enter a display name of up to {PROFILE_NAME_MAX} characters.")
            columns["display_name"] = " ".join(name.split())
        if "timeZone" in changes:
            zone = changes["timeZone"]
            if not isinstance(zone, str) or len(zone) > 64 or (zone and not (ZONE_NAME.match(zone) and known_zone(zone))):
                raise AlphaError("Choose a time zone from the list.")
            columns["time_zone"] = zone
        if "locale" in changes:
            locale = changes["locale"]
            if not isinstance(locale, str) or len(locale) > 16 or (locale and not LOCALE_TAG.match(locale)):
                raise AlphaError("Choose a language from the list.")
            columns["locale"] = locale
        if "alertNewDevice" in changes:
            if type(changes["alertNewDevice"]) is not bool:
                raise AlphaError("The new-device alert is either on or off.")
            columns["alert_new_device"] = changes["alertNewDevice"]
        if not columns:
            raise AlphaError("Nothing to update.")
        principal = self.verify_session(token)
        names = list(columns)  # fixed identifiers from the mapping above, never client strings
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"INSERT INTO public.pr_profiles(user_id,{','.join(names)}) VALUES(%s,{','.join('%s' for _ in names)}) ON CONFLICT (user_id) DO UPDATE SET {','.join(f'{n}=excluded.{n}' for n in names)} WHERE public.pr_profiles.deleted_at IS NULL RETURNING display_name,coalesce(time_zone,''),coalesce(locale,''),coalesce(alert_new_device,false)", (principal, *columns.values()))
                row = cur.fetchone()
        if not row:
            raise AlphaError("Workspace unavailable.", 403)
        return {"displayName": row[0], "preferences": {"timeZone": row[1], "locale": row[2], "alertNewDevice": bool(row[3])}}

    def my_channels(self, token):
        """Every connected channel in every workspace the user belongs to, with whether they may
        manage it there. Read-only: connecting and disconnecting stay on the workspace routes."""
        principal = self.verify_session(token)
        now = self.clock()
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"SELECT m.workspace_id::text,{MEMBER_COLUMNS},coalesce(w.state->'workspace'->>'name',''),coalesce(w.state->'phase2'->'channels','[]'::jsonb) FROM public.pr_memberships m JOIN public.pr_workspaces w ON w.id=m.workspace_id JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL ORDER BY w.created_at", (principal,))
                rows = cur.fetchall()
                # Who connected each channel: the newest channel.connected audit event names the actor.
                cur.execute("SELECT DISTINCT ON (e.subject) e.subject,e.actor::text,coalesce(p.display_name,''),extract(epoch from e.at) FROM public.pr_audit_events e LEFT JOIN public.pr_profiles p ON p.user_id=e.actor WHERE e.kind='channel.connected' AND e.workspace_id=ANY(%s::uuid[]) ORDER BY e.subject,e.at DESC", ([row[0] for row in rows],))
                connected = {item[0]: {"userId": item[1], "displayName": item[2], "at": float(item[3])} for item in cur.fetchall()}
        channels = []
        for row in rows:
            membership = Membership.from_row(*row[1:6])
            items = row[7] if isinstance(row[7], list) else json.loads(row[7]) if isinstance(row[7], str) else []
            for channel in items:
                if not isinstance(channel, dict) or not channel.get("configured"):
                    continue
                channels.append({
                    "workspaceId": row[0], "workspaceName": row[6] or "My workspace",
                    "id": channel.get("id"), "platform": channel.get("platform"), "account": channel.get("account"), "accountType": channel.get("accountType"),
                    "connectionState": connection_state(channel, now), "expiresAt": channel.get("expiresAt"), "verifiedAt": channel.get("verifiedAt"),
                    "evidenceSource": channel.get("evidenceSource", "synthetic"), "canManage": membership.allows("manage_connections"),
                    "connectedBy": connected.get(channel.get("id")),
                })
        return {"channels": channels}

    # The account history a person may see about themselves: what they did to the account, and what
    # others did to their memberships. Workspace content activity stays in the workspace audit log.
    SECURITY_KINDS = ("mfa.enabled", "mfa.disabled", "session.revoked", "session.revoked_others", "session.alerted", "member.left", "invitation.accepted", "invitation.declined", "workspace.created", "data.exported", "data.diagnostics")
    ABOUT_ME_KINDS = ("member.updated", "member.removed")

    def security_events(self, token, limit=50):
        principal = self.verify_session(token)
        limit = max(1, min(int(limit), 100))
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT e.id::text,e.kind,e.subject,extract(epoch from e.at),e.meta,e.workspace_id::text,coalesce(w.state->'workspace'->>'name','') FROM public.pr_audit_events e LEFT JOIN public.pr_workspaces w ON w.id=e.workspace_id WHERE (e.actor=%s AND e.kind=ANY(%s)) OR (e.subject=%s AND e.kind=ANY(%s)) ORDER BY e.at DESC LIMIT %s", (principal, list(self.SECURITY_KINDS), principal, list(self.ABOUT_ME_KINDS), limit))
                events = [{"id": item[0], "kind": item[1], "subject": item[2], "at": float(item[3]), "meta": item[4] if isinstance(item[4], dict) else {}, "workspaceId": item[5], "workspaceName": item[6]} for item in cur.fetchall()]
                # A session's first sighting is the sign-in on that device; nothing else records it.
                cur.execute("SELECT session_id,client_label,extract(epoch from first_seen) FROM public.pr_sessions WHERE user_id=%s ORDER BY first_seen DESC LIMIT %s", (principal, limit))
                events.extend({"id": "session:" + item[0], "kind": "session.started", "subject": item[0], "at": float(item[2]), "meta": {"client": item[1]}, "workspaceId": None, "workspaceName": ""} for item in cur.fetchall())
        events.sort(key=lambda event: event["at"], reverse=True)
        return {"events": events[:limit]}

    def _aal(self, token, principal):
        aal = getattr(self.verify_session, "aal", None)
        if aal is None:
            raise AlphaError("Two-factor authentication is not available for this identity.", 503)
        return aal(token, principal)

    def enable_mfa(self, token):
        """Record that this user must present a second factor. The session proves enrolment (AAL2),
        and the identity service confirms a verified factor exists, before anything is written."""
        principal = self.verify_session(token)
        if self._aal(token, principal) != "aal2":
            raise AlphaError("Verify a code from your authenticator app first.", 403)
        factors = getattr(self.identity, "verified_factors", None)
        if factors is not None and not factors(principal):
            raise AlphaError("No verified authenticator is enrolled on this account.", 409)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("INSERT INTO public.pr_mfa_enforcement(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING", (principal,))
                if cur.rowcount:
                    audit(cur, None, principal, "mfa.enabled")
                cur.execute("SELECT extract(epoch from enforced_at) FROM public.pr_mfa_enforcement WHERE user_id=%s", (principal,))
                enforced_at = cur.fetchone()[0]
        return {"enforced": True, "enforcedAt": float(enforced_at)}

    def disable_mfa(self, token):
        """Step-up: a fresh AAL2 session (a code entered moments ago), never a long-lived one."""
        principal = self.verify_session(token)
        if self._aal(token, principal) != "aal2":
            raise AlphaError("Verify a code from your authenticator app first.", 403)
        self.repository.assert_fresh(token, principal)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM public.pr_mfa_enforcement WHERE user_id=%s", (principal,))
                if cur.rowcount:
                    audit(cur, None, principal, "mfa.disabled")
        return {"enforced": False, "enforcedAt": None}

    def members(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            cur.execute(f"SELECT m.user_id::text,m.status,{MEMBER_COLUMNS},extract(epoch from m.updated_at),coalesce(p.display_name,'') FROM public.pr_memberships m LEFT JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s ORDER BY m.role,m.user_id", (workspace_id,))
            members = [{"userId": item[0], "status": item[1], "you": item[0] == principal, **Membership.from_row(*item[2:7]).summary(), "updatedAt": float(item[7]), "displayName": item[8]} for item in cur.fetchall()]
            return {"members": members, "membership": _membership(row).summary()}

    def update_member(self, workspace_id, token, user_id, role, flags):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            actor = _membership(row)
            require(actor, "manage_members")
            self.repository.assert_fresh(token, principal)
            if user_id == principal:
                raise AlphaError("Ask another owner or admin to change your own role.", 409)
            granted = validate_grant(role, flags, actor)
            cur.execute("SELECT role FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s AND status='active' FOR UPDATE", (workspace_id, user_id))
            current = cur.fetchone()
            if not current:
                raise AlphaError("Member unavailable.", 404)
            if current[0] == "owner":
                raise AlphaError("Ownership transfer is a separate step-up action.", 409)
            cur.execute("UPDATE public.pr_memberships SET role=%s,can_publish=%s,can_reply=%s,can_moderate=%s,can_manage_connections=%s,updated_at=now() WHERE workspace_id=%s AND user_id=%s", (role, granted["can_publish"], granted["can_reply"], granted["can_moderate"], granted["can_manage_connections"], workspace_id, user_id))
            audit(cur, workspace_id, principal, "member.updated", user_id, {"role": role, **granted})
            return {"userId": user_id, "role": role, **granted}

    def transfer_ownership(self, workspace_id, token, new_owner_id):
        """Step-up: the owner hands the role to an active admin. Both memberships change in one
        transaction, so the workspace is never briefly ownerless or double-owned."""
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "owner")
            self.repository.assert_fresh(token, principal)
            if not isinstance(new_owner_id, str) or not new_owner_id:
                raise AlphaError("Choose the member who becomes the new owner.")
            if new_owner_id == principal:
                raise AlphaError("Choose someone else to become the owner.", 409)
            cur.execute("SELECT role FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s AND status='active' FOR UPDATE", (workspace_id, new_owner_id))
            current = cur.fetchone()
            if not current:
                raise AlphaError("Member unavailable.", 404)
            if current[0] != "admin":
                raise AlphaError("Choose an active admin to become the new owner.", 409)
            cur.execute("UPDATE public.pr_memberships SET role='owner',can_publish=true,can_reply=true,can_moderate=true,can_manage_connections=true,updated_at=now() WHERE workspace_id=%s AND user_id=%s", (workspace_id, new_owner_id))
            # The outgoing owner becomes an admin with every grant, so stepping down never quietly drops a right they already had.
            cur.execute("UPDATE public.pr_memberships SET role='admin',can_publish=true,can_reply=true,can_moderate=true,can_manage_connections=true,updated_at=now() WHERE workspace_id=%s AND user_id=%s", (workspace_id, principal))
            audit(cur, workspace_id, principal, "ownership.transferred", new_owner_id)
            return {"ownerId": new_owner_id, "previousOwnerId": principal}

    def remove_member(self, workspace_id, token, user_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "manage_members")
            self.repository.assert_fresh(token, principal)
            cur.execute("SELECT role FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s AND status='active' FOR UPDATE", (workspace_id, user_id))
            current = cur.fetchone()
            if not current:
                raise AlphaError("Member unavailable.", 404)
            if current[0] == "owner":
                raise AlphaError("The owner cannot be removed.", 409)
            cur.execute("UPDATE public.pr_memberships SET status='revoked',updated_at=now() WHERE workspace_id=%s AND user_id=%s", (workspace_id, user_id))
            audit(cur, workspace_id, principal, "member.removed", user_id)
            return {"userId": user_id, "status": "revoked", "note": "Jobs this member approved are held at the next worker claim until re-approved."}

    def invite(self, workspace_id, token, email, role, flags):
        if not isinstance(email, str) or "@" not in email or not 3 <= len(email) <= 254:
            raise AlphaError("Enter the invitee's email address.")
        email = email.strip().lower()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            actor = _membership(row)
            require(actor, "manage_members")
            self.repository.assert_fresh(token, principal)
            granted = validate_grant(role, flags, actor)
            from .billing import require_plan_capacity
            require_plan_capacity(cur, workspace_id, "members")
            cur.execute("SELECT count(*) FROM public.pr_invitations WHERE workspace_id=%s AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at>now()", (workspace_id,))
            if cur.fetchone()[0] >= MAX_PENDING_INVITATIONS:
                raise AlphaError("Revoke or wait for pending invitations before adding more.", 409)
            raw = secrets.token_urlsafe(32)
            cur.execute("INSERT INTO public.pr_invitations(workspace_id,email,role,permissions,token_hash,created_by,expires_at) VALUES(%s,%s,%s,%s::jsonb,%s,%s,now()+make_interval(secs=>%s)) RETURNING id::text,extract(epoch from expires_at)", (workspace_id, email, role, json.dumps(granted), hashlib.sha256(raw.encode()).hexdigest(), principal, INVITATION_TTL))
            invitation_id, expires = cur.fetchone()
            audit(cur, workspace_id, principal, "invitation.created", invitation_id, {"role": role, **granted})
            # The raw token is returned exactly once; only its hash is stored.
            result = {"invitationId": invitation_id, "token": raw, "role": role, **granted, "expiresAt": float(expires)}
        # After commit the invitee receives the accept link; a failed send never undoes the invitation.
        result["emailSent"] = self._send_invitation(email, role, raw, float(expires), principal)
        return result

    def _send_invitation(self, email, role, raw, expires_at, inviter):
        if not self.public_base_url:
            return False
        inviter_label = self._email_for(inviter) or "A workspace owner"
        return bool(self.mailer.invitation(email, inviter_label, role, f"{self.public_base_url}/invite/{raw}", expires_at).get("sent"))

    def invitations(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(_membership(row), "manage_members")
            cur.execute("SELECT id::text,email,role,permissions,created_by::text,extract(epoch from created_at),extract(epoch from expires_at),accepted_by::text,extract(epoch from accepted_at),extract(epoch from revoked_at) FROM public.pr_invitations WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 100", (workspace_id,))
            items = []
            for item in cur.fetchall():
                state = "revoked" if item[9] else "accepted" if item[8] else "expired" if item[6] <= self.clock() else "pending"
                items.append({"invitationId": item[0], "email": item[1], "role": item[2], "permissions": item[3], "createdBy": item[4], "createdAt": float(item[5]), "expiresAt": float(item[6]), "acceptedBy": item[7], "state": state})
            return {"invitations": items}

    def revoke_invitation(self, workspace_id, token, invitation_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "manage_members")
            cur.execute("UPDATE public.pr_invitations SET revoked_at=now() WHERE workspace_id=%s AND id::text=%s AND accepted_at IS NULL AND revoked_at IS NULL", (workspace_id, invitation_id))
            if cur.rowcount != 1:
                raise AlphaError("Invitation unavailable.", 404)
            audit(cur, workspace_id, principal, "invitation.revoked", invitation_id)
            return {"invitationId": invitation_id, "state": "revoked"}

    def accept_invitation(self, token, raw, client=None):
        if not isinstance(raw, str) or not 20 <= len(raw) <= 128:
            raise AlphaError("Invitation unavailable.", 404)
        if client:
            with self.connection_factory() as db:
                with db.cursor() as cur:
                    throttle(cur, f"invite:{client}", 10, 60)
        principal = self.verify_session(token)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"SELECT {self.INVITATION_COLUMNS} FROM public.pr_invitations WHERE token_hash=%s AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at>now() FOR UPDATE", (token_hash,))
                invitation = cur.fetchone()
                if not invitation:
                    raise AlphaError("Invitation unavailable.", 404)
                return self._join(cur, token, principal, invitation)

    INVITATION_COLUMNS = "id::text,workspace_id::text,role,permissions"

    def _join(self, cur, token, principal, invitation):
        """Turn a locked pending invitation row (INVITATION_COLUMNS) into an active membership."""
        invitation_id, workspace_id, role, granted = invitation
        cur.execute("INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (principal,))
        cur.execute("SELECT role,status FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s FOR UPDATE", (workspace_id, principal))
        existing = cur.fetchone()
        if existing and existing[1] == "active":
            raise AlphaError("You are already a member of this workspace.", 409)
        from .billing import require_plan_capacity
        require_plan_capacity(cur, workspace_id, "members")
        values = (role, granted.get("can_publish", False), granted.get("can_reply", False), granted.get("can_moderate", False), granted.get("can_manage_connections", False))
        if existing:
            cur.execute("UPDATE public.pr_memberships SET status='active',role=%s,can_publish=%s,can_reply=%s,can_moderate=%s,can_manage_connections=%s,updated_at=now() WHERE workspace_id=%s AND user_id=%s", (*values, workspace_id, principal))
        else:
            cur.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections) VALUES(%s,%s,%s,'active',%s,%s,%s,%s)", (workspace_id, principal, values[0], *values[1:]))
        cur.execute("UPDATE public.pr_invitations SET accepted_by=%s,accepted_at=now() WHERE id::text=%s", (principal, invitation_id))
        audit(cur, workspace_id, principal, "invitation.accepted", invitation_id, {"role": role})
        self._touch_session(cur, principal, self._session_id(token, principal))
        return {"workspaceId": workspace_id, "role": role, **{key: granted.get(key, False) for key in ("can_publish", "can_reply", "can_moderate", "can_manage_connections")}}

    # --- invitations addressed to the signed-in person's verified email -----------------------
    # The emailed link works for anyone holding it; these routes instead match the invitation's
    # address to the identity service's confirmed email, so the profile can show and settle them.

    PENDING_INVITATION = "i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at>now()"

    def my_invitations(self, token):
        principal = self.verify_session(token)
        email = self._email_for(principal)
        if not email:
            return {"invitations": [], "available": False}
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"SELECT i.id::text,i.workspace_id::text,coalesce(w.state->'workspace'->>'name',''),i.role,i.permissions,i.created_by::text,coalesce(p.display_name,''),extract(epoch from i.created_at),extract(epoch from i.expires_at) FROM public.pr_invitations i JOIN public.pr_workspaces w ON w.id=i.workspace_id LEFT JOIN public.pr_profiles p ON p.user_id=i.created_by WHERE i.email=%s AND {self.PENDING_INVITATION} AND NOT EXISTS (SELECT 1 FROM public.pr_memberships m WHERE m.workspace_id=i.workspace_id AND m.user_id=%s AND m.status='active') ORDER BY i.created_at DESC LIMIT 20", (email, principal))
                rows = cur.fetchall()
        return {"available": True, "invitations": [{"invitationId": row[0], "workspaceId": row[1], "workspaceName": row[2] or "My workspace", "role": row[3], "permissions": row[4] if isinstance(row[4], dict) else {}, "invitedBy": {"userId": row[5], "displayName": row[6]}, "createdAt": float(row[7]), "expiresAt": float(row[8])} for row in rows]}

    def _invitation_email(self, principal):
        email = self._email_for(principal)
        if not email:
            raise AlphaError("Your sign-in email could not be confirmed, so this invitation cannot be matched to you.", 409)
        return email

    def accept_my_invitation(self, token, invitation_id):
        if not isinstance(invitation_id, str) or not 1 <= len(invitation_id) <= 64:
            raise AlphaError("Invitation unavailable.", 404)
        principal = self.verify_session(token)
        email = self._invitation_email(principal)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                throttle(cur, f"invite-accept:{principal}", 10, 60)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"SELECT {self.INVITATION_COLUMNS} FROM public.pr_invitations i WHERE i.id::text=%s AND i.email=%s AND {self.PENDING_INVITATION} FOR UPDATE", (invitation_id, email))
                invitation = cur.fetchone()
                if not invitation:
                    raise AlphaError("Invitation unavailable.", 404)
                return self._join(cur, token, principal, invitation)

    def decline_my_invitation(self, token, invitation_id):
        if not isinstance(invitation_id, str) or not 1 <= len(invitation_id) <= 64:
            raise AlphaError("Invitation unavailable.", 404)
        principal = self.verify_session(token)
        email = self._invitation_email(principal)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute(f"UPDATE public.pr_invitations i SET revoked_at=now() WHERE i.id::text=%s AND i.email=%s AND {self.PENDING_INVITATION} RETURNING i.workspace_id::text", (invitation_id, email))
                row = cur.fetchone()
                if not row:
                    raise AlphaError("Invitation unavailable.", 404)
                audit(cur, row[0], principal, "invitation.declined", invitation_id)
        return {"invitationId": invitation_id, "state": "declined"}

    def sessions(self, token, client_label=""):
        principal = self.verify_session(token)
        current = self._session_id(token, principal)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                fresh = self._touch_session(cur, principal, current, client_label)
                cur.execute("SELECT s.session_id,extract(epoch from s.first_seen),extract(epoch from s.last_seen),s.client_label,(r.session_id IS NOT NULL) FROM public.pr_sessions s LEFT JOIN public.pr_session_revocations r ON r.user_id=s.user_id AND r.session_id=s.session_id WHERE s.user_id=%s ORDER BY s.last_seen DESC LIMIT 50", (principal,))
                rows = cur.fetchall()
        if fresh:
            self._alert_new_device(principal, current, client_label)
        return {"sessions": [{"sessionId": item[0], "firstSeen": float(item[1]), "lastSeen": float(item[2]), "client": item[3], "revoked": bool(item[4]), "current": item[0] == current} for item in rows]}

    def revoke_session(self, token, session_id):
        principal = self.verify_session(token)
        self.repository.assert_fresh(token, principal)
        if not isinstance(session_id, str) or not 16 <= len(session_id) <= 160:
            raise AlphaError("Session unavailable.", 404)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT 1 FROM public.pr_sessions WHERE user_id=%s AND session_id=%s", (principal, session_id))
                if not cur.fetchone():
                    raise AlphaError("Session unavailable.", 404)
                cur.execute("INSERT INTO public.pr_session_revocations(user_id,session_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (principal, session_id))
                audit(cur, None, principal, "session.revoked", "")
        return {"sessionId": session_id, "revoked": True, "current": session_id == self._session_id(token, principal)}

    def revoke_other_sessions(self, token):
        """Deny every session this API has seen except the current one, and ask the identity service
        to revoke the other refresh tokens so sessions that never reached us end too."""
        principal = self.verify_session(token)
        self.repository.assert_fresh(token, principal)
        current = self._session_id(token, principal)
        if not current:
            raise AlphaError("Hosted session revocation is not configured.", 503)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("INSERT INTO public.pr_session_revocations(user_id,session_id) SELECT s.user_id,s.session_id FROM public.pr_sessions s WHERE s.user_id=%s AND s.session_id<>%s ON CONFLICT DO NOTHING", (principal, current))
                revoked = cur.rowcount
                audit(cur, None, principal, "session.revoked_others", "", {"count": revoked})
        logout_others = getattr(self.identity, "logout_others", None)
        remote = bool(logout_others(token)) if logout_others else False
        return {"revoked": revoked, "refreshRevoked": remote, "current": current}

    def audit_events(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            if row[2] not in ("admin", "owner"):
                raise AlphaError("Only workspace admins and owners can read the audit log.", 403, code="audit_access_required")
            cur.execute("SELECT id::text,actor::text,kind,subject,extract(epoch from at),meta FROM public.pr_audit_events WHERE workspace_id=%s ORDER BY at DESC LIMIT 200", (workspace_id,))
            return {"events": [{"id": item[0], "actor": item[1], "kind": item[2], "subject": item[3], "at": float(item[4]), "meta": item[5]} for item in cur.fetchall()]}

    def upload_media(self, workspace_id, token, revision, payload):
        if self.assets is None:
            raise AlphaError("Media uploads aren't available yet.", 503, code="media_storage_not_configured")
        principal = self.verify_session(token)
        saved = self.repository.get(workspace_id, token)
        require(Membership(saved["membership"]["role"], saved["membership"]), "edit")
        if saved['state'].get('accountDeletion'):
            raise AlphaError('Account deletion is pending.', 409, code='account_deletion_pending')
        self.commands._require_mutable_media(saved["state"])
        asset = self.assets.stage_upload(workspace_id, payload)
        try:
            saved = self.repository.command(workspace_id, token, revision, lambda state, actor: self.commands.add_asset(state, actor, asset))
        except Exception:
            self.assets.remove(workspace_id, asset)
            raise
        return self._present(saved)

    def delete_media(self, workspace_id, token, revision, asset_id):
        if self.assets is None:
            raise AlphaError("Media uploads aren't available yet.", 503, code="media_storage_not_configured")
        prepared = self.repository.command(workspace_id, token, revision, lambda state, actor: self.commands.prepare_asset_delete(state, actor, asset_id))
        asset = find(prepared["state"]["phase2"]["assets"], asset_id)
        self.assets.remove(workspace_id, asset)
        finished = self.repository.command(workspace_id, token, prepared["revision"], lambda state, actor: self.commands.finish_asset_delete(state, actor, asset_id))
        return self._present(finished)

    def media(self, workspace_id, token, asset_id):
        if self.assets is None:
            raise AlphaError("Media uploads aren't available yet.", 503, code="media_storage_not_configured")
        snapshot = self.repository.get(workspace_id, token)
        asset = find(snapshot["state"]["phase2"]["assets"], asset_id)
        if asset.get("deleted") or not asset.get("objectName"):
            raise AlphaError("This private media object is unavailable.", 404)
        return self.assets.storage.get(workspace_id, "media", asset["objectName"]), asset.get("mime", "application/octet-stream")

    def export(self, workspace_id, token):
        from .learning_service import export_files
        snapshot = self.get(workspace_id, token)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            learning_files = export_files(cur, workspace_id)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("phase2/workspace.json", json.dumps(snapshot["state"], ensure_ascii=False, indent=2))
            for name, body in learning_files.items():
                archive.writestr(name, body)
            archive.writestr("README.txt", "Private hosted export. It contains drafts and approval records but no access tokens, provider credentials, or media bytes. Export does not publish content.\n")
        return output.getvalue()

    def export_profile(self, workspace_id, token):
        snapshot = self.get(workspace_id, token)
        state = snapshot["state"]
        profile = self.commands.engine._profile(state)
        if not profile or not profile.get("packageSchema"):
            raise AlphaError("Approve the field-level Personal Voice Package before exporting it.")
        files = profiles.portable_files(state, profile)
        manifest = {
            "schema": "postriff.personal-voice.v1",
            "packageVersion": "1.0.0",
            "status": "user_approved",
            "createdAt": self.clock(),
            "profileRevision": state["speaker"]["activeRevision"],
            "workspaceId": workspace_id,
            "actualRuntime": "phase2-hosted",
            "sourceManifest": "sources/manifest.json",
            "unresolvedFields": sum(item["decision"] != "approved" for item in profile.get("review", [])),
            "permissions": {"globalInstallation": False, "memoryMutation": False, "accountConnection": False, "externalSend": False, "publication": False},
        }
        files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return output.getvalue()

    def logout(self, token):
        if self.identity is None or not hasattr(self.verify_session, "session_id"):
            raise AlphaError("Hosted session revocation is not configured.", 503)
        principal = self.verify_session(token)
        session_id = self.verify_session.session_id(token, principal)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("INSERT INTO public.pr_session_revocations(user_id,session_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (principal, session_id))
        remote = self.identity.logout(token)
        return {"signedOut": True, "refreshRevoked": remote, "sessionDenied": True}

    def delete_account(self, workspace_id, token, confirmation):
        from .account_deletion import delete_account
        return delete_account(self, workspace_id, token, confirmation)
