"""RC2 fixes for regressions the customer impact inventory found in code EXISTING customers use (Discord off).

Each class names its finding in docs/CUSTOMER-IMPACT-INVENTORY.md (branch claude/discord-impact-20261023) and pins the
behaviour of the live build, c5fc1fd1 (what rafii.io serves). Two kinds of test:

- in-tree tests assert the live behaviour directly on this tree, so they also run in a shallow CI checkout;
- differential tests run one probe script with the live tree (from `git archive`, read-only on the repository) and with
  this tree and require identical records. They skip when the live revision is not in the clone.

docs/RC2-SHARED-PATH-FIXES.md lists which of these fail on the base (the W-02 head before the fixes) and why.
No database, network, provider or credential is used here; the real-PostgreSQL proofs are in
tests/test_rc2_shared_paths_postgres.py.
"""
import atexit
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_REV = os.environ.get('RC2_LIVE_REV', 'c5fc1fd10350f3142ec6f34b2c373139e85abb39')
PROBE_TIMEOUT = 300


def _rev(rev):
    done = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', '--quiet', rev + '^{commit}'],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def _probe(script, tree, *args):
    done = subprocess.run([sys.executable, str(ROOT / 'tests' / script), str(tree), *map(str, args)],
                          capture_output=True, text=True, timeout=PROBE_TIMEOUT,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    if done.returncode:
        raise AssertionError('%s failed on %s: %s' % (script, tree, done.stderr[-3000:]))
    return json.loads(done.stdout)


class LiveTree:
    """The live source tree, extracted once per process from git (never a checkout or worktree)."""
    path = None

    @classmethod
    def get(cls):
        if cls.path is None:
            target = Path(tempfile.mkdtemp(prefix='rc2-live-'))
            atexit.register(shutil.rmtree, target, True)
            archive = subprocess.run(['git', '-C', str(ROOT), 'archive', LIVE_REV, 'src'], capture_output=True, check=True)
            subprocess.run(['tar', '-x', '-C', str(target)], input=archive.stdout, check=True)
            cls.path = target
        return cls.path


# --- FB-1: Facebook Page approvals ---------------------------------------------------------------------------------------
LIVE_JOB = {'state': 'scheduled', 'events': ['Exact local fixture approval recorded', 'Waiting for the local durable worker']}


class FacebookApprovalUnchanged(unittest.TestCase):
    """FB-1 (HIGH). RC1 refused every Facebook manifest in Phase2Store.current() unless manifest.destinationId equalled
    channel.destinationId, and nothing writes manifest.destinationId: reviews were born stale, approvals refused, and a
    post approved on the live build was held by the next invalidate() (every hosted command, every worker claim)."""

    @classmethod
    def setUpClass(cls):
        cls.record = _probe('rc2_facebook_probe.py', ROOT)

    def scenario(self, name):
        return self.record['scenarios'][name]

    def test_a_facebook_page_review_is_current_and_approvable(self):
        result = self.scenario('liveChannel')
        self.assertEqual((result['review']['status'], result['review']['current']), ('needs_review', True), result['review'])
        self.assertNotIn('refused', result['approval'], result['approval'])
        self.assertEqual({k: result['approval'][k] for k in ('state', 'events')}, LIVE_JOB)
        self.assertTrue(result['approval']['current'])
        self.assertNotIn('destinationId', result['review']['manifest'], 'the manifest is the live one: no Page id frozen')

    def test_an_approved_facebook_post_survives_invalidate_and_the_worker_claim(self):
        for name in ('liveChannel', 'channelWithPageId'):
            with self.subTest(channel=name):
                result = self.scenario(name)
                self.assertEqual(result.get('afterInvalidate'), LIVE_JOB, result['approval'])
                self.assertEqual(result.get('afterClaimInvalidation'), LIVE_JOB, result['approval'])

    def test_a_page_id_recorded_on_the_channel_changes_nothing(self):
        """A channel that already carries destinationId (written by an earlier candidate's Page choice) is treated as
        live treats it: the field is ignored, and the post is approved and kept."""
        plain, recorded = self.scenario('liveChannel'), self.scenario('channelWithPageId')
        self.assertEqual((recorded['review']['status'], recorded.get('afterClaimInvalidation')), ('needs_review', LIVE_JOB))
        self.assertEqual(json.dumps(plain, sort_keys=True), json.dumps(recorded, sort_keys=True))

    def test_choosing_a_facebook_page_changes_only_the_grant(self):
        """As live: the chosen Page goes into the encrypted grant; the workspace state, its revision, the channel record
        and the capability rows are untouched (RC1 relabelled the channel, rewrote nine capability rows, could clear
        capabilityVerified, bumped the revision and ran invalidate())."""
        chosen = self.record['choosePage']
        self.assertEqual(chosen.get('result'), {'connectionId': 'facebook-connection-1', 'destinationId': '100200300400'}, chosen)
        self.assertEqual(chosen['pageInGrant'], '100200300400')
        self.assertEqual(chosen['revision'], 7, 'the workspace row is not rewritten')
        self.assertNotIn('destinationId', chosen['channel'])
        self.assertEqual((chosen['channel']['account'], chosen['channel']['capabilityVerified']), ('Impact Studio', True))
        writes = [s for s in chosen['statements'] if s.startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(writes, [
            'UPDATE public.pr_encrypted_credentials SET scopes=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s',
            'UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND access_ciphertext=%s A',
            'INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,%s,%s,%s,%s::jsonb)'])

    def test_no_facebook_branch_in_the_approval_check_or_the_page_choice(self):
        from postriff_phase2.oauth import OAuthService
        from postriff_phase2.store import Phase2Store
        self.assertNotIn('Facebook', inspect.getsource(Phase2Store.current))
        self.assertNotIn('facebook', inspect.getsource(OAuthService.choose_destination).lower())


@unittest.skipUnless(_rev(LIVE_REV), 'the live revision is not in this clone (shallow checkout)')
class FacebookMatchesLive(unittest.TestCase):
    """FB-1, differential: the same probe with the live tree and with this tree gives the same record, including for a
    post approved on the live build and then handled by this build (the promotion case)."""

    @classmethod
    def setUpClass(cls):
        live = LiveTree.get()
        cls.live = _probe('rc2_facebook_probe.py', live)
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump(cls.live['approvedState'], handle)
        try:
            cls.live = _probe('rc2_facebook_probe.py', live, handle.name)
            cls.mine = _probe('rc2_facebook_probe.py', ROOT, handle.name)
        finally:
            os.unlink(handle.name)

    def test_reviews_approvals_and_invalidation_are_identical_to_live(self):
        self.assertEqual(self.live['scenarios']['liveChannel']['afterClaimInvalidation'], LIVE_JOB)
        for name in ('liveChannel', 'channelWithPageId'):
            with self.subTest(channel=name):
                self.assertEqual(json.dumps(self.mine['scenarios'][name], sort_keys=True),
                                 json.dumps(self.live['scenarios'][name], sort_keys=True))

    def test_a_post_approved_on_live_is_kept_by_this_build(self):
        self.assertEqual(self.live['carried'], {'current': True, 'afterInvalidate': LIVE_JOB, 'afterClaimInvalidation': LIVE_JOB})
        self.assertEqual(self.mine['carried'], self.live['carried'])

    def test_choosing_a_facebook_page_is_identical_to_live(self):
        self.assertEqual(json.dumps(self.mine['choosePage'], sort_keys=True), json.dumps(self.live['choosePage'], sort_keys=True))

    def test_no_other_facebook_code_differs_from_live(self):
        """The only Facebook-specific line in the src/ and api/ difference to live is the Discord-only public connection
        review helper (connection_review.py, called from discord/oauth.py alone)."""
        done = subprocess.run(['git', '-C', str(ROOT), 'diff', LIVE_REV, '--', 'src', 'api'], capture_output=True, text=True, check=True)
        files, hits = None, []
        for line in done.stdout.splitlines():
            if line.startswith('diff --git'):
                files = line.split(' b/')[-1]
            elif line[:1] in '+-' and not line.startswith(('+++', '---')) and 'facebook' in line.lower():
                hits.append(files)
        self.assertEqual(sorted(set(hits)), ['src/postriff_phase2/connection_review.py'], hits)
        callers = subprocess.run(['git', '-C', str(ROOT), 'grep', '-l', 'public_connection_review', '--', 'src', 'api'],
                                 capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(callers), ['src/postriff_phase2/connection_review.py', 'src/postriff_phase2/discord/oauth.py'])


if __name__ == '__main__':
    unittest.main()
