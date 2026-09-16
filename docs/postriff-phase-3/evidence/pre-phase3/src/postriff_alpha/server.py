"""Loopback-only API and static host. No legacy routes and no external requests."""
import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .domain import AlphaError, Store
from .generation import routes
from .templates import catalog
from .profiles import metadata
from .auth import LocalAuthGateway


def make_server(store, static_dir, port=4326):
    static_dir = Path(static_dir).resolve()
    auth = getattr(store, 'auth', None) or LocalAuthGateway(store)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Access keys, input and workspace IDs never enter HTTP logs.

        def reply(self, status, body, content_type="application/json; charset=utf-8", download=False):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'" + ("; style-src-attr 'unsafe-inline'" if hasattr(store, 'worker_step') else ""))
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="postriff-private-drafts.zip"')
            self.end_headers()
            self.wfile.write(body)

        def safe_origin(self, mutation=False):
            expected = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected:
                raise AlphaError("Use the private loopback address.", 403)
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + expected:
                raise AlphaError("This origin cannot access the private alpha.", 403)
            if mutation and self.headers.get("X-PostRiff-Request") != "founder-alpha":
                raise AlphaError("This request is missing the local application guard.", 403)

        def route(self, mutation=False):
            self.safe_origin(mutation)
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/health" and not mutation:
                return self.reply(200, {"status": "ok", "execution": "phase2-local-fixtures" if hasattr(store, 'worker_step') else "private-local-founder-alpha", "phase0": "incomplete", "customerValidated": False})
            if path == "/api/catalog" and not mutation:
                return self.reply(200, {"templates": catalog(), "routes": routes(), "profileMetadata": metadata(), "phase2": hasattr(store, 'worker_step')})
            if not mutation and hasattr(store, 'worker_step') and path in ("/api/content-types", "/api/content-formats", "/api/content-type-packs"):
                from postriff_phase2.content_types import formats, public_catalog, public_packs
                response = {"/api/content-types": public_catalog, "/api/content-formats": formats, "/api/content-type-packs": public_packs}[path]()
                return self.reply(200, response)
            body = {}
            if mutation:
                if "application/json" not in self.headers.get("Content-Type", ""):
                    raise AlphaError("Send a JSON action.", 415)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= (12000000 if hasattr(store, 'worker_step') else 400000):
                        raise AlphaError("This request exceeds the local action size limit.", 413)
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError) as e:
                    raise AlphaError("The local action was not valid JSON.") from e
                if not isinstance(body, dict):
                    raise AlphaError("Expected a structured action.")
            if path == "/api/workspaces" and mutation:
                if body.get("sample") is not True:
                    raise AlphaError("Complete the local account preview before creating a private workspace.", 403)
                return self.reply(201, store.create(sample=True))
            if path == "/api/auth/verify" and mutation:
                try:
                    return self.reply(200, auth.sign_in(body))
                except ValueError as e:
                    raise AlphaError(str(e)) from e
            if path == "/api/auth/challenge" and mutation and hasattr(auth, 'challenge'):
                return self.reply(200, auth.challenge(body))
            segments = path.strip("/").split("/")
            if len(segments) in (3, 4) and segments[:2] == ["api", "workspaces"]:
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                workspace_id = segments[2]
                if len(segments) == 3 and not mutation:
                    return self.reply(200, store.get(workspace_id, token))
                if len(segments) == 4 and segments[3] == "actions" and mutation:
                    return self.reply(200, store.mutate(workspace_id, token, body.get("expectedRevision"), body.get("action"), body.get("payload", {})))
                if len(segments) == 4 and segments[3] == "export" and not mutation:
                    return self.reply(200, store.export(workspace_id, token), "application/zip", True)
                if len(segments) == 4 and segments[3] == "profile-export" and not mutation:
                    return self.reply(200, store.export_profile(workspace_id, token), "application/zip", True)
            if path.startswith("/api/"):
                raise AlphaError("This route is not available in the founder alpha.", 404)
            if mutation:
                raise AlphaError("This action is not available.", 404)
            candidate = (static_dir / (path.lstrip("/") or "index.html")).resolve()
            if not candidate.is_relative_to(static_dir) or not candidate.is_file():
                raise AlphaError("This page is not available.", 404)
            return self.reply(200, candidate.read_bytes(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")

        def handle_request(self, mutation=False):
            try:
                self.route(mutation)
            except AlphaError as e:
                self.reply(e.status, {"error": str(e)})
            except Exception:
                # Do not return traceback, paths, secrets, or private input to the client.
                self.reply(500, {"error": "The local store could not complete this action. Your previous saved state is intact; check the launcher and retry."})

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request(True)

        def do_PUT(self):
            self.handle_request(True)

        def do_OPTIONS(self):
            self.reply(403, {"error": "Cross-origin access is not enabled."})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Start the private PostRiff founder alpha on loopback only.")
    parser.add_argument("--port", type=int, default=4326)
    parser.add_argument("--data", type=Path, default=Path.home() / "Library/Application Support/PostRiffFounderAlpha/alpha.sqlite3")
    parser.add_argument("--static", type=Path, default=Path(__file__).resolve().parents[2] / "studio/web/dist-alpha")
    args = parser.parse_args()
    if not (args.static / "index.html").is_file():
        parser.error("Build the alpha first: cd studio/web && npx vite build --config vite.alpha.config.ts")
    os.umask(0o077)
    server = make_server(Store(args.data), args.static, args.port)
    print(f"PostRiff private founder alpha: http://127.0.0.1:{args.port} | fixture generation | Phase 0 incomplete", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
