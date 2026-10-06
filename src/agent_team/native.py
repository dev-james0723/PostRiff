"""Reuse Conductor's read-only Codex transport; never mistake its view for writer ownership."""
from datetime import datetime,timezone
import hashlib
import importlib.util
from pathlib import Path
from .events import Event,canonical
from .observers import ObservationBatch
from .collector import coverage_event


def installed_read_client():
    source=Path(__file__).resolve().parents[1]/'vendor/conductor/daily_conductor.py'
    spec=importlib.util.spec_from_file_location('conductor_read_adapter',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.CodexReadClient()


def collect_codex_metadata(journal,workspace,*,project_id=None,client_factory=installed_read_client):
    root=Path(workspace).resolve(strict=True)
    if not root.is_dir():raise ValueError('exact_workspace_required')
    observed=datetime.now(timezone.utc).isoformat();client=None;events=[];gaps=[]
    try:
        client=client_factory()
        r=client.rpc('thread/list',{'limit':12,'sortKey':'updated_at','cwd':str(root),'useStateDbOnly':True,
            'sourceKinds':['cli','vscode','exec','appServer','unknown']})
        observed=datetime.now(timezone.utc).isoformat()
        rows=r.get('data',[])
        if not isinstance(rows,list) or len(rows)>12:raise ValueError('codex_list_schema')
        if r.get('nextCursor'):gaps.append('thread_page_limit')
        for row in rows:
            if not isinstance(row,dict) or not row.get('id') or row.get('cwd')!=str(root):
                gaps.append('exact_workspace_mismatch');continue
            updated=row.get('updatedAt')
            if type(updated) not in (int,float):gaps.append('thread_timestamp_unknown');continue
            stamp=datetime.fromtimestamp(updated,timezone.utc).isoformat()
            status=row.get('status') or {};state=status.get('type','unknown') if isinstance(status,dict) else 'unknown'
            source_id=hashlib.sha256(str(row['id']).encode()).hexdigest()
            payload={'kind':'thread_metadata','reportedState':str(state)[:64],'sourceFreshAt':stamp,'origin':'read_only_app_server_view'}
            revision=hashlib.sha256(canonical([row['id'],updated,payload]).encode()).hexdigest()
            events.append(Event('codex',source_id,revision,stamp,observed,payload,project_id=project_id or hashlib.sha256(str(root).encode()).hexdigest()))
        added=journal.ingest(events)
        status='partial' if gaps else 'ok'
    except (OSError,ValueError,TimeoutError,KeyError,OverflowError):
        events=[];added=0;status='unavailable';gaps=['codex_metadata_query_failed']
    finally:
        if client:client.close()
    batch=ObservationBatch(status,(),gaps=tuple(gaps),scanned=len(events),complete=False)
    added+=journal.ingest([coverage_event('codex',batch,observed,observed,observed)])
    return {'executionState':'real_native_read_only','status':status,'observations':len(events),'added':added,
            'gaps':gaps,'writerOwnership':'unproven','nativeRecovery':'not_requested'}
