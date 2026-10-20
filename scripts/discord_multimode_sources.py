"""Exact-source supplement to the existing Discord provenance inventory; no IO effects beyond requested receipt."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from discord_capacity_sources import source_paths


def manifest(root):
    root = Path(root)
    paths = set(source_paths(root))
    paths.update(p.relative_to(root).as_posix() for p in (root / 'tests').glob('test_discord*.py') if p.is_file())
    paths.add('scripts/postriff_pg_suite.py')
    paths.update(p.relative_to(root).as_posix() for p in (root / 'web/src').rglob('*') if p.is_file() and p.suffix in ('.ts', '.tsx', '.json', '.css'))
    paths.update(p.relative_to(root).as_posix() for p in (root / 'web/tests').rglob('*') if p.is_file() and p.suffix in ('.cjs', '.mjs', '.json'))
    paths.update({'tests/test_discord_personal_account_contract.py', 'tests/test_discord_multimode.py', 'tests/test_discord_interactions.py',
        'tests/phase2/postgres_discord_multimode.py', 'tests/discord_ui_fixture.py',
        'scripts/discord_user_install_config.py', 'scripts/discord-multimode-validation-cloud.sh',
        'scripts/discord_multimode_sources.py', 'tests/test_discord_multimode_ci_wiring.py',
        '.github/workflows/discord-multimode-qualification.yml',
        'web/package-lock.json', 'web/tsconfig.json', 'web/next.config.ts',
        'AGENTS.md', 'CLAUDE.md', 'vercel.json'})
    files = {}
    for name in sorted(paths):
        path = root / name
        if not path.is_file() or path.is_symlink(): raise ValueError('Missing/nonregular source input: ' + name)
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'execution': 'dirty-owned-source', 'baseHead': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
            'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=root, text=True).strip(),
            'fingerprint': fingerprint, 'files': files}

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    target = Path(sys.argv[1])
    if target.resolve().parent != (root / 'docs/discord-personal-account-20261019/evidence').resolve():
        raise SystemExit('Only the owned evidence directory is accepted.')
    value = manifest(root); target.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'fingerprint': value['fingerprint'], 'sourceFiles': len(value['files']), 'baseHead': value['baseHead']}))
