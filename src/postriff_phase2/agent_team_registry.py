"""Verifier-owned projection of the native recovery registry.

This stores authority already verified by the owning Kynlo/ORC adapter. It does
not create a local mission, authorize a model call, or attest a native guard.
Ordinary observer ingress cannot write here. Every question rechecks the exact
persisted registration, append-only execution lineage and fresh owner attestation.
"""
from dataclasses import asdict, fields
import json
import math
import uuid

from postriff_alpha.domain import AlphaError
from agent_team.recovery import ExecutionBinding, NativeOwner, RecoveryBlocked, Registration
from .agent_team_decision import build_question, digest, invalid

TABLE='public.pr_agent_team_mission_registry'
TUPLES=('acceptance_criteria','side_effect_ledger_refs','descendant_refs','background_refs','ci_refs')
ATTESTATION_FIELDS={'schemaVersion','source','evidenceRef','nativeGuardRef','nativeGuardVerified','observedAt',
                    'registrationSha256','executionSha256','authorizationSha256','owner'}
PROJECTION_FIELDS={'schemaVersion','actorId','workspaceId','registration','registrationSha256',
                   'execution','executionSha256','nativeAttestation'}
COLUMNS=('actor_id::text,workspace_id::text,registration_sha256,execution_sha256,ordinal,'
         'registration_document,execution_document,attestation_document,attestation_sha256')


def _typed(document,kind):
    if not isinstance(document,dict) or set(document)!={f.name for f in fields(kind)}:raise invalid('decision_registry_document_invalid')
    data=dict(document)
    owner=data.get('owner')
    if not isinstance(owner,dict) or set(owner)!={f.name for f in fields(NativeOwner)}:raise invalid('decision_registry_owner_invalid')
    data['owner']=NativeOwner(**owner)
    for name in TUPLES:
        if name in data:
            if not isinstance(data[name],list):raise invalid('decision_registry_document_invalid')
            data[name]=tuple(data[name])
    try:
        result=kind(**data)
        if isinstance(result,Registration):result.validate()
        return result
    except (RecoveryBlocked,ValueError,TypeError,AttributeError):raise invalid('decision_registry_document_invalid') from None


def validate_projection(document,*,actor_id,workspace_id,now):
    if not isinstance(document,dict) or set(document)!=PROJECTION_FIELDS or type(document['schemaVersion']) is not int or document['schemaVersion']!=1:raise invalid('decision_registry_document_invalid')
    if document['actorId']!=actor_id or document['workspaceId']!=workspace_id:raise invalid('decision_registry_principal_mismatch')
    try:
        if str(uuid.UUID(actor_id))!=actor_id or str(uuid.UUID(workspace_id))!=workspace_id:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise invalid('decision_registry_principal_mismatch') from None
    registration=_typed(document['registration'],Registration)
    execution=_typed(document['execution'],ExecutionBinding)
    try:execution.runtime_registration(registration)
    except (RecoveryBlocked,ValueError,TypeError,AttributeError):raise invalid('decision_registry_execution_invalid') from None
    if (registration.fingerprint,execution.fingerprint)!=(document['registrationSha256'],document['executionSha256']):raise invalid('decision_registry_digest_mismatch')
    attestation=document['nativeAttestation']
    if not isinstance(attestation,dict) or set(attestation)!=ATTESTATION_FIELDS:raise invalid('decision_registry_attestation_invalid')
    if type(attestation['schemaVersion']) is not int or attestation['schemaVersion']!=1 or attestation['source']!='kynlo_orc_owner' or attestation['nativeGuardVerified'] is not True:raise invalid('decision_registry_guard_unverified')
    for name in ('evidenceRef','nativeGuardRef'):
        if not isinstance(attestation[name],str) or not 1<=len(attestation[name])<=2048 or '\0' in attestation[name]:raise invalid('decision_registry_attestation_invalid')
    if (attestation['registrationSha256'],attestation['executionSha256'],attestation['authorizationSha256'],attestation['owner'])!=(registration.fingerprint,execution.fingerprint,registration.authorization_sha256,asdict(execution.owner)):raise invalid('decision_registry_attestation_mismatch')
    observed=attestation['observedAt']
    if type(now) not in (int,float) or not math.isfinite(now) or type(observed) not in (int,float) or not math.isfinite(observed) or not 0<=now-observed<=30:raise invalid('decision_registry_attestation_stale')
    return registration,execution,attestation


