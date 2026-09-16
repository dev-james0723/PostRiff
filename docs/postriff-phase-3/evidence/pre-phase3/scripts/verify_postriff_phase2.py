"""Bounded source/artifact audit; never scans credentials or private user stores."""
import difflib
import hashlib
import json
import re
from pathlib import Path

root=Path(__file__).resolve().parents[1]
evidence=root/'docs/postriff-phase-2/evidence'
baseline=json.loads((evidence/'implementation-baseline.json').read_text())
changed=[]
patch=[]
for rel,before in baseline.items():
    current=root/rel
    if not current.is_file():continue
    actual=hashlib.sha256(current.read_bytes()).hexdigest()
    if actual!=before:
        changed.append(rel)
        old=evidence/'pre-phase2'/rel
        if old.is_file():patch.extend(difflib.unified_diff(old.read_text().splitlines(True),current.read_text().splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
newpaths=list((root/'src/postriff_phase2').glob('*.py'))+list((root/'migrations/postriff').glob('*.sql'))+[root/'scripts/postriff_phase2.py',root/'scripts/verify_postriff_phase2.py',root/'scripts/check_postriff_hosted_preflight.py',root/'scripts/validate_postriff_hosted_preview.py',root/'tests/test_postriff_phase2.py',root/'tests/test_postriff_content_types.py',root/'tests/test_postriff_phase2_hosted.py',root/'tests/test_postriff_hosted_deployment.py',root/'api/index.py',root/'requirements.txt',root/'.python-version',root/'.env.example',root/'.gitignore',root/'.vercelignore',root/'vercel.json']+list((root/'tests/phase2').glob('*'))+[root/'studio/web/src/founder/Phase2.tsx',root/'studio/web/src/founder/phase2-types.ts',root/'studio/web/src/founder/phase2.css',root/'studio/web/src/founder/ContentTypes.tsx',root/'studio/web/src/founder/content-type-types.ts',root/'studio/web/src/founder/content-types.css',root/'studio/web/src/founder/hosted-auth.ts',root/'studio/web/src/founder/AuthEntry.tsx',root/'studio/web/package.json']
for path in newpaths:
    if path.is_file():patch.extend(difflib.unified_diff([],path.read_text().splitlines(True),fromfile='/dev/null',tofile='b/'+str(path.relative_to(root))))
(evidence/'source-diff.patch').write_text(''.join(patch))
# The unchanged neutral templates are the only released skills in customer bundles.
assert hashlib.sha256((root/'src/postriff_alpha/templates.py').read_bytes()).hexdigest()==baseline['src/postriff_alpha/templates.py']
assert hashlib.sha256((root/'src/postriff_alpha/domain.py').read_bytes()).hexdigest()==baseline['src/postriff_alpha/domain.py']
assert hashlib.sha256((root/'src/postriff_alpha/auth.py').read_bytes()).hexdigest()==baseline['src/postriff_alpha/auth.py']
patterns={'private_skill_name':r'james-[a-z]+(?:-[a-z]+)+','private_home_path':r'/Users/[A-Za-z0-9_.-]+/','secret_key_literal':r'\b(?:sk-proj-|sk-ant-|sb_secret_)[A-Za-z0-9_-]{16,}'}
scanned=list((root/'studio/web/dist-alpha/assets').glob('*.js'))+list((root/'src/postriff_alpha').glob('*.py'))
findings=[]
for path in scanned:
    content=path.read_text()
    for name,pattern in patterns.items():
        if re.search(pattern,content):findings.append({'file':str(path.relative_to(root)),'pattern':name})
assert not findings,findings
broken=[];links=0
for doc in (root/'docs/postriff-phase-2').glob('*.md'):
    for target in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
        if target.startswith(('http:','https:','#')):continue
        target=target.split('#',1)[0].strip('<>')
        path=Path(target) if target.startswith('/') else doc.parent/target
        links+=1
        if not path.exists():broken.append({'document':doc.name,'target':target})
assert not broken,broken
result={'status':'pass','scope':'bounded local Phase 2 implementation and review artifacts','baselineFiles':len(baseline),'changedBaselineFiles':changed,'newImplementationFiles':[str(p.relative_to(root)) for p in newpaths if p.is_file()],'neutralTemplatesUnchanged':True,'alphaDomainAndAuthUnchanged':True,'scannedCustomerSourceOrBundleFiles':len(scanned),'credentialOrPrivateSkillPatternFindings':findings,'localDocumentationLinks':links,'brokenLinks':broken,'git':'validation_unavailable: installed source tree has no Git metadata','limitations':['No production security certification','No scan of private user stores or unrelated installed skills','Hosted package is prepared locally but no project is selected, configured, migrated or deployed','Live provider qualification remains incomplete']}
(evidence/'local-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'status':'pass','baselineFiles':len(baseline),'changedFiles':len(changed),'newFiles':len(newpaths),'checkedLinks':links},indent=2))
