"""Expiring, state/PKCE-bound local identity fixtures. No real OAuth/OTP."""
import hashlib
import json
import secrets
import time
from postriff_alpha.auth import LocalAuthGateway
from postriff_alpha.domain import AlphaError, initial_state, uid
from .contracts import PLANS


def initial_phase2_state(workspace_id, user_id, display_name, plan, clock, *, execution="local-fixtures", identities=None):
    """Build the shared Phase 2 state without creating a backend-specific session."""
    if plan not in PLANS:
        raise AlphaError("This plan is not available.")
    state = initial_state(workspace_id)
    state["account"] = {
        "userId": user_id,
        "displayName": display_name,
        "gateway": "phase2-local-fixture" if execution == "local-fixtures" else "supabase-auth",
        "status": "simulated_verified" if execution == "local-fixtures" else "verified",
        "productionAccount": execution != "local-fixtures",
        "methodsPreviewed": list(identities or []),
    }
    state["membership"] = {"userId": user_id, "workspaceId": workspace_id, "role": "owner", "status": "active"}
    state["phase2"] = {
        "execution": execution,
        "trial": {
            "plan": plan,
            "startedAt": clock,
            "expiresAt": clock + 14 * 86400,
            "writingGrant": 10,
            "writingUsed": 0,
            "artworkSets": 1,
            "artworkUsed": 0,
            "autoConvert": False,
        },
        "channels": [],
        "assets": [],
        "art": {"candidates": [], "selected": None, "consents": [], "status": "local_fallback"},
        "reviews": [],
        "jobs": [],
        "devices": [],
        "identities": list(identities or []),
    }
    return state


