#!/usr/bin/env python3
"""Run and clean up bounded synthetic validation against a protected Preview."""
import argparse
import base64
import io
import json
import os
import secrets
import subprocess
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from PIL import Image


def command(args, **kwargs):
    return subprocess.run(args, capture_output=True, **kwargs)


class PreviewValidation:
    def __init__(self, project_ref, deployment, team):
        self.ref = project_ref
        self.deployment = deployment
        self.team = team
        self.project_url = f"https://{project_ref}.supabase.co"
        result = command(["supabase", "projects", "api-keys", "--project-ref", project_ref, "--output", "json"], text=True, check=True)
        raw = json.loads(result.stdout)
        self.keys = raw if isinstance(raw, list) else raw.get("keys", raw.get("api_keys", []))
        self.publishable = self._key("publishable")
        self.secret = self._key("secret")
        self.service_role = next(
            (item.get("api_key") or item.get("key") or item.get("value"))
            for item in self.keys
            if item.get("type") == "legacy" and item.get("name") == "service_role"
        )
        self.database_password = command(
            ["security", "find-generic-password", "-s", "PostRiff Phase2 Supabase Database", "-a", project_ref, "-w"],
            text=True,
            check=True,
        ).stdout.strip()
        self.cron = command(
            ["security", "find-generic-password", "-s", "PostRiff Phase2 Vercel Cron", "-a", "postriff-phase2-private", "-w"],
            text=True,
            check=True,
        ).stdout.strip()
        self.users = []
        self.workspaces = []
        self.asset = None
        self.sessions = []

    def _key(self, kind):
        row = next(item for item in self.keys if item.get("type") == kind)
        return row.get("api_key") or row.get("key") or row.get("value")

    def supabase(self, method, path, body=None, admin=False):
        token = self.service_role if admin else self.publishable
        request = Request(
            self.project_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"apikey": token, "Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=25) as response:
                return response.status, json.loads(response.read() or b"{}")
        except HTTPError as error:
            payload = error.read()
            try:
                detail = json.loads(payload)
            except (TypeError, ValueError):
                detail = {"error": "non-json"}
            return error.code, detail

    def deployed(self, path, method="GET", body=None, token=None, cron_token=None):
        args = [
            "vercel", "--scope", self.team, "curl", path, "--deployment", self.deployment, "--",
            "--silent", "--show-error", "--write-out", "\n%{http_code}", "--request", method,
        ]
        if body is not None:
            args += ["--header", "Content-Type: application/json", "--header", "X-PostRiff-Request: founder-alpha", "--data", json.dumps(body, separators=(",", ":"))]
        if token:
            args += ["--header", "Authorization: Bearer " + token]
        if cron_token:
            args += ["--header", "Authorization: Bearer " + cron_token]
        result = command(args)
        if result.returncode:
            raise RuntimeError("protected Preview request failed before an HTTP response")
        payload, raw_status = result.stdout.rsplit(b"\n", 1)
        try:
            parsed, kind = json.loads(payload), "json"
        except (TypeError, ValueError):
            parsed, kind = payload, "binary"
        return int(raw_status), parsed, kind

    def create_session(self, plan):
        email = f"postriff-phase2-{secrets.token_hex(6)}@example.invalid"
        password = secrets.token_urlsafe(24)
        status, user = self.supabase("POST", "/auth/v1/admin/users", {"email": email, "password": password, "email_confirm": True, "user_metadata": {"purpose": "synthetic-preview-validation"}}, admin=True)
        if status not in (200, 201):
            raise RuntimeError("synthetic user creation failed")
        self.users.append(str(UUID(user["id"])))
        status, signed = self.supabase("POST", "/auth/v1/token?grant_type=password", {"email": email, "password": password})
        if status != 200 or not signed.get("access_token"):
            raise RuntimeError("synthetic sign-in failed")
        status, boot, _ = self.deployed("/api/auth/verify", "POST", {"plan": plan}, token=signed["access_token"])
        if status != 201 or "token" in boot:
            raise RuntimeError("hosted bootstrap failed or reflected a credential")
        workspace = str(UUID(boot["workspaceId"]))
        self.workspaces.append(workspace)
        session = {"token": signed["access_token"], "workspace": workspace, "revision": boot["revision"], "plan": plan}
        self.sessions.append(session)
        return session

    def run(self):
        first, second = self.create_session("studio"), self.create_session("assist")
        if first["workspace"] == second["workspace"]:
            raise RuntimeError("synthetic users shared a workspace")
        own_status, _, _ = self.deployed("/api/workspaces/" + first["workspace"], token=first["token"])
        cross_status, _, _ = self.deployed("/api/workspaces/" + first["workspace"], token=second["token"])
        if own_status != 200 or cross_status != 403:
            raise RuntimeError("workspace isolation failed")
        status, changed, _ = self.deployed("/api/workspaces/" + first["workspace"] + "/actions", "POST", {"expectedRevision": first["revision"], "action": "mode", "payload": {"mode": "personal"}}, token=first["token"])
        if status != 200 or changed["revision"] != first["revision"] + 1:
            raise RuntimeError("hosted mutation failed")
        first["revision"] = changed["revision"]
        picture = io.BytesIO()
        Image.new("RGBA", (640, 480), (20, 90, 160, 128)).save(picture, "PNG")
        status, uploaded, _ = self.deployed("/api/workspaces/" + first["workspace"] + "/actions", "POST", {"expectedRevision": first["revision"], "action": "p2_media_upload", "payload": {"data": base64.b64encode(picture.getvalue()).decode()}}, token=first["token"])
        if status != 200:
            raise RuntimeError("private media upload failed")
        first["revision"] = uploaded["revision"]
        self.asset = uploaded["state"]["phase2"]["assets"][-1]
        media_path = "/api/workspaces/" + first["workspace"] + "/media/" + self.asset["id"]
        media_status, media, kind = self.deployed(media_path, token=first["token"])
        media_cross, _, _ = self.deployed(media_path, token=second["token"])
        if media_status != 200 or kind != "binary" or not media.startswith(b"\xff\xd8\xff") or media_cross != 403:
            raise RuntimeError("private media isolation failed")
        status, deleted, _ = self.deployed("/api/workspaces/" + first["workspace"] + "/actions", "POST", {"expectedRevision": first["revision"], "action": "p2_media_delete", "payload": {"assetId": self.asset["id"]}}, token=first["token"])
        if status != 200:
            raise RuntimeError("private media deletion failed")
        first["revision"], self.asset = deleted["revision"], None
        worker_status, worker, _ = self.deployed("/api/cron/worker", cron_token=self.cron)
        if worker_status != 200 or worker.get("externalExecution") is not False:
            raise RuntimeError("worker fail-closed check failed")
        return {"status": "pass", "deploymentTarget": "preview", "users": 2, "distinctWorkspaces": True, "bootstrapTokenReflected": False, "ownWorkspace": own_status, "crossWorkspace": cross_status, "mutationRevisionAdvanced": True, "privateMediaRead": media_status, "crossMedia": media_cross, "privateMediaDeleted": True, "worker": worker}

    def cleanup(self):
        results = []
        if self.asset and self.asset.get("storagePath"):
            request = Request(self.project_url + "/storage/v1/object/postriff-private/" + quote(self.asset["storagePath"], safe="/"), method="DELETE", headers={"apikey": self.secret, "Authorization": "Bearer " + self.secret})
            try:
                with urlopen(request, timeout=20) as response:
                    results.append({"fallbackStorageDelete": response.status in (200, 204)})
            except Exception:
                results.append({"fallbackStorageDelete": False})
        if self.users or self.workspaces:
            environment = {**os.environ, "PGPASSWORD": self.database_password, "PGSSLMODE": "require", "PGCONNECT_TIMEOUT": "12"}
            users = ",".join("'" + value + "'::uuid" for value in self.users) or "null::uuid"
            workspaces = ",".join("'" + value + "'::uuid" for value in self.workspaces) or "null::uuid"
            sql = f"begin; delete from public.pr_trials where user_id in ({users}); delete from public.pr_memberships where user_id in ({users}); delete from public.pr_profiles where user_id in ({users}); delete from public.pr_workspaces where id in ({workspaces}); commit;"
            database = command(["psql", "-X", "-h", f"db.{self.ref}.supabase.co", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-Atc", sql], env=environment, text=True)
            results.append({"databaseRowsRemoved": database.returncode == 0})
        removed = 0
        for user_id in self.users:
            status, _ = self.supabase("DELETE", "/auth/v1/admin/users/" + user_id, admin=True)
            removed += status in (200, 204)
        results.append({"authUsersRemoved": removed, "expected": len(self.users)})
        return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--team", required=True)
    args = parser.parse_args()
    validation = PreviewValidation(args.project_ref, args.deployment, args.team)
    try:
        result = validation.run()
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        print(json.dumps({"cleanup": validation.cleanup()}, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
