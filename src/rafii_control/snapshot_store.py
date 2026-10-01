"""Immutable LOCAL manual metadata admission; never mounted as an HTTP writer."""
import hashlib
import json
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .auth import ControlError
from .investigations import validate_capture


def import_snapshot(factory, capture, *, admit=False):
    normalized = validate_capture(capture, admit=admit)
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    with factory() as con:
        con.row_factory = dict_row
        with con.transaction():
            role = con.execute('select current_user as name,rolsuper,rolbypassrls from pg_roles where rolname=current_user').fetchone()
            if role['name'] != 'rafii_control_ingest' or role['rolsuper'] or role['rolbypassrls']:
                raise ControlError('SCOPE_DENIED')
            con.execute("set local statement_timeout='5s'")
            con.execute("select set_config('rafii_control.environment','local',true)")
            inserted = con.execute(
                'insert into rafii_control.github_check_snapshots(id,environment,source_request_id,exact_sha,provenance,observed_at,payload_digest,payload) values(%s,\'local\',%s,%s,%s,%s,%s,%s) on conflict do nothing returning id',
                (normalized['captureId'], normalized['requestId'], normalized['exactSha'], normalized['provenance'], normalized['observedAt'], digest, Jsonb(normalized))).fetchone()
            if not inserted:
                old = con.execute('select payload_digest from rafii_control.github_check_snapshots where id=%s', (normalized['captureId'],)).fetchone()
                if not old or old['payload_digest'] != digest:
                    raise ControlError('IDEMPOTENCY_CONFLICT', 409)
            return normalized['captureId'], bool(inserted)
