"""FINAL-09: LinkedIn stores post commentary as `little` text, where | { } @ [ ] ( ) < > # \\ * _ ~ are
reserved and must be backslash-escaped to stay plain text (official little-text format, updated 2025-10-16).
Sending the approved caption raw lets LinkedIn read "(" or "@" as markup, so the post could differ from what
was approved. A '#' that starts a word stays a hashtag (same visible characters). Read-back compares the
plain rendering with the approved text."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.provider_candidates import little_plain, little_text
from test_postriff_providers import FakeOAuth, Recorder, ReviewedProvider, manifest

CAPTION = 'Spring recital (free entry) with @friends — ask me [anything] <3 #music *live* ~5pm_ok \\ done | {x}'


class LittleText(unittest.TestCase):
    def test_reserved_characters_are_escaped_and_hashtags_kept(self):
        escaped = little_text(CAPTION)
        self.assertIn('\\(free entry\\)', escaped)
        self.assertIn('\\@friends', escaped)
        self.assertIn('\\[anything\\]', escaped)
        self.assertIn('\\<3', escaped)
        self.assertIn(' #music ', escaped, 'a word hashtag stays a hashtag')
        self.assertIn('\\*live\\*', escaped)
        self.assertIn('\\~5pm\\_ok', escaped)
        self.assertIn(' \\\\ done \\| \\{x\\}', escaped)
        self.assertEqual(little_text('# alone and C#'), '\\# alone and C\\#')
        self.assertEqual(little_plain(escaped), CAPTION)
        self.assertEqual(little_plain('Hello {hashtag|\\#|music} world'), 'Hello #music world')

    def test_submit_sends_little_text_and_reconcile_accepts_the_stored_form(self):
        providers = {'linkedin': ReviewedProvider()}
        m = manifest()
        m['payload']['text'] = CAPTION
        transport = Recorder([
            {'status': 201, 'headers': {'x-restli-id': 'urn:li:share:9'}, 'body': {}},
            {'status': 200, 'headers': {}, 'body': {'lifecycleState': 'PUBLISHED', 'commentary': little_text(CAPTION).replace('#music', '{hashtag|\\#|music}')}},
        ])
        social = HostedSocial(FakeOAuth(), providers, transport=transport)
        self.assertEqual(social.submit(m)['state'], 'provider_accepted')
        self.assertEqual(transport.calls[0]['body']['commentary'], little_text(CAPTION))
        self.assertEqual(social.reconcile(m, {'providerReference': 'urn:li:share:9'})['state'], 'verified')


if __name__ == '__main__':
    unittest.main()
