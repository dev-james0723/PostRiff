"""Validate release bindings before build-time storage or other backend access."""
import json
import os
from pathlib import Path
import runpy
from urllib.parse import urlparse, parse_qs, unquote
import re


def verify(values):
    guard=runpy.run_path(str(Path(__file__).resolve().parents[1]/'src/postriff_phase2/deployment.py'))
    guard['isolated_environment'](values)
    return guard['production_binding_proof'](values)


def verify_source(values):
    stamp_module = runpy.run_path(str(Path(__file__).resolve().parent / 'stamp_release_source.py'))
    return stamp_module['build_source_proof'](values)


def binding_diagnostics(values):
    """Only fixed boolean release-identity checks; never print supplied values."""
    ref='buoyhkbodnhzngaotoel'
    try:
        dsn=urlparse(values.get('POSTRIFF_DATABASE_URL',''))
        username=unquote(dsn.username or '')
        host=dsn.hostname or ''
        direct=host=='db.'+ref+'.supabase.co' and username=='postgres'
        pooled=bool(re.fullmatch(r'[a-z0-9.-]+\.pooler\.supabase\.com',host)) and username=='postgres.'+ref
        db=dsn.scheme in ('postgres','postgresql') and (direct or pooled) and parse_qs(dsn.query).get('sslmode') in (['require'],['verify-full'])
    except (ValueError,TypeError,AttributeError):
        db=False
    return {
        'project_matches':values.get('VERCEL_PROJECT_ID')=='prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L',
        'database_binding_verified':bool(db),
        'supabase_server_matches':str(values.get('POSTRIFF_SUPABASE_URL','')).rstrip('/')=='https://'+ref+'.supabase.co',
        'supabase_public_matches':str(values.get('NEXT_PUBLIC_SUPABASE_URL','')).rstrip('/')=='https://'+ref+'.supabase.co',
        'production_ref_matches':values.get('POSTRIFF_PRODUCTION_PROJECT_REF')==ref,
        'public_origin_matches':str(values.get('POSTRIFF_PUBLIC_BASE_URL','')).rstrip('/')=='https://rafii.io',
        'api_origin_empty':not bool(values.get('POSTRIFF_API_ORIGIN')),
    }


SAFE_WITNESS_PATHS = (
    'api/index.py', 'requirements.txt', 'runtime/stamp_release_source.py',
    'runtime/verify_release_target.py', 'src/postriff_phase2/deployment.py',
    'src/postriff_phase2/hosted_app.py', 'src/postriff_phase2/hosted_worker.py',
    'src/postriff_phase2/linkedin_fleet.py', 'src/postriff_phase2/official_social.py',
    'src/postriff_phase2/providers.py', 'src/postriff_phase2/release_provenance.py',
    'vercel.json',
)


def source_witness_diagnostics():
    """Only fixed filenames and booleans; never reveal file content or secrets."""
    import hashlib
    root=Path(__file__).resolve().parents[1]
    try:
        from postriff_phase2.release_provenance import read_regular, witness_bytes, MANIFEST_PATH
        manifest=json.loads(read_regular(root,MANIFEST_PATH,65536))
        files=manifest.get('files',{})
        if not isinstance(files,dict):raise ValueError('Invalid receipt')
        return {name:bool(isinstance(files.get(name),str) and
                    hashlib.sha256(witness_bytes(root,name,manifest)).hexdigest()==files[name])
                if name in files else False for name in SAFE_WITNESS_PATHS}
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,ImportError):
        return {name:False for name in SAFE_WITNESS_PATHS}



def source_config_diagnostics(root: Path) -> dict:
    """Fixed-name booleans only, never config values or personal environment."""
    import base64
    from postriff_phase2.release_provenance import read_regular, MANIFEST_PATH, _unique_object, approved_builder_transform
    keys=('$schema','services','rewrites','headers','crons','git')
    possible=('version','framework','buildCommand','routes','functions','env',
              'projectSettings','outputDirectory','regions','builds','name',
              'installCommand','ignoreCommand','cleanUrls','trailingSlash','scope')
    empty={**{k:False for k in keys},'rootKeysEqual':False,
           'semanticallyEqual':False,'approvedBuilderTransform':False,
           **{'added_'+k:False for k in possible},'addedOther':False}
    try:
        root=Path(root)
        receipt=json.loads(read_regular(root, MANIFEST_PATH, 65536), object_pairs_hook=_unique_object)
        encoded=receipt['vercelConfigSourceBase64']
        if not isinstance(encoded,str) or len(encoded)>16*1024*1024:
            return empty
        source=json.loads(base64.b64decode(encoded,validate=True), object_pairs_hook=_unique_object)
        active=json.loads(read_regular(root, 'vercel.json', 8*1024*1024), object_pairs_hook=_unique_object)
        if type(source) is not dict or type(active) is not dict:
            return empty
        added=set(active)-set(source)
        return {**{k:source.get(k)==active.get(k) for k in keys},
                'rootKeysEqual':set(source)==set(active),
                'semanticallyEqual':source==active,
                'approvedBuilderTransform':approved_builder_transform(source,active),
                **{'added_'+k:k in added for k in possible},
                'addedOther':bool(added-set(possible))}
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,RuntimeError,RecursionError,base64.binascii.Error):
        return empty


def source_diagnostics(values):
    """Bounded, redacted source-proof state. Never infer permission to build."""
    root=Path(__file__).resolve().parents[1]
    status='unavailable'
    revision=None
    try:
        module=runpy.run_path(str(root/'src/postriff_phase2/release_provenance.py'))
        proof=module['release_source_proof'](values,root=root)
        allowed=('verified','missing','metadata_only','metadata_conflict','witness_mismatch','invalid_receipt','unavailable')
        if isinstance(proof,dict):
            if proof.get('status') in allowed:
                status=proof['status']
            revision=proof.get('sourceRevision')
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,ImportError):
        pass
    supplied=values.get('VERCEL_GIT_COMMIT_SHA')
    present=isinstance(supplied,str) and bool(supplied)
    return {
        'receiptStatus':status,
        'gitPathPresent':os.path.lexists(root/'.git'),
        'gitMetadataPresent':present,
        'gitMetadataMatchesReceipt':bool(present and isinstance(revision,str) and supplied==revision),
        'witnessMatches':source_witness_diagnostics(),
        'configSemantics':source_config_diagnostics(root),
    }


def main():
    try:
        proof=verify(os.environ)
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({'status':'failed','failureStage':'binding','checks':binding_diagnostics(os.environ)}))
        return 1
    try:
        source=verify_source(os.environ)
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({'status':'failed','failureStage':'source','checks':source_diagnostics(os.environ)}))
        return 1
    print(json.dumps({'status':'passed','execution':'build_binding_check','productionBindings':proof,'sourceProvenance':source}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
