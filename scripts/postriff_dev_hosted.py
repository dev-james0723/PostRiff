"""LOCAL DEV HARNESS: run the real hosted PostRiff code on a disposable PostgreSQL.

What is real: migrations 001–008, HostedWorkspaceService, permissions, Ideas runtime,
source policy, OAuth transactions + encrypted custody, worker, ledger, audience.
What is simulated (and labelled 'dev-synthetic' in the UI banner): identity (no Supabase;
`Bearer dev:<uuid>`), the three providers (a local consent page + canned responses), and
private media storage. Nothing here talks to any external service.

Usage:  python scripts/postriff_dev_hosted.py [--port 4331]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server
from socketserver import ThreadingMixIn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LC_ALL", "C")
PG = Path(__import__("os").environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
PORT_PG = 55441

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication  # noqa: E402
from postriff_phase2.hosted_worker import PostgresWorker  # noqa: E402
from postriff_phase2.hosted_social import HostedSocial  # noqa: E402
from postriff_phase2.time_savings import with_time_back  # noqa: E402
from postriff_phase2.oauth import CredentialVault  # noqa: E402
from postriff_phase2 import insights  # noqa: E402

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class DevVerifier:
    """Accepts `Bearer dev:<uuid>`; inserts the user into auth.users on first sight."""
    def __init__(self, connection):
        self.connection = connection

    def __call__(self, token):
        if not isinstance(token, str) or not token.startswith("dev:") or not UUID.fullmatch(token[4:]):
            raise AlphaError("Verified session required.", 401)
        with self.connection() as db:
            db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (token[4:],))
        return token[4:]

    @staticmethod
    def session_id(token, principal):
        return "dev-session-" + principal.replace("-", "")[:20]

    @staticmethod
    def auth_time(token, principal):
        return time.time()


class DevTransport:
    """Canned provider responses so schedule → publish → verify → insights runs locally."""
    def __init__(self):
        self.posts = {}

    def __call__(self, method, url, headers=None, form=None, body=None):
        if "api.linkedin.com/rest/posts" in url and method == "POST":
            ref = "urn:li:share:" + uuid.uuid4().hex[:12]
            self.posts[ref] = body["commentary"]
            return {"status": 201, "headers": {"x-restli-id": ref}, "body": {}}
        if "api.linkedin.com/rest/posts/" in url and method == "GET":
            ref = url.rsplit("/", 1)[1].replace("%3A", ":")
            return {"status": 200, "headers": {}, "body": {"lifecycleState": "PUBLISHED", "commentary": self.posts.get(ref, "")}}
        if url.endswith("/threads") and method == "POST":
            cid = str(len(self.posts) + 1000)
            self.posts[cid] = form.get("text", "")
            return {"status": 200, "headers": {}, "body": {"id": cid}}
        if url.endswith("/threads_publish"):
            mid = "9" + form["creation_id"]
            self.posts[mid] = self.posts.get(form["creation_id"], "")
            return {"status": 200, "headers": {}, "body": {"id": mid}}
        if "/insights" in url:
            return {"status": 200, "headers": {}, "body": {"data": [{"name": "views", "values": [{"value": 128}]}, {"name": "likes", "values": [{"value": 7}]}, {"name": "replies", "values": [{"value": 2}]}]}}
        if "/replies" in url:
            return {"status": 200, "headers": {}, "body": {"data": [{"id": "77001", "text": "Love this — where can I read more?", "username": "curious_reader"}]}}
        if "graph.threads.net" in url and method == "GET":
            mid = url.split("/v24.0/")[1].split("?")[0]
            return {"status": 200, "headers": {}, "body": {"id": mid, "text": self.posts.get(mid, ""), "permalink": "https://www.threads.net/@dev/post/" + mid}}
        return {"status": 200, "headers": {}, "body": {}}


class DevProvider:
    """Local consent page instead of a real provider; tokens are opaque dev strings."""
    capability_version = 1
    native_schedule = False
    assisted_fallback = True
    production_reviewed = True  # dev-synthetic only; the real registry never sets this without review

    def __init__(self, pid, platform, base):
        self.id, self.platform, self.base = pid, platform, base
        self.scopes = {"linkedin": {"publish": ["openid", "profile", "w_member_social"], "identity": ["openid"]},
                       "threads": {"publish": ["threads_basic", "threads_content_publish"], "analytics": ["threads_basic", "threads_manage_insights"], "comments_read": ["threads_basic", "threads_read_replies"], "reply": ["threads_basic", "threads_manage_replies"], "identity": ["threads_basic"]}}[pid]

    def capability_scopes(self, capability):
        return list(self.scopes.get(capability, []))

    def explain(self, capability):
        return f"DEV: PostRiff would request {', '.join(self.capability_scopes(capability)) or 'no scopes'} from {self.platform}."

    def authorize_url(self, redirect, state, challenge, scopes):
        # The stored PostRiff callback is the https placeholder (DB CHECK enforces https); the
        # local consent page sends the browser back to this machine's loopback callback instead.
        local_callback = f"{self.base}/api/oauth/{self.id}/callback"
        return f"{self.base}/dev/consent?" + urlencode({"provider": self.id, "redirect": local_callback, "state": state, "scope": " ".join(scopes)})

    def exchange(self, code, verifier, redirect):
        return {"accessToken": f"dev-{self.id}-access-{code}", "refreshToken": f"dev-{self.id}-refresh", "expiresIn": 3600, "scopes": None}

    def identity(self, access_token):
        # A token minted from the consent page's "second account" choice identifies a different account.
        second = str(access_token).endswith("-good-code-2")
        if self.id == "linkedin":
            return {"providerAccountId": "urn:li:person:devmember2" if second else "urn:li:person:devmember", "handle": "Dev Member Two" if second else "Dev Member", "accountType": "member"}
        return {"providerAccountId": "17841400000000002" if second else "17841400000000", "handle": "@dev_creator_two" if second else "@dev_creator", "accountType": "profile"}

    def refresh(self, refresh_token):
        return {"accessToken": f"dev-{self.id}-access-refreshed", "refreshToken": refresh_token, "expiresIn": 3600}

    def revoke(self, token):
        return True


class DevAssets:
    """In-memory private media boundary for the synthetic harness, with the video bucket's calls (chat-context SPEC §7.3):
    the browser PUTs video bytes to a Supabase-shaped signed URL, which the browser scene forwards to `PUT /dev/upload/{token}`."""
    VIDEO_BUCKET = "postriff-video"

    def __init__(self):
        self.objects = {}
        self.uploads = {}   # token → (workspace id, object name)
        self.storage = self

    def signed_url(self, wid, kind, name, ttl=300):
        return f"https://dev.invalid/{wid}/{kind}/{name}"

    def stage_upload(self, workspace_id, payload):
        from postriff_phase2.media import decode_upload
        asset = decode_upload(payload, decoder="pillow")
        raw = base64.b64decode(asset.pop("data"), validate=True)
        object_name = f"{asset['id']}-{asset['hash']}.jpg"
        self.objects[(workspace_id, "media", object_name)] = raw
        asset.update({"storagePath": f"{workspace_id}/media/{object_name}", "objectName": object_name, "execution": "dev-synthetic-memory"})
        return asset

    def get(self, workspace_id, category, object_name):
        raw = self.objects.get((workspace_id, category, object_name))
        if raw is None:
            raise AlphaError("This private media object is unavailable.", 404)
        return raw

    def remove(self, workspace_id, asset):
        from postriff_phase2.hosted_storage import PrivateAssetService
        PrivateAssetService.remove(self, workspace_id, asset)   # the real kind-aware removal (video, poster, frames)

    # --- the video bucket, in memory -------------------------------------------------------------------------------------
    def bucket_info(self, bucket=None):
        return {"id": bucket or self.VIDEO_BUCKET, "public": False, "fileSizeLimit": 100_000_000, "allowedMimeTypes": ["video/mp4", "video/quicktime"]}

    def signed_upload_url(self, workspace_id, category, object_name):
        token = uuid.uuid4().hex
        self.uploads[token] = (workspace_id, object_name)
        return f"https://devharness.supabase.co/storage/v1/object/upload/sign/{self.VIDEO_BUCKET}/{workspace_id}/video/{object_name}?token={token}"

    def receive_upload(self, token, raw, mime):
        target = self.uploads.pop(token, None)
        if target is None or not raw:
            return False
        workspace_id, object_name = target
        if (workspace_id, "video", object_name) in self.objects:
            return False   # no upsert, like the real signed upload
        self.objects[(workspace_id, "video", object_name)] = raw
        self.objects[("mime", workspace_id, object_name)] = mime
        return True

    def object_info(self, workspace_id, category, object_name):
        raw = self.get(workspace_id, category, object_name)
        return {"bytes": len(raw), "mime": self.objects.get(("mime", workspace_id, object_name)) or "video/mp4", "etag": hashlib.sha256(raw).hexdigest()[:16]}

    def read_range(self, workspace_id, category, object_name, start, length):
        return {"data": self.get(workspace_id, category, object_name)[start:start + length], "ranged": True}

    def delete(self, workspace_id, category, object_name):
        self.objects.pop((workspace_id, category, object_name), None)

    def list_prefix(self, prefix, bucket=None):
        workspace_id = prefix.split("/", 1)[0]
        return [f"{workspace_id}/video/{name}" for (ws, category, name) in list(self.objects) if ws == workspace_id and category == "video"]


class DevMediaReader:
    """Canned photo/frame notes for the harness (provenance fixture, cost 0): no vision provider is ever called."""
    available = True

    def processor(self):
        return {"id": "dev-fixture:vision", "label": "Local fixture reader"}

    def estimate(self, kind, frames=1):
        return {"typicalUsdMicro": 0, "ceilingUsdMicro": 0, "model": "dev-fixture-vision", "provider": "dev-fixture"}

    def read(self, images, kind, timeout=None):
        what = f"{len(images)} video frame(s)" if kind == "video_frames" else "a photo"
        return {"text": f"Fixture note for {what}: a warm, well-lit scene with one clear subject. (Local harness; no model looked at it.)",
                "model": "dev-fixture-vision", "provider": "dev-fixture", "costUsdMicro": 0, "usage": {"inputTokens": 0, "outputTokens": 0}, "latencyMs": 1}


class DevImageRuntime:
    """Clearly labelled fixture used only to exercise the complete local UI flow."""
    provider = "dev-synthetic"
    model = "dev-synthetic-image"
    cost_class = "none"
    estimate_usd_micro = 0

    def generate(self, prompt, *, count=1, emit=lambda _event: None):
        from PIL import Image, ImageDraw
        if count != 1:
            raise AlphaError("The local preview creates one image at a time.")
        emit({"type": "progress.updated", "stage": "image_generation", "percent": 25})
        digest = hashlib.sha256(prompt.encode()).digest()
        image = Image.new("RGB", (1024, 1024), (246, 241, 230))
        draw = ImageDraw.Draw(image)
        palette = [(25, 45, 63), (196, 84, 55), (83, 122, 103), (226, 177, 74)]
        for index in range(11):
            color = palette[digest[index] % len(palette)]
            inset = 45 + index * 38
            draw.rounded_rectangle((inset, inset, 1024 - inset, 1024 - inset), radius=70, outline=color, width=22)
        draw.ellipse((330, 330, 694, 694), fill=palette[digest[12] % len(palette)])
        output = io.BytesIO()
        image.save(output, format="PNG")
        emit({"type": "progress.updated", "stage": "image_generation", "percent": 75})
        return {"images": [output.getvalue()], "usage": {"provenance": "fixture", "modelRequests": 0, "costUsd": 0, "model": self.model, "provider": self.provider}}


def start_postgres(port=PORT_PG):
    tmp = tempfile.mkdtemp(prefix="postriff-dev-pg-")
    data, log = Path(tmp) / "data", Path(tmp) / "postgres.log"
    subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(log), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
    dsn = f"host=127.0.0.1 port={port} dbname=postgres"
    subprocess.run([str(PG / "psql"), dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / "tests/phase2/rls.sql")], check=True, stdout=subprocess.DEVNULL)
    return dsn, data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4331)
    parser.add_argument("--credit-fixture", action="store_true", help="synthetic credit funding and model, disposable database only")
    parser.add_argument("--phone-fixture", action="store_true", help="local fake phone identity/calls; no SMS or PSTN egress")
    parser.add_argument("--notification-fixture", action="store_true", help="unified notifications with fake SMS/Push/Email only")
    parser.add_argument('--growth-fixture',action='store_true',help='Phase 1 models are deterministic and zero-network; disposable database only')
    parser.add_argument('--radar-fixture',action='store_true',help='Radar deterministic providers and models; disposable local database only')
    parser.add_argument('--growth-phase2-fixture',action='store_true',help='Phase 2 deterministic models, disposable database only')
    parser.add_argument("--pg-port", type=int, default=PORT_PG, help="disposable PostgreSQL port; change it to run a second harness beside the first")
    parser.add_argument("--static", type=Path, default=ROOT / "studio/web/dist-alpha")
    args = parser.parse_args()
    if args.growth_phase2_fixture or args.radar_fixture:args.growth_fixture=True
    import psycopg
    dsn, data = start_postgres(args.pg_port)
    connection = lambda: psycopg.connect(dsn, client_encoding="utf8", autocommit=False)
    # POSTRIFF_DEV_WEB_ORIGIN lets the Next.js dev server (which proxies /api and /dev here) own the consent + callback flow.
    base = os.environ.get("POSTRIFF_DEV_WEB_ORIGIN", "").rstrip("/") or f"http://127.0.0.1:{args.port}"
    transport = DevTransport()
    providers = {"linkedin": DevProvider("linkedin", "LinkedIn", base), "threads": DevProvider("threads", "Threads", base)}
    verifier = DevVerifier(connection)
    # OAuth rows must carry an https PostRiff callback (production guard); the dev consent page
    # redirects to the loopback callback itself, so the placeholder host is never contacted.
    # The web app labels a dev identity `dev-<first 8 of the uuid>@postriff.invalid`; the same address
    # here lets invitations addressed to it show up on the profile. Nothing is ever sent (NullTransport).
    dev_assets = DevAssets()
    # Chat attachments (chat-context SPEC §14.2): the three flags are on here, with the canned reader and the in-memory bucket.
    from postriff_phase2.video_uploads import VideoPolicy
    chat_media = {"flags": {"attachments": True, "notes": True, "video": True}, "reader": DevMediaReader(), "videoPolicy": VideoPolicy(enabled=True)}
    growth_writer=None
    if args.growth_fixture:
        sys.path.insert(0,str(ROOT/'tests'))
        from growth_phase1_fixtures import Writer, Models, ENV
        if args.growth_phase2_fixture:
            from growth_phase2_fixtures import Models, ENV
        if args.radar_fixture:
            from radar_fixtures import Models, ENV, Sources
        growth_writer=Writer()
    service = HostedWorkspaceService(connection, verifier, dev_assets, vault=CredentialVault(CredentialVault.generate_key()), providers=providers, public_base_url="https://dev.postriff.invalid", audience_transport=transport, image_runtime=DevImageRuntime(), email_lookup=lambda principal: f"dev-{principal[:8]}@postriff.invalid", chat_media=chat_media,ideas_runtime=growth_writer)
    if args.growth_fixture:
        from postriff_phase2.growth.service import GrowthService
        service.growth=GrowthService(service,env=ENV,router_factory=Models().router)
        if args.radar_fixture:service.growth.radar.sources=Sources()
    if args.credit_fixture:
        from launch_credit_fixture import configure
        configure(service, connection)
    if args.phone_fixture:
        from postriff_phase2.phone.runtime import attach
        attach(service,{'RAFII_PHONE_ENABLED':'1','RAFII_PHONE_OUTBOUND_ENABLED':'1','RAFII_PHONE_SCHEDULED_ENABLED':'1',
                        'RAFII_PHONE_PROACTIVE_ENABLED':'1','RAFII_PHONE_PROVIDER':'fake'})
    if args.notification_fixture:
        from postriff_phase2.coworker.runtime import attach as attach_notifications
        from postriff_phase2.notifications import sms, push
        fixture_values = {'RAFII_NOTIFICATIONS_V2_ENABLED':'1','RAFII_SMS_ENABLED':'1','RAFII_SMS_ESCALATION_ENABLED':'1','RAFII_WEB_PUSH_ENABLED':'1',
                          'POSTRIFF_PUBLIC_BASE_URL':'https://dev.postriff.invalid','POSTRIFF_VAPID_SUBJECT':'https://dev.postriff.invalid'}
        keys = push.generate_vapid_keys()
        fixture_values.update(POSTRIFF_VAPID_PUBLIC_KEY=keys['publicKey'],POSTRIFF_VAPID_PRIVATE_KEY=keys['privateKey'])
        attach_notifications(service,fixture_values)
        service.notifications.sms_transport = sms.FakeSMSTransport()
        class FakePush:
            name = 'fake_push'
            def send(self,*_args,**_kwargs): return {'state':'sent','providerRef':'local-push'}
        service.notifications.push_transport = FakePush()
        # The existing NullTransport remains in place for email. No customer address is contacted.
    social = HostedSocial(service.oauth, providers, dev_assets, transport=transport)

    def on_verified(cur, workspace_id, job):
        manifest = job["manifest"]
        provider = {"LinkedIn": "linkedin", "Threads": "threads"}.get(manifest["platform"])
        if provider == "threads":
            insights.ingest_post_insights(cur, transport, service.oauth, workspace_id, manifest["channelId"], provider, job["providerReference"], job["id"], time.time())
            service.audience.ingest_replies(cur, workspace_id, manifest["channelId"], provider, job["providerReference"], time.time())
        else:
            insights.ingest_post_insights(cur, transport, service.oauth, workspace_id, manifest["channelId"], provider, job["providerReference"], job["id"], time.time())

    if args.growth_fixture:
        from postriff_phase2.growth.performance import then_capture
        on_verified=then_capture(on_verified,True)
    worker = PostgresWorker(connection, social=social, on_verified=with_time_back(on_verified, service.time_savings))
    app = HostedApplication(service, worker, {"provider": "dev", "execution": "dev-synthetic", "flow": "dev"}, "d" * 24)
    static = args.static.resolve()

    def application(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        if path.startswith("/dev/upload/") and environ["REQUEST_METHOD"] == "PUT":
            # The browser scene forwards the signed-URL PUT here (the real client only PUTs to Supabase URLs).
            length = int(environ.get("CONTENT_LENGTH") or 0)
            accepted = dev_assets.receive_upload(path.rsplit("/", 1)[-1], environ["wsgi.input"].read(length), environ.get("CONTENT_TYPE") or "video/mp4")
            status = "200 OK" if accepted else "400 Bad Request"
            start_response(status, [("Content-Type", "application/json"), ("Content-Length", "2")])
            return [b"{}"]
        if path == "/dev/consent":
            q = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
            if environ["REQUEST_METHOD"] == "POST":
                length = int(environ.get("CONTENT_LENGTH") or 0)
                form = {k: v[0] for k, v in parse_qs(environ["wsgi.input"].read(length).decode()).items()}
                decision = form.get("decision")
                allow = decision in ("allow", "allow-second")
                # "Allow as a second account" lets the local harness hold two distinct accounts on one
                # platform (Rafii v9 folder evidence). The code suffix flows into the opaque dev token.
                code = "good-code-2" if decision == "allow-second" else "good-code"
                target = form["redirect"] + "?" + urlencode({"state": form["state"], **({"code": code} if allow else {"error": "access_denied"})})
                start_response("302 Found", [("Location", target), ("Content-Length", "0")])
                return [b""]
            html = f"""<!doctype html><meta charset=utf-8><title>DEV consent</title><body style="font-family:Avenir Next,sans-serif;background:#f8f7f2;color:#292f2b;padding:48px;max-width:560px;margin:auto">
