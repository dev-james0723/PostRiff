"""Synthetic thumbnail readback truth; never calls Google or repeats writes."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_phase2.youtube.service import YouTubeCreatorService


class ThumbnailReceiptTests(unittest.TestCase):
    def test_stable_resource_url_is_not_image_content_verification(self):
        url = 'https://i.ytimg.com/vi/synthetic01/default.jpg'
        api = SimpleNamespace(owned=Mock(return_value={'id': 'synthetic01',
            'snippet': {'thumbnails': {'default': {'url': url}}}}),
            call=Mock(side_effect=AssertionError('A readback must not repeat the write')))
        result = YouTubeCreatorService.verify_action(api,
            {'method': 'thumbnails.set', 'params': {'videoId': 'synthetic01'}},
            {'items': [{'default': {'url': url}}]})
        self.assertTrue(result['resourceObserved'])
        self.assertFalse(result['verified'])
        self.assertFalse(result['contentVerified'])
        api.owned.assert_called_once_with('videos', 'synthetic01')
        api.call.assert_not_called()

    def test_different_video_or_missing_urls_are_not_observed(self):
        for current, result in [
            ({'id': 'foreign0001', 'snippet': {'thumbnails': {'default': {'url': 'same'}}}},
             {'items': [{'default': {'url': 'same'}}]}),
            ({'id': 'synthetic01', 'snippet': {}}, {'items': []}),
        ]:
            with self.subTest(current=current):
                receipt = YouTubeCreatorService.verify_action(SimpleNamespace(owned=Mock(return_value=current)),
                    {'method': 'thumbnails.set', 'params': {'videoId': 'synthetic01'}}, result)
                self.assertFalse(receipt['resourceObserved'])
                self.assertFalse(receipt['verified'])
                self.assertFalse(receipt['contentVerified'])


if __name__ == '__main__':
    unittest.main()
