"""Synthetic metadata/archive fixtures; no hosted deployment or provider I/O."""
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from package_output import INPUTS, PUBLIC_KEYS, PackageRejected, trusted_context, write_output

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40
ENV = {
    "VERCEL": "1", "VERCEL_ENV": "production",
    "VERCEL_URL": "synthetic-ping-build.vercel.app",
    "VERCEL_PROJECT_ID": "prj_syntheticping", "VERCEL_DEPLOYMENT_ID": "dpl_syntheticping",
    "RAFII_A7A0_EXPECTED_PROJECT_ID": "prj_syntheticping",
    "RAFII_A7A0_SOURCE_SHA": SOURCE,
    "RAFII_A7A0_APPLICATION_ID": "1553164599086555297",
    "RAFII_A7A0_PUBLIC_KEY_HEX": "12" * 32,
}


class PackageOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.output = self.root / "output"
        self.manifest = HERE / "FROZEN-SOURCES.json"
        self.runtime = {
            name: (HERE / "frozen" / name).read_bytes()
            for name in ("a7a0_ping_core.py", "api/discord/interactions.py")
        }
        self.runtime["vc__handler__python.py"] = b"def handler(event, context): pass\n"
        self.record = {
            "status": "PASS", "runtime": "python3.12", "architecture": "x86_64",
            "source": SOURCE, "selectedInputs": INPUTS,
            "handler": "vc__handler__python.handler", "environmentKeys": [],
            "supportsResponseStreaming": True,
        }
        self.archive()

    def archive(self, extra=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, data in self.runtime.items():
                archive.writestr(name, data)
            if extra:
                name, data = extra
                archive.writestr(name, data)
        data = stream.getvalue()
        (self.evidence / "function.zip").write_bytes(data)
        self.record["sha256"] = hashlib.sha256(data).hexdigest()
        self.save_record()

    def save_record(self):
        (self.evidence / "builder-result.json").write_text(json.dumps(self.record))

    def build(self, env=None):
        return write_output(self.evidence, self.output, self.manifest, ENV if env is None else env)

    def test_actual_archive_metadata_gets_one_static_public_origin(self):
        result = self.build({**ENV, "HTTP_HOST": "forged.invalid",
                             "DATABASE_URL": "synthetic-never-export"})
        cfg = json.loads((self.output / "functions/api/discord/interactions.func/.vc-config.json").read_text())
        self.assertEqual(cfg["environment"]["RAFII_A7A0_EXPECTED_ORIGIN"],
                         "https://synthetic-ping-build.vercel.app")
        self.assertEqual(set(cfg["environment"]), PUBLIC_KEYS)
        self.assertEqual(cfg["handler"], self.record["handler"])
        self.assertEqual(cfg["maxDuration"], 5)
        self.assertFalse(result["systemVariablesOverridden"])
        self.assertNotIn("synthetic-never-export", json.dumps(cfg))
        self.assertEqual(json.loads((self.output / "config.json").read_text())["version"], 3)

    def test_all_platform_identity_fields_are_required(self):
        for key in ("VERCEL", "VERCEL_ENV", "VERCEL_URL", "VERCEL_PROJECT_ID", "VERCEL_DEPLOYMENT_ID"):
            with self.subTest(key=key), self.assertRaises(PackageRejected):
                trusted_context({k: v for k, v in ENV.items() if k != key})

    def test_hostname_cannot_be_a_url_port_path_or_caller_authority(self):
        for host in ("https://synthetic.vercel.app", "synthetic.vercel.app:443",
                     "synthetic.vercel.app/path", "127.0.0.1", "a.vercel.app\n", "a" * 64 + ".vercel.app"):
            with self.subTest(host=host), self.assertRaises(PackageRejected):
                trusted_context({**ENV, "VERCEL_URL": host})

    def test_alias_override_cannot_replace_generated_origin(self):
        with self.assertRaises(PackageRejected):
            trusted_context({**ENV, "RAFII_A7A0_EXPECTED_ORIGIN": "https://alias.vercel.app"})

    def test_wrong_project_cannot_build_an_origin_binding(self):
        with self.assertRaises(PackageRejected):
            trusted_context({**ENV, "RAFII_A7A0_EXPECTED_PROJECT_ID": "prj_other"})

    def test_public_key_application_and_source_are_validated_without_echoing_values(self):
        for name, value in (("RAFII_A7A0_APPLICATION_ID", "synthetic-invalid"),
                            ("RAFII_A7A0_PUBLIC_KEY_HEX", "synthetic-invalid"),
                            ("RAFII_A7A0_SOURCE_SHA", "synthetic-invalid")):
            with self.subTest(name=name), self.assertRaises(PackageRejected):
                trusted_context({**ENV, name: value})

    def test_archive_hash_is_checked_before_extraction(self):
        self.record["sha256"] = "0" * 64
        self.save_record()
        with self.assertRaises(PackageRejected):
            self.build()
        self.assertFalse(self.output.exists())

    def test_runtime_architecture_source_and_inputs_remain_pinned(self):
        changes = {"runtime": "python3.14", "architecture": "arm64", "source": "b" * 40,
                   "selectedInputs": INPUTS + [".env"], "environmentKeys": ["DATABASE_URL"]}
        original = dict(self.record)
        for name, value in changes.items():
            self.record = {**original, name: value}
            self.save_record()
            with self.subTest(name=name), self.assertRaises(PackageRejected):
                self.build()
        self.assertFalse(self.output.exists())

    def test_frozen_handler_change_is_rejected(self):
        self.runtime["api/discord/interactions.py"] += b"\n# changed\n"
        self.archive()
        with self.assertRaises(PackageRejected):
            self.build()

    def test_path_traversal_is_rejected(self):
        self.archive(("../escape", b"x"))
        with self.assertRaises(PackageRejected):
            self.build()
        self.assertFalse((self.root / "escape").exists())

    def test_private_files_and_generated_config_cannot_be_in_archive(self):
        for name in (".env", "postriff_phase2/hosted.py", ".vc-config.json"):
            self.archive((name, b"synthetic"))
            with self.subTest(name=name), self.assertRaises(PackageRejected):
                self.build()

    def test_symlink_is_rejected(self):
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.archive((link, b"/outside"))
        with self.assertRaises(PackageRejected):
            self.build()

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        (self.output / "keep").write_text("existing")
        with self.assertRaises(PackageRejected):
            self.build()
        self.assertEqual((self.output / "keep").read_text(), "existing")

    def test_handler_must_name_the_built_official_launcher(self):
        self.record["handler"] = "../../other.handler"
        self.save_record()
        with self.assertRaises(PackageRejected):
            self.build()


if __name__ == "__main__":
    unittest.main()
