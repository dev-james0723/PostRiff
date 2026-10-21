"""Runtime qualification driver. It never contacts Discord or a hosted Vercel API."""
from __future__ import annotations
import argparse
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
BASELINE = "e891af3591d8baabdb54c05d936ccd61c3299e42"
PRODUCT = "fe45c568ed65c80f76afebc9911eeaa1a1a59c29"
APP = "1553164599086555297"
HOST = "synthetic-ping-build.vercel.app"
ROUTE = "/api/discord/interactions"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(name, data):
    out = HERE / "evidence"
    out.mkdir(exist_ok=True)
    (out / name).write_text(json.dumps(data, indent=2) + "\n")


def verify_source():
    repo = HERE.parents[1]
    manifest = json.loads((HERE / "FROZEN-SOURCES.json").read_text())
    assert manifest["originalBaseline"] == BASELINE
    frozen = HERE / "frozen"
    found = {}
    for p in frozen.rglob("*"):
        assert not p.is_symlink(), str(p)
        if p.is_file():
            found[p.relative_to(frozen).as_posix()] = digest(p.read_bytes())
    assert found == manifest["files"]
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", PRODUCT, "HEAD"], cwd=repo, text=True).splitlines()
    allowed = ("validation/discord-ping-runtime/", ".github/workflows/discord-ping-runtime.yml")
    assert all(p.startswith(allowed[0]) or p == allowed[1] for p in changed), changed
    assert not subprocess.check_output(["git", "diff", "--name-only"], cwd=repo, text=True).strip()
    assert json.loads((repo / "vercel.json").read_text())["git"]["deploymentEnabled"] is False
    result = {"status": "PASS", "execution": "source hash and diff verification",
              "source": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
              "productSource": PRODUCT, "originalBaseline": BASELINE,
              "frozenFiles": len(found), "fingerprint": digest(json.dumps(found, sort_keys=True).encode()),
              "productSourceUnchanged": True, "deployment": "NOT_RUN"}
    write("frozen-source.json", result)
    print(json.dumps(result))


def unpack():
    out = HERE / "evidence"
    record = json.loads((out / "builder-result.json").read_text())
    data = (out / "function.zip").read_bytes()
    assert record["sha256"] == digest(data) and record["runtime"] == "python3.12"
    target = out / "function"
    target.mkdir()
    manifest = json.loads((HERE / "FROZEN-SOURCES.json").read_text())
    with zipfile.ZipFile(out / "function.zip") as archive:
        assert len(archive.infolist()) < 10000
        assert sum(i.file_size for i in archive.infolist()) < 150_000_000
        for info in archive.infolist():
            parts = PurePosixPath(info.filename)
            assert not parts.is_absolute() and ".." not in parts.parts
            assert not stat.S_ISLNK(info.external_attr >> 16)
            assert not re.search(r"(^|/)(\.env[^/]*|\.git|\.token-pilot)(/|$)", info.filename)
        for name in ("a7a0_ping_core.py", "api/discord/interactions.py"):
            assert digest(archive.read(name)) == manifest["files"][name]
        archive.extractall(target)  # Validated, self-built archive in a fresh CI-only directory.
    print(json.dumps({"status": "PASS", "archiveSourcesByteIdentical": True,
                      "runtime": record["runtime"], "sha256": record["sha256"]}))


def synthetic_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    # Public, deterministic fixture only. Never use it for a hosted Discord app.
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"rafii-origin-package-fixture-only").digest())


def build_origin():
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    source = os.environ["GITHUB_SHA"]
    public = synthetic_key().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL") if key in os.environ}
    env.update({"VERCEL": "1", "VERCEL_ENV": "production", "VERCEL_URL": HOST,
           "VERCEL_PROJECT_ID": "prj_syntheticping", "VERCEL_DEPLOYMENT_ID": "dpl_syntheticping",
           "RAFII_A7A0_EXPECTED_PROJECT_ID": "prj_syntheticping", "RAFII_A7A0_SOURCE_SHA": source,
           "RAFII_A7A0_APPLICATION_ID": APP, "RAFII_A7A0_PUBLIC_KEY_HEX": public,
           "VERCEL_BUILDER_MODULES": os.environ["VERCEL_BUILDER_MODULES"]})
    subprocess.run(["node", str(HERE / "build-deployment.cjs")], cwd=HERE, env=env, check=True)
    result = json.loads((HERE / "evidence/origin-binding.json").read_text())
    result["execution"] = "synthetic platform context through hosted-build entrypoint and actual builder ZIP"
    write("origin-binding.json", result)
    print(json.dumps(result))


