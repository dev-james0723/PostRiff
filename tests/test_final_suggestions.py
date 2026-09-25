"""FINAL-08: suggestions are evidence-based, say when they were last checked, and do not nag.

- A confirmed campaign date within 14 days with no draft yet is suggested (with the date and days left).
- A brief with drafts for some connected, ready accounts but not another is suggested for that account.
- The check time is recorded; a dismissed suggestion does not come back for 7 days just because its
  evidence revision changed. Reusable images are described as unused, not as "approved".
- No suggestion is inferred from analytics or posting-time guesses.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase2 import suggestions

DAY = 86400
NOW = 1_900_000_000.0


def state(**extra):
    base = {'workspace': {'id': 'w1'}, 'brief': {'revision': 3, 'idea': 'Spring recital'}, 'variants': [], 'phase2': {'jobs': [], 'assets': [], 'channels': []}, 'raffi': {'campaignPlanning': {'campaigns': []}}}
    base.update(extra)
    return base


def ready(cid, platform, account):
    return {'id': cid, 'platform': platform, 'account': account, 'identityVerified': True, 'capabilityVerified': True, 'revoked': False, 'expiresAt': NOW + DAY}


class Suggestions(unittest.TestCase):
    def kinds(self, s):
        return sorted(item['kind'] for item in suggestions.refresh(s, NOW) if item['status'] == 'open')

    def test_upcoming_confirmed_date_is_suggested_with_days_left(self):
        date = '2030-03-17'  # NOW is 2030-03-17T17:46Z, so the date is today
        soon = {'id': 'c1', 'version': 2, 'status': 'draft', 'items': [], 'goal': 'Recital', 'facts': {'date': '2030-03-24'}}
        later = {'id': 'c2', 'version': 1, 'status': 'draft', 'items': [], 'goal': 'Autumn tour', 'facts': {'date': '2030-09-01'}}
        s = state(raffi={'campaignPlanning': {'campaigns': [soon, later]}})
        items = [i for i in suggestions.refresh(s, NOW) if i['status'] == 'open']
        upcoming = [i for i in items if i['kind'] == 'upcoming_event']
        self.assertEqual(len(upcoming), 1)
        self.assertIn('2030-03-24', upcoming[0]['reason'])
        self.assertIn('7 days', upcoming[0]['reason'])
        self.assertEqual({i['evidence'][0]['id'] for i in items if i['kind'] == 'campaign_gap'}, {'c2'}, 'the dated campaign is not suggested twice')
        del date

    def test_missing_variant_for_a_ready_account(self):
        s = state()
        s['phase2']['channels'] = [ready('a', 'LinkedIn', 'Me'), ready('b', 'Threads', '@me')]
        s['variants'] = [{'id': 'v1', 'platform': 'LinkedIn', 'channelId': 'a', 'language': 'en-US', 'briefRevision': 3}]
        items = [i for i in suggestions.refresh(s, NOW) if i['kind'] == 'missing_variant']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['evidence'][0], {'type': 'channel', 'id': 'b', 'revision': 3})
        self.assertIn('@me', items[0]['reason'])
        s['variants'].append({'id': 'v2', 'platform': 'Threads', 'channelId': 'b', 'language': 'en-US', 'briefRevision': 3})
        self.assertEqual([i for i in suggestions.refresh(s, NOW) if i['kind'] == 'missing_variant' and i['status'] == 'open'], [])

    def test_check_time_and_dismiss_cooldown(self):
        s = state()
        s['phase2']['jobs'] = [{'id': 'j1', 'state': 'held', 'events': [{}]}]
        item = next(i for i in suggestions.refresh(s, NOW) if i['kind'] == 'held_draft')
        self.assertEqual(s['raffi']['suggestionsCheckedAt'], NOW)
        suggestions.apply_action(s, 'raffi_suggestion_dismiss', {'suggestionId': item['id']}, 'actor', NOW)
        s['phase2']['jobs'][0]['events'].append({})  # the same held job gains an event: a new evidence revision
        self.assertEqual(self.kinds(s), [], 'dismissed within 7 days: not suggested again')
        later = [i for i in suggestions.refresh(s, NOW + 8 * DAY) if i['status'] == 'open' and i['kind'] == 'held_draft']
        self.assertEqual(len(later), 1)

    def test_unused_image_wording_is_accurate(self):
        s = state()
        s['phase2']['assets'] = [{'id': 'a1', 'processing': 'decoded', 'deleted': False}]
        item = next(i for i in suggestions.refresh(s, NOW) if i['kind'] == 'unused_asset')
        self.assertNotIn('approved', item['reason'].lower())


if __name__ == '__main__':
    unittest.main()
