"""Offline secret scan of release source. Output paths/types/hashes only, never matched values."""
import json
import hashlib
import re
from pathlib import Path
import sys
from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings
from consumer_ready_check import ROOT, OUT, fingerprint



# This precisely scoped exception accepts no credential-like string:
# the digest has to be an actual checksum of one of the two reviewed,
# locally vendored Google Fonts assets. Any change to bytes, size, file
# name, origin, field type, line, or manifest value fails closed.
_FONT_MANIFEST = 'web/src/components/themes/fonts/SOURCE.json'
_FONT_SOURCES = {
    'Merriweather.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/merriweather/Merriweather%5Bopsz%2Cwdth%2Cwght%5D.ttf',
    'OFL.txt': 'https://raw.githubusercontent.com/google/fonts/main/ofl/merriweather/OFL.txt',
}


def verified_font_checksum(finding):
    if finding.get('path') != _FONT_MANIFEST or finding.get('type') != 'Hex High Entropy String':
        return False
    manifest_path = ROOT / _FONT_MANIFEST
    try:
        line_number = finding.get('line')
        lines = manifest_path.read_text().splitlines()
        if not isinstance(line_number, int) or not 1 <= line_number <= len(lines):
            return False
        matched = re.fullmatch(r'\s*"sha256": "([a-f0-9]{64})",?\s*', lines[line_number - 1])
        if not matched:
            return False
        digest = matched.group(1)
        manifest = json.loads(manifest_path.read_text())
        records = manifest.get('files', [])
        if not isinstance(records, list) or len(records) != 2:
            return False
        matches = [row for row in records if isinstance(row, dict) and row.get('sha256') == digest]
        if len(matches) != 1:
            return False
        entry = matches[0]
        filename = entry.get('name')
        if filename not in _FONT_SOURCES or entry.get('source') != _FONT_SOURCES[filename]:
            return False
        file = manifest_path.parent / filename
        if file.is_symlink() or not file.is_file() or file.stat().st_size != entry.get('bytes'):
            return False
        if file.stat().st_size > 6 * 1024 * 1024:
            return False
        return hashlib.sha256(file.read_bytes()).hexdigest() == digest
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False

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
    # Cloud-generated OpenUI asset manifests carry sha256 digests of the component library and prompts (rafii-genui/1) that
    # change on every regeneration. Accept only a 64-hex value on a libraryHash/promptHash line (or a bare digest inside the
    # compatibleLibraryHashes array) in exactly these two generated files; every other string there is still scanned.
    generated_manifests={'src/postriff_phase2/agent_runtime_v2/generated/openui-assets.json','web/src/features/agent/generative-ui/generated/openui-assets.json'}
    def generated_digest(finding):
        if finding['path'] not in generated_manifests or finding['type']!='Hex High Entropy String':
            return False
        lines=(ROOT/finding['path']).read_text().splitlines()
        if not 0 < finding['line'] <= len(lines):
            return False
        line=lines[finding['line']-1]
        return bool(re.fullmatch(r'\s*"(libraryHash|promptHash)": "[a-f0-9]{64}",?\s*',line) or re.fullmatch(r'\s*"[a-f0-9]{64}",?\s*',line))
    def reviewed(finding):
        if verified_font_checksum(finding):
            return True
        if generated_digest(finding):
            return True
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
