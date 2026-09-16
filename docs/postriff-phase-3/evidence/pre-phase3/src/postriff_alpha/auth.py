"""Provider-neutral account boundary with an explicit local simulation adapter."""
import hashlib
import hmac
import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Protocol

METHODS = ["google", "apple", "microsoft", "email", "phone"]


class AuthGateway(Protocol):
    def verify(self, request: dict) -> dict: ...


class LocalVerifiedUserAdapter:
    """A preview identity, not OAuth, a real OTP verifier, or production account auth."""
    id = "local-verified-user-fixture"

    def verify(self, request):
        provider = request.get("provider")
        if provider not in METHODS:
            raise ValueError("Choose a supported sign-in preview.")
        if request.get("cancelled"):
            raise ValueError("Sign-in preview cancelled. No account, workspace or trial was created.")
        if request.get("proof") != ("123456" if provider in ("email", "phone") else "postriff-fixture-verified"):
            raise ValueError("The preview verification did not pass. Use the displayed fixture code; nothing was sent.")
        principal, request_id = request.get("principalKey"), request.get("requestId")
        if not isinstance(principal, str) or not 16 <= len(principal) <= 100 or not isinstance(request_id, str) or not 16 <= len(request_id) <= 100:
            raise ValueError("A stable local preview identity and retry ID are required.")
        display = request.get("displayName", "Founder preview")
        if not isinstance(display, str) or len(display) > 60:
            raise ValueError("Use a short preview display name.")
        return {"principalHash": hashlib.sha256(principal.encode()).hexdigest(), "requestId": request_id, "provider": provider, "displayName": display, "status": "simulated_verified", "externalVerified": False}


class LocalAuthGateway:
    def __init__(self, store):
        self.store = store
        self.adapter = LocalVerifiedUserAdapter()
        keyfile = Path(str(store.path) + ".auth-key")
        try:
            fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(secrets.token_bytes(32))
        except FileExistsError:
            pass
        self.key = keyfile.read_bytes()
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS alpha_users (id TEXT PRIMARY KEY, principal_hash TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, auth_state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alpha_memberships (user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(user_id, workspace_id));
            CREATE TABLE IF NOT EXISTS alpha_devices (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, credential_hash TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alpha_auth_requests (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, device_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alpha_auth_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, action TEXT NOT NULL);
            """)

    def sign_in(self, request):
        identity = self.adapter.verify(request)
        from .domain import initial_state
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT * FROM alpha_users WHERE principal_hash=?", (identity["principalHash"],)).fetchone()
            replay = db.execute("SELECT * FROM alpha_auth_requests WHERE id=?", (identity["requestId"],)).fetchone()
            if replay and (not user or replay["user_id"] != user["id"]):
                raise ValueError("That retry ID belongs to a different preview identity.")
            if not user:
                user_id, workspace_id = uuid.uuid4().hex, uuid.uuid4().hex
                db.execute("INSERT INTO alpha_users VALUES (?,?,?,?)", (user_id, identity["principalHash"], identity["displayName"], "simulated_verified"))
                db.execute("INSERT INTO alpha_memberships VALUES (?,?,?,?)", (user_id, workspace_id, "owner", "active"))
                state = initial_state(workspace_id)
                state["account"] = {"userId": user_id, "displayName": identity["displayName"], "gateway": self.adapter.id, "status": "simulated_verified", "productionAccount": False, "methodsPreviewed": [identity["provider"]], "locale": "en", "timeZone": "device-local"}
                state["membership"] = {"userId": user_id, "workspaceId": workspace_id, "role": "owner", "status": "active"}
                state["socialConnections"] = []
                state["trial"] = None
                # The first workspace and owner membership are in this same transaction.
                db.execute("INSERT INTO workspaces VALUES (?,?,?,?)", (workspace_id, "0" * 64, 1, json.dumps(state)))
                db.execute("INSERT INTO alpha_auth_events VALUES (?,?,?,?)", (uuid.uuid4().hex, user_id, workspace_id, "fixture_first_workspace_created"))
            else:
                user_id = user["id"]
                membership = db.execute("SELECT * FROM alpha_memberships WHERE user_id=? AND status='active'", (user_id,)).fetchone()
                if not membership:
                    raise ValueError("This preview identity has no active workspace membership.")
                workspace_id = membership["workspace_id"]
            row = db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
            state, revision = json.loads(row["state"]), row["revision"]
            if replay:
                device_id = replay["device_id"]
            else:
                device_id = uuid.uuid4().hex
                db.execute("INSERT INTO alpha_auth_requests VALUES (?,?,?,?)", (identity["requestId"], user_id, workspace_id, device_id))
            token = hmac.new(self.key, (workspace_id + ":" + device_id).encode(), hashlib.sha256).hexdigest()
            db.execute("INSERT OR IGNORE INTO alpha_devices VALUES (?,?,?,?,?)", (device_id, user_id, workspace_id, hashlib.sha256(token.encode()).hexdigest(), "active"))
            if not replay:
                state["device"] = {"id": device_id, "workspaceId": workspace_id, "status": "local_prototype_credential", "pairedCloudDevice": False, "runtimeAccess": "not_granted"}
                methods = state["account"]["methodsPreviewed"]
                if identity["provider"] not in methods:
                    methods.append(identity["provider"])
                revision += 1
                db.execute("UPDATE workspaces SET state=?,revision=? WHERE id=?", (json.dumps(state), revision, workspace_id))
            return {"workspaceId": workspace_id, "token": token, "revision": revision, "state": state, "auth": {"status": "simulated_verified", "productionAccount": False, "provider": identity["provider"], "retryReused": bool(replay)}}
