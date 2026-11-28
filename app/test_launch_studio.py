"""Run with python3 -m unittest app.test_launch_studio from the repository root."""

from contextlib import ExitStack, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import signal
import sys
import unittest
from unittest.mock import Mock, call, patch

with patch.object(sys, "path", [str(Path(__file__).resolve().parent), *sys.path]):
    import launch_studio as launcher


class LocalPreviewSwitchTests(unittest.TestCase):
    pid = 12345

    def setUp(self):
        mocks = ExitStack()
        self.addCleanup(mocks.close)
        mocks.enter_context(redirect_stdout(StringIO()))
        self.terminal = mocks.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        self.answer = mocks.enter_context(patch("builtins.input", return_value="yes"))
        self.owner = mocks.enter_context(patch.object(launcher, "local_preview_pid", return_value=self.pid))
        self.listener = mocks.enter_context(patch.object(launcher, "listener_pid", return_value=None))
        self.kill = mocks.enter_context(patch.object(launcher.os, "kill"))
        mocks.enter_context(patch.object(launcher.time, "sleep"))

    def test_confirmed_switch_signals_verified_web_child_and_waits_for_release(self):
        for answer in ("y", "yes"):
            with self.subTest(answer=answer):
                self.answer.return_value = answer
                self.listener.side_effect = [self.pid, None]
                self.assertTrue(launcher.release_local_preview(self.pid))
                self.kill.assert_called_once_with(self.pid, signal.SIGTERM)
                self.assertEqual(self.listener.call_args_list,
                                 [call(47632, launcher.APP.parent / "web")] * 2)
                self.owner.assert_called()
                self.kill.reset_mock()
                self.listener.reset_mock()
                self.owner.reset_mock()

    def test_blank_or_declined_answer_keeps_preview_running(self):
        for answer in ("", "no", "maybe"):
            with self.subTest(answer=answer):
                self.answer.return_value = answer
                self.assertFalse(launcher.release_local_preview(self.pid))
                self.kill.assert_not_called()

    def test_unattended_launch_cannot_switch(self):
        self.terminal.return_value = False
        with self.assertRaises(RuntimeError):
            launcher.release_local_preview(self.pid)
        self.answer.assert_not_called()
        self.kill.assert_not_called()

    def test_denied_switch_explains_how_to_close_the_current_studio(self):
        self.kill.side_effect = PermissionError("Operation not permitted")
        with self.assertRaisesRegex(RuntimeError, "Save your work.*original Terminal window"):
            launcher.release_local_preview(self.pid)
        self.kill.assert_called_once_with(self.pid, signal.SIGTERM)
        self.listener.assert_not_called()

    def test_changed_preview_is_left_alone(self):
        self.owner.return_value = self.pid + 1
        with self.assertRaises(RuntimeError):
            launcher.release_local_preview(self.pid)
        self.kill.assert_not_called()

    def test_unrecognized_listener_is_left_alone(self):
        self.owner.side_effect = RuntimeError("Port is owned by a different app.")
        with self.assertRaises(RuntimeError):
            launcher.release_local_preview(self.pid)
        self.kill.assert_not_called()

    def test_preview_closed_during_confirmation_needs_no_signal(self):
        self.owner.return_value = None
        self.assertTrue(launcher.release_local_preview(self.pid))
        self.kill.assert_not_called()

    def test_new_listener_during_shutdown_is_left_alone(self):
        self.listener.side_effect = [self.pid, self.pid + 1]
        with self.assertRaises(launcher.OtherListener):
            launcher.release_local_preview(self.pid)
        self.kill.assert_called_once_with(self.pid, signal.SIGTERM)


