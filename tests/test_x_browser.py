"""Retired routes cannot touch a browser or claim provider acceptance."""
import unittest
from unittest.mock import Mock
from james_au_social import x_browser


class XBrowserRetirement(unittest.TestCase):
    def test_stale_execute_and_login_are_denied_before_any_ui_action(self):
        ui = Mock()
        with self.assertRaisesRegex(x_browser.Stop, "x_direct_only"):
            x_browser.execute(Mock(), {}, "old-approval", ui)
        with self.assertRaisesRegex(x_browser.Stop, "x_direct_only"):
            x_browser.login("/unused")
        self.assertEqual(ui.mock_calls, [])

    def test_status_never_inherits_historical_browser_success(self):
        value = x_browser.status()
        self.assertEqual(value["route"], "unavailable")
        self.assertFalse(value["publishReady"])
        self.assertFalse(value["publishing"])
        self.assertFalse(value["liveTestVerified"])
        self.assertEqual(value["reasonCode"], "x_direct_only")
