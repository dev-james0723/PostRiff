"""Private bounded native collection; elapsed time and gaps remain explicit."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

MAX_BYTES = 2 * 1024**3
RETENTION_SECONDS = 48 * 3600
MIN_FREE_BYTES = 2 * 1024**3
MAX_CONSECUTIVE_FAILURES = 3

class CaptureError(ValueError):
    def __init__(self, reason, *, artifact=None, diagnostic=None):
        super().__init__(reason)
        self.artifact = artifact
        self.diagnostic = diagnostic or {}

def stored_artifact(root, identifier):
    path = root / (str(uuid.UUID(identifier)) + '.mp4')
    if not path.exists(): return None
    if path.is_symlink() or not path.is_file():
        raise ValueError('capture_artifact_identity_conflict')
    os.chmod(path, 0o600)
    return {'id': identifier, 'path': path.name, 'byteCount': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'storedAt': path.stat().st_mtime, 'retentionState': 'retained'}

def reconcile_artifacts(root, state):
    """A crashed/failed native output is storage, never verified capture evidence."""
    attempts = state.setdefault('failedAttempts', [])
    registered = {r['path'] for r in state['chunks'] + attempts}
    for path in sorted(root.glob('*.mp4')):
        if path.name in registered: continue
        try: identifier = str(uuid.UUID(path.stem))
        except ValueError: raise ValueError('unregistered_capture_artifact') from None
        row = stored_artifact(root, identifier)
        row.update(executionState='unverified_native_artifact', reason='previous_native_outcome_unknown')
        attempts.append(row)

def retain(root, state):
    rows = state['chunks'] + state.setdefault('failedAttempts', [])
    total = sum(r['byteCount'] for r in rows if r['retentionState'] == 'retained')
    for old in sorted(rows, key=lambda r: r['storedAt']):
        if old['retentionState'] != 'retained': continue
        if time.time() - old['storedAt'] <= RETENTION_SECONDS and total <= MAX_BYTES: break
        target = root / (str(uuid.UUID(old['id'])) + '.mp4')
        if target.is_symlink() or not target.is_file() or target.stat().st_size != old['byteCount'] or hashlib.sha256(target.read_bytes()).hexdigest() != old['sha256']:
            raise ValueError('retention_identity_conflict')
        target.unlink(); total -= old['byteCount']; old['retentionState'] = 'retention_removed'
    state['retainedBytes'] = total

def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n'); os.chmod(temp, 0o600)
    os.replace(temp, path)

def prepare(root):
    root = Path(root).absolute()
    if root.exists() and (root.is_symlink() or root.resolve()!=root):
        raise ValueError('private_capture_root_required')
    marker = root / 'capture-owner.json'
    if root.exists() and any(root.iterdir()) and not marker.is_file():
        raise ValueError('existing_directory_not_owned_by_capture')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.resolve() != root:
        raise ValueError('private_capture_root_required')
    os.chmod(root, 0o700)
    if not marker.exists():save(marker,{'schemaVersion':1,'ownerUid':os.getuid(),'purpose':'bounded_screen_system_audio'})
    if marker.is_symlink() or json.loads(marker.read_text())!={'schemaVersion':1,'ownerUid':os.getuid(),'purpose':'bounded_screen_system_audio'}:
        raise ValueError('capture_owner_identity_changed')
    return root

def capture(root, helper, seconds):
    if shutil.disk_usage(root).free < MIN_FREE_BYTES:
        raise ValueError('capture_storage_reserve_unavailable')
    identifier = str(uuid.uuid4()); path = root / (identifier + '.mp4')
    try:
        result = subprocess.run([str(helper), 'capture', str(path), str(seconds)], capture_output=True,
                                text=True, timeout=seconds+45)
    except subprocess.TimeoutExpired:
        raise CaptureError('native_capture_timeout', artifact=stored_artifact(root, identifier)) from None
    try: metadata = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise CaptureError('native_capture_outcome_unverified', artifact=stored_artifact(root, identifier)) from None
    if result.returncode != 0 or metadata.get('executionState') not in (
            'captured_screen_and_system_audio', 'captured_screen_system_audio_unobserved'):
        reason = 'macos_screen_system_audio_permission_required' if metadata.get('reason') == 'macos_screen_system_audio_permission_required' else 'native_capture_failed'
        diagnostic = {}
        if metadata.get('phase') in {'arguments', 'screen_audio_permission', 'shareable_content', 'start_capture',
                'recording', 'stop_capture', 'recording_finalization', 'inspect_recorded_tracks'}:
            diagnostic['phase'] = metadata['phase']
        if type(metadata.get('errorCode')) is int: diagnostic['errorCode'] = metadata['errorCode']
        if metadata.get('captureFailure') in {'invalidArguments', 'permissionRequired', 'recordingFailed',
                'invalidTracks', 'playbackTimeout', 'system_error'}:
            diagnostic['captureFailure'] = metadata['captureFailure']
        raise CaptureError(reason, artifact=stored_artifact(root, identifier), diagnostic=diagnostic)
    if path.is_symlink() or path.parent != root or metadata.get('videoTracks') != 1 or metadata.get('systemAudioTracks') not in (0,1):
        raise ValueError('native_recorded_tracks_unverified')
    if (metadata.get('systemAudioTracks')==0)!=(metadata['executionState']=='captured_screen_system_audio_unobserved'):
        raise ValueError('native_audio_observation_mismatch')
    os.chmod(path, 0o600)
    metadata.update(id=identifier, path=path.name, byteCount=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), storedAt=time.time(), retentionState='retained')
    return metadata

def retrieve(root, identifier, *, playback=False, helper=None):
    state = json.loads((root / 'manifest.json').read_text())
    rows = [r for r in state['chunks'] if r['id'] == identifier]
    if len(rows) != 1: raise ValueError('capture_identity_unavailable')
    row = rows[0]; path = root / (str(uuid.UUID(identifier)) + '.mp4')
    if row['retentionState'] != 'retained' or path.is_symlink() or not path.is_file():
        raise ValueError('capture_not_retained')
    if path.stat().st_size != row['byteCount'] or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        raise ValueError('capture_retrieval_hash_mismatch')
    receipt = {k: row[k] for k in ('id', 'sha256', 'byteCount', 'startedAt', 'finishedAt')}
    receipt.update(executionState='capture_retrieval_verified', retrievedAt=datetime.now(timezone.utc).isoformat())
    if playback:
        result = subprocess.run([str(helper), 'verify', str(path)], capture_output=True, text=True, timeout=150)
        verified = json.loads(result.stdout.strip().splitlines()[-1])
        if result.returncode != 0 or verified.get('playbackEnded') is not True:
            raise ValueError('capture_playback_unverified')
        receipt.update(playback=verified, executionState='capture_storage_retrieval_playback_verified')
    save(root / ('receipt-' + identifier + '.json'), receipt)
    return receipt

def run(root, helper, seconds, *, once=False):
    with (root / 'collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = root / 'manifest.json'
        state = json.loads(manifest.read_text()) if manifest.exists() else {
            'schemaVersion': 1, 'executionState': 'starting', 'startedAt': time.time(), 'chunks': [],
            'policy': {'maxBytes': MAX_BYTES, 'retentionSeconds': RETENTION_SECONDS, 'minFreeBytes': MIN_FREE_BYTES,
                       'chunkSeconds': seconds, 'screenSamplingFps': 1, 'systemAudio': True, 'microphone': False},
            'fullDayCoverageMatured': False, 'gaps': [], 'continuousCollection': not once}
        reconcile_artifacts(root, state); retain(root, state)
        state.update(continuousCollection=not once,collectorPid=os.getpid(),collectorStartedAt=time.time())
        state.setdefault('consecutiveFailures', 0)
        if state['consecutiveFailures'] >= MAX_CONSECUTIVE_FAILURES:
            state.update(executionState='capture_failed', reason='native_capture_retry_ceiling', updatedAt=time.time())
            save(manifest, state)
            raise ValueError('native_capture_retry_ceiling')
        while True:
            start = time.time()
            try:
                row = capture(root, helper, seconds)
                if state['chunks']:
                    previous = datetime.fromisoformat(state['chunks'][-1]['finishedAt'].replace('Z', '+00:00')).timestamp()
                    gap = max(0, datetime.fromisoformat(row['startedAt'].replace('Z', '+00:00')).timestamp() - previous)
                    if gap: state['gaps'].append({'startedAt': previous, 'seconds': gap, 'reason': 'native_chunk_rotation'})
                state['chunks'].append(row); state['executionState'] = 'running' if not once else 'bounded_capture_complete'
                state['consecutiveFailures'] = 0
                state.pop('reason', None); state.pop('diagnostic', None)
                if row['systemAudioTracks']==0:
                    state['gaps'].append({'startedAt':start,'seconds':row['durationSeconds'],
                        'reason':'no_recorded_system_audio_samples'})
                retain(root, state)
                retained = [r for r in state['chunks'] if r['retentionState'] == 'retained']
                state.update(updatedAt=time.time(),
                    capturedSeconds=sum(r['durationSeconds'] for r in retained),
                    recordedSystemAudioSeconds=sum(r['durationSeconds'] for r in retained if r['systemAudioTracks']==1),
                    elapsedSeconds=time.time()-state['startedAt'],
                    fullDayDurationMatured=time.time()-state['startedAt']>=86400,
                    measuredCaptureDurationMatured=sum(r['durationSeconds'] for r in retained)>=86400,
                    fullDayCoverageMatured=False,
                    maturationReason='duration_matures_from_real_time; recorded_gaps_require_coverage_review')
                save(manifest, state)
                if once: return row
            except Exception as error:
                state.update(executionState='capture_failed', updatedAt=time.time(), reason=str(error),
                             consecutiveFailures=state['consecutiveFailures']+1)
                if isinstance(error, CaptureError):
                    state['diagnostic'] = error.diagnostic
                    if error.artifact:
                        error.artifact.update(executionState='unverified_native_artifact', reason=str(error), diagnostic=error.diagnostic)
                        state['failedAttempts'].append(error.artifact)
                state['gaps'].append({'startedAt': start, 'seconds': time.time()-start, 'reason': str(error)})
                reconcile_artifacts(root, state)
                retain(root, state)
                save(manifest, state)
                raise

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('once', 'continuous', 'retrieve', 'playback', 'status'))
    parser.add_argument('--root', required=True); parser.add_argument('--helper', required=True)
    parser.add_argument('--seconds', type=int, default=120); parser.add_argument('--id')
    args = parser.parse_args(); root = prepare(args.root); helper = Path(args.helper).resolve(strict=True)
    if not 1 <= args.seconds <= 120: raise ValueError('bounded_capture_required')
    if args.mode in ('once', 'continuous'):
        value = run(root, helper, args.seconds, once=args.mode == 'once')
    elif args.mode == 'status':
        value = json.loads((root / 'manifest.json').read_text())
        value = {k: v for k, v in value.items() if k != 'chunks'} | {'chunkCount': len(value['chunks'])}
    else:
        value = retrieve(root, args.id, playback=args.mode == 'playback', helper=helper)
    print(json.dumps(value))

if __name__ == '__main__': main()
