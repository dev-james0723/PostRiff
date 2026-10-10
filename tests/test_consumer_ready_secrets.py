"""Fail-closed tests for generated checksums in the offline source secret scan."""
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from consumer_ready_secrets import CREATION_CATALOG, is_generated_creation_skill_digest  # noqa: E402

HEX_LINE = re.compile(r'\s*"sha256": "([a-f0-9]{64})",?\s*')


def finding(line, digest, path=CREATION_CATALOG, kind='Hex High Entropy String'):
    return {
        'path': path, 'line': line, 'type': kind,
        'hash': hashlib.sha1(digest.encode('ascii')).hexdigest(),
    }


def digest_lines(source):
    for number, line in enumerate(source.splitlines(), 1):
        match = HEX_LINE.fullmatch(line)
        if match:
            yield number, match.group(1)


class GeneratedCreationDigestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = (ROOT / CREATION_CATALOG).read_text(encoding='utf-8')
        cls.platforms = json.loads(cls.catalog)['platforms']
        cls.digests = list(digest_lines(cls.catalog))

    def test_every_canonical_platform_skill_checksum_is_accepted(self):
        self.assertEqual(len(self.platforms), len(self.digests))
        self.assertGreater(len(self.digests), 0)
        for number, digest in self.digests:
            with self.subTest(line=number):
                self.assertTrue(is_generated_creation_skill_digest(finding(number, digest), self.catalog))

    def test_scope_and_hash_must_match_exactly(self):
        number, digest = self.digests[0]
        good = finding(number, digest)
        for bad in (
            dict(good, path='web/tests/fixtures/other.json'),
            dict(good, type='Other Detector'),
            dict(good, line=0),
            dict(good, line=len(self.catalog.splitlines()) + 1),
            dict(good, line='34'),
            dict(good, hash='f' * 40),
        ):
            with self.subTest(bad=bad):
                self.assertFalse(is_generated_creation_skill_digest(bad, self.catalog))

    def test_unrelated_sha256_fields_still_fail_secret_scan(self):
        doc = json.loads(self.catalog)
        rogue_digest = 'a' * 64
        self.assertNotIn(rogue_digest, [p['skill']['sha256'] for p in self.platforms])
        doc['secret_like_metadata'] = {'sha256': rogue_digest}
        data = json.dumps(doc, indent=2)
        rogue_line = next(number for number, digest in digest_lines(data) if digest == rogue_digest)
        self.assertFalse(is_generated_creation_skill_digest(finding(rogue_line, rogue_digest), data))
        doc['secret_like_metadata'] = {'accessToken': rogue_digest}
        data = json.dumps(doc, indent=2)
        token_line = next(i for i, line in enumerate(data.splitlines(), 1) if '"accessToken"' in line)
        self.assertFalse(is_generated_creation_skill_digest(finding(token_line, rogue_digest), data))

    def test_invalid_schema_or_untrusted_skill_identity_is_rejected(self):
        number, digest = self.digests[0]
        bad_schema = self.catalog.replace(
            '"schema": "rafii.creation-capabilities.v1"', '"schema": "other"', 1
        )
        self.assertFalse(is_generated_creation_skill_digest(finding(number, digest), bad_schema))
        doc = json.loads(self.catalog)
        doc['platforms'][0]['skill']['id'] = 'external-secret'
        data = json.dumps(doc, indent=2)
        new_line = next(i for i, value in digest_lines(data) if value == digest)
        self.assertFalse(is_generated_creation_skill_digest(finding(new_line, digest), data))

    def test_malformed_and_duplicated_digest_is_not_exempted(self):
        number, digest = self.digests[0]
        self.assertFalse(is_generated_creation_skill_digest(finding(number, digest), '{ invalid'))
        doc = json.loads(self.catalog)
        doc['platforms'][1]['skill']['sha256'] = digest
        data = json.dumps(doc, indent=2)
        repeated = next(i for i, value in digest_lines(data) if value == digest)
        self.assertFalse(is_generated_creation_skill_digest(finding(repeated, digest), data))


if __name__ == '__main__':
    unittest.main()
