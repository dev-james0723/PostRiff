"""Real-PostgreSQL proof of what a route 429 on a server's first read does (the capacity harness's F429, development run 1028).

The harness injects a 429 on five `GET /guilds/{id}` reads, each the first read of that server, so a cold route. Its answer names
a bucket, a limit of 5, none remaining and a reset in 2 seconds. Four of the five posts were meant to wait two seconds and be
verified; they stayed `scheduled` for twenty minutes and nothing reached Discord after the 429.

The cause is the header, not the route: the harness built the bucket id from its own template, `injected-guilds-{id}`, and the
braces are not part of any Discord bucket id (they are 32 hexadecimal digits). The coordinator learns a bucket id like any other
answer's, but one outside [A-Za-z0-9_-]{1,128} is not an id it can trust, and a route that answered with one is held for an
operator (rate_limits._observe_once: "malformed hints need operator review"), as it holds a route whose numeric hints are
malformed. The hold is one route of one server; every other server is untouched. These tests pin both halves so that neither is
changed by accident: a 429 with a well-formed bucket delays the post and it is verified, and a 429 with a malformed one holds that
one route, sends nothing, shows in the health payload and lets the post through once an operator releases the hold.

Runs where POSTRIFF_PG_BIN names the PostgreSQL server binaries. Synthetic tenants only; no network.
"""
import json
import unittest

import discord_lane_fixture as F
from postriff_phase2.discord import ops

INJECTED = 'injected-guilds'


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class RouteRateLimitOnAColdServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()

    def start(self, bucket):
        """Two servers with one post each. The first read of the first server is answered with a 429 naming `bucket`."""
        self.tenants = [F.Tenant(0), F.Tenant(1)]
        self.target, self.other = self.tenants
        F.seed(self.cluster, self.tenants, 1)
        self.wire = F.MockDiscord(self.tenants)
        self.injected = []
        path = '/guilds/%s' % self.target.guild

        def fail(method, requested):
            if method == 'GET' and requested == path and not self.injected:
                self.injected.append(requested)
                return {'status': 429,
                        'headers': {'x-ratelimit-bucket': bucket, 'x-ratelimit-limit': '5', 'x-ratelimit-remaining': '0',
                                    'x-ratelimit-reset-after': '2.000', 'x-ratelimit-scope': 'user', 'retry-after': '2.000'},
                        'body': {'message': 'You are being rate limited.', 'retry_after': 2.0, 'global': False}}
            return None
        self.wire.fail = fail
        self.hosted = F.social(self.cluster, self.tenants, self.wire, capacity=200)
        self.worker = F.base_worker(self.cluster, self.hosted)

    def job_of(self, tenant):
        (job,) = [job for (workspace, _), job in F.jobs(self.cluster).items() if workspace == tenant.id]
        return job

    def guild_reads(self):
        return [call for call in self.wire.calls if call[1] == 'GET' and call[2] == '/guilds/%s' % self.target.guild]

    def holds(self):
        with self.cluster.connect(autocommit=True) as db:
            return db.execute("SELECT count(*) FROM public.pr_discord_rate_state WHERE manual_hold AND kind='route'").fetchone()[0]

    def run_lane(self, seconds=12):
        with F.no_billing():
            results, failures = F.run_lanes(self.worker, 1, seconds=seconds)
        self.assertEqual(failures, [])
        return results[0]

    def make_due(self):
        with self.cluster.connect(autocommit=True) as db:
            for workspace, state in db.execute("SELECT id,state FROM public.pr_workspaces WHERE state ? 'phase2'").fetchall():
                for job in state['phase2']['jobs']:
                    job['nextAt'] = 0
                    job.get('discordWorker', {}).pop('rateDelayedUntil', None)
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
                           (json.dumps(state), workspace))

    def test_a_route_429_with_a_discord_shaped_bucket_delays_the_post_and_it_is_verified(self):
        self.start(INJECTED)
        result = self.run_lane()
        self.assertEqual(len(self.injected), 1, 'the 429 was served')
        self.assertGreaterEqual(result['counters']['rateDelayed'], 1, 'and the post was released unsent by it')
        for tenant in self.tenants:
            self.assertEqual(self.job_of(tenant)['state'], 'verified')
        self.assertEqual(len(self.guild_reads()), 2, 'the 429 and the read that followed two seconds later')
        self.assertEqual(self.holds(), 0, 'a well-formed bucket id is learned, never held')
        self.assertEqual(len(self.wire.requests(method='POST')), 2, 'each post was created once')
        self.assertEqual(self.wire.duplicates(), 0)

    def test_a_route_429_with_a_bucket_that_is_not_a_discord_id_holds_that_one_route_until_an_operator_releases_it(self):
        self.start(INJECTED + '-{id}')    # what the capacity harness's mock sent
        self.run_lane()
        self.assertEqual(self.job_of(self.other)['state'], 'verified', 'the other server is untouched')
        held = self.job_of(self.target)
        self.assertEqual(held['state'], 'scheduled', 'the post waits, unsent: it is not failed and not uncertain')
        self.assertEqual(len(self.wire.requests(method='POST')), 1, 'only the other server was posted to')
        self.assertEqual(len(self.guild_reads()), 1, 'nothing reached Discord for that server after the 429')
        self.assertGreaterEqual(self.holds(), 1)
        with self.cluster.connect(autocommit=True) as db, db.cursor() as cur:
            health = ops.read_coordinator(cur, self.cluster.now(), {'provider': self.hosted.providers['discord']})
        self.assertGreaterEqual(health['kinds']['route']['holds'], 1, 'the health payload shows the hold')
        for _ in range(2):    # being due again changes nothing while the hold stands
            self.make_due()
            self.run_lane(seconds=8)
            self.assertEqual(self.job_of(self.target)['state'], 'scheduled')
            self.assertEqual(len(self.guild_reads()), 1)
        with self.cluster.connect(autocommit=True) as db:    # the runbook's release of a held route
            db.execute('UPDATE public.pr_discord_rate_state SET manual_hold=false WHERE manual_hold')
        self.make_due()
        self.run_lane()
        self.assertEqual(self.job_of(self.target)['state'], 'verified', 'after the release the post goes through')
        self.assertEqual(len(self.wire.requests(method='POST')), 2)
        self.assertEqual(self.wire.duplicates(), 0)


if __name__ == '__main__':
    unittest.main()
