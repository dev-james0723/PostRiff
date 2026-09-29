"""Build an allowlisted deployment candidate for a SEPARATE rafii-control project.

Never loads .env, discovers credentials, links projects, deploys or changes the consumer
configuration. The new output directory is a reviewable artifact with source hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
PACK='docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2'
REUSED=(
    'src/postriff_phase2/__init__.py','src/postriff_phase2/locales.py','src/postriff_phase2/locale_catalogue.json',
    'src/postriff_phase2/hosted_identity.py','src/postriff_phase2/provider_candidates.py','src/postriff_phase2/contracts.py',
    'src/postriff_phase2/agent_runtime_v2/__init__.py','src/postriff_phase2/agent_runtime_v2/contracts.py',
    'src/postriff_alpha/__init__.py','src/postriff_alpha/domain.py','src/postriff_alpha/generation.py',
    'src/postriff_alpha/templates.py','src/postriff_alpha/profiles.py','src/postriff_alpha/learning.py','src/postriff_alpha/visuals.py',
    'web/src/styles/rafii.css',
)


def package(output):
    output=Path(output).resolve()
    if output.exists():raise ValueError('Use a fresh output directory; no overwrite/cleanup is performed')
    if output==ROOT or output in ROOT.parents:raise ValueError('Output must be a fresh candidate directory')
    output.mkdir(parents=True)
    files=[ROOT/file for file in REUSED]+[ROOT/'api/control.py']
    files.extend((ROOT/'src/rafii_control').glob('*.py'))
    for path in (ROOT/'control-web').rglob('*'):
        relative=path.relative_to(ROOT/'control-web')
        if any(part in ('node_modules','.next','tests') or part.startswith('.env') for part in relative.parts):continue
        if path.is_file() and not path.is_symlink() and path.suffix in ('.ts','.tsx','.mjs','.css','.json'):files.append(path)
    for directory in ('catalogs','contracts'):
        files.extend(path for path in (ROOT/PACK/directory).glob('*') if path.suffix in ('.json','.yaml'))
    manifest={}
    for source in sorted(set(files)):
        name=str(source.relative_to(ROOT))
        target=output/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        manifest[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    for source,name in (('requirements-control.txt','requirements.txt'),('vercel.control.json','vercel.json'),('.python-version','.python-version'),('.node-version','.node-version')):
        shutil.copyfile(ROOT/source,output/name)
        manifest[name]=hashlib.sha256((output/name).read_bytes()).hexdigest()
    (output/'source-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps({'execution':'local deployment candidate only','files':len(package(args.output)),'output':str(Path(args.output).resolve())}))