class CloudMissionRegistry:
    def __init__(self,connection_factory,actor_id,workspace_id,clock):
        self.connection_factory=connection_factory;self.actor_id=actor_id;self.workspace_id=workspace_id;self.clock=clock

    def _decode(self,row):
        document={'schemaVersion':1,'actorId':row[0],'workspaceId':row[1],'registrationSha256':row[2],
                  'executionSha256':row[3],'registration':row[5],'execution':row[6],'nativeAttestation':row[7]}
        registration,execution,attestation=validate_projection(document,actor_id=self.actor_id,workspace_id=self.workspace_id,now=self.clock())
        if execution.ordinal!=row[4] or digest(attestation)!=row[8]:raise invalid('decision_registry_digest_mismatch')
        return registration,execution

    def put(self,document):
        registration,execution,attestation=validate_projection(document,actor_id=self.actor_id,workspace_id=self.workspace_id,now=self.clock())
        # Origin must be the canonical RecoveryStore registration binding.
        if execution.ordinal==0:
            origin=ExecutionBinding(registration.mission_id,registration.fingerprint,0,None,registration.native_session_id,
                registration.engine,registration.owner,registration.descendant_refs,registration.background_refs,
                registration.ci_refs,None,None,0,registration.authorization_ref,0.0)
            if execution.fingerprint!=origin.fingerprint:raise invalid('decision_registry_origin_invalid')
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('team-registry:'+registration.mission_id,))
            cur.execute('SELECT '+COLUMNS+' FROM '+TABLE+' WHERE mission_id=%s ORDER BY ordinal DESC,observed_at DESC LIMIT 1',(registration.mission_id,))
            old=cur.fetchone()
            if old:
                if (old[0],old[1],old[2])!=(self.actor_id,self.workspace_id,registration.fingerprint):raise invalid('decision_registration_changed')
                if execution.ordinal==old[4]:
                    if execution.fingerprint!=old[3]:raise invalid('decision_registry_lineage_conflict')
                elif execution.ordinal!=old[4]+1 or execution.predecessor_sha256!=old[3]:raise invalid('decision_registry_lineage_conflict')
            elif execution.ordinal!=0:raise invalid('decision_registry_origin_required')
            attestation_hash=digest(attestation)
            cur.execute('INSERT INTO '+TABLE+'(mission_id,actor_id,workspace_id,registration_sha256,execution_sha256,ordinal,registration_document,execution_document,attestation_document,attestation_sha256,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,to_timestamp(%s)) ON CONFLICT(mission_id,attestation_sha256) DO NOTHING RETURNING attestation_sha256',
                (registration.mission_id,self.actor_id,self.workspace_id,registration.fingerprint,execution.fingerprint,execution.ordinal,
                 json.dumps(asdict(registration)),json.dumps(asdict(execution)),json.dumps(attestation),attestation_hash,attestation['observedAt']))
            created=bool(cur.fetchone())
            cur.execute('SELECT '+COLUMNS+' FROM '+TABLE+' WHERE mission_id=%s AND attestation_sha256=%s',(registration.mission_id,attestation_hash))
            persisted=cur.fetchone()
            if not persisted or self._decode(persisted)!=(registration,execution):raise invalid('decision_registry_projection_conflict')
            db.commit()
        return {'state':'registered','missionId':registration.mission_id,'registrationSha256':registration.fingerprint,
                'executionSha256':execution.fingerprint,'attestationSha256':attestation_hash,'replayed':not created,
                'nativeExecutionState':'not_dispatched'}

    def current_execution(self,registration):
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('SELECT '+COLUMNS+' FROM '+TABLE+' WHERE mission_id=%s AND actor_id=%s AND workspace_id=%s ORDER BY ordinal DESC,observed_at DESC LIMIT 1',
                        (registration.mission_id,self.actor_id,self.workspace_id))
            row=cur.fetchone()
        if not row:raise invalid('decision_registration_unavailable')
        stored,execution=self._decode(row)
        if stored.fingerprint!=registration.fingerprint:raise invalid('decision_registration_changed')
        return execution

    def for_report(self,document,mission_id=None):
        missions=sorted({entry.get('missionId') for entry in document.get('evidence',[]) if isinstance(entry,dict) and entry.get('missionId')})
        if mission_id is not None:
            if mission_id not in missions:raise invalid('decision_registry_report_evidence_required')
            missions=[mission_id]
        if not missions:raise invalid('decision_registry_report_evidence_required')
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('SELECT DISTINCT mission_id FROM '+TABLE+' WHERE mission_id=ANY(%s) AND actor_id=%s AND workspace_id=%s LIMIT 2',
                        (missions,self.actor_id,self.workspace_id))
            matches=cur.fetchall()
            if len(matches)!=1:raise invalid('decision_registry_selection_unavailable')
            cur.execute('SELECT '+COLUMNS+' FROM '+TABLE+' WHERE mission_id=%s AND actor_id=%s AND workspace_id=%s ORDER BY ordinal DESC,observed_at DESC LIMIT 1',
                        (matches[0][0],self.actor_id,self.workspace_id))
            row=cur.fetchone()
        if not row:raise invalid('decision_registration_unavailable')
        registration,_=self._decode(row)
        now=self.clock()
        return build_question(self,registration,actor_id=self.actor_id,workspace_id=self.workspace_id,
            report_id=document['fingerprint'],report_version=document['version'],report_key=document['period']['key'],
            prompt='Continue the original registered task within its existing approved scope, wait, or request human help?',
            now=now,expires_at=now+900)
