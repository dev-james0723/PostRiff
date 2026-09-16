"""Like-for-like descriptive analysis; no audience surveillance or causal claims."""
from fractions import Fraction
from .execution import payload_hash
import json
from pathlib import Path
import sqlite3
from contextlib import closing


class AnalyticsStore:
    """Append-only observation identity with immutable content, not user profiling."""
    def __init__(self,path):
        self.path=Path(path)
        if self.path.is_symlink():
            raise ValueError('symlink_store')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS analytics(id TEXT PRIMARY KEY, body TEXT, hash TEXT)')
        self.path.chmod(0o600)

    def record(self,observation_id,row):
        required={'job_id','verification','channel','native_format_id','language','window_seconds','metrics','template_hash','confounders'}
        if set(row)!=required or not observation_id or not row['metrics']:
            raise ValueError('observation_fields_required')
        if type(row['window_seconds']) is not int or row['window_seconds']<=0:
            raise ValueError('measurement_window_required')
        if not set(row['metrics'])<={'views','saves','shares','replies','link_clicks','watch_seconds','completed_views'}:
            raise ValueError('public_aggregate_metrics_only')
        for metric in row['metrics']:
            compare_observations([row],metric=metric)
        digest=payload_hash(row)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT hash FROM analytics WHERE id=?',(observation_id,)).fetchone()
            if existing:
                if existing[0]!=digest:
                    raise ValueError('immutable_observation')
                return
            db.execute('INSERT INTO analytics VALUES(?,?,?)',(observation_id,json.dumps(row,sort_keys=True),digest))

    def get(self,observation_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            row=db.execute('SELECT body,hash FROM analytics WHERE id=?',(observation_id,)).fetchone()
        if not row:
            raise ValueError('observation_not_found')
        body=json.loads(row[0])
        if payload_hash(body)!=row[1]:
            raise ValueError('stored_observation_drift')
        return body

def compare_observations(rows, *, metric):
    if not rows or not metric:
        raise ValueError('observations_required')
    cohorts = {(r['channel'], r['native_format_id'], r['language'], r['window_seconds'], r['template_hash']) for r in rows}
    if len(cohorts) != 1:
        raise ValueError('incomparable_cohorts')
    if len({r['job_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_post_observation')
    values = []
    for row in rows:
        if row['verification'] != 'verified_published':
            raise ValueError('unverified_publication')
        value = row['metrics'].get(metric)
        if value is not None:
            if type(value) is not int or value < 0:
                raise ValueError('invalid_metric')
            values.append(value)
    return {'interpretation':'observation_only', 'sample_size':len(rows),
            'measured_sample_size':len(values), 'missing_sample_size':len(rows)-len(values),
            'mean':str(Fraction(sum(values),len(values))) if values else None,
            'causality_established':False, 'confounders':sorted({x for r in rows for x in r['confounders']}),
            'evidence_hash':payload_hash({'observations':rows,'metric':metric}),
            'next_action':'review_repeated_pattern' if len(values)>=3 else 'collect_comparable_observations'}
