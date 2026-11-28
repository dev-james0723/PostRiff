"""Build and serve the local Studio using Rafii's authenticated staging API."""

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.request import HTTPRedirectHandler, build_opener


APP = Path(__file__).resolve().parent
WEB = APP.parent / "web"
# Supabase public settings are compiled into the browser bundle. Keep the
# connected build separate from the existing local-only preview and its cache.
STAGING_SITE = APP / ".supabase-site"
STAGING_API = "https://rafii-consumer-staging.vercel.app"
SUPABASE_URL = "https://oxacvkhpfgytkepxcaqh.supabase.co"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def public_settings():
    with build_opener(NoRedirect()).open(STAGING_API + "/api/auth/config", timeout=10) as response:
        config = json.load(response)
    key = config.get("publishableKey")
    if not (config.get("provider") == "supabase" and config.get("projectUrl") == SUPABASE_URL
            and isinstance(key, str) and re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key)):
        raise ValueError("Rafii staging did not return its expected public Supabase settings.")
    return key


def check_built_settings(key):
    saved_key = STAGING_SITE / ".next/studio-publishable-key"
    if not saved_key.is_file() or saved_key.read_text() != key:
        raise ValueError("The Supabase settings have changed. Rebuild Rafii Studio before opening it.")


def run(action):
    if action not in ("--build", "--serve-web"):
        raise ValueError("Choose --build or --serve-web.")
    STAGING_SITE.mkdir(exist_ok=True)
    # A rebuild replaces chunks used by a running server. Hold the same lock
    # through exec so an open Studio keeps its complete build.
    with (STAGING_SITE / ".studio-lock").open("a") as lock:
        mode = fcntl.LOCK_EX if action == "--build" else fcntl.LOCK_SH
        try:
            fcntl.flock(lock, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A Studio build is in use. Close it before rebuilding or opening another copy.") from None
        if action == "--serve-web":
            os.set_inheritable(lock.fileno(), True)
        run_next(action)


def run_next(action):
    key = public_settings()
    env = {**os.environ, "NEXT_PUBLIC_SUPABASE_URL": SUPABASE_URL,
           "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": key, "POSTRIFF_API_ORIGIN": STAGING_API,
           "NEXT_PUBLIC_APP_URL": "http://localhost:47632", "POSTRIFF_DIST_DIR": ".next",
           "NEXT_PUBLIC_SENTRY_DISABLED": "1"}
    if action == "--build":
        # Next generates types and may update tsconfig. Keep these files private
        # to this build while sharing the project's source and installed packages.
        for name in ("src", "public", "node_modules"):
            link = STAGING_SITE / name
            if not link.exists():
                link.symlink_to(WEB / name, target_is_directory=True)
        for name in ("package.json", "tsconfig.json", "next.config.ts", "postcss.config.js"):
            shutil.copyfile(WEB / name, STAGING_SITE / name)
        subprocess.run(["npm", "run", "build", "--", "--webpack"], cwd=STAGING_SITE, env=env, check=True)
        (STAGING_SITE / ".next/studio-publishable-key").write_text(key)
        return
    check_built_settings(key)
    os.chdir(STAGING_SITE)
    os.execvpe("node", ["node", str(APP / "serve-studio.cjs")], {**env, "NODE_ENV": "production"})


if __name__ == "__main__":
    try:
        run(sys.argv[1])
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"Studio could not connect to Rafii staging. {error}")
