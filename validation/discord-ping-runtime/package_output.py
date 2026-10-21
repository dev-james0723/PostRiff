"""Freeze a PING function's public build origin into Build Output API metadata.

Packaging only: no provider calls, request headers, credentials or runtime edits.
The original verifier still compares this static origin with runtime VERCEL_URL.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

PUBLIC_KEYS = {"RAFII_A7A0_APPLICATION_ID", "RAFII_A7A0_PUBLIC_KEY_HEX",
               "RAFII_A7A0_EXPECTED_ORIGIN"}
BUILDER_ENV = {"PYTHONPATH": "_vendor", "PYTHONDONTWRITEBYTECODE": "1"}
INPUTS = [".python-version", "requirements.txt", "vercel.json",
          "a7a0_ping_core.py", "api/discord/interactions.py"]
FORBIDDEN = re.compile(r"(^|/)(\.env[^/]*|\.git|\.codex|\.token-pilot|\.agents|node_modules|postriff_[^/]*|psycopg[^/]*)(/|$)")


class PackageRejected(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise PackageRejected(reason)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def trusted_context(env):
    # These must be supplied by the approved hosted build, never an HTTP request.
    # CI supplies explicit synthetic fixtures; that is not platform attestation.
    require(env.get("VERCEL") == "1", "Hosted Vercel build context required.")
    require(env.get("VERCEL_ENV") in ("production", "preview"), "Hosted target required.")
    host = env.get("VERCEL_URL", "")
    require(isinstance(host, str) and re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.vercel\.app", host),
        "Exact generated default-suffix hostname required.")
    project = env.get("VERCEL_PROJECT_ID", "")
    require(isinstance(project, str) and re.fullmatch(r"prj_[A-Za-z0-9]{1,100}", project),
            "Platform project identifier required.")
    require(env.get("RAFII_A7A0_EXPECTED_PROJECT_ID") == project,
            "Build project differs from the explicitly approved project.")
    deployment = env.get("VERCEL_DEPLOYMENT_ID", "")
    require(isinstance(deployment, str) and re.fullmatch(r"dpl_[A-Za-z0-9]{1,100}", deployment),
            "Platform deployment identifier required.")
    source = env.get("RAFII_A7A0_SOURCE_SHA", "")
    require(isinstance(source, str) and re.fullmatch(r"[a-f0-9]{40}", source),
            "Pinned source SHA required.")
    app = env.get("RAFII_A7A0_APPLICATION_ID", "")
    public = env.get("RAFII_A7A0_PUBLIC_KEY_HEX", "")
    require(isinstance(app, str) and re.fullmatch(r"[0-9]{5,25}", app),
            "Public application identifier required.")
    require(isinstance(public, str) and re.fullmatch(r"[a-fA-F0-9]{64}", public),
            "Public Ed25519 key required.")
    origin = "https://" + host
    require(env.get("RAFII_A7A0_EXPECTED_ORIGIN", origin) == origin,
            "A configured alias or other origin cannot replace the generated build origin.")
    return {"source": source, "project": project, "deployment": deployment,
            "origin": origin, "app": app, "public": public}


def write_output(evidence, output, manifest_path, env):
    context = trusted_context(env)
    evidence, output = Path(evidence), Path(output)
    record = json.loads((evidence / "builder-result.json").read_text())
    manifest = json.loads(Path(manifest_path).read_text())
    data = (evidence / "function.zip").read_bytes()
    require(record.get("status") == "PASS" and record.get("runtime") == "python3.12",
            "Qualified Python builder result required.")
    require(record.get("source") == context["source"], "Builder source mismatch.")
    require(record.get("selectedInputs") == INPUTS, "Unexpected builder inputs.")
    require(record.get("sha256") == sha256(data), "Function archive hash mismatch.")
    require(record.get("architecture") == "x86_64", "Qualified architecture required.")
    require(record.get("environmentKeys") == sorted(BUILDER_ENV)
            and record.get("environment") == BUILDER_ENV, "Unexpected builder environment.")
    handler = record.get("handler", "")
    require(isinstance(handler, str) and re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", handler),
        "Official Python handler identifier required.")
    with zipfile.ZipFile(evidence / "function.zip") as archive:
        infos = archive.infolist()
        require(0 < len(infos) < 10000 and sum(i.file_size for i in infos) < 150_000_000,
                "Function archive exceeds packaging bounds.")
        names = [i.filename for i in infos]
        require(len(names) == len(set(names)), "Duplicate archive path.")
        for info in infos:
            path = PurePosixPath(info.filename)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in info.filename,
                    "Unsafe archive path.")
            require(not stat.S_ISLNK(info.external_attr >> 16), "Archive symlink forbidden.")
            require(not FORBIDDEN.search(info.filename) and path.name != ".vc-config.json",
                    "Unexpected private or generated configuration input.")
        require(handler.rsplit(".", 1)[0] + ".py" in names, "Official handler file missing.")
        for name in ("a7a0_ping_core.py", "api/discord/interactions.py"):
            require(name in names and sha256(archive.read(name)) == manifest["files"][name],
                    "Frozen verifier or adapter changed.")
        require(not output.exists(), "Build output already exists; do not overwrite it.")
        function = output / "functions/api/discord/interactions.func"
        function.mkdir(parents=True)
        archive.extractall(function)  # Validated self-built ZIP, fresh CI/hosted-build output.
    variables = {
        "RAFII_A7A0_APPLICATION_ID": context["app"],
        "RAFII_A7A0_PUBLIC_KEY_HEX": context["public"],
        "RAFII_A7A0_EXPECTED_ORIGIN": context["origin"],
    }
    require(set(variables) == PUBLIC_KEYS, "Unexpected function environment.")
    config = {"runtime": "python3.12", "handler": handler, "architecture": "x86_64",
              "maxDuration": 5, "environment": {**BUILDER_ENV, **variables}}
    if record.get("supportsResponseStreaming") is not None:
        require(type(record["supportsResponseStreaming"]) is bool, "Invalid streaming metadata.")
        config["supportsResponseStreaming"] = record["supportsResponseStreaming"]
    config_bytes = (json.dumps(config, indent=2) + "\n").encode()
    (function / ".vc-config.json").write_bytes(config_bytes)
    routes = {"version": 3, "routes": [
        {"src": "^/api/discord/interactions$", "dest": "/api/discord/interactions"}]}
    (output / "config.json").write_text(json.dumps(routes, indent=2) + "\n")
    return {
        "status": "PASS", "execution": "build-output metadata packaging",
        "source": context["source"], "projectId": context["project"],
        "deploymentId": context["deployment"], "expectedOrigin": context["origin"],
        "applicationId": context["app"], "publicKeySha256": sha256(context["public"].encode()),
        "functionArchiveSha256": record["sha256"], "functionConfigSha256": sha256(config_bytes),
        "functionEnvironmentKeys": sorted(config["environment"]),
        "builderEnvironmentKeys": sorted(BUILDER_ENV), "publicConfigKeys": sorted(variables),
        "maxDuration": 5,
        "frozenRuntimeSourcesUnchanged": True, "systemVariablesOverridden": False,
        "hostedAcceptance": "NOT_RUN", "realDiscordAcceptance": "NOT_RUN",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-context", action="store_true")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.check_context:
        trusted_context(os.environ)
        print("PING_BUILD_CONTEXT_VALID")
    else:
        require(all((args.evidence, args.output, args.manifest)), "Explicit packaging paths required.")
        result = write_output(args.evidence, args.output, args.manifest, os.environ)
        (args.evidence / "origin-binding.json").write_text(json.dumps(result, indent=2) + "\n")
        print("PING_ORIGIN_PACKAGE " + json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except PackageRejected as error:
        raise SystemExit("PING_PACKAGE_REJECTED: " + str(error)) from None
