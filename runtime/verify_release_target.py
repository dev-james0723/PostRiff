"""Validate release bindings before build-time storage or other backend access."""
import json
import os
from pathlib import Path
import runpy


def verify(values):
    guard=runpy.run_path(str(Path(__file__).resolve().parents[1]/'src/postriff_phase2/deployment.py'))
    guard['isolated_environment'](values)
    return guard['production_binding_proof'](values)


def main():
    try:
        proof=verify(os.environ)
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({'status':'failed','reason':'Release binding guard rejected configuration before backend access.'}))
        return 1
    print(json.dumps({'status':'passed','execution':'build_binding_check','productionBindings':proof}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
