"""ORC-owned, authenticated host guard for bounded read-only Claude continuations.

This owner is created only for a new authorized mission, never over an existing
Codex/UI writer. Its isolated Claude config/session is private; the native child
runs inside the macOS kernel sandbox with *no* built-in or MCP tools. Only this
owner admits model turns, after the existing RecoveryStore CAS and fresh checks.
It cannot attest unrestricted coding sessions or silently fall back to them.
No model, socket, process or registry is started on import.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import shlex
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from uuid import UUID

from .native_decision import NativeGuardAttestation, _checkpoint
from .native_transport import (NativeContext, NativeOwnerSnapshot, NativeOwnerTransport,
    NativeThread, ModelPermit, SQLiteRecoveryControl, digest, verify_socket)
from .recovery import (Attempt, ContinuityEvidence, ExecutionBinding, Lease,
    NativeOwner, RecoveryBlocked, RecoveryEvidence, RecoveryStore, Registration,
    WorkspaceSnapshot, WriterProof, validate_recovery)
from .recovery import _digest as checkpoint_digest

MAX_MESSAGE = 262144


def authenticated_envelope(token, body):
    raw = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
    return {'body': body, 'mac': hmac.new(token, raw, hashlib.sha256).hexdigest()}


def authenticated_body(token, envelope, *, request_id=None):
    body = envelope.get('body')
    if not isinstance(body, dict) or not isinstance(envelope.get('mac'), str):
        raise RecoveryBlocked('owner_message_authentication')
    expected = authenticated_envelope(token, body)['mac']
    if not hmac.compare_digest(expected, envelope['mac']):
        raise RecoveryBlocked('owner_message_authentication')
    if request_id is not None and body.get('requestId') != request_id:
        raise RecoveryBlocked('owner_response_request_mismatch')
    return body


def file_sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(65536),b''):h.update(block)
    return h.hexdigest()


def private(path, *, directory=False):
    p = Path(path)
    info = p.lstat()
    if p.is_symlink() or p.resolve() != p or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RecoveryBlocked('owner_private_path_required')
    if directory != stat.S_ISDIR(info.st_mode):
        raise RecoveryBlocked('owner_private_path_type')
    return p


def write_private(path, value):
    p = Path(path); tmp = p.with_suffix('.tmp')
    if p.is_symlink() or tmp.is_symlink(): raise RecoveryBlocked('owner_path_alias')
    fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)


def process_identity(pid):
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'pid=', '-o', 'ppid=', '-o', 'lstart='],
                            capture_output=True, text=True, timeout=2, check=True).stdout.strip().split(None, 2)
    if len(result) != 3 or int(result[0]) != pid: raise RecoveryBlocked('owner_pid_not_live')
    return int(result[1]), result[2]


def verify_ancestry(agent_pid, agent_start, *, pid=None):
    pid = os.getpid() if pid is None else pid
    for _ in range(20):
        parent, start = process_identity(pid)
        if pid == agent_pid:
            if start != agent_start: raise RecoveryBlocked('orc_agent_pid_reused')
            return
        if parent <= 1: break
        pid = parent
    raise RecoveryBlocked('actual_orc_bootstrap_required')


def workspace_snapshot(root):
    p = Path(root).resolve(strict=True)
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
    def git(*args):
        return subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
            '-c', 'submodule.recurse=false', '-C', str(p), *args], capture_output=True,
            timeout=3, check=True, env=env).stdout
    if git('rev-parse', '--show-toplevel').decode().strip() != str(p):
        raise RecoveryBlocked('exact_owner_worktree_required')
    head = git('rev-parse', 'HEAD').decode().strip()
    changes = git('diff', '--binary', 'HEAD', '--')
    # Include untracked file bytes; names alone never prove a preserved worktree.
    untracked = git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    items = []
    for raw in untracked:
        if not raw: continue
        path = p / os.fsdecode(raw)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
            raise RecoveryBlocked('owner_untracked_state_unverifiable')
        items.append([raw.hex(), hashlib.sha256(path.read_bytes()).hexdigest()])
    dirty = digest([hashlib.sha256(changes).hexdigest(), items])
    return WorkspaceSnapshot(str(p), head, dirty, 'tracked diff and exact untracked hashes', 'git:'+head+':'+dirty)


def configuration(worktree, model):
    return {'cwd': worktree, 'model': model, 'modelProvider': 'anthropic-subscription',
        'approvalPolicy': 'untrusted', 'approvalsReviewer': 'user',
        'sandbox': {'type': 'readOnly', 'nativeTools': [], 'mcpTools': [], 'kernel': 'macos-seatbelt'}}


def native_argv(binary, settings, session, *, resume):
    if str(UUID(session)) != session: raise RecoveryBlocked('owner_native_uuid_required')
    return ['/usr/bin/sandbox-exec', '-f', str(Path(settings).with_suffix('.sb')),
        str(binary), '-p', '--restricted', '--tools', '', '--disallowedTools', '*',
        '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--disable-slash-commands',
        '--setting-sources', '', '--settings', str(settings), '--max-turns', '1',
        '--max-budget-usd', '0.25', '--output-format', 'stream-json', '--verbose',
        '--resume' if resume else '--session-id', session]


def sandbox_profile(root, worktree, binary, python):
    """Kernel denies every native write except its own history/TP bookkeeping.

    The native child cannot execute shell/file tools. Trusted lifecycle hooks
    use the exact Python executable; unknown command hooks fail at the kernel.
    """
    quote=lambda p: json.dumps(str(p))
    return '\n'.join(['(version 1)', '(deny default)', '(allow process-fork)',
        '(allow process-info*)', '(allow sysctl-read)', '(allow mach-lookup)',
        '(allow ipc-posix-shm*)', '(allow network-outbound)', '(allow file-read*)',
        '(allow file-write* (subpath '+quote(Path(root)/'claude')+'))',
        '(allow file-write* (subpath '+quote(Path(worktree)/'.token-pilot')+'))',
        '(allow file-write* (subpath '+quote(Path(root)/'tmp')+'))',
        '(allow file-write* (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr"))',
        '(allow process-exec (literal '+quote(Path(binary).resolve())+') (literal '+quote(Path(python).resolve())+'))'])+'\n'


def subscription_token(binary):
    """Reuse the same installed CLI's existing subscription credential in RAM.

    No login/credential changes, API-key fallback, credential-file copy or secret
    output. The fixed Keychain service remains owned by the existing user.
    """
    env={k:os.environ[k] for k in ('HOME','PATH','TMPDIR','USER','LOGNAME') if k in os.environ}
    probe=subprocess.run([str(binary),'auth','status'],env=env,capture_output=True,text=True,timeout=5)
    try: status=json.loads(probe.stdout)
    except ValueError: raise RecoveryBlocked('existing_claude_subscription_unavailable') from None
    if probe.returncode or status.get('authMethod')!='claude.ai':
        raise RecoveryBlocked('existing_claude_subscription_required')
    credential=subprocess.run(['/usr/bin/security','find-generic-password','-s','Claude Code-credentials','-w'],
        env=env,capture_output=True,text=True,timeout=5)
    try: oauth=json.loads(credential.stdout)['claudeAiOauth']
    except (ValueError,KeyError):raise RecoveryBlocked('existing_claude_keychain_unavailable') from None
    if credential.returncode or oauth.get('subscriptionType') not in ('pro','max','team','enterprise'):
        raise RecoveryBlocked('included_native_subscription_required')
    token=oauth.get('accessToken')
    if not isinstance(token,str) or len(token)<32 or oauth.get('expiresAt',0)/1000<=time.time()+180:
        raise RecoveryBlocked('existing_native_credential_refresh_required')
    return token


def parse_native_result(rows, *, session, expected_model=None):
    init = next((r for r in rows if r.get('type') == 'system' and r.get('subtype') == 'init'), None)
    result = next((r for r in reversed(rows) if r.get('type') == 'result'), None)
    if (not init or init.get('session_id') != session or init.get('tools') != []
            or init.get('mcp_servers') not in ([], {}) or not result
            or result.get('session_id') != session or result.get('is_error') is not False
            or result.get('subtype') != 'success' or result.get('num_turns') != 1):
        raise RecoveryBlocked('restricted_native_result_unverified')
    model = init.get('model')
    if not isinstance(model, str) or not model or expected_model and model != expected_model:
        raise RecoveryBlocked('native_model_configuration_changed')
    turn = result.get('uuid')
    try:
        if str(UUID(turn)) != turn: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        # Never invent a native turn identity when this CLI version omits it.
        raise RecoveryBlocked('actual_native_result_uuid_required') from None
    if any(r.get('type') == 'assistant' and any(c.get('type') == 'tool_use'
        for c in r.get('message', {}).get('content', []) if isinstance(c, dict)) for r in rows):
        raise RecoveryBlocked('unexpected_native_tool_dispatch')
    return {'turnId': turn, 'sessionId': session, 'model': model,
        'resultSha256': digest(result), 'usage': result.get('usage', {}),
        'apiEquivalentCostUsd': result.get('total_cost_usd'), 'billingBasis': 'existing_subscription',
        'nativeState': 'finished', 'observedAt': time.time(), 'nativeTools': [], 'mcpTools': []}


def registration_from(body):
    d = dict(body); d['owner'] = NativeOwner(**d['owner'])
    for n in ('acceptance_criteria','side_effect_ledger_refs','descendant_refs','background_refs','ci_refs'):
        d[n] = tuple(d[n])
    return Registration(**d)


def parse_quota_rejection(rows, *, session):
    """A terminal zero-usage rejection is never a successful native turn."""
    init = next((r for r in rows if r.get('type') == 'system' and r.get('subtype') == 'init'), None)
    result = rows[-1] if rows else None
    quota = next((r.get('rate_limit_info') for r in rows if r.get('type') == 'rate_limit_event'
                  and r.get('session_id') == session), None)
    def zero_counts(value):
        if isinstance(value, dict): return all(zero_counts(v) for v in value.values())
        if isinstance(value, list): return not value
        if type(value) in (int, float): return math.isfinite(value) and value == 0
        return value is None or isinstance(value, str)
    usage = result.get('usage') if isinstance(result, dict) else None
    if (not init or init.get('session_id') != session or init.get('tools') != []
            or init.get('mcp_servers') not in ([], {}) or not isinstance(init.get('model'), str)
            or not init['model'] or not isinstance(result, dict) or result.get('type') != 'result'
            or result.get('session_id') != session or result.get('is_error') is not True
            or result.get('api_error_status') != 429 or result.get('terminal_reason') != 'api_error'
            or type(result.get('num_turns')) is not int or result['num_turns'] != 1
            or type(result.get('total_cost_usd')) not in (int, float) or result['total_cost_usd'] != 0
            or result.get('modelUsage') != {} or result.get('permission_denials') != []
            or not isinstance(usage, dict) or not zero_counts(usage)
            or any(type(usage.get(k)) is not int or usage[k] != 0 for k in
                   ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
            or not isinstance(quota, dict) or quota.get('status') != 'rejected'
            or quota.get('isUsingOverage') is not False or quota.get('overageStatus') != 'rejected'
            or type(quota.get('resetsAt')) not in (int, float) or not math.isfinite(quota['resetsAt'])
            or quota['resetsAt'] <= 0
            or any(r.get('type') == 'assistant' and any(c.get('type') in ('tool_use', 'tool_result')
                   for c in r.get('message', {}).get('content', []) if isinstance(c, dict)) for r in rows)):
        raise RecoveryBlocked('native_terminal_rejection_unproven')
    try:
        if str(UUID(session)) != session or str(UUID(result['uuid'])) != result['uuid']: raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RecoveryBlocked('native_terminal_identity_unproven') from None
    return {'sessionId': session, 'model': init['model'], 'terminalResultId': result['uuid'],
            'terminalState': 'provider_quota_rejected', 'quotaResetsAt': quota['resetsAt'],
            'successfulNativeTurn': False, 'providerUsageTokens': 0, 'apiEquivalentCostUsd': 0}


def reconcile_rejected_seed(root, *, request_id, checkpoint_sha, output_sha):
    """Offline CAS reconciliation after the owning daemon has stopped.

    Only its one sealed, tool-free, zero-usage quota rejection is recognized.
    The immutable native output/checkpoint remain intact. No resume, retry,
    guard attestation, source event or successful-result file is produced.
    """
    root = private(root, directory=True)
    policy = json.loads(private(root/'policy.json').read_text())
    ready = json.loads(private(root/'owner-ready.json').read_text())
    r = registration_from(json.loads(private(root/'registration.json').read_text()))
    if (ready.get('bootstrappedByOrc') is not True or ready.get('policySha256') != digest(policy)
            or NativeOwner(**ready['owner']) != r.owner or r.engine != 'claude-code'
            or policy['sessionId'] != r.native_session_id or policy['worktree'] != r.worktree
            or policy['authorizationSha256'] != r.authorization_sha256
            or r.descendant_refs or r.background_refs or r.ci_refs):
        raise RecoveryBlocked('terminal_reconciliation_binding_mismatch')
    try:
        _, start = process_identity(r.owner.pid)
    except subprocess.CalledProcessError:
        pass
    else:
        raise RecoveryBlocked('native_owner_must_stop_before_reconciliation' if start == r.owner.process_start
                              else 'owner_pid_reused')
    for name, expected in policy['guardedFiles'].items():
        if file_sha256(name) != expected: raise RecoveryBlocked('native_guard_configuration_changed')
    output = private(root/'native-output.jsonl')
    if output.stat().st_size > MAX_MESSAGE or file_sha256(output) != output_sha:
        raise RecoveryBlocked('native_terminal_output_changed')
    result = parse_quota_rejection([json.loads(line) for line in output.read_text().splitlines() if line.strip()],
                                  session=r.native_session_id)
    store = RecoveryStore(str(private(root/'recovery.sqlite3')))
    cp = _checkpoint(store, r, checkpoint_sha)
    current = workspace_snapshot(r.worktree)
    if (current.head, current.dirty_sha256) != (cp.workspace.head, cp.workspace.dirty_sha256):
        raise RecoveryBlocked('terminal_checkpoint_workspace_changed')
    if store.db.execute('SELECT 1 FROM recovery_leases WHERE worktree=? AND expires_at>?',
                        (r.worktree, time.time())).fetchone():
        raise RecoveryBlocked('terminal_reconciliation_active_lease')
    ledger = sqlite3.connect(str(private(root/'owner-delivery.sqlite3')), isolation_level=None)
    ledger.execute('BEGIN IMMEDIATE')
    try:
        row = ledger.execute('SELECT method,payload_sha,state FROM operations WHERE id=?', (request_id,)).fetchone()
        if (not row or row[:2] != ('seed', digest({'checkpointSha256': checkpoint_sha}))
                or row[2] not in ('unknown', 'rejected')
                or ledger.execute("SELECT 1 FROM operations WHERE id<>? AND state IN ('unknown','reserved')",
                                  (request_id,)).fetchone()):
            raise RecoveryBlocked('terminal_reconciliation_operation_mismatch')
        if row[2] == 'rejected':
            existing = json.loads(private(root/'native-terminal-rejection.json').read_text())
            if any(existing.get(k) != v for k, v in
                   {'requestId': request_id, 'checkpointSha256': checkpoint_sha, 'outputSha256': output_sha,
                    'registrationSha256': r.fingerprint, **result}.items()):
                raise RecoveryBlocked('terminal_reconciliation_receipt_mismatch')
            ledger.execute('COMMIT')
            return existing
        receipt = {**result, 'executionState': 'known_rejected_seed_reconciled', 'requestId': request_id,
                   'checkpointSha256': checkpoint_sha, 'outputSha256': output_sha,
                   'registrationSha256': r.fingerprint, 'observedAt': time.time(),
                   'ownerStopped': True, 'nativeGuardVerified': False, 'retryDispatched': False}
        write_private(root/'native-terminal-rejection.json', receipt)
        if row[2] == 'unknown':
            ledger.execute("UPDATE operations SET state='rejected' WHERE id=? AND state='unknown'", (request_id,))
            if ledger.execute('SELECT changes()').fetchone()[0] != 1:
                raise RecoveryBlocked('terminal_reconciliation_cas_failed')
        ledger.execute('COMMIT')
        return receipt
    except BaseException:
        ledger.execute('ROLLBACK'); raise
    finally:
        ledger.close(); store.db.close()


class RestrictedOwner:
    """One serial owner; every admitted continuation is tied to a durable attempt."""
    def __init__(self, root, *, clock=time.time):
        self.root = private(root, directory=True); self.clock = clock
        self.policy = json.loads(private(self.root/'policy.json').read_text())
        self.policy_sha = digest(self.policy)
        self.token = private(self.root/'owner.token').read_bytes()
        self.store = RecoveryStore(str(private(self.root/'recovery.sqlite3')))
        self.control = SQLiteRecoveryControl(self.store)
        self.job = None; self.context = None; self.permit = None
        verify_ancestry(self.policy['orcAgentPid'], self.policy['orcAgentStart'])
        self.owner = NativeOwner('orc-restricted-'+self.policy['missionId'], str(self.root/'owner.sock'),
                                 os.getpid(), process_identity(os.getpid())[1])
        self.db = sqlite3.connect(str(self.root/'owner-delivery.sqlite3'), isolation_level=None)
        self.db.execute('CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, method TEXT, payload_sha TEXT, state TEXT)')
        self.guard_ref = 'orc-owner:'+digest([asdict(self.owner), self.policy_sha])

    def binding(self):
        row = self.store.db.execute('SELECT body FROM recovery_bindings WHERE mission_id=?',
                                   (self.policy['missionId'],)).fetchone()
        if not row: raise RecoveryBlocked('genuine_owner_registration_required')
        r = registration_from(json.loads(row['body'])); b = self.store.current_execution(r)
        if (r.engine, r.owner, r.worktree, r.native_session_id, r.authorization_sha256) != (
                'claude-code', self.owner, self.policy['worktree'], self.policy['sessionId'], self.policy['authorizationSha256']):
            raise RecoveryBlocked('owner_registration_policy_mismatch')
        return r, b

    def continuity(self, r):
        script = Path(self.policy['tokenPilotScripts'])/'continuity.py'
        reply = subprocess.run([sys.executable, str(script), 'resolve', '--root', r.worktree,
            '--session', r.native_session_id, '--task', r.token_pilot_task_id],
            capture_output=True, text=True, timeout=5, check=True)
        value = json.loads(reply.stdout)
        if value.get('status') != 'ready': raise RecoveryBlocked('token_pilot_owner_not_ready')
        state_path = Path(r.worktree)/'.token-pilot/state.json'; state = json.loads(state_path.read_text())
        binding = state['sessions'][r.native_session_id]['binding']
        task = state['workspace']['tasks'][r.token_pilot_task_id]
        if (binding.get('task_id'), binding.get('root_task_id'), binding.get('phase_id')) != (
                r.token_pilot_task_id, r.token_pilot_root_task_id, r.token_pilot_phase_id):
            raise RecoveryBlocked('token_pilot_owner_binding_changed')
        if task['contract_hash'] != self.policy['tokenPilotContractSha256']:
            raise RecoveryBlocked('token_pilot_owner_scope_changed')
        return ContinuityEvidence(r.token_pilot_task_id, r.token_pilot_root_task_id, r.token_pilot_phase_id,
            state['revision'], 'ready', r.authorization_ref, r.authorization_sha256, r.scope_version,
            'token-pilot:'+task['contract_hash'], r.native_session_id)

    def validate_host(self):
        if self.job and self.job.poll() is None: raise RecoveryBlocked('native_owned_turn_running')
        if process_identity(self.owner.pid)[1] != self.owner.process_start:
            raise RecoveryBlocked('owner_pid_reused')
        if process_identity(self.policy['orcAgentPid'])[1] != self.policy['orcAgentStart']:
            raise RecoveryBlocked('orc_bootstrap_owner_changed')
        if digest(json.loads(private(self.root/'policy.json').read_text())) != self.policy_sha:
            raise RecoveryBlocked('owner_policy_changed')
        binary = Path(self.policy['claudeBinary']).resolve(strict=True)
        if file_sha256(binary) != self.policy['claudeBinarySha256']:
            raise RecoveryBlocked('native_binary_changed')
        for name, expected in self.policy['guardedFiles'].items():
            if file_sha256(name) != expected:
                raise RecoveryBlocked('native_guard_configuration_changed')

    def observe(self, checkpoint_sha):
        r, b = self.binding(); cp = _checkpoint(self.store, r, checkpoint_sha)
        self.validate_host()
        s = private(self.root/'owner.sock').stat(); now = self.clock()
        native = json.loads(private(self.root/'native-result.json').read_text())
        if native['sessionId'] != r.native_session_id or native['nativeTools'] or native['mcpTools']:
            raise RecoveryBlocked('native_session_guard_unverified')
        # No detached workers/CI can be created by this child: all tool dispatch
        # is absent and process execution is denied by its kernel sandbox.
        if b.descendant_refs or b.background_refs or b.ci_refs:
            raise RecoveryBlocked('restricted_owner_inventory_mismatch')
        ws = workspace_snapshot(r.worktree); continuity = self.continuity(r)
        unknown = tuple(x[0] for x in self.db.execute("SELECT id FROM operations WHERE state='unknown'"))
        writer = WriterProof(r.mission_id, r.native_session_id, self.owner, now, self.guard_ref,
            'same-owner-native', True, 'finished', True, 0, True)
        evidence = RecoveryEvidence(writer, continuity, cp.workspace, ws, unknown_external_effects=unknown,
            scope_still_authorized=True, side_effects_reconciled=not unknown,
            side_effect_reconciliation_ref='owner-delivery:'+digest(list(self.db.execute('SELECT * FROM operations'))))
        snapshot = NativeOwnerSnapshot(b.fingerprint, now, evidence, s.st_dev, s.st_ino, s.st_uid,
            b.native_session_id, b.native_session_id, digest(configuration(r.worktree, native['model'])), self.guard_ref, True)
        attestation = NativeGuardAttestation('kynlo_orc_owner', self.guard_ref, self.guard_ref, now,
            r.fingerprint, b.fingerprint, r.authorization_sha256, self.owner, True, True)
        verify_socket(self.owner, snapshot)
        return snapshot, attestation

    def authorize(self, data):
        r,b = self.binding(); lease = Lease(**data['lease']); attempt = Attempt(**data['attempt'])
        snapshot,_ = self.observe(data['checkpointSha256'])
        context = NativeContext(r,b,lease,attempt,data['checkpointSha256'],snapshot)
        reservation = self.control.assert_reserved(context, now=self.clock())
        gate = validate_recovery(r,snapshot.evidence,now=self.clock(),max_proof_age=5,execution=b)
        if not gate.ready: raise RecoveryBlocked(gate.reason)
        permit = ModelPermit(r.authority_fingerprint,b.fingerprint,attempt.id,lease.generation,
            data['requestSha256'], snapshot.configuration_sha256,reservation.cost_microusd,self.clock()+5,
            r.authorization_ref, 'subscription-only:'+r.authorization_sha256,self.guard_ref,True,True)
        self.context,self.permit = context,permit
        return asdict(permit)

    def execute_native(self, text, *, resume, before_dispatch):
        self.validate_host()
        p = self.policy; settings = private(self.root/'native-settings.json')
        env = {k:os.environ[k] for k in ('HOME','PATH','TMPDIR','USER','LOGNAME') if k in os.environ}
        env.update(CLAUDE_CONFIG_DIR=str(self.root/'claude'),CLAUDE_CODE_PROJECT_DIR_NAME='acceptance',
            DISABLE_TELEMETRY='1',DISABLE_ERROR_REPORTING='1',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
            TMPDIR=str(self.root/'tmp'),PYTHONPATH=p['guardModuleRoot'],
            PYTHONDONTWRITEBYTECODE='1',CLAUDE_CODE_OAUTH_TOKEN=subscription_token(p['claudeBinary']))
        # API keys/provider overrides never enter this subscription-only owner.
        auth = subprocess.run([p['claudeBinary'],'auth','status'],env=env,capture_output=True,text=True,timeout=5)
        try: status=json.loads(auth.stdout)
        except ValueError: raise RecoveryBlocked('private_native_auth_unavailable') from None
        if auth.returncode or status.get('authMethod') != 'oauth_token':
            raise RecoveryBlocked('private_claude_subscription_login_required')
        expected = json.loads((self.root/'native-result.json').read_text())['model'] if resume else None
        before = workspace_snapshot(p['worktree'])
        output = self.root/'native-output.jsonl'; errors = self.root/'native-errors.txt'
        with output.open('w') as out, errors.open('w') as err:
            os.chmod(output,0o600);os.chmod(errors,0o600)
            before_dispatch()
            self.job = subprocess.Popen(native_argv(p['claudeBinary'],settings,p['sessionId'],resume=resume),
                cwd=p['worktree'],env=env,stdin=subprocess.PIPE,stdout=out,stderr=err,start_new_session=False)
            self.job.stdin.write(text.encode());self.job.stdin.close()
            deadline = self.clock()+120
            while self.job.poll() is None:
                if self.context:
                    # An expiring/changed generation stops this owner's child;
                    # it never creates a new lease or retries the model call.
                    self.store.assert_fence(self.context.lease,now=self.clock())
                if self.clock() > deadline: raise RecoveryBlocked('native_turn_deadline')
                time.sleep(.1)
        if self.job.returncode or output.stat().st_size > MAX_MESSAGE:
            raise RecoveryBlocked('native_turn_outcome_unverified')
        rows=[json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        result=parse_native_result(rows,session=p['sessionId'],expected_model=expected)
        after=workspace_snapshot(p['worktree'])
        if (before.head,before.dirty_sha256)!=(after.head,after.dirty_sha256):
            raise RecoveryBlocked('native_readonly_workspace_changed')
        result.update(workspaceHead=after.head,workspaceDirtySha256=after.dirty_sha256,guardRef=self.guard_ref)
        write_private(self.root/'native-result.json',result)
    return result

    def dispatch(self, method, data, request_id):
        if method=='observe':
            s,a=self.observe(data['checkpointSha256']);return {'snapshot':asdict(s),'attestation':asdict(a)}
        if method=='authorize': return self.authorize(data)
        if method not in ('seed','thread/resume','turn/start'): raise RecoveryBlocked('owner_method_denied')
        r,b=self.binding(); cp_sha=data.get('checkpointSha256')
        if method=='seed':
            cp=_checkpoint(self.store,r,cp_sha)
            if self.db.execute('SELECT 1 FROM operations WHERE method=?',('seed',)).fetchone():
                raise RecoveryBlocked('native_seed_no_resend')
        else:
            if not self.context: raise RecoveryBlocked('owner_reserved_context_required')
            cp=self.control.assert_reserved(self.context,now=self.clock()).checkpoint
        payload_sha=digest(data)
        try: self.db.execute('INSERT INTO operations VALUES(?,?,?,?)',(request_id,method,payload_sha,'reserved'))
        except sqlite3.IntegrityError: raise RecoveryBlocked('native_owner_no_resend') from None
        try:
            if method=='seed':
                # Initial native activity uses the already saved checkpoint.
                self.continuity(r)
                if (workspace_snapshot(r.worktree).head,workspace_snapshot(r.worktree).dirty_sha256)!=(cp.workspace.head,cp.workspace.dirty_sha256):
                    raise RecoveryBlocked('initial_checkpoint_workspace_changed')
                result=self.execute_native(cp.next_action,resume=False,before_dispatch=lambda:
                    self.db.execute("UPDATE operations SET state='unknown' WHERE id=?",(request_id,)))
                reply={'state':'seeded','result':result}
            elif method=='thread/resume':
                native=json.loads(private(self.root/'native-result.json').read_text())
                if data['params']!={'threadId':r.native_session_id,'excludeTurns':True}:
                    raise RecoveryBlocked('owner_resume_identity_mismatch')
                reply=dict(configuration(r.worktree,native['model']),thread={'id':r.native_session_id,
                    'sessionId':r.native_session_id,'cwd':r.worktree,'status':{'type':'idle'},'ephemeral':False})
            else:
                permit=self.permit;params=data['params']
                if not permit or self.clock()>permit.expires_at or digest(params)!=permit.request_sha256:
                    raise RecoveryBlocked('owner_model_permit_mismatch')
                if params.get('threadId')!=r.native_session_id or params.get('input')!=[{'type':'text','text':cp.next_action}]:
                    raise RecoveryBlocked('owner_checkpoint_prompt_required')
                self.observe(self.context.checkpoint_sha256)
                self.control.assert_reserved(self.context,now=self.clock())
                self.permit=None
                result=self.execute_native(cp.next_action,resume=True,before_dispatch=lambda:
                    self.db.execute("UPDATE operations SET state='unknown' WHERE id=?",(request_id,)))
                reply={'turn':{'id':result['turnId'],'status':'completed'},'result':result}
            self.db.execute("UPDATE operations SET state='acknowledged' WHERE id=?",(request_id,))
            return reply
        except BaseException:
            if self.job and self.job.poll() is None:
                self.job.terminate()
            # Intent remains unknown even on a native timeout, preventing retry.
            raise

    def serve(self):
        path=self.root/'owner.sock'
        if path.exists(): raise RecoveryBlocked('owner_socket_already_exists')
        server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));os.chmod(path,0o600);server.listen(2)
        write_private(self.root/'owner-ready.json',{'owner':asdict(self.owner),'guardRef':self.guard_ref,
            'policySha256':self.policy_sha,'bootstrappedByOrc':True,'observedAt':self.clock()})
        while True:
            conn,_=server.accept()
            with conn:
                conn.settimeout(10); raw=b''
                while b'\n' not in raw and len(raw)<=MAX_MESSAGE:
                    block=conn.recv(8192)
                    if not block: break
                    raw+=block
                response={'error':'owner_authenticated_request_required'}
                request_id=None
                try:
                    if len(raw)>MAX_MESSAGE or raw.count(b'\n')!=1 or not raw.endswith(b'\n'):
                        raise RecoveryBlocked('owner_message_bounds')
                    body=authenticated_body(self.token,json.loads(raw))
                    request_id=body['requestId']
                    if not isinstance(request_id,str) or not 16<=len(request_id)<=128 or abs(self.clock()-body['sentAt'])>5:
                        raise RecoveryBlocked('owner_request_authentication')
                    response={'result':self.dispatch(body['method'],body['data'],body['requestId'])}
                except BaseException as e:
                    response={'error':str(e) if isinstance(e,RecoveryBlocked) else 'owner_operation_unverified'}
                response['requestId']=request_id
                conn.sendall(json.dumps(authenticated_envelope(self.token,response)).encode()+b'\n')


def decode_observation(value):
    s=value['snapshot'];e=s['evidence'];w=e['writer'];w['owner']=NativeOwner(**w['owner'])
    for n in ('descendants','background','ci'): w[n]=tuple(w[n])
    e['writer']=WriterProof(**w);e['continuity']=ContinuityEvidence(**e['continuity'])
    for n in ('checkpoint_workspace','current_workspace'):e[n]=WorkspaceSnapshot(**e[n])
    e['unknown_external_effects']=tuple(e['unknown_external_effects']);s['evidence']=RecoveryEvidence(**e)
    s['active_evidence']=None;a=value['attestation'];a['owner']=NativeOwner(**a['owner'])
    return NativeOwnerSnapshot(**s),NativeGuardAttestation(**a)


class RestrictedOwnerClient:
    def __init__(self,root):
        self.root=private(root,directory=True);self.token=private(self.root/'owner.token').read_bytes()
        self.context=None
    def request(self,method,data,request_id=None):
        body={'method':method,'data':data,'requestId':request_id or secrets.token_hex(16),'sentAt':time.time()}
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(125);conn.connect(str(self.root/'owner.sock'))
            conn.sendall(json.dumps(authenticated_envelope(self.token,body)).encode()+b'\n');raw=b''
            while b'\n' not in raw and len(raw)<=MAX_MESSAGE:
                block=conn.recv(8192)
                if not block: break
                raw+=block
        if len(raw)>MAX_MESSAGE or raw.count(b'\n')!=1 or not raw.endswith(b'\n'):
            raise RecoveryBlocked('owner_message_bounds')
        response=authenticated_body(self.token,json.loads(raw),request_id=body['requestId'])
        if 'error' in response:raise RecoveryBlocked(response['error'])
        return response['result']
    def observe(self,r,b,cp):
        sha=checkpoint_digest(asdict(cp));s,a=decode_observation(self.request('observe',{'checkpointSha256':sha}))
        if (a.registration_sha256,a.execution_sha256)!=(r.fingerprint,b.fingerprint):
            raise RecoveryBlocked('authenticated_owner_binding_mismatch')
        return s,a
    def authorize_model(self,c,thread,sha,reservation,snapshot):
        self.context=c
        return ModelPermit(**self.request('authorize',{'lease':asdict(c.lease),'attempt':asdict(c.attempt),
            'checkpointSha256':c.checkpoint_sha256,'requestSha256':sha}))
    def connect(self,owner,snapshot):
        verify_socket(owner,snapshot)
    def rpc(self,method,params,*,request_id,before_send):
        if method=='thread/resume' and self.context:
            # Resume admission is itself fenced; it does not dispatch a model.
            self.request('authorize',{'lease':asdict(self.context.lease),'attempt':asdict(self.context.attempt),
                'checkpointSha256':self.context.checkpoint_sha256,'requestSha256':digest(params)})
        before_send()
        return self.request(method,{'params':params},request_id)
    def close(self): pass


class RestrictedClaudeTransport(NativeOwnerTransport):
    supported_engine='claude-code'
    def continue_original(self,context):
        self.proxy.context=context
        return super().continue_original(context)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--hook',action='store_true')
    p.add_argument('--reconcile-rejected-seed', action='store_true')
    p.add_argument('--request-id');p.add_argument('--checkpoint-sha');p.add_argument('--output-sha');args=p.parse_args()
    if args.reconcile_rejected_seed:
        if args.hook or not all((args.request_id, args.checkpoint_sha, args.output_sha)):
            raise RecoveryBlocked('terminal_reconciliation_arguments_required')
        print(json.dumps(reconcile_rejected_seed(args.root, request_id=args.request_id,
            checkpoint_sha=args.checkpoint_sha, output_sha=args.output_sha))); return
    if args.hook:
        # Only genuine CLI-delivered lifecycle events reach the Token Pilot
        # adapter. A tool hook always denies; no shell/editor tool is admitted.
        event=json.load(sys.stdin);root=private(args.root,directory=True)
        policy=json.loads(private(root/'policy.json').read_text())
        if (event.get('session_id'),event.get('cwd'))!=(policy['sessionId'],policy['worktree']):
            raise RecoveryBlocked('native_hook_identity_mismatch')
        if event.get('hook_event_name')=='PreToolUse':
            print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse',
                'permissionDecision':'deny','permissionDecisionReason':'Read-only acceptance owner has no tool authority'}}));return
        sys.path.insert(0,policy['tokenPilotScripts']);import autopilot
        if event.get('hook_event_name')=='Stop':
            # Save active state before Stop to prevent a repair/model turn.
            state=autopilot.load_state(policy['worktree'])
            autopilot.checkpoint(policy['worktree'],policy['sessionId'],{
                'task':'Continue the authorized staging acceptance mission','status':'active',
                'expected_revision':state['revision'],'entries':[],
                'work_update':{'done':['Observed native Stop; acceptance remains open'],
                    'issues':[],'decisions':[],'next_action':'Verify native result and remaining acceptance evidence'}})
        reply=autopilot.handle_hook(policy['worktree'],'claude',event)
        print(json.dumps(reply));return
    RestrictedOwner(args.root).serve()

if __name__=='__main__':main()
