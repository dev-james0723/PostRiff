"""Validate operator-supplied redacted real E2E evidence; never fabricate qualification.
This is a structural validator, not proof of a Telegram round trip. Receipts/screenshots
must be reviewed before an operator installs the evidence file on the server.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from postriff_phase2.telegram.qualification import RELEASE_VERSION, DESTINATION_VERSION, proven, release_capabilities
parser=argparse.ArgumentParser();parser.add_argument('evidence');args=parser.parse_args()
p=Path(args.evidence)
if p.stat().st_size>65536:raise SystemExit('Evidence file too large')
data=json.loads(p.read_text())
if not isinstance(data,dict) or not data:raise SystemExit('No real destination or release evidence supplied')
def artifact_for(record):
 if not proven(record):raise SystemExit('Only passed cases with finite timestamps and evidence references can qualify')
 evidence_path=Path(record['evidenceRef'])
 if not evidence_path.is_file() or evidence_path.stat().st_size>524288:raise SystemExit('Missing or oversized reviewable evidence artifact')
 artifact=json.loads(evidence_path.read_text())
 if not isinstance(artifact,dict) or artifact.get('execution')!='telegram_real_e2e':raise SystemExit('Artifact is not real Telegram E2E')
 screenshot=artifact.get('screenshotRef')
 if not isinstance(screenshot,str) or not Path(screenshot).is_file():raise SystemExit('Reviewable screenshot required')
 return artifact
release=data.get('_release')
if release is not None:
 if not (release_capabilities(release,'bot') or release_capabilities(release,'business')):raise SystemExit('A reviewed current release and complete real A–D evidence are required')
 for flow,record in release['flows'].items():
  artifact=artifact_for(record)
  if flow not in ('A','B','C','D') or artifact.get('mandatoryFlow')!=flow:raise SystemExit('Mandatory-flow artifact mismatch')
 for case in release['cases']:
  artifact=artifact_for(case)
  if any(artifact.get(key)!=case.get(key) for key in ('botId','chatId','messageId','capability')):raise SystemExit('Release case artifact identity mismatch')
  if not artifact.get('redactedApiResponse'):raise SystemExit('Redacted real API response required')
for destination,evidence in data.items():
 if destination=='_release':continue
 if not isinstance(evidence,dict) or evidence.get('source')!='telegram_real_e2e' or type(evidence.get('botId')) is not int or evidence.get('qualificationVersion')!=DESTINATION_VERSION:raise SystemExit('Real bot identity/source/current qualification version required')
 if not evidence.get('cases'):raise SystemExit('No acceptance cases supplied')
 for c in evidence['cases']:
  if not proven(c) or type(c.get('messageId')) is not int or c['messageId']<=0:raise SystemExit('Only passed cases with Message IDs/timestamps can qualify')
  artifact=artifact_for(c)
  if artifact.get('execution')!='telegram_real_e2e' or artifact.get('botId')!=evidence['botId'] or str(artifact.get('chatId'))!=destination:raise SystemExit('Artifact identity/execution mismatch')
  if not artifact.get('redactedApiResponse') or not artifact.get('screenshotRef'):raise SystemExit('Redacted API response and screenshot required')
print(json.dumps({'structurallyValid':True,'reviewRequired':True,'destinations':len(data)-(1 if release else 0),'publicReleaseVersion':RELEASE_VERSION if release else None,'qualificationInstalled':False}))