class ConnectedStartupTests(unittest.TestCase):
    def setUp(self):
        mocks = ExitStack()
        self.addCleanup(mocks.close)
        mocks.enter_context(redirect_stdout(StringIO()))
        mocks.enter_context(patch.object(sys, "argv", ["launch_studio.py"]))
        mocks.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        mocks.enter_context(patch.object(launcher, "IS_LOCAL", False))
        mocks.enter_context(patch.object(launcher, "WEB", launcher.STAGING_SITE))
        mocks.enter_context(patch.object(launcher.fcntl, "flock"))
        mocks.enter_context(patch.object(Path, "is_file", return_value=True))
        self.answer = mocks.enter_context(patch("builtins.input", return_value="yes"))
        self.kill = mocks.enter_context(patch.object(launcher.os, "kill"))
        self.launch = mocks.enter_context(patch.object(launcher.subprocess, "Popen"))
        self.launch.return_value.poll.return_value = None
        self.command = mocks.enter_context(patch.object(launcher.subprocess, "run"))
        self.settings = mocks.enter_context(patch.object(launcher, "check_built_settings"))
        mocks.enter_context(patch.object(launcher, "public_settings", return_value="example-key"))
        self.pid = 12345
        mocks.enter_context(patch.object(launcher, "listener_pid", side_effect=self.existing_listener))

        local_manifest = (launcher.SITE + "/local/_buildManifest.js", b"local")
        connected_manifest = (launcher.SITE + "/connected/_buildManifest.js", b"connected")
        manifests = {launcher.APP.parent / "web": local_manifest, launcher.STAGING_SITE: connected_manifest}
        mocks.enter_context(patch.object(launcher, "build_manifest", side_effect=manifests.__getitem__))
        self.auth_url = launcher.SITE + "/api/auth/config"
        self.resources = dict((local_manifest, connected_manifest))
        self.resources[self.auth_url] = json.dumps({"provider": "supabase", "projectUrl": launcher.SUPABASE_URL}).encode()
        mocks.enter_context(patch.object(launcher, "read_url", side_effect=self.resources.__getitem__))
        sample = Mock(status=200, headers={"X-Rafii-Studio-View": "sample"})
        sample.geturl.return_value = launcher.EDITOR
        sign_in = Mock(status=200, headers={})
        sign_in.geturl.return_value = launcher.SITE + "/auth/sign-in"
        pages = mocks.enter_context(patch.object(launcher.LOCAL, "open"))
        pages.return_value.__enter__.side_effect = [sample, sample, sign_in]

    def existing_listener(self, port, directory):
        self.assertEqual(port, 47632)
        if self.kill.called:
            return None
        if directory == launcher.APP.parent / "web":
            return self.pid
        raise launcher.OtherListener("Local Studio owns the port")

    def test_switch_opens_connected_editor_after_readiness(self):
        launcher.start()
        self.settings.assert_called_once_with("example-key")
        self.kill.assert_called_once_with(self.pid, signal.SIGTERM)
        self.launch.assert_called_once_with([launcher.APP / "Start Rafii Studio.command", "--serve-web"])
        self.command.assert_called_once_with(["/usr/bin/open", launcher.EDITOR], check=True)

    def test_failed_staging_preflight_leaves_preview_running(self):
        self.settings.side_effect = ValueError("The connected build is out of date")
        with self.assertRaises(ValueError):
            launcher.start()
        self.answer.assert_not_called()
        self.kill.assert_not_called()
        self.launch.assert_not_called()
        self.command.assert_not_called()

    def test_wrong_workspace_cannot_open_browser(self):
        self.resources[self.auth_url] = b'{"provider": "dev", "execution": "dev-synthetic"}'
        with self.assertRaisesRegex(RuntimeError, "different workspace"):
            launcher.start()
        self.command.assert_not_called()

    def start_on_existing_staging(self, *flags):
        sys.argv[:] = ["launch_studio.py", "--edit", *flags]
        self.staging_listener = patch.object(launcher, "listener_pid", return_value=self.pid)
        self.staging_listener.start()
        self.addCleanup(self.staging_listener.stop)

    def test_open_current_editor_reuses_running_site(self):
        self.start_on_existing_staging()
        with patch.object(launcher, "has_local_editor", return_value=True):
            launcher.start()
        self.command.assert_called_once_with(["/usr/bin/open", launcher.LOCAL_EDIT], check=True)
        self.launch.assert_not_called()
        self.kill.assert_not_called()

    def test_legacy_site_is_preserved_on_unattended_check(self):
        self.start_on_existing_staging("--no-open")
        with patch.object(launcher, "has_local_editor", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "earlier Studio"):
                launcher.start()
        self.command.assert_not_called()
        self.answer.assert_not_called()
        self.kill.assert_not_called()

    def test_legacy_site_remains_available_if_new_bundle_fails(self):
        self.start_on_existing_staging()
        self.command.side_effect = launcher.subprocess.CalledProcessError(1, "build")
        with patch.object(launcher, "has_local_editor", return_value=False):
            with self.assertRaises(launcher.subprocess.CalledProcessError):
                launcher.start()
        self.command.assert_called_once_with([launcher.APP / "Start Rafii Studio.command", "--build-editor"], check=True)
        self.answer.assert_not_called()
        self.kill.assert_not_called()

    def test_legacy_site_is_preserved_when_person_is_still_editing(self):
        self.start_on_existing_staging()
        self.answer.return_value = ""
        with patch.object(launcher, "has_local_editor", return_value=False):
            launcher.start()
        self.answer.assert_called_once()
        self.launch.assert_not_called()
        self.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