def probe(root, manifest_path):
    assert sys.version_info[:2] == (3, 12), sys.version
    assert platform.system() == "Linux"
    root = root.resolve()
    sys.path[:0] = [str(root / "_vendor"), str(root)]
    import cryptography
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from http.server import ThreadingHTTPServer
    import a7a0_ping_core
    assert cryptography.__version__ == "50.0.1"
    assert Path(cryptography.__file__).resolve().is_relative_to(root)
    assert Path(a7a0_ping_core.__file__).resolve().is_relative_to(root)
    manifest = json.loads(manifest_path.read_text())
    for name in ("a7a0_ping_core.py", "api/discord/interactions.py"):
        assert digest((root / name).read_bytes()) == manifest["files"][name]
    spec = importlib.util.spec_from_file_location("ping_archive_handler", root / "api/discord/interactions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    key = synthetic_key()  # Deterministic public fixture; no real signing key or credential.
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    config = json.loads((root / ".vc-config.json").read_text())
    assert config["runtime"] == "python3.12" and config["maxDuration"] == 5
    assert config["environment"] == {"RAFII_A7A0_APPLICATION_ID": APP,
        "RAFII_A7A0_PUBLIC_KEY_HEX": public, "RAFII_A7A0_EXPECTED_ORIGIN": "https://" + HOST}
    env = {**config["environment"], "VERCEL_URL": HOST}
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    outcomes = []
    counts = {"loopbackConnections": 0, "rejectedExternalConnections": 0}
    original_connect = socket.socket.connect

    def guarded_connect(sock, address):
        if address != ("127.0.0.1", server.server_port):
            counts["rejectedExternalConnections"] += 1
            raise AssertionError("Unexpected connection target")
        counts["loopbackConnections"] += 1
        return original_connect(sock, address)

    def case(name, expected, *, method="POST", route=ROUTE, packet=None, raw=None,
             stamp=None, signature=None, headers=None, duplicate=None, declared=None, variables=None):
        body = raw if raw is not None else json.dumps(
            packet if packet is not None else {"application_id": APP, "type": 1},
            separators=(",", ":")).encode()
        timestamp = stamp if stamp is not None else str(int(time.time()))
        signed = signature if signature is not None else key.sign(timestamp.encode() + body).hex()
        fields = [("Host", "caller-controlled.example.invalid"), ("Content-Type", "application/json"),
                  ("Content-Length", str(len(body) if declared is None else declared)),
                  ("X-Signature-Timestamp", timestamp), ("X-Signature-Ed25519", signed),
                  ("X-Forwarded-Host", "forged.example.invalid")]
        overrides = headers or {}
        fields = [(k, overrides.get(k, v)) for k, v in fields] + list((duplicate or []))
        if "Transfer-Encoding" in overrides:
            fields.append(("Transfer-Encoding", overrides["Transfer-Encoding"]))
        request = (method + " " + route + " HTTP/1.0\r\n" +
                   "".join(k + ": " + v + "\r\n" for k, v in fields) + "\r\n").encode() + body
        with patch.dict(os.environ, env if variables is None else variables, clear=True):
            with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as conn:
                conn.sendall(request)
                conn.shutdown(socket.SHUT_WR)
                response = http.client.HTTPResponse(conn, method=method)
                response.begin()
                payload = response.read()
                assert response.status == expected, (name, expected, response.status)
                assert response.getheader("Cache-Control") == "no-store"
                assert response.getheader("X-Content-Type-Options") == "nosniff"
                assert response.getheader("Content-Type") == "application/json"
                if expected == 200:
                    assert payload == b'{"type":1}'
                elif method != "HEAD":
                    assert payload == b"{}"
        outcomes.append({"name": name, "status": expected})

    try:
        with patch.object(socket.socket, "connect", guarded_connect):
            case("valid_ping_ignores_untrusted_hosts", 200)
            case("invalid_signature", 401, signature="00" * 64)
            case("stale_timestamp", 401, stamp=str(int(time.time()) - 301))
            case("wrong_application", 401, packet={"application_id": "5555566666", "type": 1})
            case("non_ping_never_dispatches", 503, packet={"application_id": APP, "type": 2})
            case("boolean_type_rejected", 401, packet={"application_id": APP, "type": True})
            case("duplicate_length", 400, duplicate=[("content-length", "1")])
            case("duplicate_signature", 401, duplicate=[("x-signature-ed25519", "00" * 64)])
            case("chunked_body_rejected", 400, headers={"Transfer-Encoding": "chunked"})
            case("wrong_content_type", 415, headers={"Content-Type": "text/plain"})
            case("oversized_declared_body", 413, declared=65537)
            case("truncated_http_body", 400, declared=1024)
            case("get_not_available", 405, method="GET")
            case("head_not_available", 405, method="HEAD")
            case("wrong_route", 404, route="/api/anything")
            case("query_route_rejected", 404, route=ROUTE + "?alter=1")
            case("missing_configuration", 503, variables={})
            case("wrong_platform_host", 503, variables={**env, "VERCEL_URL": "other.example.invalid"})
            case("signed_non_utf8", 401, raw=json.dumps({"application_id": APP, "type": 1}).encode("utf-16"))
            case("duplicate_json_key", 401, raw=('{"application_id":"' + APP + '","type":1,"type":1}').encode())
        assert counts == {"loopbackConnections": len(outcomes), "rejectedExternalConnections": 0}
        assert not any(n.startswith(("postriff_", "psycopg")) for n in sys.modules)
        assert "sqlite3" not in sys.modules
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print(json.dumps({"status": "PASS", "execution": "real loopback HTTP in read-only network-none Lambda container",
                      "python": platform.python_version(), "cryptography": cryptography.__version__,
                      "runtimeImportsFromBuiltArchive": True, "serializedBuildOriginApplied": True, "cases": outcomes, "networkGuard": counts,
                      "liveDiscord": "NOT_RUN", "publicHttps": "NOT_RUN", "deployment": "NOT_RUN"}))


def finish():
    out = HERE / "evidence"
    unit = (out / "unit.log").read_text()
    assert "Ran 13 tests" in unit and re.search(r"\nOK\s*$", unit)
    parity = json.loads((out / "reference-parity.json").read_text())
    assert parity["offline_reference_parity"] == "PASS" and len(parity["cases"]) == 9
    smoke = json.loads((out / "lambda-probe.json").read_text())
    assert smoke["status"] == "PASS" and len(smoke["cases"]) == 20
    package_unit = (out / "package-unit.log").read_text()
    assert "Ran 14 tests" in package_unit and re.search(r"\nOK\s*$", package_unit)
    packaging = json.loads((out / "origin-binding.json").read_text())
    assert packaging["status"] == "PASS" and packaging["expectedOrigin"] == "https://" + HOST
    assert packaging["frozenRuntimeSourcesUnchanged"] and not packaging["systemVariablesOverridden"]
    assert smoke["serializedBuildOriginApplied"]
    audit = json.loads((out / "runtime-audit.json").read_text())
    assert any(d["name"].lower() == "cryptography" and d["version"] == "50.0.1" for d in audit["dependencies"])
    assert sum(len(d.get("vulns", [])) for d in audit["dependencies"]) == 0
    verify_source()
    source = json.loads((out / "frozen-source.json").read_text())
    build = json.loads((out / "builder-result.json").read_text())
    result = {"status": "PASS", "source": source["source"], "productSource": PRODUCT,
              "originalBaseline": BASELINE, "frozenFingerprint": source["fingerprint"],
              "unitTests": 13, "packageTests": 14, "referenceCases": 9, "actualHttpCases": 20,
              "buildOriginPackaging": "PASS_SYNTHETIC_CONTEXT_ACTUAL_ZIP",
              "runtime": build["runtime"], "functionSha256": build["sha256"],
              "auditedRuntimeDependencies": len(audit["dependencies"]), "runtimeVulnerabilities": 0,
              "productSourceUnchanged": True, "execution": "free standard runner and isolated Lambda image",
              "hostedVercelAcceptance": "NOT_RUN", "realDiscordAcceptance": "NOT_RUN", "release": "NO_GO"}
    write("qualification.json", result)
    print("PING_RUNTIME_QUALIFICATION " + json.dumps(result))


def emit_evidence():
    out = HERE / "evidence"
    for name in ("frozen-source.json", "reference-parity.json", "builder-result.json",
                 "runtime-audit.json", "origin-binding.json", "lambda-probe.json", "qualification.json"):
        p = out / name
        if p.exists():
            try:
                value = json.loads(p.read_text())
                if name == "builder-result.json":
                    value.pop("files", None)
                print("PING_RUNTIME_EVIDENCE " + json.dumps({"name": name, "value": value}))
            except (ValueError, OSError):
                print("PING_RUNTIME_EVIDENCE_UNREADABLE " + name)
    for name in ("unit.log", "package-unit.log", "lambda-image.txt"):
        p = out / name
        if p.exists():
            print("PING_RUNTIME_TEXT " + json.dumps({"name": name, "value": p.read_text()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify-source", "unpack", "build-origin", "probe", "finish", "emit-evidence"))
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.mode == "verify-source":
        verify_source()
    elif args.mode == "unpack":
        unpack()
    elif args.mode == "build-origin":
        build_origin()
    elif args.mode == "probe":
        probe(args.runtime_root, args.manifest)
    elif args.mode == "emit-evidence":
        emit_evidence()
    else:
        finish()
