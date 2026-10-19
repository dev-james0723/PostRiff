"""Immutable Mastodon media review contracts; no external network calls."""
import unittest
from copy import deepcopy
from unittest.mock import Mock
from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_media import review_media, prepare_library, library_bindings_current


class MediaReviewTests(unittest.TestCase):
    def setUp(self):
        self.images = [{ 'id': str(i) * 32, 'hash': 'a' * 64, 'sourceHash': 'b' * 64,
            'mime': 'image/png', 'bytes': 100, 'width': 10, 'height': 10, 'duration': None,
            'processing': 'decoded', 'deleted': False} for i in range(1, 5)]
        self.state = {'phase2': {'assets': self.images, 'channels': [{'id': 'm', 'platform': 'Mastodon'}]}}
        self.audio = {'id': '5' * 32, 'hash': 'c' * 64, 'mime': 'audio/mpeg', 'bytes': 200,
                      'objectName': '5' * 32 + '.mp3', 'etag': 'synthetic-etag', 'storageKind': 'file', 'normalizedLibrary': True}

    def payload(self, ids):
        return {'attachments': [{'assetId': i, 'alt': 'Description ' + i[0]} for i in ids], 'rightsConfirmed': True}

    def test_four_images_have_individual_frozen_bindings(self):
        media = review_media(self.state, self.payload([a['id'] for a in self.images]))
        self.assertEqual(len(media), 4)
        self.images[0]['hash'] = 'd' * 64
        self.assertEqual(media[0]['hash'], 'a' * 64)
        self.assertEqual(len({a['alt'] for a in media}), 4)

    def test_missing_description_rights_duplicate_or_deleted_image_is_refused(self):
        p = self.payload([self.images[0]['id']])
        bad = [dict(p, rightsConfirmed=False), dict(p, attachments=p['attachments'] * 2),
               dict(p, attachments=[{'assetId': self.images[0]['id'], 'alt': ''}])]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(AlphaError): review_media(self.state, item)
        self.images[0]['deleted'] = True
        with self.assertRaises(AlphaError): review_media(self.state, p)

    def test_one_audio_is_frozen_and_cannot_be_mixed(self):
        p = self.payload([self.audio['id']]); p['_mastodonLibrary'] = {self.audio['id']: self.audio}
        self.assertEqual(review_media(self.state, p)[0]['storageKind'], 'file')
        p['attachments'].append({'assetId': self.images[0]['id'], 'alt': 'Image'})
        with self.assertRaises(AlphaError): review_media(self.state, p)

    def test_untrusted_audio_custody_is_discarded_before_database_lookup(self):
        p = self.payload([self.audio['id']]); p.update(channelId='m', _mastodonLibrary={self.audio['id']: self.audio})
        cur = Mock(); cur.fetchone.return_value = None
        with self.assertRaises(AlphaError): prepare_library(cur, 'workspace', self.state, p)
        self.assertNotIn('_mastodonLibrary', p)

    def test_forged_or_changed_audio_is_refused(self):
        for field, value in [('normalizedLibrary', False), ('storageKind', 'media'), ('hash', 'bad'), ('objectName', '../a.mp3'), ('bytes', True)]:
            audio = {**self.audio, field: value}; p = self.payload([audio['id']]); p['_mastodonLibrary'] = {audio['id']: audio}
            with self.subTest(field=field), self.assertRaises(AlphaError): review_media(self.state, p)
        cur = Mock(); cur.fetchone.return_value = ('audio', 'audio/mpeg', 200, 'd' * 64, self.audio['objectName'], 'synthetic-etag', 'unsupported')
        self.assertFalse(library_bindings_current(cur, 'workspace', {'platform': 'Mastodon', 'media': [{**self.audio, 'rightsConfirmed': True}]}))

    def test_other_platform_and_caller_ambiguous_attachment_input_is_refused(self):
        p = self.payload([self.images[0]['id']]); p['channelId'] = 'other'
        with self.assertRaises(AlphaError): prepare_library(Mock(), 'workspace', self.state, p)
        p['channelId'] = 'm'; p['assetId'] = self.images[0]['id']
        with self.assertRaises(AlphaError): prepare_library(Mock(), 'workspace', self.state, p)
