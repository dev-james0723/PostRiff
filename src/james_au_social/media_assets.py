"""Local media acceptance: byte binding is not visual/decoder verification."""
import hashlib
from pathlib import Path

def inspect_asset(path, manifest, *, required_kind):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular_local_asset_required')
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    blockers=[]
    if digest!=manifest['sha256']:
        blockers.append('asset_hash_drift')
    if manifest['kind']!=required_kind:
        blockers.append('native_media_kind_mismatch')
    if manifest.get('rights_review')!='approved':
        blockers.append('rights_review_required')
    if manifest.get('visual_review')!='approved':
        blockers.append('visual_review_required')
    if not manifest.get('alt_text'):
        blockers.append('accessibility_required')
    # Require an independently supplied decoder/renderer assertion bound to
    # these bytes; a declared MIME type or filename never proves valid media.
    if manifest.get('decoder_verified_hash')!=digest:
        blockers.append('decoder_verification_required')
    if manifest.get('constraints_verified_hash')!=digest or not manifest.get('constraint_version'):
        blockers.append('platform_constraints_unverified')
    if required_kind=='video' and manifest.get('audio_review')!='approved':
        blockers.append('audio_review_required')
    return {'sha256':digest,'ready':not blockers,'blockers':blockers,'uploaded':False,'published':False}
