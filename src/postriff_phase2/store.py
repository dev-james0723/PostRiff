"""Transactional local repository, immutable approvals and leased destination jobs."""
import base64
import copy
import hashlib
import io
import json
import time
import zipfile
from postriff_alpha.domain import Store, AlphaError, uid, clean
from postriff_alpha import learning, visuals
from .auth import Phase2Auth
from .contracts import PLANS, LIMITS, SCENARIOS, FixtureImages, FixtureSocial, digest, resolve_time
from .media import decode_upload
from .content_types import apply_content_action, content_preflight, ensure_content_state, projection as content_projection
from .outcomes import normalize_result, unknown
from . import learning_signals as signals, source_policy

TERMINAL = ("verified", "failed", "canceled")
IN_FLIGHT = ("submitting", "provider_accepted", "published", "uncertain")
# Official per-account publish limits per 24 h (connector-audit.md); enforced at approval time.
DAILY_LIMITS = {"Instagram": 100, "Threads": 250, "LinkedIn": 150}
# Why a person does not want a draft (variant_feedback). General vocabulary; the note is the person's own words.
FEEDBACK_REASONS = ("wrong_facts", "not_my_voice", "too_long", "too_short", "wrong_angle", "wrong_language", "other")


def signals_epoch(value):
    """ISO or epoch → epoch seconds; 0 when absent (used for the local learning windows)."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            from datetime import datetime, timezone
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def find(items, key):
    found = next((x for x in items if x["id"] == key), None)
    if found is None:
        raise AlphaError("This item is not available in your workspace.", 404)
    return found


class Phase2Store(Store):
    def __init__(self, path, clock=time.time, social=None, images=None):
        self.clock, self.social, self.images = clock, social or FixtureSocial(), images or FixtureImages()
        super().__init__(path)
        with self.connect() as db:
            # Learning signals (preference-learning design §5.1): ids and numeric features per command, never draft text.
            db.execute("CREATE TABLE IF NOT EXISTS learning_events (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, consumed_by TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS learning_events_workspace ON learning_events (workspace_id, created_at)")
        self.auth = Phase2Auth(self)

    def _row(self, db, workspace_id, token):
        row = super()._row(db, workspace_id, token)
        session = db.execute("SELECT s.expires FROM p2_sessions s JOIN alpha_devices d ON d.id=s.device_id WHERE d.workspace_id=? AND d.credential_hash=? AND d.status='active'", (workspace_id, hashlib.sha256(token.encode()).hexdigest())).fetchone()
        if not session or session["expires"] <= self.clock():
            raise AlphaError("This session expired or was revoked. Sign in again.", 401)
        return row

    def _present(self, state, revision):
        result = super()._present(state, revision)
        ensure_content_state(result["state"])
        result["state"]["contentTypes"] = content_projection(result["state"])
        p = result["state"].get("phase2")
        if p:
            p["trial"]["status"] = "active" if self.clock() < p["trial"]["expiresAt"] else "expired"
            p["art"]["providerBrief"] = self.art_brief(state)
            p["art"]["briefHash"] = digest(p["art"]["providerBrief"]) if p["art"]["providerBrief"] else None
            p["plans"] = [{"id": key, **value} for key, value in PLANS.items()]
            p["channels"] = [{**x, "displayState": self.channel_state(x)} for x in p["channels"]]
        return result

    def channel_state(self, c):
        if not c["configured"]:
            return "Connect"
        if c["revoked"] or c["expiresAt"] <= self.clock():
            return "Reconnect"
        if not c["identityVerified"] or not c["capabilityVerified"] or c["verifiedAt"]+3600 < self.clock():
            return "Finish setup"
        return "Ready for posting"

    def mutate(self, wid, token, expected_revision, action, payload):
        if wid in self.samples:
            return super().mutate(wid, token, expected_revision, action, payload)
        if not isinstance(action, str) or not isinstance(payload, dict):
            raise AlphaError("Expected a structured action.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, wid, token)
            if type(expected_revision) is not int or expected_revision != row["revision"]:
                raise AlphaError("This workspace changed. Reload the saved version before continuing.", 409)
            s = json.loads(row["state"])
            before = json.loads(row["state"])
            ensure_content_state(s)
            device = db.execute("SELECT d.id,d.user_id,m.role FROM alpha_devices d JOIN alpha_memberships m ON m.workspace_id=d.workspace_id AND m.user_id=d.user_id WHERE d.workspace_id=? AND d.credential_hash=? AND d.status='active' AND m.status='active'", (wid, hashlib.sha256(token.encode()).hexdigest())).fetchone()
            if not device or device['role'] not in ('owner', 'editor'):
                raise AlphaError("Read-only or revoked membership.", 403)
            if source_policy.apply_policy_action(s, action, payload, device["user_id"], self.clock()):
                pass
            elif action.startswith("p2_"):
                self.apply_phase2(db, s, action[3:], payload, device)
            else:
                if action in ("generate", "adapt"):
                    trial = s["phase2"]["trial"]
                    if trial["expiresAt"] <= self.clock() or trial["writingUsed"] >= 10:
                        raise AlphaError("The local trial simulation has no writing allowance left. Your drafts and exports remain available.")
                    trial["writingUsed"] += 1
                self._apply(s, action, payload)
                if action in ("generate", "adapt") and s.get("variants"):
                    selection = ensure_content_state(s)["selection"]
                    variant = s["variants"][-1]
                    selected_type = next((item for item in content_projection(s)["catalog"] if item["id"] == selection["contentTypeId"]), None)
                    variant.update({"contentTypeId": selection["contentTypeId"], "contentTypeVersion": selection["contentTypeVersion"], "formatId": selection["formatId"], "contentSkillRouteIds": selected_type["skillRouteIds"] if selected_type else []})
                if action in ("variant_edit", "opening"):
                    variant = self._variant(s, payload.get("variantId"))
                    variant["needsReview"] = True
                    previous_review = variant.pop("uncertaintyReview", {})
                    variant["unknowns"] = previous_review.get("excludedFromDraft", variant["unknowns"])
            source_policy.stamp(s)
            self.invalidate(s)
            if action == "p2_delete_account":
                return {"revision": row["revision"]+1, "state": None, "deleted": True}
            self._record_events(db, wid, signals.derive_events(before, s, device["user_id"], self.clock(), action, payload))
            self._learn(db, wid, s)
            db.execute("UPDATE workspaces SET revision=?,state=? WHERE id=?", (row["revision"]+1, json.dumps(s), wid))
            return self._present(s, row["revision"]+1)

    def _learn(self, db, wid, s):
        """Local extraction (design §5.2 C1) inline: once five events wait, or one has waited a day, the
        deterministic rules over the last 90 days become proposals in this workspace's own list."""
        from . import learning_extract as extract
        now = self.clock()
        if (s.get("learning") or {}).get("enabled") is False:
            return
        pending = db.execute("SELECT count(*), min(created_at) FROM learning_events WHERE workspace_id=? AND consumed_by IS NULL", (wid,)).fetchone()
        if not pending[0] or (pending[0] < 5 and pending[1] > now - 86400):
            return
        rows = db.execute("SELECT id, body FROM learning_events WHERE workspace_id=? AND created_at > ? ORDER BY created_at, rowid", (wid, now - extract.WINDOW_DAYS * 86400)).fetchall()
        events = [{**json.loads(r["body"]), "id": r["id"]} for r in rows]
        support, counter = extract.observations(events)
        proposals = s.get("preferences") or []
        dismissed = {p.get("scopeKey") for p in proposals if p.get("status") == "rejected" and signals_epoch(p.get("decidedAt")) > now - 90 * 86400}
        decisions = [p.get("status") for p in sorted(proposals, key=lambda p: p.get("decidedAt") or "", reverse=True) if p.get("decidedAt")]
        recent = {"remembered": "remembered", "post-only": "post_only", "rejected": "dismissed"}
        budget = 1 - sum(1 for p in proposals if p.get("source") in ("deterministic", "model") and signals_epoch(p.get("createdAt")) > now - 86400)
        candidates = extract.consolidate(support, counter, s, now, dismissed, [recent.get(d, d) for d in decisions])
        replaced = {c.get("replaces") for c in candidates}
        candidates += [r for r in extract.regressions(s, events, now) if r["replaces"] not in replaced]
        for candidate in candidates:
            if budget <= 0:
                break
            try:
                if learning.propose(s, candidate, now) is not None:
                    budget -= 1
            except ValueError:
                continue
        db.execute("UPDATE learning_events SET consumed_by=? WHERE workspace_id=? AND consumed_by IS NULL AND created_at <= ?", (uid(), wid, now))

    def _record_events(self, db, wid, events):
        """Learning signals for this workspace, kept 180 days (learning_signals: ids and numbers only)."""
        for event in events:
            at = float(event["at"])
            db.execute("INSERT INTO learning_events VALUES (?,?,?,?,?,?,NULL)", (uid(), wid, event["kind"], json.dumps(event, ensure_ascii=False), at, at + signals.EVENT_TTL_DAYS * 86400))

    def learning_events(self, wid, token, limit=500):
        with self.connect() as db:
            self._row(db, wid, token)
            rows = db.execute("SELECT id, body, consumed_by FROM learning_events WHERE workspace_id=? AND expires_at > ? ORDER BY created_at, rowid LIMIT ?", (wid, self.clock(), limit)).fetchall()
        return [{**json.loads(r["body"]), "id": r["id"], "consumedBy": r["consumed_by"]} for r in rows]

    def art_brief(self, s):
        visuals.ensure(s)
        local = visuals.art_brief(s)
        # Provider request keys are an allowlist; source IDs and account data never cross it.
        allowed = ("themes", "energy", "visualRhythm", "motifs", "palette", "light", "avoid", "promptVersion")
        return {key: local[key] for key in allowed if key in local} if local["status"] != "insufficient_approved_context" else None

    def apply_phase2(self, db, s, action, p, device):
        data, now = s["phase2"], self.clock()
        learning.ensure(s, now)
        if apply_content_action(s, action, p, device["user_id"], now):
            return
        if action == "plan":
            if p.get("plan") not in PLANS:
                raise AlphaError("Business is unavailable; choose Studio or Assist.")
            data["trial"]["plan"] = p["plan"]
        elif action in ("logout", "revoke_device"):
            target = device["id"] if action == "logout" else p.get("deviceId")
            d = find(data["devices"], target)
            d["status"] = "revoked"
            db.execute("UPDATE alpha_devices SET status='revoked' WHERE id=? AND workspace_id=?", (target, s["workspace"]["id"]))
        elif action == "link_identity":
            self.auth.link(db, s, p)
        elif action == "unlink_identity":
            provider = p.get("provider")
            if provider not in data["identities"] or len(data["identities"]) <= 1:
                raise AlphaError("Keep at least one verified recovery method.")
            db.execute("DELETE FROM p2_identities WHERE user_id=? AND provider=?", (device["user_id"], provider))
            data["identities"].remove(provider)
        elif action == "delete_account":
            if p.get("confirmation") != "DELETE":
                raise AlphaError("Type DELETE to confirm removal of this local fixture account.")
            if any(j["state"] in IN_FLIGHT for j in data["jobs"]):
                raise AlphaError("Reconcile in-flight outcomes before deletion; canceling cannot recall a submitted post.")
            wid = s["workspace"]["id"]
            db.execute("DELETE FROM p2_challenges WHERE principal IN (SELECT principal FROM p2_identities WHERE user_id=?)", (device["user_id"],))
            db.execute("DELETE FROM p2_sessions WHERE device_id IN (SELECT id FROM alpha_devices WHERE workspace_id=?)", (wid,))
            for table in ("alpha_devices", "alpha_auth_events", "alpha_auth_requests", "alpha_memberships"):
                db.execute(f"DELETE FROM {table} WHERE workspace_id=?", (wid,))
            db.execute("UPDATE alpha_users SET display_name='',auth_state='deleted' WHERE id=?", (device["user_id"],))
            db.execute("DELETE FROM workspaces WHERE id=?", (wid,))
        elif action == "art_generate":
            brief, art = self.art_brief(s), data["art"]
            if p.get("consent") is not True:
                art["status"] = "refused_local_fallback"
                return
            if not brief or p.get("briefHash") != digest(brief):
                raise AlphaError("Review the current image-eligible ArtBrief first.", 409)
            count = p.get("count", 3)
            if type(count) is not int or not 1 <= count <= 3:
                raise AlphaError("Choose one to three previews.")
            if art.get("cacheHash") == digest(brief) and art["candidates"]:
                art["status"] = "cached_fixture_previews"
                return
            if data["trial"]["artworkUsed"] >= 1 or data["trial"]["expiresAt"] <= now:
                art["status"] = "allowance_unavailable_local_fallback"
                return
            event = {"id": uid(), "at": now, "actor": device["user_id"], "briefHash": digest(brief), "count": count, "provider": "local-procedural-fixture", "model": "none", "estimatedCost": 0}
            art["consents"].append(event)
            if p.get("scenario") == "failed":
                art["status"] = "failed_local_fallback"
                return
            candidates = self.images.previews(brief, count)
            if len(candidates) > 3:
                raise AlphaError("Image adapter exceeded the preview limit.")
            local = visuals.art_brief(s)
            art["candidates"] = [{"id": uid(), "data": base64.b64encode(raw).decode(), "hash": hashlib.sha256(raw).hexdigest(), "mime": "image/svg+xml", "brief": brief, "briefHash": digest(brief), "sourceFieldIds": local["sourceFieldIds"], "profileRevision": s["speaker"]["activeRevision"], "consentId": event["id"], "provider": "local-procedural-fixture", "model": "none", "deleted": False} for raw in candidates]
            art.update({"status": "fixture_previews", "cacheHash": digest(brief)})
            data["trial"]["artworkUsed"] += 1
        elif action == "art_select":
            item = find(data["art"]["candidates"], p.get("assetId"))
            focal = p.get("focal", [0.5, 0.5])
            if item["deleted"] or not isinstance(focal, list) or len(focal) != 2 or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in focal):
                raise AlphaError("Choose an available artwork and a valid focal position.")
            data["art"]["selected"] = {**copy.deepcopy(item), "focal": focal, "crop": "cover", "selectedAt": now}
            data["art"]["status"] = "selected_fixture"
        elif action == "art_delete":
            art = data["art"]
            art.update({"selected": None, "candidates": [], "cacheHash": None, "status": "deleted_local_fallback", "deletedAt": now})
        elif action == "media_upload":
            data["assets"].append(decode_upload(p))
        elif action == "media_delete":
            asset = find(data["assets"], p.get("assetId"))
            if any(j["state"] in IN_FLIGHT and any(m["id"] == asset["id"] for m in j["manifest"]["media"]) for j in data["jobs"]):
                raise AlphaError("Reconcile this asset's in-flight jobs before deleting its bytes.")
            asset.update({"deleted": True, "data": ""})
        elif action == "channel_add":
            platform = p.get("platform")
            if platform not in LIMITS:
                raise AlphaError("Use native drafting/export for this channel.")
            data["channels"].append({"id": uid(), "platform": platform, "account": f"Fictional {platform} account {len(data['channels'])+1}", "accountType": "member" if platform == "LinkedIn" else "professional", "language": p.get("language", "English"), "configured": True, "identityVerified": False, "capabilityVerified": False, "scopes": [], "verifiedAt": 0, "expiresAt": now+86400, "revoked": False, "capabilityVersion": 0, "qualification": "implemented_with_fixtures", "evidenceSource": "synthetic", "scenario": "success"})
        elif action == "channel_verify":
            c = find(data["channels"], p.get("channelId"))
            scenario = p.get("scenario", "success")
            if scenario not in SCENARIOS:
                raise AlphaError("Choose a supported fixture outcome.")
            c.update({"identityVerified": scenario != "denied", "capabilityVerified": scenario not in ("denied", "capability_loss"), "scopes": ["w_member_social"] if c["platform"] == "LinkedIn" else ["instagram_business_basic", "instagram_business_content_publish"], "expiresAt": now-1 if scenario == "expired" else now+86400, "verifiedAt": now, "revoked": False, "capabilityVersion": c["capabilityVersion"]+1, "scenario": scenario})
        elif action == "channel_disconnect":
            find(data["channels"], p.get("channelId"))["revoked"] = True
        elif action == "variant_review":
            v = self._variant(s, p.get("variantId"))
            if p.get("variantRevision") != v["revision"] or p.get("confirmed") is not True:
                raise AlphaError("Read this exact draft and confirm the source and uncertainty review.", 409)
            if v["blockedByRetraction"] or v.get("briefRevision") != s["brief"]["revision"] or v["voiceRevision"] != s["speaker"]["activeRevision"] or any(not self._source(s, i)["active"] for i in v["sourceIds"]):
                raise AlphaError("Regenerate against current approved sources and voice before reviewing.")
            if p.get("excludedUnknowns") != v["unknowns"]:
                raise AlphaError("Review every unknown. Confirm that unsupported details are excluded from this draft.")
            v["uncertaintyReview"] = {"excludedFromDraft": v["unknowns"], "actor": device["user_id"], "at": now, "revision": v["revision"], "claim": "user_confirmed_exclusion_not_fact_verification"}
            v["unknowns"], v["needsReview"] = [], False
        elif action == "review":
            manifest = self.build_manifest(s, p, device["user_id"])
            data["reviews"] = data["reviews"][-19:]+[{"id": uid(), "manifest": manifest, "digest": digest(manifest), "status": "needs_review", "createdAt": now}]
        elif action == "approve":
            review = find(data["reviews"], p.get("reviewId"))
            if review["digest"] != p.get("digest") or p.get("confirmed") is not True or review["status"] not in ("needs_review", "approved"):
                raise AlphaError("Review and explicitly approve this exact destination manifest.", 409)
            manifest = review["manifest"]
            if not self.current(s, manifest) or manifest["expiresAt"] <= now or (not getattr(self, "hosted_entitlements", False) and data["trial"]["expiresAt"] <= now) or self.channel_state(find(data["channels"], manifest["channelId"])) != "Ready for posting":
                raise AlphaError("This approval is stale. Prepare a new review.", 409)
            existing = next((j for j in data["jobs"] if j["manifest"]["idempotencyKey"] == manifest["idempotencyKey"]), None)
            if existing:
                if existing["state"] in ("failed", "canceled") and review["status"] != "approved":
                    raise AlphaError("This review belongs to an ended job. Prepare a new review to try again.", 409, code="review_consumed")
                review.update({"status": "approved", "jobId": existing["id"]})
                return
            channel = find(data["channels"], manifest["channelId"])
            limit = DAILY_LIMITS.get(channel["platform"])
            recent = [j for j in data["jobs"] if j["manifest"]["channelId"] == manifest["channelId"] and j.get("approvedAt", 0) > now - 86400 and j["state"] not in ("canceled", "failed")]
            if limit and len(recent) >= limit:
                raise AlphaError(f"{channel['platform']} allows {limit} posts per 24 hours for this account; this approval would exceed it.", 409)
            review["status"] = "approved"
            job = {"id": uid(), "manifest": copy.deepcopy(manifest), "approvalDigest": review["digest"], "approvedAt": now, "approvedBy": device["user_id"], "state": "approved", "events": [], "attempts": [], "checks": 0, "leaseOwner": None, "leaseUntil": 0, "nextAt": manifest["timing"]["timestamp"], "cancelRequested": False, "scheduleId": p.get("scheduleId")}
            self.event(job, "approved", "Exact local fixture approval recorded")
            self.event(job, "scheduled", "Waiting for the local durable worker")
            data["jobs"].append(job)
            review["jobId"] = job["id"]
        elif action == "approve_many":
            reviews = p.get("reviews")
            if p.get("confirmed") is not True or not isinstance(reviews, list) or not 1 <= len(reviews) <= 10:
                raise AlphaError("Explicitly review between one and ten exact destinations.")
            # One schedule, many destinations: each job keeps its own state under a shared scheduleId.
            schedule_id = uid()
            for review in reviews:
                if not isinstance(review, dict):
                    raise AlphaError("Expected exact review IDs and digests.")
                self.apply_phase2(db, s, "approve", {**review, "confirmed": True, "scheduleId": schedule_id}, device)
        elif action == "cancel":
            job = find(data["jobs"], p.get("jobId"))
            if job["state"] in TERMINAL:
                return
            job["cancelRequested"] = True
            self.event(job, "uncertain" if job["state"] in IN_FLIGHT else "canceled", "Cancellation cannot recall an accepted submission; reconcile" if job["state"] in IN_FLIGHT else "Canceled before submission")
        elif action == "variant_feedback":
            # "Don't use this draft": kept on the draft as a learning signal for a later phase, and it blocks
            # scheduling until the person edits the draft or accepts a new candidate for it.
            v = self._variant(s, p.get("variantId"))
            if p.get("variantRevision") != v["revision"]:
                raise AlphaError("This draft changed. Reload before giving feedback on it.", 409)
            reasons = p.get("reasons")
            if not isinstance(reasons, list) or not reasons or len(set(reasons)) != len(reasons) or any(r not in FEEDBACK_REASONS for r in reasons):
                raise AlphaError("Choose at least one reason from the list.")
            if any(j["state"] not in ("canceled", "failed") and j["manifest"]["variantId"] == v["id"] for j in data["jobs"]):
                raise AlphaError("This draft is already scheduled or published. Cancel the job first, or give feedback on a newer draft.", 409)
            v.setdefault("feedback", []).append({"id": uid(), "reasons": reasons, "note": clean(p.get("note", ""), 200), "actor": device["user_id"], "at": now, "revision": v["revision"]})
            v["rejected"] = True
        elif action == "refresh":
            pass
        else:
            raise AlphaError("This Phase 2 action is unavailable.", 404)

    def build_manifest(self, s, p, actor):
        data = s["phase2"]
        v = self._variant(s, p.get("variantId"))
        preflight = content_preflight(s, v["sourceIds"])
        blockers = [item for item in preflight if item["severity"] == "blocker"]
        if blockers:
            raise AlphaError(blockers[0]["message"], 409)
        c = find(data["channels"], p.get("channelId"))
        if not getattr(self, "hosted_entitlements", False) and data["trial"]["expiresAt"] <= self.clock():
            raise AlphaError("Trial expired. Export remains available; scheduling is held.")
        if self.channel_state(c) != "Ready for posting":
            raise AlphaError("Verify this exact fixture account and its capability first.")
        if v.get("rejected"):
            raise AlphaError("You marked this draft as one you don't want to use. Edit it or draft again before scheduling it.")
        if v["needsReview"] or v["blockedByRetraction"] or v.get("policyBlocked") or v["unknowns"] or v.get("briefRevision") != s["brief"]["revision"] or any(not self._source(s, i)["active"] for i in v["sourceIds"]):
            raise AlphaError("Resolve draft review, retracted sources and unknown facts before scheduling.")
        policy_blockers = source_policy.publication_issues(s, v["sourceIds"])
        if policy_blockers:
            raise AlphaError(policy_blockers[0]["message"], 409)
        if v["voiceRevision"] != s["speaker"]["activeRevision"] or v["platform"] != c["platform"] or v["language"] != c["language"]:
            raise AlphaError("The variant, language and current speaker must match this destination.")
        text = v["text"]
        if not text.strip() or len(text) > LIMITS[c["platform"]]["characters"]:
            raise AlphaError("The content exceeds this destination's versioned text limit.")
        acknowledged = p.get("acknowledgedWarnings", [])
        if sorted(acknowledged) != sorted(v["warnings"]):
            raise AlphaError("Acknowledge every displayed draft warning.")
        media = []
        if p.get("assetId"):
            a = find(data["assets"], p["assetId"])
            if a["deleted"] or a["processing"] != "decoded" or not p.get("rightsConfirmed") or not clean(p.get("alt", ""), 1000):
                raise AlphaError("Decoded media, alt text and rights confirmation are required.")
            if c["platform"] == "Instagram" and not 0.8 <= a["width"]/a["height"] <= 1.91:
                raise AlphaError("Instagram images must have an aspect ratio between 4:5 and 1.91:1.")
            media = [{key: a[key] for key in ("id", "hash", "sourceHash", "mime", "bytes", "width", "height", "duration")} | {"alt": clean(p["alt"], 1000), "rightsConfirmed": True}]
        if c["platform"] == "Instagram" and not media:
            raise AlphaError("Instagram requires a decoded image. Upload one and confirm its rights.")
        timing = resolve_time(p.get("localTime"), p.get("timeZone"), p.get("fold"), self.clock())
        evidence = c.get("evidenceSource", "synthetic")
        selection = ensure_content_state(s)["selection"]
        manifest = {"schema": "postriff.approval.v1", "workspaceId": s["workspace"]["id"], "actor": actor, "brandHubId": s["brandHub"]["id"], "brandDigest": digest(s["brandHub"]), "speakerId": s["speaker"]["id"], "voiceRevision": s["speaker"]["activeRevision"], "styleRevision": learning.revision(s), "channelId": c["id"], "account": c["account"], "platform": c["platform"], "operation": LIMITS[c["platform"]]["operation"], "variantId": v["id"], "contentRevision": v["revision"], "contentType": {"id": v.get("contentTypeId", selection["contentTypeId"]), "version": v.get("contentTypeVersion", selection["contentTypeVersion"]), "formatId": v.get("formatId", selection["formatId"]), "preflight": preflight, "skillRouteIds": v.get("contentSkillRouteIds", [])}, "payload": {"text": text, "language": v["language"]}, "payloadDigest": digest({"text": text, "language": v["language"], "media": media}), "media": media, "timing": timing, "capability": {"version": c["capabilityVersion"], "scopes": c["scopes"], "verifiedAt": c["verifiedAt"], "source": evidence}, "limitsVersion": LIMITS[c["platform"]]["version"], "acknowledgedWarnings": acknowledged, "expiresAt": timing["timestamp"]+3600, "execution": "synthetic" if evidence == "synthetic" else "hosted-live"}
        manifest["briefRevision"] = s["brief"]["revision"]
        manifest["sourceDigest"] = self.source_digest(s, v)
        manifest["providerAccountId"] = c.get("providerAccountId", c["account"])
        root_key = digest(manifest)
        # A fresh review may retry a definitively ended job. Keep old manifests immutable and
        # key all duplicate reviews for this retry to the same preceding job, never a random nonce.
        ended = [j for j in data["jobs"] if j["state"] in ("failed", "canceled")
                 and j["manifest"].get("retryRoot", j["manifest"]["idempotencyKey"]) == root_key]
        if ended:
            manifest.update({"retryRoot": root_key, "retryOf": ended[-1]["id"]})
        manifest["idempotencyKey"] = digest(manifest)
        return manifest

    def source_digest(self, s, variant):
        # Policy and use-approval are part of the digest: changing either invalidates approvals.
        return digest([{"id": source["id"], "active": source["active"], "policy": source.get("sourcePolicy"), "useApproved": source_policy.use_approved(source),
                        "facts": [fact for fact in source["facts"] if fact["approved"]]}
                       for source in (self._source(s, i) for i in variant["sourceIds"])])

    def current(self, s, m):
        try:
            v, c = self._variant(s, m["variantId"]), find(s["phase2"]["channels"], m["channelId"])
            if (m.get("workspaceId") != s["workspace"]["id"]
                    or m.get("brandHubId") != s["brandHub"]["id"]
                    or m.get("briefRevision") != s["brief"]["revision"]
                    or v.get("briefRevision") != s["brief"]["revision"]
                    or m.get("sourceDigest") != self.source_digest(s, v)
                    or m.get("providerAccountId") != c.get("providerAccountId", c["account"])
                    or m["capability"]["scopes"] != c["scopes"]):
                return False
            media_ok = all(not find(s["phase2"]["assets"], a["id"])["deleted"] and find(s["phase2"]["assets"], a["id"])["hash"] == a["hash"] for a in m["media"])
            content_type_ok = m.get("contentType") == {"id": v.get("contentTypeId", "unclassified"), "version": v.get("contentTypeVersion", "legacy"), "formatId": v.get("formatId"), "preflight": content_preflight(s, v["sourceIds"]), "skillRouteIds": v.get("contentSkillRouteIds", [])}
            # styleRevision is recorded in the manifest but never compared: a learned preference shapes the
            # next draft and leaves approved text alone (design decision A1).
            return bool(media_ok and content_type_ok and not v["needsReview"] and not v.get("rejected") and not v["blockedByRetraction"] and not v.get("policyBlocked") and not source_policy.publication_issues(s, v["sourceIds"]) and not v["unknowns"] and v["revision"] == m["contentRevision"] and v["text"] == m["payload"]["text"] and v["language"] == m["payload"]["language"] and c["language"] == v["language"] and c["platform"] == v["platform"] and c["account"] == m["account"] and s["speaker"]["id"] == m["speakerId"] and s["speaker"]["activeRevision"] == m["voiceRevision"] and digest(s["brandHub"]) == m["brandDigest"] and c["capabilityVersion"] == m["capability"]["version"] and m["operation"] == LIMITS[c["platform"]]["operation"] and m["limitsVersion"] == LIMITS[c["platform"]]["version"] and all(self._source(s, i)["active"] for i in v["sourceIds"]))
        except (AlphaError, KeyError, TypeError, ValueError):
            return False

    def event(self, job, state, message):
        job["state"] = state
        job["events"].append({"at": self.clock(), "state": state, "message": message, "execution": job.get("manifest", {}).get("execution", "synthetic")})

    def invalidate(self, s):
        data = s["phase2"]
        for review in data["reviews"]:
            if review["status"] == "needs_review" and not self.current(s, review["manifest"]):
                review["status"] = "stale"
        for j in data["jobs"]:
            if j["state"] not in ("scheduled", "approved", "claimed"):
                continue
            c = find(data["channels"], j["manifest"]["channelId"])
            if not self.current(s, j["manifest"]) or self.channel_state(c) != "Ready for posting" or (not getattr(self, "hosted_entitlements", False) and data["trial"]["expiresAt"] <= self.clock()) or j["manifest"]["expiresAt"] < self.clock():
                self.event(j, "held", "Approval, capability or entitlement changed. Review timing and approve a new job; reconnection does not release this one.")

    def export(self, wid, token):
        snapshot = self.get(wid, token)
        data = snapshot["state"].get("phase2")
        if not data:
            return super().export(wid, token)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as pack:
            pack.writestr("phase2/workspace.json", json.dumps(snapshot["state"], ensure_ascii=False, indent=2))
            pack.writestr("learning/events.jsonl", "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in self.learning_events(wid, token, limit=20000)))
            pack.writestr("README.txt", "Private local account export. Contains your drafts, including unapproved work, sources, approved voice, artwork and synthetic receipts. Export does not approve or publish any content.\n")
        return out.getvalue()

    def worker_step(self, owner="local-worker", crash=None):
        """Claim and mark submitting before calling adapter outside the DB transaction.

        A crashed submit is never retried blind. Leases expire into reconciliation.
        """
        selected = None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT * FROM workspaces").fetchall():
                s = json.loads(row["state"])
                if "phase2" not in s:
                    continue
                self.invalidate(s)
                for j in s["phase2"]["jobs"]:
                    if j["leaseUntil"] > self.clock() or j["nextAt"] > self.clock() or j["state"] in (*TERMINAL, "held"):
                        continue
                    if j.get("cancelRequested") and j["state"] not in IN_FLIGHT:
                        self.event(j, "canceled", "Canceled before provider submission")
                        continue
                    if j["state"] == "submitting":
                        self.event(j, "uncertain", "Worker lease expired after submission started; reconcile before retry")
                    reconciliation = j["state"] in IN_FLIGHT
                    if not reconciliation:
                        member = db.execute("SELECT role FROM alpha_memberships WHERE workspace_id=? AND user_id=? AND status='active'", (row["id"], j["approvedBy"])).fetchone()
                        if (not member or member['role'] not in ('owner', 'editor')
                                or j['approvalDigest'] != digest(j['manifest'])
                                or j['approvedBy'] != j['manifest']['actor']):
                            self.event(j, "held", "Approval authority changed; a new review is required")
                            continue
                    if not reconciliation and len(j["attempts"]) >= 3:
                        self.event(j, "failed", "Bounded retry limit reached")
                        continue
                    j["leaseOwner"], j["leaseUntil"], j["leaseId"] = owner, self.clock()+30, uid()
                    c = find(s["phase2"]["channels"], j["manifest"]["channelId"])
                    if reconciliation:
                        j["checks"] += 1
                    else:
                        self.event(j, "claimed", "Local worker acquired lease")
                        if crash != "before_submit":
                            j["attempts"].append({"number": len(j["attempts"])+1, "startedAt": self.clock(), "idempotencyKey": j["manifest"]["idempotencyKey"]})
                            self.event(j, "submitting", "Submitting to the deterministic local adapter")
                    selected = (row["id"], copy.deepcopy(j), c["scenario"], reconciliation)
                    break
                if json.dumps(s) != row["state"]:
                    db.execute("UPDATE workspaces SET state=?,revision=revision+1 WHERE id=?", (json.dumps(s), row["id"]))
                if selected:
                    break
        if not selected or crash == "before_submit":
            return bool(selected)
        wid, job, scenario, reconciliation = selected
        try:
            result = self.social.reconcile(job["manifest"], scenario, job["checks"]) if reconciliation else self.social.submit(job["manifest"], scenario)
        except Exception:
            # Provider errors may contain tokens or request bodies. Preserve only a safe state.
            result = unknown()
        if crash in ("after_submit", "after_acceptance"):
            return True
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
            if not row:
                return True
            s = json.loads(row["state"])
            j = find(s["phase2"]["jobs"], job["id"])
            if j["leaseOwner"] != owner or j.get("leaseId") != job.get("leaseId"):
                return True
            result = normalize_result(result, j, reconciliation)
            self.event(j, result["state"], result["confirmed"])
            j["providerReference"] = result.get("reference", j.get("providerReference"))
            j["providerConfirmed"] = result["confirmed"]
            j["verification"] = {"method": result.get("verification"), "at": self.clock()} if result["state"] == "verified" else None
            if result["state"] == "verified":
                self._record_events(db, wid, [signals.published_event(j, None, self.clock())])
            if j["attempts"] and not reconciliation:
                j["attempts"][-1]["endedAt"] = self.clock()
            j["leaseOwner"], j["leaseUntil"] = None, 0
            j["nextAt"] = self.clock()+(60 if result["state"] == "scheduled" else 5)
            if j["checks"] >= 5 and j["state"] in IN_FLIGHT:
                j["nextAt"] = self.clock()+86400
                j["nextAction"] = "Manual provider review required; do not resubmit"
            else:
                j["nextAction"] = "Review permission and timing again" if j["state"] == "held" else "Review the failed attempt, correct the cause and approve a new schedule" if j["state"] == "failed" else "Inspect receipt" if j["state"] in TERMINAL else "Await local worker reconciliation"
            db.execute("UPDATE workspaces SET state=?,revision=revision+1 WHERE id=?", (json.dumps(s), wid))
        return True

    def heartbeat(self, wid, job_id, owner):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
            if not row:
                return False
            s = json.loads(row["state"])
            j = find(s["phase2"]["jobs"], job_id)
            if j["leaseOwner"] != owner or j["leaseUntil"] <= self.clock():
                return False
            j["leaseUntil"] = self.clock()+30
            db.execute("UPDATE workspaces SET state=?,revision=revision+1 WHERE id=?", (json.dumps(s), wid))
            return True