<p style="letter-spacing:.12em;font-size:12px;color:#a34325">LOCAL DEV · SYNTHETIC PROVIDER · NOTHING LEAVES THIS MACHINE</p>
<h1 style="font-family:Iowan Old Style,Palatino,serif;font-weight:400">Allow PostRiff to access your {q.get('provider','')} account?</h1>
<p>Requested scopes: <code>{q.get('scope','')}</code></p>
<form method=post><input type=hidden name=redirect value="{q.get('redirect','')}"><input type=hidden name=state value="{q.get('state','')}">
<button name=decision value=allow style="padding:12px 20px;background:#284e3a;color:#fff;border:0;border-radius:8px;font-size:16px">Allow</button>
<button name=decision value=allow-second style="padding:12px 20px;background:#3b4a6b;color:#fff;border:0;border-radius:8px;font-size:16px;margin-left:12px">Allow as a second account</button>
<button name=decision value=deny style="padding:12px 20px;background:transparent;border:1px solid #dedfd4;border-radius:8px;font-size:16px;margin-left:12px">Deny</button></form></body>"""
            raw = html.encode()
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(raw)))])
            return [raw]
        if path.startswith("/api/"):
            return app(environ, start_response)
        candidate = (static / path.lstrip("/")).resolve()
        if not candidate.is_relative_to(static) or not candidate.is_file():
            candidate = static / "index.html"  # SPA fallback (e.g. /channels/connect)
        raw = candidate.read_bytes()
        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        start_response("200 OK", [("Content-Type", ctype), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store")])
        return [raw]

    def ticker():
        while True:
            time.sleep(4)
            try:
                worker.tick(max_jobs=5, max_seconds=5)
            except Exception as error:  # keep the harness alive; surface in the log
                print("worker tick error:", error, flush=True)

    threading.Thread(target=ticker, daemon=True).start()

    class Quiet(WSGIRequestHandler):
        def log_message(self, *_):
            pass

    class LocalConcurrentServer(ThreadingMixIn, WSGIServer):
        # Test concurrent application/DB requests instead of overflowing wsgiref's backlog of five.
        # This remains a loopback-only synthetic harness, not a production HTTP server.
        daemon_threads = True
        request_queue_size = 64
    server = make_server("127.0.0.1", args.port, application, server_class=LocalConcurrentServer, handler_class=Quiet)
    print(f"PostRiff DEV hosted harness: {base} | disposable PostgreSQL {dsn} | providers: dev-synthetic | identity: dev", flush=True)
    import signal

    def stop(*_):  # SIGTERM/SIGINT → orderly shutdown so the disposable cluster never orphans
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], stdout=subprocess.DEVNULL)
        import shutil
        shutil.rmtree(data.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
