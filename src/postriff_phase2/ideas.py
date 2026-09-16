"""Hosted Ideas conversation service: durable conversations, runs, safe events, apply.

Every call runs inside the workspace membership transaction. Runs execute the
AgentRuntime against a policy projection only; artifacts are candidates until an explicit
`apply`, which re-checks the projection so stale candidates are never applied silently.
"""
import copy
import json
from postriff_alpha.domain import AlphaError, clean, uid
from .contracts import digest
from .permissions import require
from .source_policy import project_context, stamp
from .agent_runtime import SAFE_EVENTS, FixtureAgentRuntime

MAX_TEXT = 6000
MAX_EVENTS = 2000


class IdeasService:
    def __init__(self, repository, commands, runtime=None, clock=None, ledger=None):
        from .billing import Ledger
        self.repository = repository
        self.commands = commands
        self.runtime = runtime or FixtureAgentRuntime()
        self.clock = clock or __import__("time").time
        self.ledger = ledger or Ledger()

    # --- helpers -------------------------------------------------------------------
    @staticmethod
    def _state(row):
        return json.loads(row[1]) if isinstance(row[1], str) else row[1]

    @staticmethod
    def _member(row):
        from .permissions import Membership
        return Membership.from_row(*row[2:7])

    def _conversation(self, cur, workspace_id, conversation_id):
        cur.execute("SELECT id::text,title,created_by::text,extract(epoch from created_at),extract(epoch from updated_at),archived_at IS NOT NULL FROM public.pr_conversations WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (conversation_id, workspace_id))
        row = cur.fetchone()
        if not row:
            raise AlphaError("Conversation unavailable.", 404)
        return {"conversationId": row[0], "title": row[1], "createdBy": row[2], "createdAt": float(row[3]), "updatedAt": float(row[4]), "archived": bool(row[5])}

    def _append_message(self, cur, workspace_id, conversation_id, role, body, run_id=None):
        cur.execute("SELECT coalesce(max(seq),0)+1 FROM public.pr_messages WHERE conversation_id::text=%s", (conversation_id,))
        seq = cur.fetchone()[0]
        cur.execute("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body,run_id) VALUES(%s,%s,%s,%s,%s::jsonb,%s) RETURNING id::text", (conversation_id, workspace_id, seq, role, json.dumps(body), run_id))
        message_id = cur.fetchone()[0]
        cur.execute("UPDATE public.pr_conversations SET updated_at=now() WHERE id::text=%s", (conversation_id,))
        return {"messageId": message_id, "seq": seq, "role": role, "body": body}

    # --- conversations -------------------------------------------------------------
    def conversations(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("SELECT id::text,title,created_by::text,extract(epoch from created_at),extract(epoch from updated_at),archived_at IS NOT NULL FROM public.pr_conversations WHERE workspace_id=%s ORDER BY updated_at DESC LIMIT 100", (workspace_id,))
            return {"conversations": [{"conversationId": r[0], "title": r[1], "createdBy": r[2], "createdAt": float(r[3]), "updatedAt": float(r[4]), "archived": bool(r[5])} for r in cur.fetchall()]}

    def create_conversation(self, workspace_id, token, title=""):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text", (workspace_id, principal, clean(title or "New idea", 200)))
            conversation_id = cur.fetchone()[0]
            self.runtime.start_conversation(workspace_id, principal)
            return {"conversationId": conversation_id, "title": clean(title or "New idea", 200)}

    def messages(self, workspace_id, token, conversation_id, cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise AlphaError("Invalid message cursor.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            conversation = self._conversation(cur, workspace_id, conversation_id)
            cur.execute("SELECT id::text,seq,role,body,run_id::text,extract(epoch from created_at) FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s AND seq>%s ORDER BY seq LIMIT 500", (conversation_id, workspace_id, cursor))
            return {**conversation, "messages": [{"messageId": r[0], "seq": r[1], "role": r[2], "body": r[3], "runId": r[4], "at": float(r[5])} for r in cur.fetchall()]}

    def attach(self, workspace_id, token, conversation_id, payload):
        """Attach a permitted source (text/markdown ≤ 20 KB), an existing private asset, or a link."""
        kind = payload.get("kind")
        if kind not in ("source", "asset", "link"):
            raise AlphaError("Attach a text/markdown source, an uploaded image, or a link.")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            if kind == "asset":
                asset = next((a for a in state.get("phase2", {}).get("assets", []) if a["id"] == payload.get("assetId") and not a.get("deleted")), None)
                if not asset:
                    raise AlphaError("Upload the image to this workspace first.", 404)
                ref = {"assetId": asset["id"], "hash": asset["hash"], "mime": asset["mime"]}
            else:
                ref = {"sourceId": payload.get("sourceId")} if kind == "source" else {"url": clean(payload.get("url", ""), 2000)}
                if kind == "source" and not any(s["id"] == ref["sourceId"] and s.get("active") for s in state.get("sources", [])):
                    raise AlphaError("Add the source to this workspace first.", 404)
            cur.execute("INSERT INTO public.pr_attachments(conversation_id,workspace_id,kind,ref,created_by) VALUES(%s,%s,%s,%s::jsonb,%s) RETURNING id::text", (conversation_id, workspace_id, kind, json.dumps(ref), principal))
            return {"attachmentId": cur.fetchone()[0], "kind": kind, "ref": ref}

    # --- runs ----------------------------------------------------------------------
    def turn(self, workspace_id, token, conversation_id, payload):
        text = clean(payload.get("text", ""), MAX_TEXT)
        reasoning = payload.get("reasoning", "quick")
        key = clean(payload.get("idempotencyKey", ""), 100) or uid()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            self._conversation(cur, workspace_id, conversation_id)
            state = self._state(row)
            stamp(state)
            source_ids = payload.get("sourceIds") if isinstance(payload.get("sourceIds"), list) else [s["id"] for s in state.get("sources", []) if s.get("active")][:20]
            context = project_context(state, "draft", "local", source_ids)
            cur.execute("SELECT id::text,status FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
            existing = cur.fetchone()
            if existing:
                return self._events_for(cur, workspace_id, existing[0], 0)
            if text:
                self._append_message(cur, workspace_id, conversation_id, "user", {"text": text, "sourceIds": source_ids})
            idea = text or state.get("brief", {}).get("idea", "")
            request = {"context": context, "idea": idea, "tone": self._tone(state), "destinations": payload.get("destinations"), "reasoning": reasoning}
            cur.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key) VALUES(%s,%s,%s,'running',%s,%s,%s,%s,%s) RETURNING id::text", (conversation_id, workspace_id, principal, self.runtime.model, reasoning if reasoning in ("quick", "standard", "deep") else "quick", digest(context), context["policyEpoch"], key))
            run_id = cur.fetchone()[0]
            # Credits gate before execution (§17): the fixture costs $0 and consumes no batch; a paid route would.
            paid = self.runtime.model != FixtureAgentRuntime.model
            reservation = self.ledger.reserve(cur, workspace_id, principal, "text_model", 0 if not paid else 500_000, f"run:{run_id}", charge_batch=paid, provider="fixture" if not paid else self.runtime.model, model=self.runtime.model, run_id=run_id)
            counter = {"seq": 0}

            def emit(event):
                if event["type"] not in SAFE_EVENTS:
                    raise AlphaError("Unsupported client event.", 500)
                counter["seq"] += 1
                if counter["seq"] > MAX_EVENTS:
                    raise AlphaError("Event limit reached.", 413)
                body = {k: v for k, v in event.items() if k != "type"}
                cur.execute("INSERT INTO public.pr_agent_events(run_id,workspace_id,seq,kind,body) VALUES(%s,%s,%s,%s,%s::jsonb)", (run_id, workspace_id, counter["seq"], event["type"], json.dumps(body, ensure_ascii=False)))

            try:
                result = self.runtime.start_turn(request, emit)
            except AlphaError as error:
                emit({"type": "run.failed", "message": str(error)})
                cur.execute("UPDATE public.pr_agent_runs SET status='failed',updated_at=now() WHERE id::text=%s", (run_id,))
                self.ledger.settle(cur, workspace_id, reservation["reservationId"], "failed", 0)
                raise
            self.ledger.settle(cur, workspace_id, reservation["reservationId"], "completed", int(result["usage"].get("costUsd", 0) * 1_000_000))
            artifact_hash = digest(result["artifact"])
            cur.execute("UPDATE public.pr_agent_runs SET status='completed',artifact=%s::jsonb,artifact_hash=%s,usage=%s::jsonb,updated_at=now() WHERE id::text=%s", (json.dumps(result["artifact"], ensure_ascii=False), artifact_hash, json.dumps(result["usage"]), run_id))
            summary = {"text": f"Drafted {len(result['artifact']['variants'])} candidate variants from {len(context['sources'])} approved sources.", "runId": run_id, "artifactHash": artifact_hash, "excluded": context["excluded"], "candidateOnly": context["candidateOnly"]}
            self._append_message(cur, workspace_id, conversation_id, "assistant", summary, run_id)
            return self._events_for(cur, workspace_id, run_id, 0)

    @staticmethod
    def _tone(state):
        active = state.get("speaker", {}).get("activeRevision")
        revision = next((r for r in state.get("speaker", {}).get("revisions", []) if r.get("revision") == active), None)
        return (revision or {}).get("profile", {}).get("tone", "warm")

    def _events_for(self, cur, workspace_id, run_id, cursor):
        cur.execute("SELECT status,artifact_hash,usage,conversation_id::text,model,reasoning,artifact FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
        run = cur.fetchone()
        if not run:
            raise AlphaError("Run unavailable.", 404)
        cur.execute("SELECT seq,kind,body,extract(epoch from at) FROM public.pr_agent_events WHERE run_id::text=%s AND workspace_id=%s AND seq>%s ORDER BY seq LIMIT 500", (run_id, workspace_id, cursor))
        events = [{"id": f"{run_id}:{r[0]}", "seq": r[0], "type": r[1], **r[2], "at": float(r[3])} for r in cur.fetchall()]
        # The candidate artifact is the customer's own draft text; it is safe to show and required for preview.
        return {"runId": run_id, "conversationId": run[3], "status": run[0], "artifactHash": run[1], "usage": run[2], "model": run[4], "reasoning": run[5], "artifact": run[6] if run[0] in ("completed", "applied") else None, "events": events, "cursor": events[-1]["seq"] if events else cursor}

    def events(self, workspace_id, token, run_id, cursor=0):
        if type(cursor) is not int or cursor < 0:
            raise AlphaError("Invalid event cursor.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            return self._events_for(cur, workspace_id, run_id, cursor)

    def cancel(self, workspace_id, token, run_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "edit")
            cur.execute("SELECT status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s FOR UPDATE", (run_id, workspace_id))
            run = cur.fetchone()
            if not run:
                raise AlphaError("Run unavailable.", 404)
            if run[0] == "running":
                cur.execute("SELECT coalesce(max(seq),0)+1 FROM public.pr_agent_events WHERE run_id::text=%s", (run_id,))
                seq = cur.fetchone()[0]
                cur.execute("INSERT INTO public.pr_agent_events(run_id,workspace_id,seq,kind,body) VALUES(%s,%s,%s,'run.cancelled',%s::jsonb)", (run_id, workspace_id, seq, json.dumps({"message": "Cancelled. Partial text retained; no automatic retry."})))
                cur.execute("UPDATE public.pr_agent_runs SET status='cancelled',updated_at=now() WHERE id::text=%s", (run_id,))
                return {"runId": run_id, "status": "cancelled"}
            return {"runId": run_id, "status": run[0], "note": "Already finished; nothing to cancel."}

    def apply(self, workspace_id, token, revision, run_id, artifact_hash):
        """Turn a completed candidate into reviewable workspace variants. Never publishes."""
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "edit")
            cur.execute("SELECT status,artifact,artifact_hash,policy_epoch,context_digest FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
            run = cur.fetchone()
        if not run:
            raise AlphaError("Run unavailable.", 404)
        status, artifact, stored_hash, epoch, context_digest = run
        if status == "applied":
            return {"runId": run_id, "status": "applied", "note": "Already applied."}
        if status != "completed" or not artifact:
            raise AlphaError("No completed candidate to review.", 409)
        if artifact_hash != stored_hash:
            raise AlphaError("Review the exact candidate.", 409)

        def command(state, actor):
            stamp(state)
            source_ids = sorted({sid for v in artifact["variants"] for sid in v["sourceIds"]})
            current = project_context(state, "draft", "local", source_ids)
            if current["policyEpoch"] != epoch or any(s["hash"] != next((c["hash"] for c in current["sources"] if c["id"] == s["id"]), None) for s in current["sources"]) or current["excluded"]:
                raise AlphaError("Sources or their policies changed. Preserve the candidate and draft again from current context.", 409)
            for candidate in artifact["variants"]:
                old = next((v for v in state["variants"] if v["platform"] == candidate["platform"] and v["language"] == candidate["language"]), None)
                values = {"text": candidate["text"], "sourceIds": candidate["sourceIds"], "unknowns": candidate["unknowns"], "warnings": candidate.get("warnings", []) + (["Rewritten-source candidate: approve public use before publishing."] if candidate.get("candidateOnly") else []), "openings": [], "voiceRevision": state["speaker"].get("activeRevision"), "briefRevision": state["brief"]["revision"], "runId": run_id}
                if old:
                    old["proposedUpdate"] = {**values, "baseVariantRevision": old["revision"]}
                    old["needsReview"] = True
                else:
                    state["variants"].append({**values, "id": uid(), "revision": 1, "platform": candidate["platform"], "language": candidate["language"], "speakerId": state["speaker"].get("id"), "customized": False, "needsReview": True, "blockedByRetraction": False, "selectedOpening": 0, "localPreferences": {}, "revisions": [{"revision": 1, "text": candidate["text"], "origin": "ideas-candidate"}], "provenance": {"runId": run_id, "contextDigest": context_digest, "policyEpoch": epoch, "model": self.runtime.model}})
            return state

        saved = self.repository.command(workspace_id, token, revision, command)
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("UPDATE public.pr_agent_runs SET status='applied',updated_at=now() WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
        return {"runId": run_id, "status": "applied", "revision": saved["revision"], "variants": len(artifact["variants"])}

    # --- source-first activation --------------------------------------------------
    def quick_start(self, workspace_id, token, revision, payload):
        """Thought/text/URL → one useful preview without connecting a channel."""
        text = clean(payload.get("text", ""), 20000)
        url = clean(payload.get("url", ""), 2000)
        if not text and not url:
            raise AlphaError("Paste a thought or text, or add a link, to start.")
        if payload.get("confirmUse") is not True:
            raise AlphaError("Confirm that you want PostRiff to use this content for a draft.")
        own = payload.get("ownContent") is True
        destinations = payload.get("destinations") or [{"platform": "LinkedIn", "language": payload.get("language", "English")}]

        def command(state, actor):
            kind = "idea" if (own and text and len(text) <= 500 and "\n" not in text) else ("text" if text else "link")
            self.commands(state, actor, "source", {"kind": kind, "text": text or url, "title": clean(payload.get("title", "Pasted source" if text else "Link"), 200)})
            source = state["sources"][-1]
            stamp(state)
            if own:
                source["sourcePolicy"] = "public_quote"
                self.commands(state, actor, "approve_source", {"sourceId": source["id"], "factIds": [f["id"] for f in source["facts"]]})
            if payload.get("audience"):
                state["brandHub"]["audience"] = clean(payload["audience"], 1500)
            if payload.get("goal"):
                state["brandHub"]["purpose"] = clean(payload["goal"], 1500)
            return state

        saved = self.repository.command(workspace_id, token, revision, command)
        source = saved["state"]["sources"][-1]
        conversation = self.create_conversation(workspace_id, token, clean(text[:60] or url, 60))
        run = self.turn(workspace_id, token, conversation["conversationId"], {"text": "", "sourceIds": [source["id"]], "destinations": destinations, "reasoning": "quick"})
        return {"conversationId": conversation["conversationId"], "sourceId": source["id"], "sourcePolicy": source.get("sourcePolicy"), "revision": saved["revision"], **run}
