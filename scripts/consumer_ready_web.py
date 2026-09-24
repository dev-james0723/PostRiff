"""Credential-free isolated web source copy and command runner, for local checks only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'.codex/consumer-ready/web'

def main():
    args=sys.argv[1:]
    if args and args[0]=='--prepare':
        args=args[1:]
        def ignored(directory,names):
            return [n for n in names if n.startswith(('.env','.next')) or n in ('node_modules','.git','tsconfig.tsbuildinfo')]
        shutil.copytree(ROOT/'web',DEST,dirs_exist_ok=True,ignore=ignored)
    if not args: return 0
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','TERM','CI')}
    env.update(NEXT_PUBLIC_APP_URL='http://127.0.0.1:4439',NEXT_PUBLIC_SUPABASE_URL='',NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='',NEXT_PUBLIC_SENTRY_DISABLED='1',NEXT_TELEMETRY_DISABLED='1',POSTRIFF_API_ORIGIN='http://127.0.0.1:4438',POSTRIFF_DEV_SSR='1',LC_ALL='C')
    return subprocess.call(args,cwd=DEST,env=env)
if __name__=='__main__':sys.exit(main())
