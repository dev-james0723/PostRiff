"""Evaluate an operator-provided Radar release dataset locally, without network access.

PYTHONPATH=src python scripts/postriff_radar_evaluate.py evidence.json
Schema: {execution: 'real'|'synthetic', scans: [{id, topFive: [bool]*5,
actualUsdMicro: int|null, quotedUsdMicro: int}], weeklyUsers: [{id, createdDraft: bool}]}.
The execution provenance must be independently reviewed; this tool cannot attest it.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from postriff_phase2.radar.core import release_gate
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Provide one local evidence JSON file.')
    result=release_gate(json.loads(Path(sys.argv[1]).read_text()))
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['status']=='PASS' else 2)
