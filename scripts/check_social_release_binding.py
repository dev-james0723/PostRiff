#!/usr/bin/env python3
"""Secret-safe release/build guard. This script never connects to any backend."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from postriff_phase2.social_release import reject_forbidden_bindings, require_production_binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-production', action='store_true')
    args = parser.parse_args()
    values = dict(os.environ)
    manifest = ROOT / '.vercel/project.json'
    if manifest.is_file():
        try:
            project = json.loads(manifest.read_text()).get('projectId')
        except (OSError, ValueError):
            raise SystemExit('Issue #179: unreadable Vercel project binding.')
        if values.get('VERCEL_PROJECT_ID') and project != values['VERCEL_PROJECT_ID']:
            raise SystemExit('Issue #179: CLI project and runtime project bindings differ.')
        values['VERCEL_PROJECT_ID'] = project
    try:
        reject_forbidden_bindings(values)
        if args.require_production or values.get('VERCEL_ENV') in ('production', 'preview'):
            receipt = require_production_binding(values)
        else:
            receipt = {'status': 'PASS_LOCAL_OR_DISPOSABLE_CI', 'productionBindingVerified': False}
    except ValueError as error:
        raise SystemExit(str(error))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
