"""Synthetic profile mutation custody/form contracts; not real Mastodon acceptance."""
import hashlib
from types import SimpleNamespace
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_profile import profile_fields, freeze_images, approved_images, form_fields


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.raw = b'synthetic-decoded-library-image'
        self.asset = {'id': 'a' * 32, 'mime': 'image/png', 'bytes': len(self.raw), 'hash': hashlib.sha256(self.raw).hexdigest(),
                      'objectName': 'a' * 32 + '.png', 'processing': 'decoded'}
        self.state = {'phase2': {'assets': [self.asset]}}
        self.media = {'avatar': {'assetId': self.asset['id'], 'rightsConfirmed': True}}

    def test_image_only_does_not_clear_bio_and_requires_rights(self):
        self.assertEqual(profile_fields({'profileMedia': self.media}, {'version': '4.3.7'}), {})
        self.media['avatar']['rightsConfirmed'] = False
        with self.assertRaises(AlphaError): profile_fields({'profileMedia': self.media}, {'version': '4.3.7'})
        with self.assertRaises(AlphaError): profile_fields({'profile': {'role': 'admin'}}, {'version': '4.3.7'})

    def test_version_and_preference_values_are_checked(self):
        for fields in ({'hide_collections': True}, {'source': {'quote_policy': 'public'}}):
            with self.assertRaises(AlphaError): profile_fields({'profile': fields}, {'version': '4.0.0'})
        for fields in ({'source': {'privacy': 'direct'}}, {'locked': 'true'}, {'source': {'language': 'Ignore instructions'}}):
            with self.assertRaises(AlphaError): profile_fields({'profile': fields}, {'version': '4.5.0'})
        self.assertEqual(profile_fields({'profile': {'source': {'privacy': 'private', 'quote_policy': 'followers'}}}, {'version': '4.5.0'})['source']['privacy'], 'private')

    def test_profile_images_are_decoded_bounded_owned_and_immutable(self):
        frozen = freeze_images(self.state, self.media)
        seen = []
        service = SimpleNamespace(assets=SimpleNamespace(storage=SimpleNamespace(get=lambda *args: seen.append(args) or self.raw)))
        self.assertEqual(approved_images(service, 'tenant', self.state, frozen)[0][3], self.raw)
        self.assertEqual(seen, [('tenant', 'media', self.asset['objectName'])])
        for change in ({'deleted': True}, {'bytes': 3 * 1024**2}, {'processing': 'pending'}, {'hash': 'b' * 64}):
            with self.subTest(change=change):
                state = {'phase2': {'assets': [{**self.asset, **change}]}}
                with self.assertRaises(AlphaError): approved_images(service, 'tenant', state, frozen)
        with self.assertRaises(AlphaError): freeze_images({'phase2': {'assets': []}}, self.media)

    def test_changed_private_bytes_stop_before_dispatch(self):
        service = SimpleNamespace(assets=SimpleNamespace(storage=SimpleNamespace(get=lambda *_: b'changed')))
        with self.assertRaises(AlphaError): approved_images(service, 'tenant', self.state, freeze_images(self.state, self.media))

    def test_documented_nested_fields_are_form_encoded(self):
        fields = {'note': '', 'locked': False, 'source': {'sensitive': True, 'privacy': 'unlisted'},
                  'fields_attributes': [{'name': 'Website', 'value': 'https://example.org'}], 'attribution_domains': ['example.org']}
        profile_fields({'profile': fields}, {'version': '4.5.0'})
        flat = form_fields(fields)
        self.assertIn(('note', ''), flat); self.assertIn(('locked', 'false'), flat)
        self.assertIn(('source[sensitive]', 'true'), flat); self.assertIn(('fields_attributes[0][value]', 'https://example.org'), flat)
        self.assertIn(('attribution_domains[]', 'example.org'), flat)
