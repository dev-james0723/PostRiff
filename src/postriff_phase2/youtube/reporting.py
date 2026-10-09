"""Bounded official CSV ingestion with coverage, late corrections and authorized-data expiry."""
import csv
import io
import json
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from postriff_alpha.domain import AlphaError

NON_MONETARY_TYPES = frozenset(json.loads(Path(__file__).with_name('report-types.json').read_text())['nonMonetaryTypes'])
MAX_BYTES, MAX_ROWS = 32 * 1024**2, 50000  # explicit Rafii ingestion budget; larger files require a bulk runner


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(api, url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'youtubereporting.googleapis.com' or parsed.port not in (None, 443) or parsed.username or parsed.password or not parsed.path.startswith('/v1/media/') or parsed.fragment:
        raise AlphaError('YouTube returned an invalid official report download address.', 502)
    try:
        with build_opener(NoRedirect()).open(Request(url, headers={'Authorization': 'Bearer ' + api.provider.bearer(api.grant['accessToken'])}), timeout=25) as response:
            raw = response.read(MAX_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError):
        raise AlphaError('Official report download is unavailable; the reporting job was not recreated.', 503) from None
    if len(raw) > MAX_BYTES:
        raise AlphaError('This report exceeds Rafii’s 32 MB interactive ingestion budget; use a bulk ingestion runner.', 413)
    return raw


def ingest(service, workspace, connection, api, job_id, report_id, monetary_authorized=False, downloader=download, job=None):
    job = job or api.call('reporting.jobs.get', {'jobId': job_id})
    report_type = job.get('reportTypeId')
    if report_type not in NON_MONETARY_TYPES and not monetary_authorized:
        raise AlphaError('This report type is financial, system-managed or unclassified. Separate revenue authorization is required.', 403)
    report = api.call('reporting.jobs.reports.get', {'jobId': job_id, 'reportId': report_id})
    period = tuple(datetime.fromisoformat(report[k].replace('Z', '+00:00')) for k in ('startTime', 'endTime', 'createTime'))
    if period[0] >= period[1]:
        raise AlphaError('Official report coverage is invalid.', 502)
    with service.service.connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT report_created_at FROM public.pr_youtube_reporting_coverage WHERE workspace_id=%s AND connection_id=%s AND job_id=%s AND start_time=%s AND end_time=%s', (workspace, connection, job_id, period[0], period[1]))
        old = cur.fetchone()
    if old and old[0] >= period[2]:
        return {'source': 'YouTube Reporting API', 'reportId': report_id, 'coverage': report, 'alreadyIngested': True}
    raw = downloader(api, report['downloadUrl'])
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        columns = reader.fieldnames
        if not columns or len(columns) > 200 or any(len(x) > 100 for x in columns):
            raise ValueError()
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS or None in row or any(v is None for v in row.values()):
                raise ValueError()
            if row.get('channel_id') and row['channel_id'] != api.channel_id:
                raise AlphaError('Reporting data belongs to another channel; no data was stored.', 403)
            rows.append(row)
    except (UnicodeError, csv.Error, ValueError):
        raise AlphaError('This report exceeds the interactive row budget or is not a valid official CSV.', 413) from None
    data = {'reportTypeId': report_type, 'columns': columns, 'rows': rows, 'source': 'YouTube Reporting API', 'channelId': api.channel_id}
    with service.service.connection_factory() as db, db.cursor() as cur:
        cur.execute('INSERT INTO public.pr_youtube_reporting_coverage(workspace_id,connection_id,job_id,start_time,end_time,report_id,report_created_at,dataset) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(workspace_id,connection_id,job_id,start_time,end_time) DO UPDATE SET report_id=excluded.report_id,report_created_at=excluded.report_created_at,dataset=excluded.dataset,ingested_at=now() WHERE excluded.report_created_at>public.pr_youtube_reporting_coverage.report_created_at', (workspace, connection, job_id, period[0], period[1], report_id, period[2], json.dumps(data)))
    return {'source': 'YouTube Reporting API', 'reportId': report_id, 'rowCount': len(rows), 'coverage': {'startTime': report['startTime'], 'endTime': report['endTime']}, 'ingestedAt': service.clock(), 'replacedCorrection': bool(old), 'retentionDays': 30}
