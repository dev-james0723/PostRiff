"""Offline secret scan of release source. Output paths/types/hashes only, never matched values."""
import json
import hashlib
import re
from pathlib import Path
import sys
from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings
from consumer_ready_check import ROOT, OUT, fingerprint


def main():
    manifest=fingerprint(); collection=SecretsCollection()
    paths=list(manifest['files']) + ['.env.example']
    with default_settings():
        for name in paths:
            path=ROOT/name
            if path.suffix.lower() in ('.png','.jpg','.jpeg','.woff','.woff2','.ico','.mp4','.pdf','.zip'):
                continue
            collection.scan_file(str(path))
    findings=[]
    for name, items in collection.json().items():
        for item in items:
            findings.append({'path':str(Path(name).relative_to(ROOT)), 'line':item['line_number'], 'type':item['type'], 'hash':item['hashed_secret']})
    allow_path=ROOT/'docs/consumer-ready/secret-allowlist.json'
    allowed=json.loads(allow_path.read_text()) if allow_path.exists() else []
    # Hash metadata is not a secret. Permit only this validated field in this exact file;
    # reasons and paths remain scanned, and no directory/file gets a blanket exemption.
    for entry in allowed:
        if set(entry) != {'path','hash','reason'} or not all(isinstance(entry[k],str) and entry[k] for k in entry) or not re.fullmatch(r'[a-f0-9]{40}',entry['hash']):
            raise ValueError('Malformed secret allowlist entry')
    metadata_hashes={hashlib.sha1(a['hash'].encode()).hexdigest() for a in allowed}
    metadata_lines=allow_path.read_text().splitlines() if allow_path.exists() else []
    def reviewed(finding):
        if finding['path']=='docs/consumer-ready/secret-allowlist.json' and finding['type']=='Hex High Entropy String' and finding['hash'] in metadata_hashes:
            line=metadata_lines[finding['line']-1]
            if re.fullmatch(r'\s*"hash": "[a-f0-9]{40}",?\s*',line):
                return True
        return any(a['path']==finding['path'] and a['hash']==finding['hash'] and a.get('reason') for a in allowed)
    unexpected=[f for f in findings if not reviewed(f)]
    result={'execution':'offline source scan; no credential verification or network calls', 'source':manifest['sha256'], 'files':len(paths), 'findings':findings, 'unexpected':unexpected, 'status':'FAIL' if unexpected else 'PASS'}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'secret-scan.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'files':len(paths),'findings':len(findings),'unexpected':unexpected}))
    return int(bool(unexpected))
if __name__=='__main__':sys.exit(main())
