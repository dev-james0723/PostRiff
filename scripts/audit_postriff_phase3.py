#!/usr/bin/env python3
"""Phase 3 receipt-only audit. Does not rewrite earlier phase evidence."""
from pathlib import Path
import difflib,hashlib,json,re
root=Path(__file__).resolve().parents[1];e=root/'docs/postriff-phase-3/evidence'
baseline=json.loads((e/'baseline.json').read_text())['files']
owned_existing={'src/postriff_alpha/server.py','studio/web/src/founder/FounderApp.tsx','studio/web/src/founder/types.ts'}
new=list((root/'src/postriff_phase3').glob('*.py'))+list((root/'integrations/postriff').glob('*.md'))+list((root/'tests/phase3').glob('*.py'))+[root/x for x in ['scripts/postriff_phase3.py','scripts/postriff_agent_tools.py','scripts/package_postriff_phase3.py','scripts/audit_postriff_phase3.py','tests/test_postriff_phase3.py','studio/web/tests/runtime-recovery.test.ts','studio/web/src/founder/RuntimePanel.tsx','studio/web/src/founder/runtime-state.ts','studio/web/src/founder/runtime.css','migrations/postriff/003_phase3_runtime.sql']]
new+=list((root/'desktop').glob('*.cjs'))+[root/'desktop/package.json',root/'desktop/package-lock.json',root/'desktop/windows-build.yml']+list((root/'desktop/tests').glob('*.cjs'))
patch=[];hashes={};concurrent=[];shared_concurrent=[]
for rel,before in baseline.items():
 p=root/rel
 if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()!=before and rel not in owned_existing:concurrent.append(rel)
for p in [root/rel for rel in sorted(owned_existing)]+sorted(new):
 rel=str(p.relative_to(root));hashes[rel]=hashlib.sha256(p.read_bytes()).hexdigest();old=e/'pre-phase3'/rel
 before_text=old.read_text() if old.is_file() else ''
 if rel=='studio/web/src/founder/FounderApp.tsx':
  before_text=p.read_text().replace('import RuntimePanel from "./RuntimePanel";\n','').replace('{state?.phase3 ? "PHASE 3 · LOCAL" : phase2 ? "PHASE 2 · LOCAL" : "FOUNDER ALPHA"}','{phase2 ? "PHASE 2 · LOCAL" : "FOUNDER ALPHA"}')
  before_text=''.join(line for line in before_text.splitlines(True) if '<RuntimePanel key={state.workspace.id}' not in line)
 elif rel=='studio/web/src/founder/types.ts':
  before_text=p.read_text().replace('  phase3?: import("./runtime-state").RuntimeState;\n','').replace('  runtimeResult?: Record<string,unknown>;\n','')
 if old.is_file() and before_text!=old.read_text():shared_concurrent.append(rel)
 patch.extend(difflib.unified_diff(before_text.splitlines(True),p.read_text().splitlines(True),fromfile='a/'+rel if old.is_file() else '/dev/null',tofile='b/'+rel))
(e/'source-diff.patch').write_text(''.join(patch))
app=root/'desktop/artifacts/PostRiff-darwin-arm64/PostRiff.app';files={}
for p in sorted(app.rglob('*')):
 if p.is_file():files[str(p.relative_to(app))]=hashlib.sha256(p.read_bytes()).hexdigest()
treehash=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
customer=app/'Contents/Resources/app'
assert set(p.name for p in customer.iterdir()) <= {'package.json','main.cjs','preload.cjs','boundary.cjs','bundle'}
assert not list(customer.rglob('.env*'))
assert not list(customer.rglob('*.sqlite3'))
assert not list(customer.rglob('device-vault.bin'))
neutral_unchanged=hashlib.sha256((root/'src/postriff_alpha/templates.py').read_bytes()).hexdigest()==baseline['src/postriff_alpha/templates.py']
assert neutral_unchanged
result={'status':'pass','scope':'owned Phase 3 sources and packaged allowlist','git':'validation_unavailable: no .git','ownedSourceHashes':hashes,'concurrentChangesOutsideOwnedScope':concurrent,'sharedFilesWithPreservedConcurrentHunks':shared_concurrent,'neutralTemplatesUnchanged':neutral_unchanged,'packageTreeSha256':treehash,'packageFiles':len(files),'packageRoot':str(app),'privateDataFilesInPackage':False}
(e/'source-and-package-audit.json').write_text(json.dumps(result,indent=2)+'\n');(e/'package-files.json').write_text(json.dumps(files,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('ownedSourceHashes','concurrentChangesOutsideOwnedScope')},indent=2))
