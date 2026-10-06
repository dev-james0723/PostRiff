"""Read-only association of real native metadata with an approved local mission.

This supplies report labels only. It never creates registrations, checkpoints,
source activity, writer proofs, model permits or recovery authority.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import UUID

from .events import canonical
from .evidence_sources import EvidenceBatch
from .recovery import NativeOwner, Registration


@dataclass(frozen=True)
class MissionEvidenceBinding:
    recovery_store: Path
    mission_id: str
    registration_sha256: str
    session_id: str

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, dict) or set(value) != {
                'recovery_store', 'mission_id', 'registration_sha256', 'session_id'}:
            raise ValueError('mission_evidence_fields_required')
        binding = cls(Path(value['recovery_store']), value['mission_id'],
                      value['registration_sha256'], value['session_id'])
        binding.validate()
        return binding

    def validate(self):
        p = self.recovery_store
        if not p.is_absolute() or p.resolve() != p or p.is_symlink() or '..' in p.parts:
            raise ValueError('mission_evidence_exact_path_required')
        if (not isinstance(self.mission_id, str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', self.mission_id)
                or not isinstance(self.registration_sha256, str)
                or not re.fullmatch(r'[0-9a-f]{64}', self.registration_sha256)):
            raise ValueError('mission_evidence_identity_required')
        try:
            if str(UUID(self.session_id)) != self.session_id: raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('mission_evidence_session_uuid_required') from None

    def as_dict(self):
        return asdict(self) | {'recovery_store': str(self.recovery_store)}


def _private_file(path, limit):
    p = Path(path); info = p.lstat()
    if (p.resolve() != p or p.is_symlink() or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > limit):
        raise ValueError('mission_evidence_private_file_required')
    return p


def associate_mission(batch, binding, *, workspace, project_id):
    """Validate the durable registration and current TP binding each normal tick."""
    if binding is None: return batch
    try:
        binding.validate()
        db_path = _private_file(binding.recovery_store, 8 * 1024 * 1024)
        parent = db_path.parent.stat()
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise ValueError('mission_evidence_private_directory_required')
        db = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            rows = db.execute('SELECT fingerprint,body FROM recovery_bindings WHERE mission_id=? LIMIT 2',
                              (binding.mission_id,)).fetchall()
        finally:
            db.close()
        if len(rows) != 1 or rows[0][0] != binding.registration_sha256:
            raise ValueError('mission_evidence_registration_unavailable')
        data = json.loads(rows[0][1]); data['owner'] = NativeOwner(**data['owner'])
        for name in ('acceptance_criteria', 'side_effect_ledger_refs', 'descendant_refs', 'background_refs', 'ci_refs'):
            data[name] = tuple(data[name])
        registered = Registration(**data)
        if (registered.fingerprint != binding.registration_sha256
                or (registered.mission_id, registered.native_session_id, registered.engine, registered.worktree)
                != (binding.mission_id, binding.session_id, 'claude-code', str(workspace))):
            raise ValueError('mission_evidence_registration_mismatch')
        state = json.loads(_private_file(Path(workspace)/'.token-pilot/state.json', 1048576).read_text())
        if state.get('schema_version') != 2 or state.get('project') != str(workspace):
            raise ValueError('mission_evidence_continuity_unsupported')
        session = state['sessions'][binding.session_id]
        expected = {'task_id': registered.token_pilot_task_id,
                    'root_task_id': registered.token_pilot_root_task_id,
                    'phase_id': registered.token_pilot_phase_id}
        if session.get('binding') != expected:
            raise ValueError('mission_evidence_continuity_mismatch')
        task = state['workspace']['tasks'][registered.token_pilot_task_id]
        if task.get('status') in ('needs_review', 'stale'):
            raise ValueError('mission_evidence_continuity_requires_review')
        if any(a.get('status') in ('started', 'outcome_unknown') for a in task.get('actions', {}).values()):
            raise ValueError('mission_evidence_unreconciled_action')
        events = tuple(replace(event, mission_id=binding.mission_id, revision=hashlib.sha256(
            canonical([event.revision, binding.registration_sha256]).encode()).hexdigest()).validate()
            for event in batch.events if event.source == 'claude' and event.project_id == project_id)
        return replace(batch, events=events)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        # No paths, source contents, mission labels or fabricated observations on failure.
        return EvidenceBatch('claude', 'unavailable', gaps=('mission_evidence_binding_unverified',))
