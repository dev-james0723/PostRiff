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

    def test_advertised_profile_limits_and_description_api_version(self):
        caps = {'version': '4.6.1', 'profileLimits': {'max_display_name_length': 60, 'max_note_length': 600,
            'max_profile_fields': 6, 'profile_field_name_limit': 64, 'profile_field_value_limit': 255,
            'max_avatar_description_length': 120, 'max_header_description_length': 120}}
        fields = {'display_name': 'n' * 60, 'note': 'b' * 600, 'avatar_description': 'a' * 120,
                  'header_description': 'h' * 120, 'fields_attributes': [{'name': 'n' * 64, 'value': 'v' * 255}] * 6}
        self.assertEqual(profile_fields({'profile': fields}, caps), fields)
        for key, value in [('display_name', 'x' * 61), ('note', 'x' * 601), ('avatar_description', 'x' * 121),
                           ('header_description', 'x' * 121), ('fields_attributes', fields['fields_attributes'] * 2),
                           ('fields_attributes', [{'name': 'x' * 65, 'value': ''}]),
                           ('fields_attributes', [{'name': '', 'value': 'x' * 256}])]:
            with self.subTest(key=key), self.assertRaises(AlphaError):
                profile_fields({'profile': {key: value}}, caps)
        for version in ('4.3.7', '4.6.0'):
            with self.subTest(version=version), self.assertRaises(AlphaError):
                profile_fields({'profile': {'avatar_description': 'Reviewed description'}}, {**caps, 'version': version})

    def test_explicit_clear_is_encoded_without_clearing_unselected_fields(self):
        fields = {'source': {'language': ''}, 'fields_attributes': [], 'attribution_domains': []}
        self.assertEqual(profile_fields({'profile': fields}, {'version': '4.6.1'}), fields)
        flat = form_fields(fields)
        self.assertIn(('source[language]', ''), flat)
        self.assertIn(('fields_attributes[0][name]', ''), flat)
        self.assertIn(('attribution_domains[]', ''), flat)
        self.assertFalse(any(key in ('display_name', 'note', 'avatar', 'header') for key, _ in flat))
        self.assertEqual(profile_fields({'profile': {'source': {'privacy': 'private'}}}, {'version': '2.4.0'}), {'source': {'privacy': 'private'}})
        with self.assertRaises(AlphaError): profile_fields({'profile': {'source': {'language': ''}}}, {'version': '2.4.0'})
