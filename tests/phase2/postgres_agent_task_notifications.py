"""Real PostgreSQL task/outbox integration. Synthetic task state; no network delivery."""
import unittest
from unittest.mock import patch

import postgres_agent_task_engine as fixture
from postriff_phase2.agent_runtime_v2.task_engine import notifications
from postriff_phase2.coworker import flags as notification_flags
from postriff_phase2.notifications.service import NotificationService
from postriff_phase2.notifications import store as notification_store


class TaskNotificationPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TaskEnginePG.setUpClass()
        cls.helper = fixture.TaskEnginePG()
        cls.service = cls.helper.service
        cls.runtime = cls.helper.runtime
        cls.w = cls.helper.w
        cls.prior_flags = notification_flags._values
        notification_flags.attach({'RAFII_NOTIFICATIONS_V2_ENABLED': '1'})
        cls.service.notifications = NotificationService(cls.service)

    @classmethod
    def tearDownClass(cls):
        notification_flags.attach(cls.prior_flags)
        fixture.TaskEnginePG.tearDownClass()

    def setUp(self):
        with fixture.connect() as db:
            db.execute('DELETE FROM public.pr_notification_events WHERE workspace_id=%s', (self.w,))
            db.execute('DELETE FROM public.pr_notification_preferences WHERE user_id IN (%s,%s)', (fixture.A, fixture.B))
            db.execute("UPDATE public.pr_agent_tasks SET state='cancelled',finished_at=now(),next_wake_at=NULL WHERE workspace_id=%s", (self.w,))
            db.execute("UPDATE public.pr_memberships SET status='active' WHERE workspace_id=%s AND user_id IN (%s,%s)", (self.w, fixture.A, fixture.B))

    def task(self, state='completed', actor=fixture.A):
        task = self.helper.create(actor=actor)
        with fixture.connect() as db:
            db.execute('UPDATE public.pr_agent_tasks SET state=%s,finished_at=CASE WHEN %s THEN now() ELSE NULL END,updated_at=now() WHERE id=%s', (state, state in ('completed', 'failed', 'cancelled'), task['taskId']))
        return task

    def rows(self):
        with fixture.connect() as db:
            return db.execute('SELECT e.event_type,e.payload,d.user_id::text,d.channel,d.status FROM public.pr_notification_events e LEFT JOIN public.pr_notification_deliveries d ON d.event_id=e.id WHERE e.workspace_id=%s ORDER BY e.created_at', (self.w,)).fetchall()

    def test_creator_only_exact_link_and_single_delivery(self):
        task = self.task(actor=fixture.B)
        self.assertEqual(notifications.scan(self.runtime)['created'], 1)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2:], (fixture.B, 'in_app', 'delivered'))
        self.assertEqual(rows[0][1]['href'], '/app/tasks?task=' + task['taskId'])
        self.assertNotIn('Engine test', str(rows))
        self.assertEqual(notifications.scan(self.runtime)['created'], 0)

    def test_new_state_version_has_one_new_notice(self):
        task = self.task('blocked')
        notifications.scan(self.runtime)
        with fixture.connect() as db:
            db.execute("UPDATE public.pr_agent_tasks SET state='completed',finished_at=now(),version=version+1,updated_at=now() WHERE id=%s", (task['taskId'],))
        self.assertEqual(notifications.scan(self.runtime)['created'], 1)
        self.assertEqual([r[0] for r in self.rows()], ['agent.task_blocked', 'agent.task_completed'])

    def test_revoked_creator_not_notified_or_shown_prior_notice(self):
        self.task(actor=fixture.B)
        notifications.scan(self.runtime)
        self.task('failed', actor=fixture.B)
        with fixture.connect() as db:
            db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (self.w, fixture.B))
        self.assertEqual(notifications.scan(self.runtime)['created'], 0)
        with fixture.connect() as db, db.cursor() as cur:
            self.assertEqual(notification_store.center(cur, fixture.B, self.w)['items'], [])

    def test_opt_out_respected_without_external_delivery(self):
        self.task()
        self.service.notifications.set_preference(self.w, fixture.OWNER, {'category': 'automation', 'in_app': False})
        self.assertEqual(notifications.scan(self.runtime)['created'], 1)
        rows = self.rows()
        self.assertTrue(all(r[3] is None or r[3] == 'in_app' for r in rows))
        self.assertTrue(all(r[4] != 'delivered' for r in rows))

    def test_other_workspace_and_shadow_emit_nothing(self):
        self.task()
        with patch.dict('os.environ', {'RAFII_TASK_ENGINE_WORKSPACES': self.helper.w2}):
            self.assertEqual(notifications.scan(self.runtime)['created'], 0)
        with patch.dict('os.environ', {'RAFII_TASK_ENGINE_AUTHORITATIVE': '0'}):
            self.assertEqual(notifications.scan(self.runtime)['status'], 'disabled')
        self.assertEqual(self.rows(), [])

    def test_outbox_failure_rolls_back_then_retries(self):
        self.task()
        original = self.service.notifications.emit
        def fail_after_write(cur, **event):
            original(cur, **event)
            raise RuntimeError('synthetic outbox failure')
        with patch.object(self.service.notifications, 'emit', side_effect=fail_after_write):
            result = notifications.scan(self.runtime)
        self.assertEqual((result['status'], result['failed']), ('partial', 1))
        self.assertEqual(self.rows(), [])
        self.assertEqual(notifications.scan(self.runtime)['created'], 1)

    def test_budget_exhaustion_does_not_drop_pending_event(self):
        self.task()
        self.assertEqual(notifications.scan(self.runtime, budget_seconds=0)['created'], 0)
        self.assertEqual(notifications.scan(self.runtime)['created'], 1)


if __name__ == '__main__':
    unittest.main()
