"""Import one reviewed capture into the caller's disposable LOCAL database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from rafii_control.auth import ControlError
from rafii_control.snapshot_store import import_snapshot
from rafii_control.store import connection_factory


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('capture')
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--admit-read-only',action='store_true')
    args=parser.parse_args()
    if os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'):
        raise ControlError('SCOPE_DENIED')
    dsn=os.environ.get('RAFII_CONTROL_TEST_DSN','')
    if not dsn.startswith('host=127.0.0.1 port='):
        raise ControlError('SCOPE_DENIED')
    file=Path(args.capture)
    if file.stat().st_size>131072:raise ControlError('BUDGET_EXCEEDED',400)
    raw=file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.expected_sha256:
        raise ControlError('IDEMPOTENCY_CONFLICT',409)
    capture=json.loads(raw)
    identity,inserted=import_snapshot(connection_factory(dsn,'rafii_control_ingest','local'),capture,admit=args.admit_read_only)
    print(json.dumps({'captureId':identity,'inserted':inserted,'environment':'local','hostedExecution':False}))


if __name__=='__main__':
    try:main()
    except Exception:
        print('SOURCE_UNAVAILABLE: local capture import failed; no private input is printed')
        raise SystemExit(1)