class Phase2Auth(LocalAuthGateway):
    def __init__(self, store):
        super().__init__(store)
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS p2_challenges(id TEXT PRIMARY KEY, principal TEXT NOT NULL, provider TEXT NOT NULL, verifier_hash TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0, response TEXT);
            CREATE TABLE IF NOT EXISTS p2_sessions(device_id TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS p2_identities(principal TEXT NOT NULL, provider TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY(principal,provider));
            CREATE TABLE IF NOT EXISTS p2_trial_grants(user_id TEXT PRIMARY KEY, granted_at REAL NOT NULL);
            """)

    def challenge(self, request):
        if request.get("provider") not in ("google", "email"):
            raise AlphaError("This provider needs configuration. Use the Google or email fixture.")
        principal, verifier = request.get("principalKey"), request.get("verifier")
        if not isinstance(principal, str) or not 16 <= len(principal) <= 100 or not isinstance(verifier, str) or not 32 <= len(verifier) <= 128:
            raise AlphaError("A stable fixture identity and PKCE verifier are required.")
        nonce = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute("INSERT INTO p2_challenges(id,principal,provider,verifier_hash,expires) VALUES(?,?,?,?,?)", (nonce, hashlib.sha256(principal.encode()).hexdigest(), request["provider"], hashlib.sha256(verifier.encode()).hexdigest(), self.store.clock()+300))
        return {"state": nonce, "expiresIn": 300, "execution": "synthetic", "delivery": "none"}

    def sign_in(self, request):
        identity = self.adapter.verify(request)
        selected_plan = request.get("plan", "studio")
        if selected_plan not in PLANS:
            raise AlphaError("This plan is not available.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            challenge = db.execute("SELECT * FROM p2_challenges WHERE id=?", (request.get("state"),)).fetchone()
            if not challenge or challenge["principal"] != identity["principalHash"] or challenge["provider"] != identity["provider"] or challenge["verifier_hash"] != hashlib.sha256(str(request.get("verifier", "")).encode()).hexdigest():
                raise AlphaError("Callback state, identity or PKCE verification failed.", 403)
            if challenge["expires"] < self.store.clock():
                raise AlphaError("This callback expired. Start sign-in again.", 401)
            if challenge["used"]:
                saved = json.loads(challenge["response"])
                self.store._row(db, saved["workspaceId"], saved["token"])
                current = db.execute("SELECT revision,state FROM workspaces WHERE id=?", (saved["workspaceId"],)).fetchone()
                return {**saved, "state": self.store._present(json.loads(current["state"]), current["revision"])["state"], "revision": current["revision"], "auth": {"retryReused": True, "productionAccount": False}}
            found = db.execute("SELECT user_id FROM p2_identities WHERE principal=? AND provider=?", (identity["principalHash"], identity["provider"])).fetchone()
            if found:
                user_id = found["user_id"]
                member = db.execute("SELECT workspace_id FROM alpha_memberships WHERE user_id=? AND status='active'", (user_id,)).fetchone()
                if not member:
                    raise AlphaError("This account was deleted. Recovery cannot recreate its trial.", 403)
                wid = member["workspace_id"]
                row = db.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
                state, revision = json.loads(row["state"]), row["revision"]
            else:
                user_id, wid, revision = uid(), uid(), 0
                # The fixture principal includes provider; matching email strings never merge workspaces.
                db.execute("INSERT INTO alpha_users VALUES(?,?,?,?)", (user_id, identity["principalHash"]+":"+identity["provider"], identity["displayName"], "simulated_verified"))
                db.execute("INSERT INTO p2_identities VALUES(?,?,?)", (identity["principalHash"], identity["provider"], user_id))
                db.execute("INSERT INTO alpha_memberships VALUES(?,?,?,?)", (user_id, wid, "owner", "active"))
                db.execute("INSERT INTO p2_trial_grants VALUES(?,?)", (user_id, self.store.clock()))
                state = initial_phase2_state(wid, user_id, identity["displayName"], selected_plan, self.store.clock(), identities=[identity["provider"]])
                db.execute("INSERT INTO workspaces VALUES(?,?,?,?)", (wid, "0"*64, 0, "{}"))
            device, token = uid(), secrets.token_urlsafe(32)
            db.execute("INSERT INTO alpha_devices VALUES(?,?,?,?,?)", (device, user_id, wid, hashlib.sha256(token.encode()).hexdigest(), "active"))
            db.execute("INSERT INTO p2_sessions VALUES(?,?)", (device, self.store.clock()+86400))
            state["device"] = {"id": device, "workspaceId": wid, "status": "synthetic-session", "runtimeAccess": "not_granted"}
            state["phase2"]["devices"].append({"id": device, "createdAt": self.store.clock(), "expiresAt": self.store.clock()+86400, "status": "active"})
            db.execute("UPDATE workspaces SET revision=?,state=? WHERE id=?", (revision+1, json.dumps(state), wid))
            receipt = {"workspaceId": wid, "token": token}
            # The response contains a credential and stays only inside the private auth database.
            db.execute("UPDATE p2_challenges SET used=1,response=? WHERE id=?", (json.dumps(receipt), challenge["id"]))
            return {**receipt, "revision": revision+1, "state": self.store._present(state, revision+1)["state"], "auth": {"retryReused": False, "productionAccount": False}}

    def link(self, db, state, payload):
        identity = self.adapter.verify(payload)
        challenge = db.execute("SELECT * FROM p2_challenges WHERE id=?", (payload.get("state"),)).fetchone()
        if not challenge or challenge["used"] or challenge["expires"] < self.store.clock() or challenge["principal"] != identity["principalHash"] or challenge["provider"] != identity["provider"] or challenge["verifier_hash"] != hashlib.sha256(str(payload.get("verifier", "")).encode()).hexdigest():
            raise AlphaError("Start a fresh verified linking preview.", 403)
        other = db.execute("SELECT * FROM p2_identities WHERE principal=? AND provider=?", (identity["principalHash"], identity["provider"])).fetchone()
        if other and other["user_id"] != state["account"]["userId"]:
            raise AlphaError("This identity belongs to another account. Workspaces cannot be merged.", 409)
        db.execute("INSERT OR IGNORE INTO p2_identities VALUES(?,?,?)", (identity["principalHash"], identity["provider"], state["account"]["userId"]))
        db.execute("UPDATE p2_challenges SET used=1,expires=0 WHERE id=?", (challenge["id"],))
        if identity["provider"] not in state["phase2"]["identities"]:
            state["phase2"]["identities"].append(identity["provider"])
